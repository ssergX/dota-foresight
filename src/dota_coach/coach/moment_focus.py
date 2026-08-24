from __future__ import annotations

from dota_coach.models import ScoredMoment, Verdict

# mistake первым (есть измеримая ошибка); not_enough_info последним (данные не докажут)
VERDICT_RANK = {
    Verdict.MISTAKE: 0,
    Verdict.NEUTRAL: 1,
    Verdict.FINE_VARIANCE: 1,
    Verdict.NOT_ENOUGH_INFO: 2,
}


def select_focus_moment(moments: list[ScoredMoment]) -> ScoredMoment | None:
    if not moments:
        return None
    return sorted(
        moments,
        key=lambda m: (VERDICT_RANK.get(m.verdict, 9), -m.score, m.event.game_time),
    )[0]
