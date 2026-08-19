from dota_coach.leaks.rows import Row, build_rows
from dota_coach.leaks.roles import role_of, segment_by_role
from dota_coach.models import Match, PlayerMatch


def _me(**kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return PlayerMatch(**base)


def _match(mid, me, parsed=True):
    return Match(match_id=mid, duration=1800, radiant_win=True, players=[me], parsed=parsed)


def test_role_from_position_est_wins():
    assert role_of(_me(position_est=3, lane_role=1)) == 3


def test_role_fallback_lane_role_and_roaming():
    assert role_of(_me(position_est=None, lane_role=2)) == 2                      # mid
    assert role_of(_me(position_est=None, lane_role=1, is_roaming=False)) == 1    # safe carry
    assert role_of(_me(position_est=None, lane_role=1, is_roaming=True)) == 5     # roaming support
    assert role_of(_me(position_est=None, lane_role=3, is_roaming=False)) == 3    # offlane
    assert role_of(_me(position_est=None, lane_role=3, is_roaming=True)) == 4     # roaming pos4


def test_role_undetermined_returns_none():
    assert role_of(_me(position_est=None, lane_role=None)) is None


def test_build_rows_skips_missing_account():
    empty = Match(match_id=9, duration=1800, radiant_win=True, players=[], parsed=True)
    rows = build_rows([_match(1, _me(position_est=3)), empty], 7)
    assert [r.match_id for r in rows] == [1]
    assert rows[0].role == 3 and rows[0].parsed is True


def test_segment_by_role_groups_and_drops_none():
    rows = build_rows([
        _match(1, _me(position_est=3)),
        _match(2, _me(position_est=3)),
        _match(3, _me(position_est=4)),
        _match(4, _me(position_est=None, lane_role=None)),  # роль не определена
    ], 7)
    seg = segment_by_role(rows)
    assert sorted(seg) == [3, 4]
    assert len(seg[3]) == 2 and len(seg[4]) == 1
