"""Reproduce observations of the 2026-10-05 snapshot; not acceptance tests.

Run with Python 3.12+, no third-party dependencies. No source files are changed.
After product fixes, `matches_audited_snapshot` should change for fixed defects.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.info_state import info_state_at
from dota_coach.coach.progress import compare_focus
from dota_coach.models import (
    EventCandidate, EventType, ParsedReplay, ReplayFrame, UnitState, WardEvent,
)
from dota_coach.scoring import _score_one


def unit(slot: int, x: float) -> UnitState:
    return UnitState(slot, x, 0.0, 100, 100, 50.0, 1, 0, True)


def replay(enemy_x: float, wards=(), include_me=True) -> ParsedReplay:
    units = {5: unit(5, enemy_x)}
    if include_me:
        units[0] = unit(0, 0.0)
    return ParsedReplay(
        match_id=0, game_start_time=0.0,
        heroes={0: "SyntheticOwnHero", 5: "SyntheticEnemyHero"},
        frames=[ReplayFrame(10, units)], teams={0: 2, 5: 3}, wards=list(wards),
    )


def main() -> None:
    results = []

    def record(name, observed, audited):
        results.append({
            "probe": name, "observed": observed,
            "audited_snapshot_observation": audited,
            "matches_audited_snapshot": observed == audited,
        })

    event = EventCandidate(EventType.NETWORTH_SWING, 60, True,
                           "synthetic change", {"delta": -500})
    scored = _score_one(event, 0)
    record("economic_change_becomes_error",
           [scored.verdict.value, scored.confidence.value], ["mistake", "high"])

    wards = [WardEvent(7, 0, "obs", 2, 5000, 0, "placed"),
             WardEvent(7, 20, "obs", 2, 5000, 0, "gone")]
    before = info_state_at(replay(5000, wards), 10, 0)
    after = info_state_at(replay(5000, wards + [
        WardEvent(7, 30, "obs", 2, 10000, 0, "placed")]), 10, 0)
    record("future_ward_changes_past_visibility",
           [before.enemies[0].visible, after.enemies[0].visible], [True, False])

    close = replay(100)
    at10, at11 = info_state_at(close, 10, 0), info_state_at(close, 11, 0)
    record("between_frames_visibility_changes_without_observation",
           [at10.enemies[0].visible, at11.enemies[0].visible], [True, False])

    missing = info_state_at(replay(100, include_me=False), 10, 0)
    record("missing_own_unit_becomes_zero_and_dead",
           [missing.my_x, missing.my_hp, missing.my_alive, missing.zone],
           [0.0, 0, False, "у реки/центр"])

    prior = CoachBrief(
        focus_leak_key="low_obs", headline="", diagnosis="", why_it_costs="",
        focus_metric="obs_per_game", focus_value=1.0,
        focus_direction="higher_is_better")
    record("missing_detector_becomes_resolved", compare_focus(prior, []).status,
           "resolved")

    paths = [
        "src/dota_coach/models.py", "src/dota_coach/scoring.py",
        "src/dota_coach/coach/info_state.py", "src/dota_coach/coach/progress.py",
        "src/dota_coach/coach/brief.py", "replay_tool/main.go",
    ]
    print(json.dumps({
        "dataset_kind": "synthetic_diagnostic",
        "meaning": "Reproduced legacy defects, not passing new-system quality gates",
        "sources_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                           for p in paths},
        "results": results,
    }, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
