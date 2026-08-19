from dota_coach.leaks.detectors.vision import (
    low_dewarding, low_obs, low_sentries, wards_die_fast)
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, role=5, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=role, me=PlayerMatch(**base))


def test_low_obs_fires_pos5():
    rows = [_row(i, role=5, obs_placed=2) for i in range(5)]  # 2 < 6
    leak = low_obs(rows, 5, TH)
    assert leak is not None and leak.key == "low_obs" and leak.family == "vision"


def test_low_obs_silent_pos5_ok():
    rows = [_row(i, role=5, obs_placed=8) for i in range(5)]
    assert low_obs(rows, 5, TH) is None


def test_low_sentries_fires():
    rows = [_row(i, role=5, sen_placed=1) for i in range(5)]  # 1 < 4
    assert low_sentries(rows, 5, TH) is not None


def test_low_dewarding_counts_dewards():
    rows = [_row(i, role=5, observer_kills=0, sentry_uses=0) for i in range(5)]
    assert low_dewarding(rows, 5, TH) is not None


def test_wards_die_fast_when_short_lifetime():
    # поставлен на 60, снят на 120 -> жизнь 60с < 180
    log = [{"time": 60, "ehandle": 1}]
    left = [{"time": 120, "ehandle": 1}]
    rows = [_row(i, role=5, obs_log=log, obs_left_log=left) for i in range(5)]
    assert wards_die_fast(rows, 5, TH) is not None
