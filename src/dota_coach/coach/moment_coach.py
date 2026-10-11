from __future__ import annotations

from dota_coach.coach.info_state import InfoState
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.models import ScoredMoment, Verdict


def explain_scored(moment: ScoredMoment, llm: CoachLLM,
                   info_state: InfoState | None = None) -> MomentBrief:
    # Legacy incident heuristics have no validated criterion/claims.
    # An old MISTAKE label cannot authorize a model to accuse the player.
    return MomentBrief(
        headline="Повод для ручного просмотра",
        hypothesis="Недостаточно данных для оценки решения: проверенный критерий отсутствует.",
        process_question="Какая информация и какие действия были доступны до выбора?",
        checklist=["Проверь информацию до выбора на записи.",
                   "Проверь ресурсы, ограничения и выполнимость альтернатив."],
        principle="Сам исход эпизода не устанавливает качество решения.",
        game_time=moment.event.game_time, verdict=Verdict.NOT_ENOUGH_INFO.value,
        event_type=moment.event.type.value,
    )


def explain_moment(moments: list[ScoredMoment], llm: CoachLLM,
                   info_state: InfoState | None = None) -> MomentBrief | None:
    focus = select_focus_moment(moments)
    return None if focus is None else explain_scored(focus, llm, info_state)
