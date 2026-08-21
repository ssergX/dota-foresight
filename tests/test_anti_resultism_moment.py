import json
from dataclasses import asdict

from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.moment_coach import explain_moment
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict

_BANNED_TOKENS = ("radiant_win", "radiant_score", "dire_score")
_BANNED_WORDS = ("победа", "поражени", "выигр", "проигр")


def _moment():
    ev = EventCandidate(type=EventType.TEAMFIGHT, game_time=845, involves_me=True, summary="",
                        data={"deaths": 3, "my_deaths": 1, "my_gold_delta": -700})
    return ScoredMoment(event=ev, score=6.0, confidence=Confidence.LOW,
                        verdict=Verdict.NOT_ENOUGH_INFO, reasons=["слитая драка — нужен ручной разбор"])


def test_moment_prompt_and_brief_carry_no_outcome():
    focus = _moment()
    msgs = build_moment_prompt(focus, principle_for_moment(focus))
    whole = "".join(m["content"] for m in msgs).lower()
    assert not any(t in whole for t in _BANNED_TOKENS)
    user = msgs[1]["content"].lower()
    assert not any(w in user for w in _BANNED_WORDS)

    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})
    brief = explain_moment([focus], FakeLLM(canned))
    blob = str(asdict(brief)).lower()
    assert not any(t in blob for t in _BANNED_TOKENS)
    assert not any(w in blob for w in _BANNED_WORDS)
