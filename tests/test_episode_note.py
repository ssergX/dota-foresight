import json

from dota_coach.coach.episode_note import (
    EpisodeNote, build_note_prompt, explain_note, parse_note,
)
from dota_coach.coach.info_state import EnemyInfo, InfoState
from dota_coach.coach.llm import FakeLLM
from dota_coach.episodes import Episode
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def _episode(gt=600, etype=EventType.DEATH):
    ev = EventCandidate(type=etype, game_time=gt, involves_me=True,
                        summary="твоя смерть на 10:00", data={"solo": True})
    m = ScoredMoment(event=ev, score=5.0, confidence=Confidence.LOW, verdict=Verdict.NEUTRAL)
    return Episode(moment=m, severity=5.0)


def _info():
    return InfoState(
        time=600, my_slot=1, my_x=0.0, my_y=0.0, my_hp=500, my_max_hp=1000,
        my_mana=200.0, my_level=9, my_alive=True,
        enemies=[EnemyInfo(6, "CDOTA_Unit_Hero_Pudge", 0, 0, True, False, 40)],
        unseen_enemies=1, max_missing_for=40,
        allies_near=0, nearest_ally_dist=5000.0, enemies_near=2, enemies_near_visible=0,
        zone="на половине противника",
    )


def test_parse_note():
    note = parse_note(json.dumps({"situation": "с", "takeaway": "т"}))
    assert note == EpisodeNote(situation="с", takeaway="т")


def test_explain_note_returns_situation_and_takeaway():
    llm = FakeLLM(json.dumps({"situation": "оторван на чужой половине", "takeaway": "держи ТП"}))
    note = explain_note(_episode(), _info(), llm)
    assert note.situation == "оторван на чужой половине"
    assert note.takeaway == "держи ТП"
    # заземление дошло до модели
    prompt = "".join(m["content"] for m in llm.calls[0])
    assert "на половине противника" in prompt


def test_note_prompt_carries_no_outcome():
    from dota_coach.coach.info_state import render_grounding
    banned_tokens = ("radiant_win", "radiant_score", "dire_score")
    banned_words = ("победа", "поражени", "выигр", "проигр")
    msgs = build_note_prompt(_episode(), render_grounding(_info()))
    whole = "".join(m["content"] for m in msgs).lower()
    assert not any(t in whole for t in banned_tokens)
    user = msgs[1]["content"].lower()          # system легитимно несёт анти-результат-инструкцию
    assert not any(w in user for w in banned_words)
