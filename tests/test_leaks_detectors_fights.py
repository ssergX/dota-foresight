from dota_coach.leaks.detectors.fights import low_fight_participation, present_no_damage
from dota_coach.leaks.detectors.objectives import low_tower_damage
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, role=3, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=role, me=PlayerMatch(**base))


def test_low_fight_participation_fires():
    rows = [_row(i, role=4, teamfight_participation=0.35) for i in range(5)]  # 0.35 < 0.55
    leak = low_fight_participation(rows, 4, TH)
    assert leak is not None and leak.metric == "teamfight_participation"


def test_present_no_damage_uses_bench():
    rows = [_row(i, role=2, benchmarks={"hero_damage_per_min": {"raw": 100, "pct": 0.15}})
            for i in range(5)]
    leak = present_no_damage(rows, 2, TH)
    assert leak is not None and leak.source == "bench"


def test_low_tower_damage_uses_bench():
    rows = [_row(i, role=1, benchmarks={"tower_damage": {"raw": 500, "pct": 0.1}}) for i in range(5)]
    leak = low_tower_damage(rows, 1, TH)
    assert leak is not None and leak.metric == "tower_damage_pct" and leak.family == "objectives"
