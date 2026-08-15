from __future__ import annotations

import json
from pathlib import Path

from dota_coach.coach.brief import CoachBrief, brief_to_dict, parse_brief


def _history_path(account_id: int | None, cache_dir: Path) -> Path:
    return cache_dir / f"coach_history_{account_id}.json"


def load_history(account_id: int | None, cache_dir: Path = Path("cache")) -> list[CoachBrief]:
    path = _history_path(account_id, cache_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [parse_brief(item) for item in data]


def save_brief(account_id: int | None, brief: CoachBrief, cache_dir: Path = Path("cache")) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _history_path(account_id, cache_dir)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    existing.append(brief_to_dict(brief))
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def latest_brief(account_id: int | None, cache_dir: Path = Path("cache")) -> CoachBrief | None:
    history = load_history(account_id, cache_dir)
    return history[-1] if history else None
