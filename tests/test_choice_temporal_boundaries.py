"""Synthetic adversarial clocks; no Dota client or game expert certification."""
from dataclasses import replace
from fractions import Fraction
import json
import pytest
from dota_coach.evidence.clock_math import decimal, numeric_interval, numeric_bound, verified_bounds
from dota_coach.evidence.contracts import content_hash
from dota_coach.decisions.choice_window import derive_feasibility, resolve_choice_windows
from dota_coach.decisions.choice_monitor import ContinuityAdmission, monitor_choice_stream
from dota_coach.decisions.mechanics_adapter import monitor_mechanical_stream
from tests.test_choice_window import inputs, admission, clock, operand
from tests.test_choice_monitor import stream, run
from tests.test_mechanics_adapter import mechanical_stream


@pytest.mark.parametrize('value',[Fraction(1,3),Fraction(-1,3),Fraction(17,10),
    Fraction(10**16)+Fraction(1,10**7),Fraction(10**16)-Fraction(1,10**7),
    Fraction(1,10**324),Fraction(-1,10**324)])
def test_export_never_enlarges_guaranteed_interval(value):
    lower,upper=numeric_bound(value,upper=False),numeric_bound(value,upper=True)
    assert decimal(lower)<=value<=decimal(upper)
    interval=(value,value+Fraction(1,1000))
    guaranteed=numeric_interval(interval,guaranteed=True)
    possible=numeric_interval(interval,guaranteed=False)
    assert decimal(guaranteed[0])>=interval[0] and decimal(guaranteed[1])<=interval[1]
    assert decimal(possible[0])<=interval[0] and decimal(possible[1])>=interval[1]
    json.dumps([guaranteed,possible],allow_nan=False)


@pytest.mark.parametrize('mapping',['unknown','Unknown','unavailable',' Unverified','legacy/unknown',None])
def test_reserved_mapping_cannot_support_choice_even_with_typed_review(mapping):
    scope,semantics,sample,cue=inputs()
    if mapping is None:
        assert verified_bounds(replace(sample.at,clock_mapping_version=mapping),mapping) is None
        return
    scope=replace(scope,clock_mapping_version=mapping)
    def mapped(t):return replace(t,clock_mapping_version=mapping) if t else None
    def fact(f):return replace(f,fact=replace(f.fact,valid_at=mapped(f.fact.valid_at),available_at=mapped(f.fact.available_at)))
    sample=replace(sample,at=mapped(sample.at),facts=tuple(fact(f) for f in sample.facts))
    cue=replace(cue,observation=fact(cue.observation),expires_at=mapped(cue.expires_at),expiry_available_at=mapped(cue.expiry_available_at))
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=semantics,
        admission=admission(scope,semantics,sample,cues=(cue,)))
    assert result['supported_choice_count']==result['excluded_count']==0
    assert result['feasibility_samples'][0]['feasibility']=='unknown'


@pytest.mark.parametrize('status',['unknown','partial'])
def test_unknown_sample_order_cannot_exclude_choice_using_false_cue(status):
    scope,semantics,sample,cue=inputs()
    sample=replace(sample,at=replace(sample.at,order_status=status))
    cue=replace(cue,observation=operand('screen.reaction_cue',False,available=500,record=20))
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=semantics,
        admission=admission(scope,semantics,sample,cues=(cue,)))
    assert result['excluded_count']==result['supported_choice_count']==0
    assert result['unknown_count']==1


@pytest.mark.parametrize('availability',[None,replace(clock(800),clock_mapping_version='foreign'),
    replace(clock(800),order_status='unknown'),clock(1000,1e-14)])
def test_unreadable_mana_cannot_enter_candidate_arithmetic(availability):
    scope,semantics,sample,cue=inputs()
    sample=replace(sample,facts=tuple(replace(f,fact=replace(f.fact,available_at=availability,value=999))
        if f.fact.predicate=='self.mana' else f for f in sample.facts))
    result=derive_feasibility(scope,sample,semantics=semantics,
                             admission=admission(scope,semantics,sample,cues=(cue,)))
    assert result['mana_after_cost_arithmetic'] is None
    assert result['candidate_feasibility']==result['feasibility']=='unknown'


@pytest.mark.parametrize('predicate',['self.mana','self.control_bits','item.cooldown','item.entity_index'])
def test_missing_material_operand_is_not_interpolated_to_next_frame(predicate):
    scope,semantics,samples,cues,cov,_=stream()
    following=replace(samples[1],facts=tuple(f for f in samples[1].facts if f.fact.predicate!=predicate))
    samples=(samples[0],following)
    cov=replace(cov,sample_hashes=tuple(content_hash(s) for s in samples))
    registry=ContinuityAdmission(admission(scope,semantics,*samples,cues=cues),frozenset({content_hash(cov)}))
    result=run((scope,semantics,samples,cues,cov,registry))
    assert result['spans'][0]['status']=='unknown' and result['spans'][0]['interval_ms'] is None
    assert 'material_operand_removal_time_unknown' in result['spans'][0]['reason_codes']


def test_expiry_uncertainty_below_float_ulp_prevents_supported_sample():
    scope,semantics,sample,cue=inputs()
    sample=replace(sample,at=clock(1800))
    cue=replace(cue,expires_at=clock(1800,1e-14))
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=semantics,
        admission=admission(scope,semantics,sample,cues=(cue,)))
    window=result['windows'][0]
    assert window['status']=='unknown'
    assert decimal(window['guaranteed_interval_ms'][1])<1800
    assert window['possible_interval_ms'][1]>1800
    json.dumps(result,allow_nan=False)


def test_tiny_staleness_uncertainty_cannot_be_rounded_into_freshness():
    scope,semantics,sample,cue=inputs()
    scope=replace(scope,max_fact_age_ms=200)
    sample=replace(sample,at=clock(1000,1e-14))
    result=derive_feasibility(scope,sample,semantics=semantics,admission=admission(scope,semantics,sample))
    assert result['feasibility']=='unknown'


def test_undelivered_fact_mutation_does_not_change_analytical_hash():
    scope,semantics,sample,cue=inputs()
    def calculate(value):
        changed=replace(sample,facts=tuple(replace(f,fact=replace(f.fact,value=value,available_at=None,
            fact_id='undelivered:'+str(value),derived_from=('future:'+str(value),)))
            if f.fact.predicate=='self.mana' else f for f in sample.facts))
        return derive_feasibility(scope,changed,semantics=semantics)
    one,two=calculate(100),calculate(999)
    assert one['input_hash']==two['input_hash']
    assert one['derived_fact']==two['derived_fact']
    assert one['conditions']==two['conditions']


def test_review_artifact_and_derived_fact_ids_do_not_change_prefix_features():
    scope,semantics,sample,cue=inputs()
    def revised(f):
        return replace(f,fact=replace(f.fact,fact_id='replacement:'+f.fact.fact_id,
            derived_from=('whole-future-archive',),source_refs=tuple(replace(ref,artifact_id='new-archive',content_hash='f'*64)
                for ref in f.fact.source_refs)))
    newer=replace(sample,sample_id='sample-derived-from-new-archive',facts=tuple(revised(f) for f in sample.facts))
    newcue=replace(cue,observation=revised(cue.observation))
    def query(s,c):
        return monitor_choice_stream(scope,(s,),(c,),cutoff=clock(2000),cutoff_record_index=200,
            semantics=semantics,admission=ContinuityAdmission(admission(scope,semantics,s,cues=(c,)),frozenset()))
    old,new=query(sample,cue),query(newer,newcue)
    assert old['prefix_feature_hash']==new['prefix_feature_hash']
    assert old['sampled']['feasibility_samples'][0]['input_hash']==new['sampled']['feasibility_samples'][0]['input_hash']
    assert old['sampled']['windows'][0]['window_id']==new['sampled']['windows'][0]['window_id']


def test_mechanical_adapter_does_not_reintroduce_future_time_sample():
    scope,binding,raw,cues,cov,continuity,truth,review=mechanical_stream()
    def query(samples):
        return monitor_mechanical_stream(scope,samples,cues,binding=binding,cutoff=clock(1200),
            cutoff_record_index=120,review=review,coverages=(cov,),continuity_admission=continuity,truth_coverages=(truth,))
    baseline=query(raw[:1])
    for value in (777,888):
        sample=replace(raw[0].sample,sample_id='future',prefix_record_index=110,at=clock(1400),
            facts=tuple(operand('self.mana',value,available=1300,record=105) if f.fact.predicate=='self.mana'
                        else f for f in raw[0].sample.facts))
        future=replace(raw[0],sample=sample)
        assert query((raw[0],future))==baseline
    assert len(baseline['mechanical_samples'])==1


@pytest.mark.parametrize('component',['operand','cue'])
def test_observation_delivered_before_occurrence_cannot_grant_choice(component):
    scope,semantics,sample,cue=inputs()
    if component=='operand':
        sample=replace(sample,facts=tuple(replace(f,fact=replace(f.fact,valid_at=clock(900),available_at=clock(800)))
            if f.fact.predicate=='self.mana' else f for f in sample.facts))
    else:
        cue=replace(cue,observation=replace(cue.observation,fact=replace(cue.observation.fact,
            valid_at=clock(600),available_at=clock(500))))
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=semantics,
        admission=admission(scope,semantics,sample,cues=(cue,)))
    assert result['supported_choice_count']==0 and result['unknown_count']==1


@pytest.mark.parametrize('availability',[None,replace(clock(800),order_status='unknown'),
    replace(clock(800),clock_mapping_version='foreign')])
def test_unreadable_extended_guard_is_not_candidate_disproof(availability):
    from dota_coach.decisions.mechanics_adapter import RawMechanicalSample, evaluate_mechanical_sample
    scope,binding,raw,cues,cov,continuity,truth,review=mechanical_stream()
    guard=replace(raw[0].restrictions[0],fact=replace(raw[0].restrictions[0].fact,value=False,available_at=availability))
    changed=replace(raw[0],restrictions=(guard,))
    newer=replace(review,restriction_fact_hashes=review.restriction_fact_hashes|{guard.input_hash})
    result=evaluate_mechanical_sample(scope,changed,binding=binding,review=newer)
    assert result['candidate_feasibility']==result['feasibility']=='unknown'
    assert result['restrictions'][0]['candidate_value'] is None


def ambiguous_stream():
    scope,semantics,samples,cues,cov,_=stream()
    following=replace(samples[1],at=clock(1200,300),facts=tuple(
        replace(f,fact=replace(f.fact,valid_at=clock(1100),available_at=clock(1150)))
        if f.fact.predicate=='self.control_bits' else f for f in samples[1].facts))
    cov=replace(cov,end=clock(1250),available_at=clock(1275),source_record_index=175)
    registry=ContinuityAdmission(admission(scope,semantics,samples[0],following,cues=cues),frozenset())
    return scope,semantics,(samples[0],following),cues,cov,registry


def test_omitted_ambiguous_sample_cannot_be_hidden_by_cutoff_filter():
    scope,semantics,samples,cues,cov,registry=ambiguous_stream()
    cov=replace(cov,sample_hashes=(content_hash(samples[0]),))
    registry=replace(registry,coverage_hashes=frozenset({content_hash(cov)}))
    with pytest.raises(ValueError,match='omitted'):
        monitor_choice_stream(scope,samples,cues,cutoff=clock(1300),cutoff_record_index=200,
            semantics=semantics,coverages=(cov,),admission=registry)


def test_complete_review_cannot_certify_through_ambiguous_sample_delivery():
    scope,semantics,samples,cues,cov,registry=ambiguous_stream()
    cov=replace(cov,sample_hashes=tuple(content_hash(s) for s in samples))
    registry=replace(registry,coverage_hashes=frozenset({content_hash(cov)}))
    result=monitor_choice_stream(scope,samples,cues,cutoff=clock(1300),cutoff_record_index=200,
        semantics=semantics,coverages=(cov,),admission=registry)
    assert result['supported_span_count']==0
    assert result['sampled']['sample_count']==1
    assert result['unresolved_transition_boundaries'][0]['source_record_index']==150


def test_unknown_cue_delivery_cannot_be_omitted_from_complete_transition_manifest():
    from dota_coach.decisions.choice_window import ChoiceCue
    scope,semantics,samples,cues,cov,registry=stream()
    cue=ChoiceCue(replace(operand('screen.reaction_cue',False,available=1100,record=120),
        fact=replace(operand('screen.reaction_cue',False,available=1100,record=120).fact,
            fact_id='withdrawal',available_at=None)))
    cues=(*cues,cue)
    registry=ContinuityAdmission(admission(scope,semantics,*samples,cues=cues),frozenset({content_hash(cov)}))
    with pytest.raises(ValueError,match='cue transition'):
        run((scope,semantics,samples,cues,cov,registry))
    cov=replace(cov,cue_transition_hashes=tuple(content_hash(c) for c in cues))
    registry=replace(registry,coverage_hashes=frozenset({content_hash(cov)}))
    result=run((scope,semantics,samples,cues,cov,registry))
    assert result['supported_span_count']==0
    assert result['unresolved_transition_boundaries'][0]['reason']=='cue_delivery_unresolved'


def test_ambiguous_future_value_cannot_enter_prefix_features():
    scope,semantics,samples,cues,cov,registry=ambiguous_stream()
    def query(value):
        following=replace(samples[1],facts=tuple(replace(f,fact=replace(f.fact,value=value))
            if f.fact.predicate=='self.mana' else f for f in samples[1].facts))
        return monitor_choice_stream(scope,(samples[0],following),cues,cutoff=clock(1300),
            cutoff_record_index=200,semantics=semantics,admission=registry)
    assert query(777)==query(888)


@pytest.mark.parametrize('validity',[clock(1100),clock(1000,1e-14),replace(clock(500),order_status='unknown'),clock(600)])
def test_unreadable_cue_value_does_not_enter_window_hash_or_reasons(validity):
    scope,semantics,sample,cue=inputs()
    def query(value):
        changed=replace(cue,observation=replace(cue.observation,fact=replace(cue.observation.fact,
            value=value,valid_at=validity)))
        return resolve_choice_windows(scope,(sample,),(changed,),semantics=semantics,
            admission=admission(scope,semantics,sample,cues=(changed,)))
    first,second=query(True),query(False)
    assert first['windows']==second['windows']
    assert first['supported_choice_count']==first['excluded_count']==0
