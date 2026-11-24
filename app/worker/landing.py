"""
Landing zone (R4): los registros del stream se guardan TAL CUAL llegaron (JSON por línea, gzip)
en objetos inmutables. Es append-only: los duplicados se quedan aquí y se eliminan en el ETL.

Se escribe un objeto cada LANDING_FLUSH_SECONDS (o al juntar LANDING_FLUSH_RECORDS registros),
así un evento tarda como máximo ~1 minuto en llegar a S3 (el contrato permite 5).
Las claves son planas (raw/events/20260324T101500Z-<uuid>.json.gz) y ordenables por hora de llegada.
"""
import gzip
import threading
import time
import uuid
from datetime import datetime, timezone

from .lake import Lake


class LandingWriter:
    def __init__(self, lake: Lake, flush_seconds: int = 60, flush_records: int = 5000):
        self.lake = lake
        self.flush_seconds = flush_seconds
        self.flush_records = flush_records
        self._buf: list[bytes] = []
        self._pending_ckpt: dict[str, str] = {}      # shard -> última secuencia en el buffer
        self._lock = threading.RLock()
        self._first_at: float | None = None
        self.objects_written = 0
        self.records_written = 0
        self.last_flush_at: str | None = None
        self.on_flushed = None                       # callback(dict shard->seq) tras escribir en S3

    def add(self, data: bytes, shard_id: str, seq: str):
        with self._lock:
            self._buf.append(data.rstrip(b"\n"))
            self._pending_ckpt[shard_id] = seq
            if self._first_at is None:
                self._first_at = time.monotonic()

    def due(self) -> bool:
        with self._lock:
            if not self._buf:
                return False
            return (len(self._buf) >= self.flush_records
                    or time.monotonic() - self._first_at >= self.flush_seconds)

    def pending(self) -> int:
        return len(self._buf)

    def flush(self) -> int:
        """Escribe el buffer como un objeto gzip. Si S3 falla, el buffer se conserva y se reintenta."""
        with self._lock:
            if not self._buf:
                return 0
            body = gzip.compress(b"\n".join(self._buf) + b"\n")
            now = datetime.now(timezone.utc)
            key = f"{now:%Y%m%dT%H%M%S}Z-{uuid.uuid4().hex[:12]}.json.gz"
            self.lake.put(key, body, content_type="application/json")
            n = len(self._buf)
            ckpt = dict(self._pending_ckpt)
            self._buf, self._pending_ckpt, self._first_at = [], {}, None
            self.objects_written += 1
            self.records_written += n
            self.last_flush_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if self.on_flushed:
            self.on_flushed(ckpt)
        return n
