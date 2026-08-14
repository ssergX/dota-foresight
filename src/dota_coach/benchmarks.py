from __future__ import annotations

from dota_coach.models import Match, MetricBenchmark


def player_benchmarks(match: Match, account_id: int | None) -> list[MetricBenchmark]:
    me = match.player_by_account(account_id)
    if me is None or not me.benchmarks:
        return []
    out: list[MetricBenchmark] = []
    for metric, values in me.benchmarks.items():
        if not isinstance(values, dict) or "pct" not in values:
            continue
        out.append(MetricBenchmark(metric=metric,
                                   raw=float(values.get("raw", 0.0)),
                                   pct=float(values["pct"])))
    return out


def weak_metrics(benchmarks: list[MetricBenchmark], threshold: float = 0.4) -> list[MetricBenchmark]:
    return [b for b in benchmarks if b.pct < threshold]
