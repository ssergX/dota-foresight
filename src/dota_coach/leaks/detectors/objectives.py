from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, median_pct
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="low_tower_damage", title="Мало урона по строениям", roles=(1, 2, 3),
          requires=("benchmarks",), impact=0.6, phase="objectives", family="objectives")
def low_tower_damage(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    med = median_pct(rows, "tower_damage")
    floor = th.bench_floor()
    if med is None or med >= floor:
        return None
    return make_leak(role=role, rows=rows, metric="tower_damage_pct", value=round(med, 3),
                     threshold=floor, direction="higher_is_better", source="bench",
                     magnitude=f"медиана урона по вышкам в p{round(med * 100)}",
                     worst_key=lambda r: r.me.benchmarks.get("tower_damage", {}).get("pct", 1.0),
                     worst_reverse=False)
