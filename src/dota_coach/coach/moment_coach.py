from __future__ import annotations

from dota_coach.coach.info_state import InfoState, render_grounding
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief, parse_moment_brief
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import ScoredMoment


def explain_scored(moment: ScoredMoment, llm: CoachLLM,
                   info_state: InfoState | None = None) -> MomentBrief:
    principle = principle_for_moment(moment)
    info_block = render_grounding(info_state) if info_state is not None else ""
    messages = build_moment_prompt(moment, principle, info_block)
    brief = parse_moment_brief(llm.complete(messages))
    # идентичность момента ставит КОД (детерминизм + анти-результатничество):
    brief.game_time = moment.event.game_time
    brief.verdict = moment.verdict.value
    brief.event_type = moment.event.type.value
    return brief


def explain_moment(moments: list[ScoredMoment], llm: CoachLLM,
                   info_state: InfoState | None = None) -> MomentBrief | None:
    focus = select_focus_moment(moments)
    if focus is None:
        return None
    return explain_scored(focus, llm, info_state)
