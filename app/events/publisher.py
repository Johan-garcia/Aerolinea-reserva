"""
Publicador asíncrono hacia Kinesis (R1, R2).

El endpoint solo encola el evento (microsegundos) y responde; un hilo en segundo plano arma
lotes de hasta 500 registros y llama a PutRecords. Así la latencia de la API no depende de
Kinesis (R2: p95 <= 1 s con 50 búsquedas concurrentes).

Dos clases de eventos, dos políticas:
  * best-effort (búsquedas): cola acotada; si se llena o Kinesis falla demasiadas veces, el
    evento se descarta y se cuenta en `dropped`. Perder una búsqueda es aceptable.
  * críticos (reservas/cancelaciones): cola sin tope, se reintentan con backoff hasta que
    Kinesis los acepte. Nunca se descartan mientras el proceso viva. (En producción se usaría
    el patrón transactional outbox: ver DOCUMENTO_PARCIAL3.md, decisión 1.)

Cada worker de uvicorn es un proceso distinto: el hilo se crea perezosamente por PID.
"""
import json
import logging
import os
import queue
import threading
import time
from collections import deque

from app.core.config import settings

log = logging.getLogger("events.publisher")

MAX_BATCH = 500             # límite de PutRecords
BEST_EFFORT_ATTEMPTS = 6    # ~6 intentos con backoff antes de descartar una búsqueda


class KinesisPublisher:
    def __init__(self, stream: str, region: str, queue_max: int, batch_wait: float):
        self.stream = stream
        self.region = region
        self.batch_wait = batch_wait
        self._best = queue.Queue(maxsize=queue_max)    # (pk, data, attempts)
        self._critical = deque()                       # (pk, data, attempts)
        self._cv = threading.Condition()
        self._pid = None
        self._thread = None
        self._client = None
        self.sent = 0
        self.dropped = 0
        self.failures = 0

    @property
    def enabled(self) -> bool:
        return bool(self.stream)

    # ------------------------------------------------------------------ API pública
    def publish(self, partition_key: str, event: dict, critical: bool = False) -> None:
        """Encola el evento y vuelve de inmediato. Nunca lanza excepciones al llamador."""
        if not self.enabled:
            return
        try:
            self._ensure_thread()
            data = json.dumps(event, separators=(",", ":")).encode()
            item = (partition_key, data, 0)
            if critical:
                with self._cv:
                    self._critical.append(item)
                    self._cv.notify()
            else:
                try:
                    self._best.put_nowait(item)
                except queue.Full:
                    self.dropped += 1
                    return
                with self._cv:
                    self._cv.notify()
        except Exception:  # noqa: BLE001 - publicar nunca debe romper la petición
            log.exception("no se pudo encolar el evento")

    def stats(self) -> dict:
        return {"enabled": self.enabled, "stream": self.stream, "sent": self.sent, "dropped": self.dropped,
                "failures": self.failures, "pending_best_effort": self._best.qsize(),
                "pending_critical": len(self._critical)}

    def flush(self, timeout: float = 5.0) -> None:
        """Espera (con tope) a que las colas se vacíen; se usa al apagar el proceso."""
        t0 = time.monotonic()
        while (self._best.qsize() or self._critical) and time.monotonic() - t0 < timeout:
            with self._cv:
                self._cv.notify()
            time.sleep(0.05)

    # ------------------------------------------------------------------ hilo de envío
    def _ensure_thread(self):
        pid = os.getpid()
        if self._pid == pid and self._thread and self._thread.is_alive():
            return
        with self._cv:
            if self._pid == pid and self._thread and self._thread.is_alive():
                return
            self._pid = pid
            self._client = None   # un cliente boto3 nuevo por proceso
            self._thread = threading.Thread(target=self._run, name="kinesis-publisher", daemon=True)
            self._thread.start()

    def _kinesis(self):
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client("kinesis", region_name=self.region,
                                        config=Config(retries={"max_attempts": 2, "mode": "standard"},
                                                      connect_timeout=3, read_timeout=10))
        return self._client

    def _take_batch(self) -> list:
        """Hasta 500 registros: primero los críticos, luego las búsquedas."""
        with self._cv:
            if not self._critical and self._best.empty():
                self._cv.wait(timeout=1.0)
        # pequeña espera para agrupar ráfagas en un solo PutRecords
        if self.batch_wait:
            time.sleep(self.batch_wait)
        batch = []
        with self._cv:
            while self._critical and len(batch) < MAX_BATCH:
                batch.append(self._critical.popleft() + (True,))
        while len(batch) < MAX_BATCH:
            try:
                batch.append(self._best.get_nowait() + (False,))
            except queue.Empty:
                break
        return batch

    def _requeue(self, items):
        retry_best = []
        with self._cv:
            for pk, data, attempts, critical in reversed(items):
                if critical:
                    self._critical.appendleft((pk, data, attempts + 1))
                elif attempts + 1 < BEST_EFFORT_ATTEMPTS:
                    retry_best.append((pk, data, attempts + 1))
                else:
                    self.dropped += 1
        for it in retry_best:
            try:
                self._best.put_nowait(it)
            except queue.Full:
                self.dropped += 1

    def _run(self):
        backoff = 0.2
        while True:
            batch = self._take_batch()
            if not batch:
                continue
            try:
                resp = self._kinesis().put_records(
                    StreamName=self.stream,
                    Records=[{"Data": d, "PartitionKey": pk} for pk, d, _, _ in batch])
                failed = [batch[i] for i, r in enumerate(resp["Records"]) if "ErrorCode" in r]
                self.sent += len(batch) - len(failed)
                if failed:
                    self.failures += len(failed)
                    self._requeue(failed)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 5.0)
                else:
                    backoff = 0.2
            except Exception as e:  # noqa: BLE001 - red, permisos, stream borrado...
                self.failures += len(batch)
                log.warning("PutRecords falló (%s); %d eventos se reintentan", e, len(batch))
                self._requeue(batch)
                time.sleep(backoff)
                backoff = min(backoff * 2, 5.0)


publisher = KinesisPublisher(settings.KINESIS_STREAM, settings.AWS_REGION,
                             settings.EVENTS_QUEUE_MAX, settings.EVENTS_BATCH_WAIT_SECONDS)
