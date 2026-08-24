import json

from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.match_review import MatchReview, review_match
from dota_coach.models import (
    Match, ParsedReplay, PlayerMatch, ReplayFrame, Teamfight, UnitState,
)


def _u(alive, hp=100):
    return UnitState(slot=0, x=0, y=0, hp=hp, max_hp=100, mana=0, level=1, xp=0, alive=alive)


def _match():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=1, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100, 200], xp_t=[0, 0, 0])
    tf = Teamfight(start=120, end=140, deaths=3,
                   players=[{"deaths": 1, "gold_delta": -300, "damage": 100}])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[tf], objectives=[])


def _replay():
    frames = [ReplayFrame(time=t, units={1: _u(t != 600)}) for t in range(0, 700, 10)]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina"},
                        frames=frames, teams={1: 2})


def test_review_match_returns_notes_for_all_and_one_deep_brief():
    # canned несёт ключи и брифа, и комментария — FakeLLM отдаёт одно на все вызовы
    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p",
                         "situation": "ситуация", "takeaway": "совет"})
    review = review_match(_match(), _replay(), account_id=7, llm=FakeLLM(canned), deep_n=1)
    assert isinstance(review, MatchReview)
    n = len(review.episodes)
    assert len(review.cards) == n >= 2
    assert len(review.deep_briefs) == 1                       # один острый — полный разбор
    assert len(review.notes) == n - 1                         # остальные — комментарии
    # каждый эпизод покрыт ровно одним: комментарий ИЛИ бриф
    times = {e.moment.event.game_time for e in review.episodes}
    assert set(review.notes) | set(review.deep_briefs) == times
    assert not (set(review.notes) & set(review.deep_briefs))
    assert list(review.notes.values())[0].takeaway == "совет"
