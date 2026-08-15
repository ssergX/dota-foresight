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


def test_leaks_select_worst_offender_matches_in_order():
    # (match_id, gpm_pct, deaths, obs) — deliberately varied per match
    specs = [
        (0, 0.30, 5, 5),
        (1, 0.10, 15, 0),
        (2, 0.20, 12, 1),
        (3, 0.35, 9, 2),
        (4, 0.15, 20, 3),
    ]
    matches = [_m(mid, 111, gpm, d, obs) for (mid, gpm, d, obs) in specs]
    leaks = {l.key: l for l in detect_leaks(matches, 111)}
    # farm: lowest gpm pct first (ascending) -> 0.10(m1), 0.15(m4), 0.20(m2)
    assert leaks["farm_below_bracket"].example_matches == [1, 4, 2]
    # feeding: most deaths first (descending) -> 20(m4), 15(m1), 12(m2)
    assert leaks["feeding"].example_matches == [4, 1, 2]
    # low_warding: fewest wards first (ascending) -> 0(m1), 1(m2), 2(m3)
    assert leaks["low_warding"].example_matches == [1, 2, 3]


def test_leaks_carry_numeric_fields():
    matches = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=1) for i in range(5)]
    leaks = {l.key: l for l in detect_leaks(matches, 111)}

    feeding = leaks["feeding"]
    assert feeding.metric == "deaths_per_game"
    assert feeding.value == 11.0
    assert feeding.threshold == 8.0
    assert feeding.direction == "lower_is_better"

    farm = leaks["farm_below_bracket"]
    assert farm.metric == "gpm_pct"
    assert farm.value == 0.25
    assert farm.threshold == 0.4
    assert farm.direction == "higher_is_better"

    warding = leaks["low_warding"]
    assert warding.metric == "obs_per_game"
    assert warding.value == 1.0
    assert warding.threshold == 4.0
    assert warding.direction == "higher_is_better"
