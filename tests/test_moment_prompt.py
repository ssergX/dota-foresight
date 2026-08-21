from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def _moment():
    ev = EventCandidate(type=EventType.NETWORTH_SWING, game_time=845, involves_me=True,
                        summary="просадка", data={"delta": -650})
    return ScoredMoment(event=ev, score=6.5, confidence=Confidence.HIGH,
                        verdict=Verdict.MISTAKE, reasons=["измеримая просадка нетворса"])


def test_prompt_shape_and_content():
    msgs = build_moment_prompt(_moment(), "принцип про нетворс")
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    assert "14:05" in user            # 845s -> 14:05
    assert "networth_swing" in user
    assert "mistake" in user
    assert "принцип про нетворс" in user


def test_system_fixes_json_schema_and_hypothesis_rule():
    system = build_moment_prompt(_moment(), "p")[0]["content"]
    for key in ("headline", "hypothesis", "process_question", "checklist", "principle"):
        assert key in system
    assert "гипотез" in system.lower()   # правило «формулируй гипотезу, не факт»


def test_prompt_never_leaks_outcome():
    msgs = build_moment_prompt(_moment(), "p")
    user = msgs[1]["content"].lower()
    for banned in ("победа", "поражени", "выигр", "проигр"):
        assert banned not in user
    whole = "".join(m["content"] for m in msgs).lower()
    for banned in ("radiant_win", "radiant_score", "dire_score"):
        assert banned not in whole
