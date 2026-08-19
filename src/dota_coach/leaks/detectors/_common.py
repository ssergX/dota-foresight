from __future__ import annotations

from statistics import mean, median
from typing import Callable

from dota_coach.leaks.rows import Row
from dota_coach.models import Confidence, Leak


def mean_of(rows: list[Row], getter: Callable[[Row], float]) -> float:
    return float(mean(getter(r) for r in rows))


def median_pct(rows: list[Row], metric: str) -> float | None:
    vals = []
    for r in rows:
        b = r.me.benchmarks.get(metric)
        if isinstance(b, dict) and "pct" in b:
            vals.append(float(b["pct"]))
    return float(median(vals)) if vals else None


def make_leak(*, role: int, rows: list[Row], metric: str, value: float,
              threshold: float, direction: str, source: str, magnitude: str,
              worst_key: Callable[[Row], float], worst_reverse: bool) -> Leak:
    # Идентичность (key/title/phase/family) НЕ ставится здесь — её проставит обёртка
    # @detector из метаданных декоратора. make_leak отвечает только за числа.
    worst = sorted(rows, key=worst_key, reverse=worst_reverse)[:3]
    return Leak(
        key="", title="", magnitude=magnitude,
        example_matches=[r.match_id for r in worst], confidence=Confidence.HIGH,
        metric=metric, value=value, threshold=threshold, direction=direction,
        role=role, source=source, sample_size=len(rows),
    )
