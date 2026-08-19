from dota_coach.leaks.detectors.deaths import feeding, repeat_victim, time_dead
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=4, me=PlayerMatch(**base))


def test_feeding_fires_above_threshold_with_worst_examples():
    rows = [_row(i, deaths=d) for i, d in enumerate([12, 9, 15, 8, 20])]
    leak = feeding(rows, 4, TH)
    assert leak is not None and leak.key == "feeding"
    assert leak.value == 12.8 and leak.threshold == 8.0
    assert leak.direction == "lower_is_better" and leak.family == "deaths"
    assert leak.example_matches == [4, 2, 0]  # 20,15,12 — худшие первыми
    assert leak.sample_size == 5


def test_feeding_silent_when_clean():
    rows = [_row(i, deaths=4) for i in range(5)]
    assert feeding(rows, 4, TH) is None


def test_time_dead_uses_fraction_of_duration():
    # 300с мёртв из 1800 = 0.1667 > 0.13
    rows = [Row(mid, 1800, True, 4,
                PlayerMatch(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                            kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0,
                            last_hits=0, life_state_dead=300)) for mid in range(5)]
    leak = time_dead(rows, 4, TH)
    assert leak is not None and leak.metric == "time_dead_frac"
    assert round(leak.value, 3) == 0.167 and leak.direction == "lower_is_better"


def test_repeat_victim_sums_killed_by_over_series():
    rows = [_row(i, killed_by={"npc_dota_hero_lion": 3}) for i in range(5)]  # 3/матч одним героем
    leak = repeat_victim(rows, 4, TH)
    assert leak is not None and leak.key == "repeat_victim"
