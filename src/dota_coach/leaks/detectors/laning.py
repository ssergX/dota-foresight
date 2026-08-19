from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, mean_of, median_pct
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="farm_below_bracket", title="Фарм ниже бракета", roles=(1, 2, 3, 4, 5),
          requires=("benchmarks",), impact=0.9, phase="laning", family="economy")
def farm_below_bracket(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    med = median_pct(rows, "gold_per_min")
    floor = th.bench_floor()
    if med is None or med >= floor:
        return None
    return make_leak(role=role, rows=rows, metric="gpm_pct", value=round(med, 3),
                     threshold=floor, direction="higher_is_better", source="bench",
                     magnitude=f"медиана GPM в p{round(med * 100)}",
                     worst_key=lambda r: r.me.benchmarks.get("gold_per_min", {}).get("pct", 1.0),
                     worst_reverse=False)


@detector(key="cs_behind_at_10", title="Мало ластхитов к 10 мин", roles=(1, 2, 3),
          requires=("lh_t",), impact=0.7, phase="laning", family="laning")
def cs_behind_at_10(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("cs_at_10", role)
    usable = [r for r in rows if len(r.me.lh_t) > 10]
    if thr is None or len(usable) < 5:
        return None
    avg = mean_of(usable, lambda r: r.me.lh_t[10])
    if avg >= thr:
        return None
    return make_leak(role=role, rows=usable, metric="cs_at_10", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.0f} ластхитов к 10 мин (планка {thr:.0f})",
                     worst_key=lambda r: r.me.lh_t[10], worst_reverse=False)


@detector(key="low_denies", title="Мало денаев", roles=(1, 2, 3),
          requires=("denies",), impact=0.4, phase="laning", family="laning")
def low_denies(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("denies_per_game", role)
    avg = mean_of(rows, lambda r: r.me.denies)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="denies_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} денаев за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.denies, worst_reverse=False)


@detector(key="lane_collapse", title="Проваленный лейн", roles=(1, 2, 3),
          requires=("lane_efficiency_pct",), impact=0.8, phase="laning", family="laning")
def lane_collapse(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("lane_efficiency_pct", role)
    avg = mean_of(rows, lambda r: r.me.lane_efficiency_pct)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="lane_efficiency_pct", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"эффективность лейна {avg:.0f}% (планка {thr:.0f}%)",
                     worst_key=lambda r: r.me.lane_efficiency_pct, worst_reverse=False)
