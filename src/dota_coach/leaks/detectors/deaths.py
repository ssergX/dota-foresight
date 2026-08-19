from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, mean_of
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="feeding", title="Слишком много смертей", roles=(1, 2, 3, 4, 5),
          requires=("deaths",), impact=1.0, phase="deaths", family="deaths")
def feeding(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("deaths_per_game", role)
    avg = mean_of(rows, lambda r: r.me.deaths)
    if thr is None or avg <= thr:
        return None
    return make_leak(role=role, rows=rows, metric="deaths_per_game", value=round(avg, 1),
                     threshold=thr, direction="lower_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} смертей за игру (порог {thr:.0f})",
                     worst_key=lambda r: r.me.deaths, worst_reverse=True)


@detector(key="time_dead", title="Долго лежит мёртвым", roles=(1, 2, 3, 4, 5),
          requires=("life_state_dead",), impact=0.7, phase="deaths", family="deaths")
def time_dead(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("time_dead_frac", role)
    frac = mean_of(rows, lambda r: r.me.life_state_dead / r.duration if r.duration else 0.0)
    if thr is None or frac <= thr:
        return None
    return make_leak(role=role, rows=rows, metric="time_dead_frac", value=round(frac, 3),
                     threshold=thr, direction="lower_is_better", source="manual",
                     magnitude=f"в среднем {frac * 100:.0f}% игры мёртвым (порог {thr * 100:.0f}%)",
                     worst_key=lambda r: r.me.life_state_dead / (r.duration or 1), worst_reverse=True)


def _hero_max(r: Row) -> float:
    # killed_by содержит крипов/вышки/нейтралов — считаем только героев (npc_dota_hero_*)
    return float(max((v for k, v in r.me.killed_by.items() if k.startswith("npc_dota_hero_")),
                     default=0))


def _hero_totals(rows: list[Row]) -> dict[str, float]:
    # суммируем убийства одним и тем же героем по всей серии матчей (killed_by содержит
    # только крипов/вышки/нейтралов/героев за конкретный матч — их НЕ считаем, кроме героев)
    totals: dict[str, float] = {}
    for r in rows:
        for k, v in r.me.killed_by.items():
            if k.startswith("npc_dota_hero_"):
                totals[k] = totals.get(k, 0.0) + v
    return totals


@detector(key="repeat_victim", title="Одна и та же жертва", roles=(1, 2, 3, 4, 5),
          requires=("killed_by",), impact=0.5, phase="deaths", family="deaths")
def repeat_victim(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("repeat_victim_kills", role)
    # metric = "суммарно один герой убил ≥ N раз по серии" (thresholds.py) — сумма
    # по одному герою за всю рассматриваемую серию матчей, а не среднее за игру.
    worst_total = max(_hero_totals(rows).values(), default=0.0)
    if thr is None or worst_total <= thr:
        return None
    return make_leak(role=role, rows=rows, metric="repeat_victim_kills", value=round(worst_total, 1),
                     threshold=thr, direction="lower_is_better", source="manual",
                     magnitude=f"один герой убил вас суммарно {worst_total:.0f} раз за серию",
                     worst_key=_hero_max, worst_reverse=True)
