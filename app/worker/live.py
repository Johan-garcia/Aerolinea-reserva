"""Vista en vivo (R3): contadores en memoria por segundo de event_ts (no por hora de llegada)."""
import threading
import time
from datetime import datetime, timezone

TYPES = {"search_performed": 0, "reservation_created": 1, "reservation_cancelled": 2}
FUTURE_SKEW_SECONDS = 120   # tolera relojes un poco adelantados; más allá se ignora


def parse_ts(ts: str) -> int | None:
    try:
        return int(datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None


class LiveCounters:
    def __init__(self, retention_minutes: int = 60, clock=time.time):
        self.retention = retention_minutes * 60
        self.clock = clock
        self._buckets: dict[int, list[int]] = {}   # segundo epoch -> [búsquedas, reservas, cancelaciones]
        self._seen: dict[str, int] = {}            # event_id -> segundo (deduplicación dentro de la retención)
        self._lock = threading.Lock()
        self._last_prune = 0.0
        self.ignored_old = 0

    def add(self, event: dict) -> bool:
        """Cuenta el evento si es reciente y no se había visto. Devuelve True si se contó."""
        idx = TYPES.get(event.get("event_type"))
        ts = parse_ts(event.get("event_ts"))
        eid = event.get("event_id")
        if idx is None or ts is None or not eid:
            return False
        now = self.clock()
        if ts < now - self.retention or ts > now + FUTURE_SKEW_SECONDS:
            self.ignored_old += 1           # p. ej. el replay del harness con fechas de 2025
            return False
        with self._lock:
            if eid in self._seen:           # duplicado (reintento del productor o relectura)
                return False
            self._seen[eid] = ts
            self._buckets.setdefault(ts, [0, 0, 0])[idx] += 1
        self._maybe_prune(now)
        return True

    def snapshot(self, window_minutes: int) -> dict:
        now = self.clock()
        since = now - window_minutes * 60
        s = r = c = 0
        with self._lock:
            for ts, (a, b, x) in self._buckets.items():
                if since < ts <= now + FUTURE_SKEW_SECONDS:
                    s += a
                    r += b
                    c += x
        return {"window_minutes": window_minutes, "searches": s, "reservations": r, "cancellations": c,
                "conversion": (r / s) if s else 0.0}

    def _maybe_prune(self, now: float):
        if now - self._last_prune < 30:
            return
        self._last_prune = now
        limit = now - self.retention
        with self._lock:
            for ts in [t for t in self._buckets if t < limit]:
                del self._buckets[ts]
            for eid in [e for e, t in self._seen.items() if t < limit]:
                del self._seen[eid]
