from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from math import isfinite

from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak

Detector = Callable[[list[Row], int, Thresholds], "Leak | None"]


@dataclass(frozen=True)
class DetectorSpec:
    fn: Detector
    key: str
    title: str
    roles: tuple[int, ...]
    requires: tuple[str, ...]
    impact: float
    phase: str
    family: str


DETECTORS: list[DetectorSpec] = []


def detector(*, key: str, title: str, roles: tuple[int, ...], requires: tuple[str, ...],
             impact: float, phase: str, family: str):
    def deco(fn: Detector) -> Detector:
        def wrapper(rows, role, th):
            # Coverage belongs to the target benchmark, not any benchmark dict.
            target = {"farm_below_bracket": "gold_per_min", "level_behind": "xp_per_min",
                      "present_no_damage": "hero_damage_per_min", "low_tower_damage": "tower_damage"}.get(key)
            if target:
                rows = [r for r in rows if _valid_pct(r.me.benchmarks.get(target))]
                if len(rows) < 5:
                    return None
            leak = fn(rows, role, th)
            if leak is not None:
                # идентичность лика ставит ОДНО место — обёртка, из метаданных декоратора.
                # Детекторы и make_leak key/title/phase/family НЕ задают.
                leak.key = key
                leak.title = title
                leak.phase = phase
                leak.family = family
            return leak
        DETECTORS.append(DetectorSpec(fn=wrapper, key=key, title=title, roles=tuple(roles),
                                      requires=tuple(requires), impact=impact,
                                      phase=phase, family=family))
        return wrapper
    return deco


def applicable(role: int) -> list[DetectorSpec]:
    return [d for d in DETECTORS if role in d.roles]


def _present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, str)):
        return len(value) > 0
    return True


def _valid_pct(value) -> bool:
    if not isinstance(value, dict):
        return False
    pct = value.get("pct")
    return isinstance(pct, (int, float)) and not isinstance(pct, bool) and isfinite(pct) and 0 <= pct <= 1


def filter_rows(rows: list[Row], requires: tuple[str, ...]) -> list[Row]:
    return [r for r in rows if all(_present(getattr(r.me, f)) for f in requires)]
