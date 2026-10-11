from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.moment_coach import explain_moment, explain_scored
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def _m(score, verdict, time):
    return ScoredMoment(EventCandidate(EventType.NETWORTH_SWING, time, True,
                        "future result", {"delta": -600}), score, Confidence.HIGH, verdict)


def test_unverified_mistake_cannot_authorize_llm_accusations():
    llm = FakeLLM('{"headline": "Ты виноват"}')
    brief = explain_moment([_m(3., Verdict.NEUTRAL, 100), _m(6., Verdict.MISTAKE, 845)], llm)
    assert brief.game_time == 845
    assert brief.verdict == "not_enough_info"
    assert brief.event_type == "networth_swing"
    assert "ручного" in brief.headline
    assert llm.calls == []


def test_explain_no_moments_returns_none():
    llm = FakeLLM("{}")
    assert explain_moment([], llm) is None
    assert llm.calls == []


def test_future_data_changes_do_not_change_legacy_explanation():
    moment = _m(3., Verdict.MISTAKE, 100)
    llm = FakeLLM("{}")
    before = explain_scored(moment, llm)
    moment.event.summary = "team killed everyone"
    moment.event.data = {"my_gold_delta": 9000, "deaths": 5, "hidden_enemies": 5}
    moment.reasons = ["wrong decision"]
    assert explain_scored(moment, llm) == before
    assert llm.calls == []
