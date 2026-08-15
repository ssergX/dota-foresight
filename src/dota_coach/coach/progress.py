from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.brief import CoachBrief
from dota_coach.models import Leak

_FLAT_EPS = 1e-9

_METRIC_RU = {
    "deaths_per_game": "смерти за игру",
    "gpm_pct": "GPM-перцентиль",
    "obs_per_game": "варды за игру",
}

_LEAK_RU = {
    "feeding": "смерти",
    "farm_below_bracket": "фарм",
    "low_warding": "варды",
}


@dataclass
class ProgressNote:
    status: str
    metric: str
    prev_value: float | None
    curr_value: float | None
    text: str


def _find_leak(leaks: list[Leak], key: str) -> Leak | None:
    for leak in leaks:
        if leak.key == key:
            return leak
    return None


def _fmt(metric: str, value: float) -> str:
    if metric == "gpm_pct":
        return f"p{round(value * 100)}"
    return f"{value:.1f}"


# Отслеживает только фокус-лик ИЗ ПРЕДЫДУЩЕГО брифа (подотчётность по одному лику
# намеренно; лик, который перестал быть фокусом, не отслеживается, пока снова не станет фокусом).
def compare_focus(prev_brief: CoachBrief | None, current_leaks: list[Leak]) -> ProgressNote:
    if prev_brief is None or not prev_brief.focus_leak_key:
        return ProgressNote("no_history", "", None, None,
                            "Первый разбор — базовая точка отсчёта.")

    key = prev_brief.focus_leak_key
    metric = prev_brief.focus_metric
    metric_ru = _METRIC_RU.get(metric, metric)
    prev_value = prev_brief.focus_value
    direction = prev_brief.focus_direction or "lower_is_better"

    curr_leak = _find_leak(current_leaks, key)
    if curr_leak is None:
        return ProgressNote("resolved", metric, prev_value, None,
                            f"Лик «{_LEAK_RU.get(key, key)}» больше не срабатывает — прогресс.")

    curr_value = curr_leak.value
    delta = curr_value - prev_value
    if direction == "higher_is_better":
        improved = delta > _FLAT_EPS
        regressed = delta < -_FLAT_EPS
    else:
        improved = delta < -_FLAT_EPS
        regressed = delta > _FLAT_EPS

    if not improved and not regressed:
        status, word = "flat", "без сдвига"
    elif improved:
        status, word = "improved", "прогресс"
    else:
        status, word = "regressed", "регресс"

    text = f"{metric_ru}: {_fmt(metric, prev_value)} → {_fmt(metric, curr_value)} — {word}."
    return ProgressNote(status, metric, prev_value, curr_value, text)
