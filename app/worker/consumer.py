"""
Consumidor del stream (sin enhanced fan-out, R11): GetRecords sobre cada shard abierto.

Entrega "al menos una vez": el checkpoint (última secuencia escrita en S3) se guarda en disco
DESPUÉS de cada objeto de la landing zone. Si el proceso se cae, al volver relee desde el
checkpoint y puede repetir algunos registros; el ETL los deduplica por event_id.
Si el stream se borró y se volvió a crear (se borra al terminar de trabajar, por costo), el
checkpoint ya no vale y se relee desde TRIM_HORIZON.
"""
import json
import logging
import os
import threading
import time

from .landing import LandingWriter
from .live import LiveCounters

log = logging.getLogger("worker.consumer")

IDLE_SLEEP = 1.0      # 1 GetRecords/s por shard deja margen dentro del límite de 5/s
BEHIND_SLEEP = 0.4    # si vamos atrasados (p. ej. tras el replay de 20.000 eventos) se lee más seguido
LIMIT = 4000          # ~1 MB por llamada: por debajo del límite de 2 MB/s de lectura por shard


class StreamConsumer:
    def __init__(self, stream: str, region: str, landing: LandingWriter, live: LiveCounters, state_dir: str):
        self.stream = stream
        self.region = region
        self.landing = landing
        self.live = live
        self.ckpt_path = os.path.join(state_dir, "checkpoint.json")
        os.makedirs(state_dir, exist_ok=True)
        self._kinesis = None
        self._stream_created = None
        self._last_read: dict[str, str] = {}
        self.status = "starting"
        self.records_read = 0
        self.millis_behind = 0
        self.landing.on_flushed = self._save_checkpoint
        self._flush_lock = threading.Lock()

    @property
    def kinesis(self):
        if self._kinesis is None:
            import boto3
            from botocore.config import Config
            self._kinesis = boto3.client("kinesis", region_name=self.region,
                                         config=Config(retries={"max_attempts": 3, "mode": "standard"}))
        return self._kinesis

    # ---------------------------------------------------------------- checkpoint
    def _load_checkpoint(self) -> dict:
        try:
            with open(self.ckpt_path, encoding="utf-8") as fh:
                c = json.load(fh)
            if c.get("stream") == self.stream and c.get("stream_created") == self._stream_created:
                return c.get("shards", {})
        except (OSError, ValueError):
            pass
        return {}

    def _save_checkpoint(self, flushed: dict):
        shards = self._load_checkpoint()
        shards.update(flushed)
        tmp = self.ckpt_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"stream": self.stream, "stream_created": self._stream_created, "shards": shards}, fh)
        os.replace(tmp, self.ckpt_path)

    # ---------------------------------------------------------------- lectura
    def _iterator(self, shard_id: str) -> str:
        seq = self._last_read.get(shard_id) or self._load_checkpoint().get(shard_id)
        if seq:
            try:
                return self.kinesis.get_shard_iterator(StreamName=self.stream, ShardId=shard_id,
                                                       ShardIteratorType="AFTER_SEQUENCE_NUMBER",
                                                       StartingSequenceNumber=seq)["ShardIterator"]
            except self.kinesis.exceptions.InvalidArgumentException:
                log.warning("checkpoint inválido para %s; se lee desde TRIM_HORIZON", shard_id)
        return self.kinesis.get_shard_iterator(StreamName=self.stream, ShardId=shard_id,
                                               ShardIteratorType="TRIM_HORIZON")["ShardIterator"]

    def _handle(self, shard_id: str, rec: dict):
        data = rec["Data"]
        self.landing.add(data, shard_id, rec["SequenceNumber"])
        self._last_read[shard_id] = rec["SequenceNumber"]
        self.records_read += 1
        try:
            ev = json.loads(data)
            if isinstance(ev, dict):
                self.live.add(ev)
        except ValueError:
            pass   # basura en el stream: se guarda en la landing (auditoría) pero no se cuenta

    def flush(self):
        with self._flush_lock:
            try:
                return self.landing.flush()
            except Exception as e:  # noqa: BLE001
                log.warning("no se pudo escribir en la landing zone (%s); se reintenta", e)
                return 0

    def _session(self):
        """Lee hasta que algo falle; el bucle exterior decide qué hacer."""
        summ = self.kinesis.describe_stream_summary(StreamName=self.stream)["StreamDescriptionSummary"]
        created = summ["StreamCreationTimestamp"].isoformat()
        if self._stream_created and created != self._stream_created:
            self._last_read = {}      # stream nuevo: las secuencias anteriores no existen
        self._stream_created = created
        shards = [s["ShardId"] for s in self.kinesis.list_shards(StreamName=self.stream)["Shards"]
                  if "EndingSequenceNumber" not in s.get("SequenceNumberRange", {})]
        its = {sid: self._iterator(sid) for sid in shards}
        self.status = f"reading {len(shards)} shard(s)"
        while its:
            got_any, behind = False, 0
            for sid, it in list(its.items()):
                r = self.kinesis.get_records(ShardIterator=it, Limit=LIMIT)
                for rec in r["Records"]:
                    self._handle(sid, rec)
                got_any |= bool(r["Records"])
                behind = max(behind, r.get("MillisBehindLatest", 0))
                if r.get("NextShardIterator"):
                    its[sid] = r["NextShardIterator"]
                else:
                    its.pop(sid)          # shard cerrado (resharding): se vuelve a listar
            self.millis_behind = behind
            if self.landing.due():
                self.flush()
            time.sleep(BEHIND_SLEEP if (got_any and behind > 0) else IDLE_SLEEP)

    def run_forever(self):
        while True:
            try:
                self._session()
                time.sleep(5)       # sin shards abiertos (stream recién creado o en resharding)
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                if "ResourceNotFound" in name:
                    self.status = "stream not found (¿se borró para ahorrar?)"
                    wait = 30
                elif "ProvisionedThroughputExceeded" in name:
                    self.status = "throttled"
                    wait = 2
                elif "ExpiredIterator" in name:
                    wait = 0
                else:
                    self.status = f"error: {name}: {e}"
                    log.warning("consumidor: %s", self.status)
                    wait = 5
                self.flush()
                time.sleep(wait)
