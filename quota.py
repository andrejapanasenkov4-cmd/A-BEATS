"""Conservative local guard for the YouTube videos.insert daily quota bucket."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Google documents a default 100 videos.insert requests/day bucket. Reserve 10
# calls for retries/other tools using the same Google Cloud project.
APP_DAILY_UPLOAD_LIMIT = 90
API_RESET_ZONE = ZoneInfo("America/Los_Angeles")
_LOCK = threading.Lock()


def _today_key(now: datetime | None = None) -> str:
    return (now or datetime.now(API_RESET_ZONE)).astimezone(API_RESET_ZONE).date().isoformat()


def load_usage(path: str | Path, now: datetime | None = None) -> int:
    file = Path(path)
    key = _today_key(now)
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0
        return max(0, int(data.get(key, 0)))
    except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
        return 0


def record_attempt(path: str | Path, now: datetime | None = None) -> int:
    """Record one attempted videos.insert call before network I/O."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    key = _today_key(now)
    with _LOCK:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            data = {}
        try:
            previous = max(0, int(data.get(key, 0)))
        except (ValueError, TypeError):
            previous = 0
        count = previous + 1
        data[key] = count
        # Keep a short audit trail, enough to cover clock / timezone changes.
        for old_key in sorted(k for k in data if k < key)[:-13]:
            data.pop(old_key, None)
        temp = file.with_suffix(file.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp.replace(file)
        return count


def remaining(path: str | Path, now: datetime | None = None, limit: int = APP_DAILY_UPLOAD_LIMIT) -> int:
    return max(0, limit - load_usage(path, now))
