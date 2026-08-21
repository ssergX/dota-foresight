from dota_coach.models import ParsedReplay, ReplayFrame, UnitState


def _u(slot, x=0.0, y=0.0):
    return UnitState(slot=slot, x=x, y=y, hp=100, max_hp=100, mana=50.0, level=1, xp=0, alive=True)


def _frame(t):
    return ReplayFrame(time=t, units={0: _u(0), 5: _u(5)})


def _replay(times):
    return ParsedReplay(match_id=1, game_start_time=200.0,
                        heroes={0: "CDOTA_Unit_Hero_Axe"},
                        frames=[_frame(t) for t in times])


def test_frame_at_exact():
    r = _replay([0, 10, 20])
    assert r.frame_at(10).time == 10


def test_frame_at_between_returns_latest_leq():
    r = _replay([0, 10, 20])
    assert r.frame_at(15).time == 10


def test_frame_at_before_first_returns_none():
    r = _replay([10, 20])
    assert r.frame_at(5) is None


def test_frame_at_after_last_returns_last():
    r = _replay([0, 10, 20])
    assert r.frame_at(999).time == 20
