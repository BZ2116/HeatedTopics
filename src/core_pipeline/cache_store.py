import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


class CacheStore:
    def __init__(
        self,
        root: str | Path = "data/cache",
        ttl_days: int = 7,
        refresh: bool = False,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        self.ttl = timedelta(days=ttl_days)
        self.refresh = refresh
        self.now = now or (lambda: datetime.now(timezone.utc))

    def read(self, key: str) -> Any | None:
        if self.refresh:
            return None
        path = self._path_for_key(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        fetched_at = _parse_datetime(str(payload.get("fetched_at", "")))
        if fetched_at is None:
            return None
        if self.now() - fetched_at > self.ttl:
            return None
        return payload.get("data")

    def write(self, key: str, data: Any, fetched_at: str | None = None) -> None:
        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "key": key,
            "fetched_at": fetched_at or self.now().isoformat(timespec="seconds"),
            "data": data,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        namespace = key.split(":", 1)[0] if ":" in key else "misc"
        return self.root / namespace / f"{digest}.json"


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
