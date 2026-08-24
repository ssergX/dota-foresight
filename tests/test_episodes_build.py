from dota_coach.episodes import Episode, build_episodes, slot_index
from dota_coach.models import (
    Match, ParsedReplay, PlayerMatch, ReplayFrame, Teamfight, UnitState,
)


def _u(alive, hp=100):
    return UnitState(slot=0, x=0, y=0, hp=hp, max_hp=100, mana=0, level=1, xp=0, alive=alive)


def _match():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=2, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100, 700, 100], xp_t=[0, 0, 0, 0])
    tf = Teamfight(start=120, end=140, deaths=3,
                   players=[{"deaths": 1, "gold_delta": -300, "damage": 100}])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[tf], objectives=[])


def _replay():
    # death at 600 (solo, far from teamfight@120), death at 130 (inside teamfight -> folded)
    frames = []
    for t in range(0, 700, 10):
        alive = not (t in (130, 600))
        frames.append(ReplayFrame(time=t, units={1: _u(alive)}))
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina"},
                        frames=frames, teams={1: 2})


def test_build_episodes_has_teamfight_and_solo_death_not_folded():
    eps = build_episodes(_match(), _replay(), account_id=7)
    kinds = [e.moment.event.type.value for e in eps]
    times = [e.moment.event.game_time for e in eps]
    assert "teamfight" in kinds
    assert 600 in times            # solo death kept
    assert 130 not in times        # death inside teamfight window folded away
    assert times == sorted(times)  # chronological
    assert all(isinstance(e, Episode) for e in eps)


def test_slot_index():
    assert slot_index(1) == 1
    assert slot_index(130) == 7
