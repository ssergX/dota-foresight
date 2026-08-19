from dota_coach.leaks.thresholds import Thresholds


def test_bench_floor_is_04():
    assert Thresholds().bench_floor() == 0.4


def test_manual_is_role_specific():
    th = Thresholds()
    assert th.manual("obs_per_game", 5) > th.manual("obs_per_game", 4)  # pos5 требует больше обсов


def test_manual_unknown_metric_returns_none():
    assert Thresholds().manual("nope", 1) is None
