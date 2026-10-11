from copy import deepcopy
import pytest
from dota_coach.decisions.resource_review import review_resource_prefix


def state():
    fact=lambda v,r:{'value':v,'status':'raw_observed','source_record_index':r,'net_tick':4}
    return {'action_id':'a','cutoff_record_index':10,'cutoff_policy':'strict_previous_network_tick',
        'hero':{'fields':{'m_flMana':fact(686,7)}},'inventory':[{'item_id':'item_black_king_bar',
        'relation_status':'resolved_exact_handle','handle':'123','generation':2,'fields':{'m_iManaCost':fact(50,6)},
        'checks':[{'code':'control_allows_activation','value':None,'status':'unknown'}]}]}


def test_real_arithmetic_has_no_gameplay_verdict_or_quality_claim():
    r=review_resource_prefix(state(),item_id='item_black_king_bar')
    assert r['mana_after_cost_arithmetic']==636 and r['resource_evidence_records']==(6,7)
    assert r['verdict']=='insufficient_evidence' and r['feasibility']=='unknown'
    assert r['calculation_status']=='arithmetic_on_unverified_raw_prefix'


def test_unknown_zero_and_ambiguous_items_stay_distinct():
    s=state();s['hero']['fields']['m_flMana']['value']=0
    assert review_resource_prefix(s,item_id='item_black_king_bar')['mana_after_cost_arithmetic']==-50
    s['hero']['fields']['m_flMana']['value']=None
    assert review_resource_prefix(s,item_id='item_black_king_bar')['mana_after_cost_arithmetic'] is None
    s=state();s['inventory']*=2
    assert review_resource_prefix(s,item_id='item_black_king_bar')['activation_mana_cost_raw'] is None


def test_hidden_future_full_hash_and_outcome_cannot_change_input():
    s=state();r=review_resource_prefix(s,item_id='item_black_king_bar')
    s.update(enemy_positions={'x':2},future_hp=0,trace_sha256='b'*64,radiant_win=False)
    assert review_resource_prefix(s,item_id='item_black_king_bar')==r


def test_late_resource_field_rejected():
    s=state();s['hero']['fields']['m_flMana']['source_record_index']=10
    with pytest.raises(ValueError,match='precede'):
        review_resource_prefix(s,item_id='item_black_king_bar')


@pytest.mark.parametrize('reference',[None,True,-1])
def test_missing_or_invalid_known_field_source_cannot_support_calculation(reference):
    s=state();s['hero']['fields']['m_flMana']['source_record_index']=reference
    with pytest.raises(ValueError):
        review_resource_prefix(s,item_id='item_black_king_bar')


def test_nested_extra_metadata_not_an_analytical_feature():
    s=state();r=review_resource_prefix(s,item_id='item_black_king_bar')
    s['hero']['fields']['m_flMana']['future_hp']=100
    s['inventory'][0]['checks'][0]['future_outcome']='win'
    assert review_resource_prefix(s,item_id='item_black_king_bar')['input_hash']==r['input_hash']


def test_legacy_positive_cooldown_flag_demoted_and_rebuilt_from_raw_prefix():
    s=state()
    fact=lambda v:{'value':v,'status':'raw_observed','source_record_index':6,'net_tick':4}
    s['sampled_net_tick']=30000
    s['clock']={'tick_interval':0.1,'paused_ticks':0,'paused':False,
        'evidence_records':[5],'semantic_validation':'unverified'}
    item=s['inventory'][0]
    item['fields'].update(m_fCooldown=fact(95),m_bFrozenCooldown=fact(False),m_bInIndefiniteCooldown=fact(False))
    item['checks'].append({'code':'raw_cooldown_end_not_after_clock','value':True,
        'status':'unverified_candidate','evidence_record_indices':[5,6]})
    r=review_resource_prefix(s,item_id='item_black_king_bar')
    check=next(c for c in r['checks'] if c['code']=='raw_cooldown_end_not_after_clock')
    assert check['value'] is None and check['status']=='unknown'
    assert check['raw_cooldown_fact']['value']==95
    assert [h['arithmetic_comparison_value'] for h in check['interpretations']]==[False,True]
    assert check['chosen_interpretation'] is None
    assert r['mana_after_cost_arithmetic']==636 and r['feasibility']=='unknown'
    item['checks'][-1]['value']=False
    assert review_resource_prefix(s,item_id='item_black_king_bar')['input_hash']==r['input_hash']


def test_cooldown_source_injection_rejected_despite_legacy_candidate():
    s=state();s['inventory'][0]['fields']['m_fCooldown']={
        'value':0,'status':'raw_observed','source_record_index':10,'net_tick':4}
    with pytest.raises(ValueError,match='precede cutoff'):
        review_resource_prefix(s,item_id='item_black_king_bar')
