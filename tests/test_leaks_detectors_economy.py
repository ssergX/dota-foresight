from dota_coach.leaks.detectors.economy import (
    idle_gold_gaps, level_behind, low_neutral_farm, missing_runes, no_stacks)
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, role=1, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=role, me=PlayerMatch(**base))


def test_low_neutral_farm_fires():
    rows = [_row(i, neutral_kills=5) for i in range(5)]  # 5 < 20 (pos1)
    assert low_neutral_farm(rows, 1, TH) is not None


def test_no_stacks_only_supports():
    rows = [_row(i, role=5, camps_stacked=0) for i in range(5)]  # 0 < 2
    assert no_stacks(rows, 5, TH) is not None


def test_missing_runes_pos2():
    rows = [_row(i, role=2, rune_pickups=1) for i in range(5)]  # 1 < 3
    assert missing_runes(rows, 2, TH) is not None


def test_level_behind_uses_bench_percentile():
    rows = [_row(i, benchmarks={"xp_per_min": {"raw": 300, "pct": 0.2}}) for i in range(5)]
    leak = level_behind(rows, 1, TH)
    assert leak is not None and leak.metric == "xpm_pct" and leak.source == "bench"


def test_idle_gold_gaps_flags_flat_curve():
    # прирост золота почти нулевой между минутами -> простой
    flat = list(range(0, 300, 30)) + [270] * 15  # длинное плато в конце
    rows = [_row(i, gold_t=flat) for i in range(5)]
    assert idle_gold_gaps(rows, 1, TH) is not None
