from dataclasses import asdict,replace
import json

import pytest

from dota_coach.evidence.contracts import EntityRef,Fact,SourceRef,TimeRef,content_hash
from dota_coach.decisions.choice_window import PrefixFact
from dota_coach.decisions.defensive_impact import (
    ASSUMPTIONS,ImpactScope,ImpactGoal,HistoricalImpactModel,ImpactAdmission,
    chosen_action_binding_hash,evaluate_defensive_impact,load_defensive_impact_input,
)


def context():
    at=TimeRef(1000,10,5,0,'fixture.clock','verified')
    prior=TimeRef(900,9,1,0,'fixture.clock','verified')
    receipt=SourceRef('fixture','a'*64,'synthetic','fixture.v1','prefix','fixture.extractor')
    scope=ImpactScope(7,'account:11','account:11','fixture.patch','fixture.item',EntityRef('match:7',44,7),
        'fixture.known_committed_impact',at,40,dataset_kind='synthetic')
    goal=ImpactGoal(100,50,(receipt,),prior)
    model=HistoricalImpactModel(scope.patch,scope.item_id,scope.threat_id,'fixture.historical_model',
        10,10,200,200,0.2,0.2,'fixture.damage',(),(receipt,),prior,ASSUMPTIONS)
    values={'self.hp_min':500,'self.hp_max':500,'self.mana_min':150,'self.mana_max':150,
        'item.mana_cost_min':50,'item.mana_cost_max':50,
        'threat.damage_before_resistance_min':500,'threat.damage_before_resistance_max':500,
        'threat.baseline_multiplier_min':1,'threat.baseline_multiplier_max':1,
        'threat.projected_impact_time_min_ms':1100,'threat.projected_impact_time_max_ms':1100,
        'self.activation_feasible':True,'self.hold_feasible':True,'screen.reaction_cue':True,
        'context.single_impact_complete':True,'context.window_stable':True,'threat.committed':True,
        'threat.damage_tag':'fixture.damage'}
    facts=tuple(PrefixFact(Fact(key,scope.subject_ref,key,value,'observed',prior,prior,
        'screen' if key=='screen.reaction_cue' else 'team',(receipt,),observer_ref=scope.observer_ref,
        method_version='fixture.prefix_prediction'),i+1) for i,(key,value) in enumerate(values.items()))
    return scope,model,goal,facts,receipt


def portable():
    """Inspectable synthetic proposal DTO; no review, chosen action or grants."""
    scope,model,goal,facts,_=context()
    return json.loads(json.dumps({'schema_version':'foresight.defensive-impact-input.v1',
        'scope':asdict(scope),'model':asdict(model),'goal':asdict(goal),'facts':[asdict(f) for f in facts]}))


def review(scope,model,goal,facts,receipt,chosen=None):
    input_hash=evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts)['input_hash']
    action_sources=(replace(receipt,artifact_id='postchoice.fixture',locator='action:40'),) if chosen else ()
    return ImpactAdmission(content_hash(scope),input_hash,content_hash(model),content_hash(goal),
        frozenset(f.input_hash for f in facts),(receipt,),
        chosen_action_binding_hash(input_hash,chosen,action_sources) if chosen else None,action_sources)


def change(facts,key,value):
    return tuple(replace(f,fact=replace(f.fact,value=value)) if f.fact.predicate==key else f for f in facts)


def run(*,changes=(),model_change=None,goal_change=None,reviewed=False,chosen=None,reviewed_choice=False):
    scope,model,goal,facts,receipt=context()
    for key,value in changes:facts=change(facts,key,value)
    if model_change:model=replace(model,**model_change)
    if goal_change:goal=replace(goal,**goal_change)
    admission=review(scope,model,goal,facts,receipt,chosen if reviewed_choice else None) if reviewed else None
    return evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts,admission=admission,chosen_action=chosen)


def test_computes_conditional_hp_mana_without_ready_utility_or_grant():
    result=run();candidate=result['candidate_arithmetic'];actions=candidate['alternatives']
    assert candidate['timing_coverage']=='full'
    assert actions['activate']['hp_after_impact']=={'minimum':400,'maximum':400}
    assert actions['activate']['mana_after_action']=={'minimum':100,'maximum':100}
    assert actions['hold']['hp_after_impact']=={'minimum':0,'maximum':0}
    assert actions['activate']['goal_status']=='robustly_meets'
    assert actions['hold']['goal_status']=='robustly_fails'
    assert result['verdict']=='unknown' and result['research_only'] and not result['training_eligible']
    assert candidate['hp_semantics']=='unclamped_hp_balance_not_death_forecast'


def test_reviewed_constraints_and_separate_actual_choice_receipt():
    result=run(reviewed=True,chosen='hold',reviewed_choice=True)
    assert result['verdict']=='chosen_action_violates_declared_constraints_alternative_robustly_meets'
    assert result['chosen_action_status']=='separately_reviewed_receipts'
    assert not result['training_eligible'] and result['strategic_quality']=='not_established'


def test_primitive_chosen_switch_does_not_assert_observed_bad_choice():
    result=run(reviewed=True,chosen='hold')
    assert result['verdict']=='alternative_robustly_meets_declared_goal'
    assert result['chosen_binding_hash'] is None
    assert result['chosen_action_status']=='supplied_scenario_action_not_observed_choice'
    scope,model,goal,facts,receipt=context();admission=review(scope,model,goal,facts,receipt,'hold')
    switched=evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts,admission=admission,chosen_action='activate')
    assert switched['chosen_binding_hash'] is None


@pytest.mark.parametrize('changes,goal,status',[
    ((),{'minimum_hp_after_impact':0},'both_actions_meet_goal'),
    ((),{'minimum_hp_after_impact':450},'both_actions_fail_goal'),
    ((('threat.damage_before_resistance_min',300),),None,'overlapping_or_incomplete_bounds_abstain'),
    ((),{'minimum_mana_after_action':125},'both_actions_fail_goal'),
])
def test_constraint_outcomes_and_mana_tradeoff(changes,goal,status):
    result=run(changes=changes,goal_change=goal,reviewed=True)
    assert result['verdict']==status


@pytest.mark.parametrize('impact,model_change,coverage,hp',[
    (1009,None,'none',(0,0)),
    (1010,None,'full',(400,400)),
    (1210,None,'none',(0,0)),
    (1100,{'effect_duration_min_ms':0,'effect_duration_max_ms':0},'none',(0,0)),
    (1100,{'activation_latency_min_ms':0,'activation_latency_max_ms':150},'partial',(0,400)),
    (1100,{'effect_duration_min_ms':0,'effect_duration_max_ms':200},'partial',(0,400)),
])
def test_half_open_timing_and_partial_protection_union(impact,model_change,coverage,hp):
    result=run(changes=(('threat.projected_impact_time_min_ms',impact),('threat.projected_impact_time_max_ms',impact)),model_change=model_change)
    candidate=result['candidate_arithmetic'];assert candidate['timing_coverage']==coverage
    assert candidate['alternatives']['activate']['hp_after_impact']=={'minimum':hp[0],'maximum':hp[1]}


def test_impact_interval_partial_overlap_not_full_protection():
    result=run(changes=(('threat.projected_impact_time_min_ms',1005),))
    candidate=result['candidate_arithmetic'];assert candidate['timing_coverage']=='partial'
    assert candidate['alternatives']['activate']['goal_status']=='uncertain'


def test_exempt_damage_tag_retains_baseline_and_explains_no_effect():
    result=run(model_change={'exempt_tags':('fixture.damage',)},reviewed=True)
    candidate=result['candidate_arithmetic'];assert candidate['timing_coverage']=='exempt'
    assert candidate['exemption_reason']=='declared_damage_tag_exempt_from_item'
    assert candidate['alternatives']['activate']['hp_after_impact']==candidate['alternatives']['hold']['hp_after_impact']
    assert result['verdict']=='both_actions_fail_goal'


@pytest.mark.parametrize('predicate',['screen.reaction_cue','context.single_impact_complete','context.window_stable','threat.committed'])
def test_unknown_or_false_local_completeness_abstains(predicate):
    result=run(changes=((predicate,False),));assert result['candidate_arithmetic'] is None


def test_false_feasibility_excludes_action_not_mana_only_override():
    result=run(changes=(('self.activation_feasible',False),),reviewed=True)
    assert result['candidate_arithmetic']['alternatives']['activate']['hp_after_impact'] is None
    assert result['verdict']=='action_excluded_in_reviewed_feasibility'
    conflict=run(changes=(('self.mana_min',10),('self.mana_max',10)))
    entry=conflict['candidate_arithmetic']['alternatives']['activate']
    assert entry['feasibility'] is None and entry['hp_after_impact'] is None


def test_unknown_fact_value_is_not_zero():
    scope,model,goal,facts,_=context()
    facts=tuple(replace(f,fact=replace(f.fact,value=None,status='unknown',unknown_reason='missing'))
        if f.fact.predicate=='self.hp_min' else f for f in facts)
    assert evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts)['candidate_arithmetic'] is None


def test_future_fact_does_not_change_prefix_hash_or_arithmetic():
    scope,model,goal,facts,_=context()
    baseline=evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts)
    future=replace(facts[0],source_record_index=99,fact=replace(facts[0].fact,value=1,valid_at=replace(scope.at,game_time_ms=2000,replay_tick=20)))
    result=evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts+(future,),chosen_action='hold')
    assert result['input_hash']==baseline['input_hash'] and result['candidate_arithmetic']==baseline['candidate_arithmetic']


@pytest.mark.parametrize('mutate',[
    lambda f:replace(f,fact=replace(f.fact,perspective='world')),
    lambda f:replace(f,fact=replace(f.fact,observer_ref='opponent:99')),
    lambda f:replace(f,fact=replace(f.fact,predicate='outcome.actual_damage')),
])
def test_hidden_foreign_or_outcome_operands_forbidden(mutate):
    scope,model,goal,facts,_=context()
    with pytest.raises(ValueError):evaluate_defensive_impact(scope,model=model,goal=goal,facts=(mutate(facts[0]),)+facts[1:])


@pytest.mark.parametrize('version',['unknown','unavailable','unverified','legacy/unverified'])
def test_reserved_clock_versions_never_admit(version):
    scope,model,goal,facts,_=context();scope=replace(scope,at=replace(scope.at,clock_mapping_version=version))
    assert evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts)['candidate_arithmetic'] is None


def test_stale_missing_clock_and_future_goal_abstain():
    scope,model,goal,facts,_=context()
    for scoped in (replace(scope,max_fact_age_ms=1),replace(scope,at=replace(scope.at,sequence_in_tick=None))):
        assert evaluate_defensive_impact(scoped,model=model,goal=goal,facts=facts)['candidate_arithmetic'] is None
    goal=replace(goal,available_at=replace(scope.at,game_time_ms=2000,replay_tick=20))
    assert evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts)['candidate_arithmetic'] is None


def test_receipt_change_excluded_from_feature_hash_but_revokes_admission():
    scope,model,goal,facts,receipt=context();admission=review(scope,model,goal,facts,receipt)
    baseline=evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts,admission=admission)
    changed=tuple(replace(f,fact=replace(f.fact,source_refs=(replace(receipt,artifact_id='different_whole_source',content_hash='b'*64),),
        fact_id='new-source-wide-hash:'+f.fact.fact_id,derived_from=('new-source-wide-receipt:'+f.fact.fact_id,))) for f in facts)
    result=evaluate_defensive_impact(scope,model=model,goal=goal,facts=changed,admission=admission)
    assert result['input_hash']==baseline['input_hash']
    assert result['verdict']=='unknown'


def test_overflow_abstains_without_infinity_or_fake_utility():
    result=run(changes=(('threat.damage_before_resistance_min',1e308),('threat.damage_before_resistance_max',1e308),
        ('threat.baseline_multiplier_min',1e308),('threat.baseline_multiplier_max',1e308)))
    assert result['candidate_arithmetic'] is None and 'arithmetic_overflow_or_nonfinite_result' in result['reason_codes']


@pytest.mark.parametrize('key,value',[('self.hp_min',True),('self.mana_min',-1),('threat.damage_before_resistance_min',600)])
def test_malformed_or_reversed_numeric_bounds_rejected(key,value):
    with pytest.raises(ValueError):run(changes=((key,value),))


def test_portable_example_computes_math_without_admitting_game_verdict():
    loaded=load_defensive_impact_input(portable());result=evaluate_defensive_impact(**loaded)
    assert result['candidate_arithmetic'] is not None and result['verdict']=='unknown'
    assert result['dataset_kind']=='synthetic' and not result['training_eligible']


@pytest.mark.parametrize('extra',['validated','admission','chosen_action','utility_bounds','outcome'])
def test_portable_grants_and_outcomes_rejected(extra):
    data=portable();data[extra]=True
    with pytest.raises(ValueError):load_defensive_impact_input(data)


def test_real_default_unknown_and_typed_foreign_model_rejected():
    scope,_,goal,facts,_=context();scope=replace(scope,dataset_kind='replay')
    result=evaluate_defensive_impact(scope,goal=goal,facts=facts)
    assert result['candidate_arithmetic'] is None and result['verdict']=='unknown'
    _,model,_,_,_=context()
    with pytest.raises(ValueError):evaluate_defensive_impact(scope,model=replace(model,patch='other.patch'),goal=goal,facts=facts)


def test_exact_goal_boundary_uses_fraction_math_without_rounding_grant():
    result=run(goal_change={'minimum_hp_after_impact':400,'minimum_mana_after_action':100})
    assert result['candidate_arithmetic']['alternatives']['activate']['goal_status']=='robustly_meets'


@pytest.mark.parametrize('perspective',['team','public'])
def test_team_or_public_receipt_cannot_be_renamed_screen_cue(perspective):
    scope,model,goal,facts,_=context()
    facts=tuple(replace(f,fact=replace(f.fact,perspective=perspective)) if f.fact.predicate=='screen.reaction_cue' else f for f in facts)
    with pytest.raises(ValueError,match='screen'):evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts)


def test_another_observers_screen_does_not_establish_selected_subject_cue():
    scope,model,goal,facts,_=context();scope=replace(scope,observer_ref='observer:99')
    facts=tuple(replace(f,fact=replace(f.fact,observer_ref=scope.observer_ref)) for f in facts)
    with pytest.raises(ValueError,match='screen'):evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts)


def test_zero_cost_is_known_and_protected_multiplier_is_not_guessed():
    result=run(changes=(('item.mana_cost_min',0),('item.mana_cost_max',0)),
        model_change={'protected_damage_multiplier_min':1,'protected_damage_multiplier_max':1})
    action=result['candidate_arithmetic']['alternatives']['activate']
    assert action['mana_after_action']=={'minimum':150,'maximum':150}
    assert action['hp_after_impact']=={'minimum':0,'maximum':0}


def test_uncertain_start_and_duration_guarantee_uses_latest_start_earliest_end():
    result=run(model_change={'activation_latency_min_ms':10,'activation_latency_max_ms':100,
        'effect_duration_min_ms':50,'effect_duration_max_ms':200})
    assert result['candidate_arithmetic']['timing_coverage']=='partial'
    assert result['candidate_arithmetic']['alternatives']['activate']['hp_after_impact']['minimum']==0


def test_goal_and_model_exact_receipts_independently_revoke_review():
    scope,model,goal,facts,receipt=context();admission=review(scope,model,goal,facts,receipt)
    for changed_model,changed_goal in ((replace(model,source_refs=(replace(receipt,content_hash='b'*64),)),goal),
            (model,replace(goal,source_refs=(replace(receipt,content_hash='b'*64),)))):
        result=evaluate_defensive_impact(scope,model=changed_model,goal=changed_goal,facts=facts,admission=admission)
        assert result['verdict']=='unknown' and result['candidate_arithmetic'] is not None


def test_future_declared_impact_values_are_predictions_from_earlier_fact_receipts():
    scope,model,goal,facts,_=context()
    result=evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts)
    assert result['candidate_arithmetic'] is not None
    changed=tuple(replace(f,fact=replace(f.fact,valid_at=replace(scope.at,game_time_ms=1100,replay_tick=11)))
        if f.fact.predicate.startswith('threat.projected_impact') else f for f in facts)
    assert evaluate_defensive_impact(scope,model=model,goal=goal,facts=changed)['candidate_arithmetic'] is None


def test_postchoice_action_receipt_hash_changes_no_prefix_features():
    scope,model,goal,facts,receipt=context();admission=review(scope,model,goal,facts,receipt,'hold')
    altered=replace(admission,chosen_action_sources=(replace(admission.chosen_action_sources[0],content_hash='b'*64),))
    result=evaluate_defensive_impact(scope,model=model,goal=goal,facts=facts,admission=altered,chosen_action='hold')
    assert result['input_hash']==admission.input_hash and result['chosen_binding_hash'] is None
    assert result['verdict']=='alternative_robustly_meets_declared_goal'


def test_declared_existing_immunity_exemption_does_not_replace_zero_baseline():
    result=run(changes=(('threat.baseline_multiplier_min',0),('threat.baseline_multiplier_max',0)),
        model_change={'exempt_tags':('fixture.damage',)},reviewed=True)
    assert result['candidate_arithmetic']['timing_coverage']=='exempt'
    for action in ('activate','hold'):
        assert result['candidate_arithmetic']['alternatives'][action]['hp_after_impact']=={'minimum':500,'maximum':500}
    assert result['verdict']=='both_actions_meet_goal'


def test_zero_hp_balance_is_not_survival_and_negative_balance_is_preserved():
    result=run(changes=(('threat.damage_before_resistance_min',1000),('threat.damage_before_resistance_max',1000)))
    assert result['candidate_arithmetic']['alternatives']['hold']['hp_after_impact']=={'minimum':-500,'maximum':-500}
    assert result['candidate_arithmetic']['alternatives']['hold']['goal_status']=='robustly_fails'


def test_oversized_integer_clock_is_portable_validation_error():
    data=portable();data['scope']['at']['game_time_ms']=10**1000
    with pytest.raises(ValueError):load_defensive_impact_input(data)
