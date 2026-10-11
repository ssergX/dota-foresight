from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def _moment():
    return ScoredMoment(EventCandidate(EventType.TEAMFIGHT, 845, True,
                        "future death count", {"deaths": 5, "my_gold_delta": -1000}),
                        6.5, Confidence.HIGH, Verdict.MISTAKE,
                        reasons=["lost fight"])


def test_prompt_is_incident_identity_and_insufficient_status_only():
    msgs = build_moment_prompt(_moment(), "unverified causal principle")
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    assert "14:05" in user and "teamfight" in user and "not_enough_info" in user
    assert "mistake" not in user and "death" not in user and "gold_delta" not in user
    assert "unverified causal" not in user


def test_future_outcome_and_hidden_truth_cannot_change_prompt():
    m = _moment()
    first = build_moment_prompt(m, "", "")
    m.event.summary = "radiant_win true, hidden enemy behind hero"
    m.event.data = {"deaths": 0, "my_gold_delta": 10000}
    m.reasons = ["positive outcome"]
    assert build_moment_prompt(m, "future knowledge", "hidden coordinates") == first


def test_system_schema_and_no_decision_authority():
    system = build_moment_prompt(_moment(), "")[0]["content"]
    for key in ("headline", "hypothesis", "process_question", "checklist", "principle"):
        assert key in system
    assert "Не устанавливай ошибку" in system
