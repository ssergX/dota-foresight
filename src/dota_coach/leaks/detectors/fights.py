from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, mean_of, median_pct
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="low_fight_participation", title="Не участвует в драках", roles=(3, 4, 5),
          requires=("teamfight_participation",), impact=0.7, phase="fights", family="fights")
def low_fight_participation(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("teamfight_participation", role)
    avg = mean_of(rows, lambda r: r.me.teamfight_participation)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="teamfight_participation", value=round(avg, 2),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"участие в драках {avg * 100:.0f}% (планка {thr * 100:.0f}%)",
                     worst_key=lambda r: r.me.teamfight_participation, worst_reverse=False)


@detector(key="present_no_damage", title="В драке, но без урона", roles=(1, 2, 3),
          requires=("benchmarks",), impact=0.6, phase="fights", family="fights")
def present_no_damage(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    med = median_pct(rows, "hero_damage_per_min")
    floor = th.bench_floor()
    if med is None or med >= floor:
        return None
    return make_leak(role=role, rows=rows, metric="hero_dmg_pct", value=round(med, 3),
                     threshold=floor, direction="higher_is_better", source="bench",
                     magnitude=f"медиана урона по героям в p{round(med * 100)}",
                     worst_key=lambda r: r.me.benchmarks.get("hero_damage_per_min", {}).get("pct", 1.0),
                     worst_reverse=False)
