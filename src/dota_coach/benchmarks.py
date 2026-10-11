from __future__ import annotations
from math import isfinite

from dota_coach.models import Match, MetricBenchmark


def player_benchmarks(match: Match, account_id: int | None) -> list[MetricBenchmark]:
    me = match.player_by_account(account_id)
    if me is None or not me.benchmarks:
        return []
    out: list[MetricBenchmark] = []
    for metric, values in me.benchmarks.items():
        if not isinstance(values, dict) or "pct" not in values:
            continue
        pct, raw = values.get("pct"), values.get("raw")
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not isfinite(v)
               for v in (pct, raw)) or not 0 <= pct <= 1:
            continue
        out.append(MetricBenchmark(metric=metric,
                                   raw=float(raw), pct=float(pct)))
    return out


def weak_metrics(benchmarks: list[MetricBenchmark], threshold: float = 0.4) -> list[MetricBenchmark]:
    return [b for b in benchmarks if b.pct < threshold]
