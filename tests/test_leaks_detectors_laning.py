from dota_coach.leaks.detectors.laning import (
    cs_behind_at_10, farm_below_bracket, lane_collapse, low_denies)
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, role=1, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=role, me=PlayerMatch(**base))


def test_farm_below_bracket_fires_on_low_median_percentile():
    rows = [_row(i, benchmarks={"gold_per_min": {"raw": 400, "pct": 0.19}}) for i in range(5)]
    leak = farm_below_bracket(rows, 1, TH)
    assert leak is not None and leak.metric == "gpm_pct"
    assert leak.value == 0.19 and leak.threshold == 0.4
    assert leak.direction == "higher_is_better" and leak.source == "bench"


def test_farm_below_bracket_silent_when_percentile_ok():
    rows = [_row(i, benchmarks={"gold_per_min": {"raw": 600, "pct": 0.7}}) for i in range(5)]
    assert farm_below_bracket(rows, 1, TH) is None


def test_cs_behind_at_10_reads_minute_10():
    rows = [_row(i, lh_t=[0, 5, 10, 14, 18, 22, 26, 30, 33, 36, 30]) for i in range(5)]  # lh_t[10]=30 < 45
    leak = cs_behind_at_10(rows, 1, TH)
    assert leak is not None and leak.metric == "cs_at_10" and leak.value == 30.0


def test_cs_behind_short_series_skips_when_no_minute_10():
    rows = [_row(i, lh_t=[0, 5, 10]) for i in range(5)]  # нет 10-й минуты
    assert cs_behind_at_10(rows, 1, TH) is None


def test_lane_collapse_uses_efficiency():
    rows = [_row(i, lane_efficiency_pct=30) for i in range(5)]  # 30 < 40
    leak = lane_collapse(rows, 3, TH)
    assert leak is not None and leak.metric == "lane_efficiency_pct"


def test_low_denies_fires_below_manual():
    rows = [_row(i, denies=3) for i in range(5)]  # 3 < 8
    assert low_denies(rows, 1, TH) is not None
