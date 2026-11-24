"""
Proceso worker:  python -m app.worker.main

Hilos:
  * consumidor de Kinesis (vista en vivo + landing zone)
  * programador del micro-lote de la estrella (cada STAR_REFRESH_MINUTES, solo si llegó algo nuevo)
  * servidor HTTP interno (puerto 8001, no se publica fuera de Docker) que usa la API:
        GET  /live?window=5    GET /status    POST /refresh    GET /health
"""
import json
import logging
import os
import threading
import time
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.core.config import settings
from app.star.etl import run_refresh

from .consumer import StreamConsumer
from .lake import Lake
from .landing import LandingWriter
from .live import LiveCounters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RefreshManager:
    """Un solo job a la vez. Si piden un refresco mientras otro corre, se encola UNA corrida más y el
    estado sigue en RUNNING hasta que termine: así quien llama nunca ve SUCCEEDED de una corrida que
    empezó antes de que sus eventos llegaran a la landing zone."""

    def __init__(self, job):
        self.job = job
        self._lock = threading.Lock()
        self.state = "IDLE"
        self.job_id = 0
        self.running = False
        self.pending = False
        self.last = {}
        self.last_error = None

    def request(self, reason="api") -> dict:
        with self._lock:
            self.job_id += 1
            if self.running:
                self.pending = True
            else:
                self.running = True
                self.state = "RUNNING"
                threading.Thread(target=self._loop, args=(reason,), daemon=True, name="star-refresh").start()
            return {"job_id": self.job_id, "state": "RUNNING"}

    def _loop(self, reason):
        while True:
            started = _now()
            try:
                stats = self.job()
                ok, err = True, None
            except Exception as e:  # noqa: BLE001
                ok, err, stats = False, f"{type(e).__name__}: {e}", {}
                log.error("refresh falló:\n%s", traceback.format_exc())
            with self._lock:
                self.last = {"started_at": started, "ended_at": _now(), "reason": reason, **stats}
                self.last_error = err
                if self.pending:
                    self.pending = False
                    reason = "encolado"
                    continue
                self.running = False
                self.state = "SUCCEEDED" if ok else "FAILED"
                return

    def status(self) -> dict:
        with self._lock:
            return {"state": "RUNNING" if self.running else self.state, "job_id": self.job_id,
                    "last_run": self.last, "error": self.last_error}


def main():
    live = LiveCounters(settings.LIVE_RETENTION_MINUTES)
    raw_uri = settings.RAW_EVENTS_URI or os.path.join(settings.LOCAL_LAKE, "raw", "events")
    landing = LandingWriter(Lake(raw_uri, settings.AWS_REGION), settings.LANDING_FLUSH_SECONDS,
                            settings.LANDING_FLUSH_RECORDS)
    consumer = None
    if settings.KINESIS_STREAM:
        consumer = StreamConsumer(settings.KINESIS_STREAM, settings.AWS_REGION, landing, live, settings.STATE_DIR)
        threading.Thread(target=consumer.run_forever, daemon=True, name="kinesis-consumer").start()
    else:
        log.warning("KINESIS_STREAM vacío: el worker no lee eventos (solo ETL bajo demanda)")

    refresh = RefreshManager(lambda: run_refresh(settings, consumer.flush if consumer else None))

    def scheduler():
        seen = 0
        while settings.STAR_REFRESH_MINUTES > 0:
            time.sleep(settings.STAR_REFRESH_MINUTES * 60)
            if landing.objects_written > seen and not refresh.running:
                seen = landing.objects_written
                refresh.request(reason="programado")
    threading.Thread(target=scheduler, daemon=True, name="star-scheduler").start()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/live":
                try:
                    w = int(q.get("window", ["5"])[0])
                except ValueError:
                    return self._json(422, {"detail": "window debe ser un entero"})
                if not 1 <= w <= settings.LIVE_RETENTION_MINUTES:
                    return self._json(422, {"detail": f"window entre 1 y {settings.LIVE_RETENTION_MINUTES}"})
                return self._json(200, live.snapshot(w))
            if u.path == "/status":
                return self._json(200, refresh.status())
            if u.path == "/health":
                return self._json(200, {
                    "consumer": consumer.status if consumer else "disabled",
                    "records_read": consumer.records_read if consumer else 0,
                    "millis_behind": consumer.millis_behind if consumer else 0,
                    "landing": {"objects": landing.objects_written, "records": landing.records_written,
                                "pending": landing.pending(), "last_flush_at": landing.last_flush_at},
                    "live_ignored_old_events": live.ignored_old})
            self._json(404, {"detail": "no existe"})

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path == "/refresh":
                return self._json(202, refresh.request())
            self._json(404, {"detail": "no existe"})

        def log_message(self, *a):  # silencio: la vista en vivo se consulta seguido
            pass

    port = int(os.environ.get("WORKER_PORT", "8001"))
    log.info("worker escuchando en :%d (stream=%s, landing=%s)", port, settings.KINESIS_STREAM or "-", raw_uri)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
