import pytest
from dota_coach.profile import describe_series


def test_missing_zero_separate_context_and_duplicate_ids():
    a = {"match_id": 1, "patch": 1, "players": [{"account_id": 11, "hero_id": 1, "deaths": 0}]}
    b = {"match_id": 2, "patch": 1, "players": [{"account_id": 11, "hero_id": 1}]}
    group, = describe_series([a, b], 11)
    deaths = next(m for m in group.metrics if m.metric == "deaths")
    assert deaths.median_value == 0 and deaths.measured_matches == 1 and deaths.considered_matches == 2
    assert next(m for m in group.metrics if m.metric == "obs_placed").median_value is None
    c = b | {"match_id": 3, "patch": 2}
    assert len(describe_series([a, c], 11)) == 2
    with pytest.raises(ValueError):
        describe_series([a, a], 11)


def test_opponent_context_and_purchase_denominators_do_not_invent_mmr_or_style():
    own={'account_id':11,'player_slot':0,'hero_id':1,
        'purchase_log':[{'key':'blink','time':600},{'key':'blink','time':800}]}
    enemies=[{'account_id':100+i,'player_slot':128+i,'rank_tier':80} for i in range(5)]
    a={'match_id':1,'patch':1,'players':[own]+enemies}
    b={'match_id':2,'patch':1,'players':[own|{'purchase_log':None}]+enemies}
    g,=describe_series([a,b],11)
    item,=g.item_preferences
    assert item.matches_with_purchase==1 and item.matches_with_purchase_log==1 and item.considered_matches==2
    assert item.median_first_purchase_seconds==600
    assert 'not_numeric_mmr' in g.opponent_level_proxy
    assert g.style_status=='descriptive_features_no_stable_label'
    c={'match_id':3,'patch':1,'players':[own]+[p|{'rank_tier':None} for p in enemies]}
    assert len(describe_series([a,c],11))==2
