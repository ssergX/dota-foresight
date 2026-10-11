from __future__ import annotations

from pathlib import Path

from dota_coach.coach.brief import CoachBrief, Drill
from dota_coach.coach.history import latest_brief, save_brief
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.progress import compare_focus
from dota_coach.leaks import detect_leaks
from dota_coach.models import Leak, Match

LEGACY_DETECTOR_VERSION = "legacy-descriptive.s0.v1"


def _select_focus(leaks: list[Leak]) -> Leak | None:
    return leaks[0] if leaks else None


def run_coach(matches: list[Match], account_id: int | None, llm: CoachLLM,
              cache_dir: Path = Path("cache")) -> CoachBrief:
    leaks = detect_leaks(matches, account_id)
    match_ids = list(dict.fromkeys(m.match_id for m in matches))
    prior = latest_brief(account_id, cache_dir)
    # The legacy provider does not supply patch/source/coverage identity.
    # Do not invent comparability from matching metric names alone.
    progress = compare_focus(prior, leaks, match_ids=match_ids,
                             detector_version=LEGACY_DETECTOR_VERSION)
    focus = _select_focus(leaks)
    if focus is None:
        brief = CoachBrief(
            focus_leak_key="", headline="Описательные сигналы не обнаружены",
            diagnosis="Отсутствие сигнала не подтверждает хорошую игру: охват и качество решений не установлены.",
            why_it_costs="", drills=[],
        )
    else:
        # No validated criterion accompanies Leak. A model cannot upgrade an
        # aggregate threshold crossing into a decision/habit diagnosis.
        brief = CoachBrief(
            focus_leak_key=focus.key,
            headline="Описательный сигнал для ручной проверки",
            diagnosis=f"pos{focus.role}: {focus.metric}={focus.value:.3f}; "
                      f"порог={focus.threshold:.3f}; выборка={focus.sample_size}. "
                      "Это отклонение метрики, а не доказанная ошибка или привычка.",
            why_it_costs="Причина и цена решений не установлены; нужен разбор доступной информации и альтернатив.",
            drills=[Drill("Просмотри примеры и запиши доступную до выбора информацию, "
                          "ресурсы и ограничения. Проверь также эпизоды без этого сигнала.",
                          metric_ref=focus.metric)],
            focus_metric=focus.metric, focus_value=focus.value,
            focus_direction=focus.direction, focus_role=focus.role,
        )
    brief.progress_note = progress.text if progress.status != "no_history" else None
    brief.generated_for_matches = match_ids
    brief.detector_version = LEGACY_DETECTOR_VERSION
    brief.leaks_snapshot = [
        {"key": l.key, "metric": l.metric, "value": l.value,
         "direction": l.direction, "role": l.role, "source": l.source,
         "confidence": l.confidence.value, "sample_size": l.sample_size,
         "considered": l.considered}
        for l in leaks
    ]
    save_brief(account_id, brief, cache_dir)
    return brief
