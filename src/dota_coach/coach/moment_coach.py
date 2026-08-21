from __future__ import annotations

from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief, parse_moment_brief
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import ScoredMoment


def explain_moment(moments: list[ScoredMoment], llm: CoachLLM) -> MomentBrief | None:
    focus = select_focus_moment(moments)
    if focus is None:
        return None
    principle = principle_for_moment(focus)
    messages = build_moment_prompt(focus, principle)
    brief = parse_moment_brief(llm.complete(messages))
    # идентичность момента ставит КОД (не ЛЛМ) — детерминизм и анти-результатничество:
    brief.game_time = focus.event.game_time
    brief.verdict = focus.verdict.value
    brief.event_type = focus.event.type.value
    return brief
