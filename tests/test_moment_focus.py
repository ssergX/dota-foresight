from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def _m(score, verdict, t, etype=EventType.TEAMFIGHT):
    ev = EventCandidate(type=etype, game_time=t, involves_me=True, summary="", data={})
    return ScoredMoment(event=ev, score=score, confidence=Confidence.LOW, verdict=verdict, reasons=[])


def test_empty_returns_none():
    assert select_focus_moment([]) is None


def test_mistake_preferred_over_higher_score_not_enough_info():
    nei = _m(score=99.0, verdict=Verdict.NOT_ENOUGH_INFO, t=100)   # выше score, но not_enough_info
    mistake = _m(score=5.0, verdict=Verdict.MISTAKE, t=200)
    assert select_focus_moment([nei, mistake]) is mistake


def test_among_same_verdict_higher_score_wins():
    a = _m(score=3.0, verdict=Verdict.MISTAKE, t=100)
    b = _m(score=8.0, verdict=Verdict.MISTAKE, t=200)
    assert select_focus_moment([a, b]) is b


def test_deterministic_tiebreak_by_game_time():
    a = _m(score=5.0, verdict=Verdict.MISTAKE, t=100)
    b = _m(score=5.0, verdict=Verdict.MISTAKE, t=300)
    assert select_focus_moment([a, b]) is a
    assert select_focus_moment([b, a]) is a   # порядок входа не влияет
