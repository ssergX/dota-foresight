from dota_coach.leaks.severity import rank, score
from dota_coach.models import Leak


def _leak(key, family, value, threshold, direction, source="manual", sample=12, severity=0.0):
    return Leak(key=key, title=key, magnitude="", metric=key, value=value, threshold=threshold,
                direction=direction, source=source, sample_size=sample, family=family, severity=severity)


def test_score_bench_uses_percentile_gap():
    s = score(_leak("farm_below_bracket", "economy", value=0.2, threshold=0.4, direction="higher_is_better", source="bench"))
    assert s > 0


def test_score_zero_below_min_sample():
    assert score(_leak("feeding", "deaths", 20, 8, "lower_is_better", sample=4)) == 0.0


def test_rank_picks_highest_severity_and_dedups_family():
    a = _leak("feeding", "deaths", 20, 8, "lower_is_better", severity=0.9)
    b = _leak("time_dead", "deaths", 0.3, 0.13, "lower_is_better", severity=0.6)  # та же семья
    c = _leak("low_obs", "vision", 1, 6, "higher_is_better", severity=0.5)
    focus, also = rank([b, a, c])
    assert focus.key == "feeding"
    also_keys = {l.key for l in also}
    assert "time_dead" not in also_keys      # семья deaths уже представлена фокусом
    assert "low_obs" in also_keys


def test_rank_deterministic_tiebreak_by_key():
    a = _leak("aaa", "f1", 10, 5, "lower_is_better", severity=0.5)
    b = _leak("bbb", "f2", 10, 5, "lower_is_better", severity=0.5)
    focus1, _ = rank([a, b])
    focus2, _ = rank([b, a])
    assert focus1.key == focus2.key == "aaa"
