from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, mean_of, median_pct
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak

_IDLE_GOLD_STEP = 200  # прирост золота за минуту ниже этого = "простой"
_IDLE_FRAC_THRESHOLD = 0.35  # доля простойных минут, выше которой — лик


def _idle_fraction(gold_t: list[int]) -> float:
    if len(gold_t) < 2:
        return 0.0
    idle = sum(1 for a, b in zip(gold_t, gold_t[1:]) if (b - a) < _IDLE_GOLD_STEP)
    return idle / (len(gold_t) - 1)


@detector(key="idle_gold_gaps", title="Простой — золото не растёт", roles=(1, 2, 3),
          requires=("gold_t",), impact=0.6, phase="economy", family="economy")
def idle_gold_gaps(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    avg = mean_of(rows, lambda r: _idle_fraction(r.me.gold_t))
    if avg <= _IDLE_FRAC_THRESHOLD:
        return None
    return make_leak(role=role, rows=rows, metric="idle_gold_frac", value=round(avg, 3),
                     threshold=_IDLE_FRAC_THRESHOLD, direction="lower_is_better", source="manual",
                     magnitude=f"{avg * 100:.0f}% минут без прироста золота",
                     worst_key=lambda r: _idle_fraction(r.me.gold_t), worst_reverse=True)


@detector(key="low_neutral_farm", title="Не фармит лес", roles=(1, 2, 3),
          requires=("neutral_kills",), impact=0.5, phase="economy", family="economy")
def low_neutral_farm(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("neutral_kills_per_game", role)
    avg = mean_of(rows, lambda r: r.me.neutral_kills)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="neutral_kills_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.0f} лесных крипов за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.neutral_kills, worst_reverse=False)


@detector(key="no_stacks", title="Не стакает лес", roles=(4, 5),
          requires=("camps_stacked",), impact=0.4, phase="economy", family="economy")
def no_stacks(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("camps_stacked_per_game", role)
    avg = mean_of(rows, lambda r: r.me.camps_stacked)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="camps_stacked_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} стака за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.camps_stacked, worst_reverse=False)


@detector(key="missing_runes", title="Не берёт руны", roles=(2,),
          requires=("rune_pickups",), impact=0.4, phase="economy", family="economy")
def missing_runes(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("rune_pickups_per_game", role)
    avg = mean_of(rows, lambda r: r.me.rune_pickups)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="rune_pickups_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} руны за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.rune_pickups, worst_reverse=False)


@detector(key="level_behind", title="Отстаёт по опыту", roles=(1, 2, 3, 4, 5),
          requires=("benchmarks",), impact=0.6, phase="economy", family="economy")
def level_behind(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    med = median_pct(rows, "xp_per_min")
    floor = th.bench_floor()
    if med is None or med >= floor:
        return None
    return make_leak(role=role, rows=rows, metric="xpm_pct", value=round(med, 3),
                     threshold=floor, direction="higher_is_better", source="bench",
                     magnitude=f"медиана XPM в p{round(med * 100)}",
                     worst_key=lambda r: r.me.benchmarks.get("xp_per_min", {}).get("pct", 1.0),
                     worst_reverse=False)
