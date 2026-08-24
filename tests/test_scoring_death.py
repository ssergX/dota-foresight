from dota_coach.models import EventCandidate, EventType, Verdict
from dota_coach.scoring import _score_one


def test_death_scored_neutral_with_reason():
    ev = EventCandidate(type=EventType.DEATH, game_time=600, involves_me=True,
                        summary="твоя смерть", data={"solo": True})
    m = _score_one(ev, weak_count=0)
    assert m.verdict == Verdict.NEUTRAL
    assert "твоя смерть" in m.reasons
    assert m.score >= 5.0   # 2.5 impact + 3.0 involves_me
