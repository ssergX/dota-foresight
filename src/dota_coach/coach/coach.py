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

_FOCUS_PRIORITY = ["feeding", "farm_below_bracket", "low_warding"]


def _select_focus(leaks: list[Leak]) -> Leak | None:
    if not leaks:
        return None

    def deviation(leak: Leak) -> float:
        if not leak.threshold:
            return abs(leak.value)
        return abs(leak.value - leak.threshold) / abs(leak.threshold)

    def priority(leak: Leak) -> int:
        return _FOCUS_PRIORITY.index(leak.key) if leak.key in _FOCUS_PRIORITY else len(_FOCUS_PRIORITY)

    return sorted(leaks, key=lambda leak: (-deviation(leak), priority(leak)))[0]


def run_coach(matches: list[Match], account_id: int | None, llm: CoachLLM,
              cache_dir: Path = Path("cache")) -> CoachBrief:
    leaks = detect_leaks(matches, account_id)
    match_ids = [m.match_id for m in matches]
    prior = latest_brief(account_id, cache_dir)
    progress = compare_focus(prior, leaks)
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

    save_brief(account_id, brief, cache_dir)
    return brief
