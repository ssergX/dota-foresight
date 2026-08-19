from __future__ import annotations

from statistics import mean

from dota_coach.leaks.detectors._common import make_leak, mean_of
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="low_obs", title="Мало обсов", roles=(4, 5),
          requires=("obs_placed",), impact=0.8, phase="vision", family="vision")
def low_obs(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("obs_per_game", role)
    avg = mean_of(rows, lambda r: r.me.obs_placed)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="obs_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} обсов за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.obs_placed, worst_reverse=False)


@detector(key="low_sentries", title="Мало сентрей", roles=(4, 5),
          requires=("sen_placed",), impact=0.5, phase="vision", family="vision")
def low_sentries(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("sen_per_game", role)
    avg = mean_of(rows, lambda r: r.me.sen_placed)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="sen_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} сентрей за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.sen_placed, worst_reverse=False)


@detector(key="low_dewarding", title="Не снимает вражеский вижн", roles=(4, 5),
          requires=("observer_kills",), impact=0.5, phase="vision", family="vision")
def low_dewarding(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    # dewarding = снятые вражеские обсы (observer_kills). sentry_uses убран из requires:
    # был мёртвым условием (не влиял на фильтр) и не входит в метрику — считаем результат честно.
    thr = th.manual("dewards_per_game", role)
    avg = mean_of(rows, lambda r: float(r.me.observer_kills))
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="dewards_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} снятых вардов за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.observer_kills, worst_reverse=False)


def _avg_ward_lifetime(obs_log: list[dict], obs_left_log: list[dict]) -> float | None:
    if not obs_log or not obs_left_log:
        return None
    left_by_handle = {e.get("ehandle"): e.get("time") for e in obs_left_log if "ehandle" in e}
    spans = []
    for e in obs_log:
        h, placed = e.get("ehandle"), e.get("time")
        removed = left_by_handle.get(h)
        if placed is not None and removed is not None and removed > placed:
            spans.append(removed - placed)
    return float(mean(spans)) if spans else None


@detector(key="wards_die_fast", title="Варды живут мало", roles=(4, 5),
          requires=("obs_log", "obs_left_log"), impact=0.5, phase="vision", family="vision")
def wards_die_fast(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("obs_lifetime_s", role)
    usable = [(r, _avg_ward_lifetime(r.me.obs_log, r.me.obs_left_log)) for r in rows]
    usable = [(r, v) for r, v in usable if v is not None]
    if thr is None or len(usable) < 5:
        return None
    avg = float(mean(v for _, v in usable))
    if avg >= thr:
        return None
    kept = [r for r, _ in usable]
    life = {r.match_id: v for r, v in usable}
    return make_leak(role=role, rows=kept, metric="obs_lifetime_s", value=round(avg, 0),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"варды живут в среднем {avg:.0f}с (планка {thr:.0f}с)",
                     worst_key=lambda r: life[r.match_id], worst_reverse=False)
