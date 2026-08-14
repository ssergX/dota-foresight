from dota_coach.leaks import detect_leaks
from dota_coach.models import Match, PlayerMatch


def _p(account_id, gpm_pct, deaths, obs):
    return PlayerMatch(
        account_id=account_id, player_slot=0, hero_id=1, is_radiant=True,
        kills=0, deaths=deaths, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
        gold_t=[], xp_t=[], lh_t=[], kills_log=[], purchase_log=[],
        obs_log=[{"time": 60}] * obs, sen_log=[],
        benchmarks={"gold_per_min": {"raw": 400, "pct": gpm_pct}},
    )


def _m(mid, account_id, gpm_pct, deaths, obs):
    return Match(match_id=mid, duration=1800, radiant_win=True,
                 players=[_p(account_id, gpm_pct, deaths, obs)],
                 teamfights=[], objectives=[], parsed=True)


def test_detects_farm_feeding_and_warding_leaks():
    matches = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=1) for i in range(5)]
    leaks = detect_leaks(matches, 111)
    keys = {l.key for l in leaks}
    assert "farm_below_bracket" in keys
    assert "feeding" in keys
    assert "low_warding" in keys
    farm = next(l for l in leaks if l.key == "farm_below_bracket")
    assert len(farm.example_matches) <= 3


def test_clean_player_has_no_leaks():
    matches = [_m(i, 111, gpm_pct=0.7, deaths=3, obs=8) for i in range(5)]
    assert detect_leaks(matches, 111) == []
