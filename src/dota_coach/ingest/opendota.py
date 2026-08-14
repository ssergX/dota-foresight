from __future__ import annotations

import json
import time
from pathlib import Path

import requests

BASE = "https://api.opendota.com/api"
_MIN_INTERVAL = 1.1  # ~<60 req/min
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def fetch_match(match_id: int, cache_dir: Path = Path("cache")) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{match_id}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    _throttle()
    resp = requests.get(f"{BASE}/matches/{match_id}", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    cached.write_text(json.dumps(data), encoding="utf-8")
    return data


def fetch_recent(account_id: int, n: int, cache_dir: Path = Path("cache")) -> list[int]:
    _throttle()
    resp = requests.get(f"{BASE}/players/{account_id}/matches",
                        params={"limit": n}, timeout=30)
    resp.raise_for_status()
    return [row["match_id"] for row in resp.json()]
