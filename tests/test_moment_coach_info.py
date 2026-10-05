import json

from dota_coach.coach.info_state import EnemyInfo, InfoState, render_info_state
from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.moment_coach import explain_moment
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict

_CANNED = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                      "checklist": ["c"], "principle": "p"})


def _info():
    return InfoState(
        time=845, my_slot=8, my_x=0.0, my_y=0.0, my_hp=300, my_max_hp=1000,
        my_mana=200.0, my_level=7, my_alive=True,
        enemies=[
            EnemyInfo(5, "CDOTA_Unit_Hero_Invoker", 0.0, 0.0, True, False, 72),
            EnemyInfo(6, "CDOTA_Unit_Hero_Pudge", 0.0, 0.0, True, True, 0),
        ],
        unseen_enemies=1, max_missing_for=72,
    )


def _moment():
    ev = EventCandidate(type=EventType.NETWORTH_SWING, game_time=845, involves_me=True,
                        summary="просадка", data={"delta": -650})
    return ScoredMoment(event=ev, score=6.5, confidence=Confidence.HIGH,
                        verdict=Verdict.MISTAKE, reasons=["просадка"])


def test_render_info_state_has_signals():
    txt = render_info_state(_info()).lower()
    assert "не видно" in txt and "72" in txt and "300" in txt  # пропажа + мой hp
    assert "invoker" in txt


def test_prompt_carries_info_block():
    msgs = build_moment_prompt(_moment(), "принцип", render_info_state(_info()))
    user = msgs[1]["content"].lower()
    assert "что было знаемо" in user and "72" in user


def test_prompt_with_info_no_outcome_leak():
    msgs = build_moment_prompt(_moment(), "p", render_info_state(_info()))
    user = msgs[1]["content"].lower()                    # _SYSTEM легитимно поминает «побед/поражений» в правиле
    for banned in ("победа", "поражени", "выигр", "проигр"):
        assert banned not in user
    whole = "".join(m["content"] for m in msgs).lower()
    for banned in ("radiant_win", "radiant_score", "dire_score"):
        assert banned not in whole


def test_explain_moment_passes_info_to_llm():
    llm = FakeLLM(_CANNED)
    explain_moment([_moment()], llm, info_state=_info())
    prompt_text = "".join(m["content"] for m in llm.calls[0])
    assert "72" in prompt_text        # инфо-состояние дошло до модели


def test_explain_moment_without_info_still_works():
    llm = FakeLLM(_CANNED)
    b = explain_moment([_moment()], llm)   # без info_state — прежнее поведение
    assert b.headline == "h"
    assert "что было знаемо" not in "".join(m["content"] for m in llm.calls[0]).lower()


def test_deep_prompt_does_not_leak_hidden_ground_truth():
    # глубокий разбор тоже не должен получать ground-truth о скрытых врагах
    from dataclasses import replace

    from dota_coach.coach.moment_coach import explain_scored

    info3 = replace(_info(), enemies_near=3, enemies_near_visible=0)
    llm = FakeLLM(_CANNED)
    explain_scored(_moment(), llm, info_state=info3)
    prompt = "".join(m["content"] for m in llm.calls[0])
    assert "ФАКТ ДЛЯ КОНТЕКСТА" not in prompt
