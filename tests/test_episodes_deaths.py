from dota_coach.episodes import my_death_times
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState


def _u(alive):
    return UnitState(slot=0, x=0, y=0, hp=100 if alive else 0, max_hp=100,
                     mana=0, level=1, xp=0, alive=alive)


def _replay(alive_by_time):
    frames = [ReplayFrame(time=t, units={0: _u(a)}) for t, a in alive_by_time]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={0: "Lina"},
                        frames=frames, teams={0: 2})


def test_death_and_respawn_then_second_death():
    # alive, alive, DEAD@3, dead, ALIVE@5 (respawn), DEAD@7
    parsed = _replay([(1, True), (2, True), (3, False), (4, False),
                      (5, True), (6, True), (7, False)])
    assert my_death_times(parsed, 0) == [3, 7]


def test_no_deaths():
    parsed = _replay([(1, True), (2, True)])
    assert my_death_times(parsed, 0) == []
