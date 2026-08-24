from dota_coach.episodes import Episode, select_deep
from dota_coach.models import (
    Confidence, EventCandidate, EventType, ScoredMoment, Verdict,
)


def _ep(game_time, severity, verdict=Verdict.NEUTRAL):
    ev = EventCandidate(type=EventType.DEATH, game_time=game_time, involves_me=True,
                        summary="", data={})
    m = ScoredMoment(event=ev, score=severity, confidence=Confidence.LOW, verdict=verdict)
    return Episode(moment=m, severity=severity)


def test_select_deep_picks_highest_severity_first():
    eps = [_ep(100, 2.0), _ep(200, 9.0), _ep(300, 5.0)]
    top = select_deep(eps, n=1)
    assert [e.moment.event.game_time for e in top] == [200]


def test_select_deep_prefers_mistake_verdict_over_neutral():
    eps = [_ep(100, 9.0, Verdict.NEUTRAL), _ep(200, 1.0, Verdict.MISTAKE)]
    top = select_deep(eps, n=1)
    assert top[0].moment.event.game_time == 200   # mistake ранжируется выше
