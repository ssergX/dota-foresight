from dota_coach.coach.episode_card import EpisodeCard, build_card
from dota_coach.episodes import Episode
from dota_coach.models import (
    Confidence, EventCandidate, EventType, ParsedReplay, ReplayFrame, ScoredMoment,
    UnitState, Verdict,
)


def _episode(game_time=600):
    ev = EventCandidate(type=EventType.DEATH, game_time=game_time, involves_me=True,
                        summary="твоя смерть на 10:00", data={"solo": True})
    m = ScoredMoment(event=ev, score=5.0, confidence=Confidence.LOW, verdict=Verdict.NEUTRAL)
    return Episode(moment=m, severity=5.0)


def _replay():
    me = UnitState(slot=1, x=0, y=0, hp=50, max_hp=100, mana=200, level=9, xp=0, alive=True)
    enemy = UnitState(slot=6, x=9000, y=9000, hp=100, max_hp=100, mana=0, level=9, xp=0, alive=True)
    frames = [ReplayFrame(time=t, units={1: me, 6: enemy}) for t in range(0, 601, 10)]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina", 6: "Pudge"},
                        frames=frames, teams={1: 2, 6: 3})


def test_build_card_with_replay_has_facts_from_info_state():
    card = build_card(_episode(), _replay(), my_slot=1)
    assert isinstance(card, EpisodeCard)
    assert card.game_time == 600
    assert card.info is not None
    assert "HP" in card.facts            # render_info_state текст
    assert card.numbers == {"solo": True}


def test_build_card_without_replay_falls_back_to_summary():
    card = build_card(_episode(), None, my_slot=1)
    assert card.info is None
    assert card.facts == "твоя смерть на 10:00"


def test_build_card_grounds_at_decision_time():
    ep = _episode(game_time=600)
    ep.decision_time = 580                       # точка решения раньше смерти
    card = build_card(ep, _replay(), my_slot=1)
    assert card.game_time == 600                 # таймстамп/клип остаются на моменте смерти
    assert card.info is not None and card.info.time == 580   # разбор грунтится в точке решения
