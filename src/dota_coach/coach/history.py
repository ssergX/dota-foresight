from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from dota_coach.coach.brief import CoachBrief, brief_to_dict, parse_brief

_LEGACY_KEY_MAP = {"low_warding": "low_obs"}


def _history_path(account_id: int | None, cache_dir: Path) -> Path:
    return cache_dir / f"coach_history_{account_id}.json"


def load_history(account_id: int | None, cache_dir: Path = Path("cache")) -> list[CoachBrief]:
    if account_id is None:
        return []
    path = _history_path(account_id, cache_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    briefs = [parse_brief(item) for item in data]
    for b in briefs:
        if b.focus_leak_key in _LEGACY_KEY_MAP:
            b.focus_leak_key = _LEGACY_KEY_MAP[b.focus_leak_key]
            # старое значение считалось по всей серии без роли -> несравнимо с новым ролевым:
            b.baseline_reset = True
    return briefs


def save_brief(account_id: int | None, brief: CoachBrief, cache_dir: Path = Path("cache")) -> None:
    if account_id is None:
        return
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _history_path(account_id, cache_dir)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    payload = brief_to_dict(brief)
    replaced = False
    if brief.generated_for_matches:
        for index in range(len(existing) - 1, -1, -1):
            previous = existing[index]
            if (sorted(previous.get("generated_for_matches", [])) == sorted(brief.generated_for_matches)
                    and previous.get("detector_version", "") == brief.detector_version
                    and previous.get("source_version", "") == brief.source_version
                    and previous.get("schema_version") == brief.schema_version):
                existing[index] = payload
                replaced = True
                break
    if not replaced:
        existing.append(payload)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_dir,
                                         suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump(existing, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def latest_brief(account_id: int | None, cache_dir: Path = Path("cache")) -> CoachBrief | None:
    history = load_history(account_id, cache_dir)
    return history[-1] if history else None
