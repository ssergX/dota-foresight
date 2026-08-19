from __future__ import annotations

from pathlib import Path

from dota_coach.coach.brief import CoachBrief, parse_brief
from dota_coach.coach.history import latest_brief, save_brief
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.principles import principles_for
from dota_coach.coach.progress import compare_focus
from dota_coach.coach.prompt import build_coach_prompt
from dota_coach.leaks import detect_leaks
from dota_coach.models import Leak, Match


def _select_focus(leaks: list[Leak]) -> Leak | None:
    # detect_leaks уже возвращает список, ранжированный по severity (фокус первым).
    return leaks[0] if leaks else None


def run_coach(matches: list[Match], account_id: int | None, llm: CoachLLM,
              cache_dir: Path = Path("cache")) -> CoachBrief:
    leaks = detect_leaks(matches, account_id)
    match_ids = [m.match_id for m in matches]
    prior = latest_brief(account_id, cache_dir)
    progress = compare_focus(prior, leaks)
    if prior is not None and getattr(prior, "baseline_reset", False):
        from dota_coach.coach.progress import ProgressNote

        progress = ProgressNote("baseline_reset", "obs_per_game", None, None,
                                "Метрика вардов переведена на ролевую основу — сравнение начинается заново.")
    focus = _select_focus(leaks)

    if focus is None:
        brief = CoachBrief(
            focus_leak_key="",
            headline="Системных ликов по этой серии не найдено",
            diagnosis="",
            why_it_costs="",
            drills=[],
            progress_note=(progress.text if progress.status != "no_history" else None),
            generated_for_matches=match_ids,
        )
        brief.leaks_snapshot = [
            {"key": l.key, "metric": l.metric, "value": l.value,
             "direction": l.direction, "role": l.role}
            for l in leaks
        ]
        save_brief(account_id, brief, cache_dir)
        return brief

    principles = principles_for(focus.key)
    messages = build_coach_prompt(leaks, progress, principles, prior, focus.key)
    brief = parse_brief(llm.complete(messages))

    # фокус и снимок метрики ставит КОД (не ЛЛМ) — чтобы петля была детерминированной:
    brief.focus_leak_key = focus.key
    brief.focus_metric = focus.metric
    brief.focus_value = focus.value
    brief.focus_direction = focus.direction
    brief.progress_note = progress.text if progress.status != "no_history" else None
    brief.generated_for_matches = match_ids
    brief.leaks_snapshot = [
        {"key": l.key, "metric": l.metric, "value": l.value,
         "direction": l.direction, "role": l.role}
        for l in leaks
    ]

    save_brief(account_id, brief, cache_dir)
    return brief
