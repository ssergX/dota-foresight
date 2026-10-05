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


def _hp_frame(t, hp, alive):
    return ReplayFrame(time=t, units={
        0: UnitState(slot=0, x=0, y=0, hp=hp, max_hp=100, mana=0, level=1, xp=0, alive=alive)})


def test_decision_time_is_last_safe_moment_before_death():
    from dota_coach.episodes import _decision_time
    from dota_coach.models import EventCandidate, EventType
    # HP полный до 8с, спад 9-10, смерть в 11с -> точка решения = 8 (последний безопасный),
    # не 11 (уже мёртв) и не 6 (произвольное −5с)
    frames = ([_hp_frame(t, 100, True) for t in range(0, 9)]
              + [_hp_frame(9, 60, True), _hp_frame(10, 20, True), _hp_frame(11, 0, False)])
    parsed = ParsedReplay(match_id=1, game_start_time=0, heroes={0: "Lina"},
                          frames=frames, teams={0: 2})
    ev = EventCandidate(type=EventType.DEATH, game_time=11, involves_me=True, summary="", data={})
    assert _decision_time(parsed, 0, ev) == 8


def test_decision_time_non_death_is_event_time():
    from dota_coach.episodes import _decision_time
    from dota_coach.models import EventCandidate, EventType
    parsed = ParsedReplay(match_id=1, game_start_time=0, heroes={0: "Lina"},
                          frames=[_hp_frame(0, 100, True)], teams={0: 2})
    ev = EventCandidate(type=EventType.TEAMFIGHT, game_time=300, involves_me=True, summary="", data={})
    assert _decision_time(parsed, 0, ev) == 300
