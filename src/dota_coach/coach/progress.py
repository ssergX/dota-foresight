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
def compare_focus(prev_brief: CoachBrief | None, current_leaks: list[Leak], *,
                  match_ids: list[int] | None = None, detector_version: str = "",
                  source_version: str = "", coverage_signature: str = "") -> ProgressNote:
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
        return ProgressNote("insufficient_data", metric, prev_value, None,
                            "Сигнал отсутствует; это не доказывает улучшение или исправление привычки.")

    comparable = (
        bool(match_ids) and bool(prev_brief.generated_for_matches)
        and not set(match_ids).intersection(prev_brief.generated_for_matches)
        and len(match_ids) == len(set(match_ids))
        and len(prev_brief.generated_for_matches) == len(set(prev_brief.generated_for_matches))
        and prev_brief.focus_role is not None and curr_leak.role == prev_brief.focus_role
        and metric == curr_leak.metric and direction == curr_leak.direction
        and bool(detector_version) and detector_version == prev_brief.detector_version
        and bool(source_version) and source_version == prev_brief.source_version
        and bool(coverage_signature) and coverage_signature == prev_brief.coverage_signature
        and not prev_brief.baseline_reset
    )
    if not comparable:
        return ProgressNote("insufficient_data", metric, prev_value, curr_leak.value,
                            "Недостаточно сравнимых данных: нужны отдельные периоды, одинаковые роль, версии и покрытие.")

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
        status, word = "improved", "метрика снизилась" if direction != "higher_is_better" else "метрика выросла"
    else:
        status, word = "regressed", "метрика выросла" if direction != "higher_is_better" else "метрика снизилась"

    text = f"{metric_ru}: {_fmt(metric, prev_value)} → {_fmt(metric, curr_value)} — {word}. Качество решений по этой метрике не установлено."
    return ProgressNote(status, metric, prev_value, curr_value, text)
