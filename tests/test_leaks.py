from dota_coach.leaks import detect_leaks
from dota_coach.models import Match, PlayerMatch


def _me(**kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return PlayerMatch(**base)


def _match(mid, me):
    return Match(match_id=mid, duration=1800, radiant_win=True, players=[me], parsed=True)


def test_role_below_five_games_not_analyzed():
    # 3 игры на pos5 -> роль не разбирается -> ликов нет
    matches = [_match(i, _me(position_est=5, deaths=20, obs_placed=0)) for i in range(3)]
    assert detect_leaks(matches, 7) == []


def test_pos3_zero_wards_is_not_a_leak():
    # 10 оффлейн-игр с 0 обсов: low_obs не применим к pos3 -> не срабатывает
    matches = [_match(i, _me(position_est=3, obs_placed=0, deaths=2,
                             benchmarks={"gold_per_min": {"raw": 500, "pct": 0.7}}))
               for i in range(10)]
    keys = {l.key for l in detect_leaks(matches, 7)}
    assert "low_obs" not in keys


def test_pos4_low_farm_surfaces():
    # pos4, GPM-перцентиль 0.19 -> farm_below_bracket срабатывает
    matches = [_match(i, _me(position_est=4, deaths=2, obs_placed=8,
                             benchmarks={"gold_per_min": {"raw": 300, "pct": 0.19}}))
               for i in range(6)]
    keys = {l.key for l in detect_leaks(matches, 7)}
    assert "farm_below_bracket" in keys


def test_leaks_are_ordered_by_severity_and_deterministic():
    matches = [_match(i, _me(position_est=4, deaths=18, obs_placed=1,
                             benchmarks={"gold_per_min": {"raw": 300, "pct": 0.19}}))
               for i in range(8)]
    a = detect_leaks(matches, 7)
    b = detect_leaks(matches, 7)
    assert [l.key for l in a] == [l.key for l in b]          # детерминизм
    assert a and a[0].severity >= a[-1].severity             # фокус первым
    assert all(l.role == 4 for l in a)                        # роль проставлена
