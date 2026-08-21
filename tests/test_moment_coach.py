import json

from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.moment_coach import explain_moment
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict

_CANNED = json.dumps({
    "headline": "заголовок-от-ллм", "hypothesis": "вероятно зашёл без вижна",
    "process_question": "был ли эскейп?", "checklist": ["проверь варды", "проверь CD"],
    "principle": "вижн перед заходом",
})


def _m(score, verdict, t, etype=EventType.NETWORTH_SWING):
    ev = EventCandidate(type=etype, game_time=t, involves_me=True, summary="", data={"delta": -600})
    return ScoredMoment(event=ev, score=score, confidence=Confidence.HIGH, verdict=verdict, reasons=["r"])


def test_explain_builds_brief_and_stamps_identity_by_code():
    moments = [_m(3.0, Verdict.NOT_ENOUGH_INFO, 100), _m(6.0, Verdict.MISTAKE, 845)]
    llm = FakeLLM(_CANNED)
    brief = explain_moment(moments, llm)
    assert brief.headline == "заголовок-от-ллм"          # текст от ЛЛМ
    assert brief.checklist == ["проверь варды", "проверь CD"]
    # идентичность ставит КОД по выбранному фокусу (mistake @ 845), не ЛЛМ:
    assert brief.game_time == 845
    assert brief.verdict == "mistake"
    assert brief.event_type == "networth_swing"
    assert len(llm.calls) == 1


def test_explain_no_moments_returns_none_and_skips_llm():
    llm = FakeLLM(_CANNED)
    assert explain_moment([], llm) is None
    assert llm.calls == []
