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


def _match_with_death():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=1, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100], xp_t=[0, 0])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[], objectives=[])


def _replay_blind_full_hp_death():
    # заход в 595с на фулл-ХП, 3 непросвеченных живых врага; смерть в 600с (hp 0)
    def frame(t, alive, hp):
        me = UnitState(slot=1, x=0, y=0, hp=hp, max_hp=100, mana=100, level=9, xp=0, alive=alive)
        # 3 живых врага далеко (не видно)
        en = {s: UnitState(slot=s, x=9000, y=9000, hp=100, max_hp=100, mana=0,
                           level=9, xp=0, alive=True) for s in (6, 7, 8)}
        return ReplayFrame(time=t, units={1: me, **en})
    frames = [frame(t, alive=(t < 600), hp=(0 if t >= 600 else 100)) for t in range(0, 660, 5)]
    return ParsedReplay(match_id=1, game_start_time=0,
                        heroes={1: "Lina", 6: "Pudge", 7: "Storm", 8: "LC"},
                        frames=frames, teams={1: 2, 6: 3, 7: 3, 8: 3})


def test_death_severity_bonus_uses_pre_death_state():
    from dota_coach.episodes import _severity
    eps = build_episodes(_match_with_death(), _replay_blind_full_hp_death(), account_id=7)
    death = next(e for e in eps if e.moment.event.game_time == 600)
    # 5с до смерти: full HP + 3 непросвеченных -> бонус +5 к базовому score
    assert death.severity >= death.moment.score + 5.0
