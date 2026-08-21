from dota_coach.coach.info_state import info_state_at
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState, WardEvent


def _u(slot, x, y, alive=True, hp=600):
    return UnitState(slot=slot, x=x, y=y, hp=hp, max_hp=600, mana=100.0, level=1, xp=0, alive=alive)


def _frame(t, me_xy, en_xy, en_alive=True):
    return ReplayFrame(time=t, units={0: _u(0, *me_xy), 5: _u(5, *en_xy, alive=en_alive)})


def _replay(frames, wards=None):
    return ParsedReplay(
        match_id=1, game_start_time=0.0,
        heroes={0: "CDOTA_Unit_Hero_Axe", 5: "CDOTA_Unit_Hero_Pudge"},
        frames=frames, teams={0: 2, 5: 3}, wards=wards or [],
    )


def test_enemy_close_is_visible():
    r = _replay([_frame(0, (0, 0), (100, 0))])
    s = info_state_at(r, 0, my_slot=0)
    e = s.enemies[0]
    assert e.slot == 5 and e.visible is True and e.missing_for == 0
    assert s.unseen_enemies == 0


def test_enemy_far_is_missing_with_growing_duration():
    r = _replay([_frame(0, (0, 0), (100, 0)),      # виден
                 _frame(1, (0, 0), (5000, 0)),     # ушёл из вижна
                 _frame(2, (0, 0), (6000, 0))])
    s = info_state_at(r, 2, my_slot=0)
    e = s.enemies[0]
    assert e.visible is False
    assert e.missing_for == 2                       # last seen at t=0, now t=2
    assert s.unseen_enemies == 1 and s.max_missing_for == 2


def test_ward_grants_vision():
    # враг далеко от героя, но рядом со СВОИМ (team 2) обс-вардом
    wards = [WardEvent(id=1, time=0, kind="obs", team=2, x=5000.0, y=0.0, op="placed")]
    r = _replay([_frame(0, (0, 0), (100, 0)), _frame(1, (0, 0), (5050, 0))], wards=wards)
    s = info_state_at(r, 1, my_slot=0)
    assert s.enemies[0].visible is True and s.enemies[0].missing_for == 0


def test_my_resources_and_view_from_enemy_side():
    r = _replay([_frame(0, (10, 20), (100, 0), en_alive=True)])
    s = info_state_at(r, 0, my_slot=5)              # смотрим глазами Dire (slot 5)
    assert s.my_slot == 5 and s.my_x == 100.0
    assert [e.slot for e in s.enemies] == [0]       # враги для slot5 — team 2 = slot 0
    assert s.enemies[0].hero == "CDOTA_Unit_Hero_Axe"


def test_dead_enemy_not_counted_visible():
    r = _replay([_frame(0, (0, 0), (100, 0), en_alive=False)])
    s = info_state_at(r, 0, my_slot=0)
    assert s.enemies[0].alive is False
    assert s.unseen_enemies == 0                     # мёртвых не считаем «пропавшими»
