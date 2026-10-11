"""Computed feasibility/window contracts; fixtures are not Dota certification."""
from dataclasses import asdict, replace
import json

import pytest

from dota_coach.decisions.choice_window import (
    ChoiceCue, ChoiceSample, ChoiceScope, EvidenceAdmission, MechanicalSemantics,
    PrefixFact, derive_feasibility, load_choice_evidence, resolve_choice_windows,
)
from dota_coach.evidence.contracts import EntityRef, Fact, SourceRef, TimeRef, content_hash


def clock(ms, uncertainty=0):
    return TimeRef(ms, int(ms)//10, 0, uncertainty, 'fixture.clock.v1', 'verified')


def operand(predicate, value, *, available=800, perspective='screen', record=40):
    ref=SourceRef('fixture','a'*64,'synthetic_observation','fixture.v1','record:'+str(record))
    fact=Fact('fixture:'+predicate,'account:9',predicate,value,'observed',clock(available),
        clock(available),perspective,(ref,),observer_ref='account:9',method_version='fixture.v1')
    return PrefixFact(fact,record)


def inputs(**changes):
    scope=ChoiceScope(7,'account:9','fixture.patch','item_fixture',EntityRef('match:7',12,3),
        'fixture.clock.v1',dataset_kind='synthetic')
    mechanics=MechanicalSemantics('fixture.patch','item_fixture','fixture.mechanics.v1',
        'remaining_duration',4,'self')
    values={'self.alive':True,'self.mana':100,'item.mana_cost':50,'item.entity_index':12,
        'item.generation':3,'item.slot':2,'self.control_bits':0,'item.cooldown':0,
        'item.cooldown_frozen':False,'item.cooldown_indefinite':False,'item.requires_charges':False}
    values.update(changes)
    sample=ChoiceSample('s1',clock(1000),100,tuple(operand(k,v) for k,v in values.items()),False)
    cue=ChoiceCue(operand('screen.reaction_cue',True,available=500,record=20),clock(1800),False,clock(500),20)
    return scope,mechanics,sample,cue


def admission(scope, mechanics, *samples, cues=()):
    all_facts=[f for s in samples for f in s.facts]+[c.observation for c in cues]
    ref=SourceRef('fixture.review','b'*64,'synthetic_review','fixture.v1','review:fixture')
    return EvidenceAdmission(scope.match_id,scope.subject_ref,scope.patch,scope.item_id,
        frozenset(f.input_hash for f in all_facts),frozenset({content_hash(mechanics)}),(ref,),
        frozenset(content_hash(s) for s in samples),frozenset(content_hash(c) for c in cues))


def test_feasibility_is_computed_from_operands_and_admits_no_portable_verified_switch():
    scope,mechanics,sample,cue=inputs()
    proposed=derive_feasibility(scope,sample,semantics=mechanics)
    assert proposed['candidate_feasibility']=='feasible' and proposed['feasibility']=='unknown'
    reviewed=derive_feasibility(scope,sample,semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    assert reviewed['feasibility']=='feasible' and reviewed['mana_after_cost_arithmetic']==50
    assert reviewed['derived_fact']['value'] is True and reviewed['training_eligible'] is False
    with pytest.raises(TypeError,match='portable'):
        derive_feasibility(scope,sample,admission={'status':'validated'})


@pytest.mark.parametrize('values,code', [
    ({'self.mana':49},'mana_covers_exact_item_cost'),
    ({'self.alive':False},'subject_alive'),
    ({'item.generation':4},'exact_item_generation'),
    ({'item.slot':7},'interpreted_inventory_slot'),
    ({'self.control_bits':4},'interpreted_control_allows_activation'),
    ({'item.cooldown':10},'interpreted_cooldown_allows_activation'),
    ({'item.requires_charges':True,'item.charges':0},'interpreted_charges_available'),
])
def test_operand_disproof_excludes_action_without_utility_or_outcome(values,code):
    scope,mechanics,sample,cue=inputs(**values)
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    assert result['excluded_count']==1 and result['supported_choice_count']==0
    conditions=result['feasibility_samples'][0]['conditions']
    assert next(c for c in conditions if c['code']==code)['value'] is False
    assert result['strategic_quality']=='not_established' and result['training_eligible'] is False


def test_reviewed_cue_and_source_conditions_compute_supported_sampled_choice():
    scope,mechanics,sample,cue=inputs()
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    window,=result['windows']
    assert window['status']=='supported_choice'
    assert window['guaranteed_interval_ms']==[650,1800]
    assert window['stability']=='sampled_step_only_not_interpolated'
    assert result['game_opportunity_coverage'] is None


@pytest.mark.parametrize('mutator', [
    lambda s,c:(replace(s,paused=True),c),
    lambda s,c:(replace(s,at=clock(1000,600)),c),
    lambda s,c:(s,replace(c,paused=None)),
    lambda s,c:(s,replace(c,observation=operand('team.reaction_cue',True,available=500,perspective='team',record=20))),
])
def test_pause_uncertainty_and_team_cue_do_not_grant_reaction_window(mutator):
    scope,mechanics,sample,cue=inputs();sample,cue=mutator(sample,cue)
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    assert result['supported_choice_count']==0 and result['unknown_count']==1


def test_material_control_change_closes_later_sample_without_rewriting_earlier_one():
    scope,mechanics,first,cue=inputs()
    second=replace(first,sample_id='s2',prefix_record_index=110,at=clock(1100),
        facts=tuple(operand('self.control_bits',4) if f.fact.predicate=='self.control_bits' else f for f in first.facts))
    registry=admission(scope,mechanics,first,second,cues=(cue,))
    combined=resolve_choice_windows(scope,(first,second),(cue,),semantics=mechanics,admission=registry)
    original=resolve_choice_windows(scope,(first,),(cue,),semantics=mechanics,admission=registry)
    assert combined['windows'][0]==original['windows'][0]
    assert [w['status'] for w in combined['windows']]==['supported_choice','excluded']


def test_missing_cost_expired_operand_and_altered_sample_binding_stay_unknown():
    scope,mechanics,sample,cue=inputs()
    registry=admission(scope,mechanics,sample,cues=(cue,))
    for changed in (replace(sample,facts=tuple(f for f in sample.facts if f.fact.predicate!='item.mana_cost')),
                    replace(sample,at=clock(2500))):
        result=derive_feasibility(scope,changed,semantics=mechanics,admission=registry)
        assert result['feasibility']=='unknown'


def test_future_and_foreign_resource_facts_are_refused():
    scope,mechanics,sample,_=inputs()
    for invalid in (replace(sample.facts[0],source_record_index=100),
                    replace(sample.facts[0],fact=replace(sample.facts[0].fact,subject_ref='account:8'))):
        with pytest.raises(ValueError):
            derive_feasibility(scope,replace(sample,facts=(invalid,*sample.facts[1:])),semantics=mechanics)


@pytest.mark.parametrize('valid_at',[clock(1200),replace(clock(500),clock_mapping_version='foreign.clock')])
def test_review_receipt_cannot_admit_future_or_foreign_cue_validity(valid_at):
    scope,mechanics,sample,cue=inputs()
    cue=replace(cue,observation=replace(cue.observation,
        fact=replace(cue.observation.fact,valid_at=valid_at)))
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    assert result['supported_choice_count']==0 and result['unknown_count']==1
    assert 'cue_validity_not_established_before_sample' in result['windows'][0]['reason_codes']


@pytest.mark.parametrize('component',['validity','expiry'])
def test_unknown_cue_order_cannot_grant_or_exclude_choice(component):
    scope,mechanics,sample,cue=inputs()
    if component=='validity':
        cue=replace(cue,observation=replace(cue.observation,fact=replace(cue.observation.fact,
            valid_at=replace(cue.observation.fact.valid_at,order_status='unknown'))))
    else:cue=replace(cue,expires_at=replace(cue.expires_at,order_status='unknown'))
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    assert result['supported_choice_count']==0 and result['unknown_count']==1


def test_future_operand_tick_cannot_grant_feasibility_despite_older_numeric_time():
    scope,mechanics,sample,cue=inputs()
    sample=replace(sample,facts=tuple(replace(f,fact=replace(f.fact,
        valid_at=replace(f.fact.valid_at,replay_tick=101))) if f.fact.predicate=='self.mana' else f for f in sample.facts))
    result=derive_feasibility(scope,sample,semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    assert result['feasibility']=='unknown'


def test_late_observed_cue_disappearance_cannot_change_earlier_window():
    scope,mechanics,sample,cue=inputs()
    missing=replace(cue,expires_at=None,expiry_available_at=None,expiry_source_record_index=None)
    future=replace(cue,expires_at=clock(950),expiry_available_at=clock(1200),expiry_source_record_index=120)
    changed=replace(future,expires_at=clock(700))
    results=[resolve_choice_windows(scope,(sample,),(c,),semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(c,))) for c in (missing,future,changed)]
    assert results[0]['windows']==results[1]['windows']==results[2]['windows']
    assert results[0]['unknown_count']==1


def test_unparsed_unit_target_identity_remains_unknown_instead_of_disproof():
    scope,mechanics,sample,cue=inputs()
    scope=replace(scope,target_entity=EntityRef('match:7',55,2))
    mechanics=replace(mechanics,target_mode='unit',allowed_target_teams=(3,))
    extra={'target.entity_index':'unparsed','target.generation':2,'target.alive':True,
        'target.team':3,'target.distance':100,'self.cast_range':500}
    sample=replace(sample,facts=sample.facts+tuple(operand(k,v) for k,v in extra.items()))
    result=derive_feasibility(scope,sample,semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    assert result['feasibility']=='unknown'


def test_portable_loader_refuses_duplicate_json_fields_and_admission(tmp_path):
    scope,mechanics,_,cue=inputs()
    payload={'schema_version':'foresight.choice-evidence.v1','scope':asdict(scope),
        'semantics':asdict(mechanics),'cues':[asdict(cue)]}
    assert load_choice_evidence(payload)['scope']==scope
    with pytest.raises(ValueError):load_choice_evidence(payload|{'admission':'validated'})
    path=tmp_path/'input.json';path.write_text('{"schema_version":"x","schema_version":"y"}',encoding='utf-8')
    with pytest.raises(ValueError,match='duplicate'):load_choice_evidence(path)


def test_raw_adapter_processes_uncast_frames_without_future_entity_selection():
    from copy import deepcopy
    from tests.test_opportunity_discovery import artifact,seal
    from dota_coach.decisions.choice_window import resolve_resource_choice_windows
    states,extraction=artifact()
    states['timeline'][0]['inventory']=[];seal(states)
    first=resolve_resource_choice_windows(states,extraction)
    changed=deepcopy(states)
    item=changed['timeline'][1]['inventory'][0]
    item['generation']=8;item['handle']=str(item['entity_index']+(8<<14))
    item['handle_fact']['value']=int(item['handle']);seal(changed)
    second=resolve_resource_choice_windows(changed,extraction)
    assert first['scope']['item_entity'] is None
    assert first['windows'][0]==second['windows'][0]
    assert first['feasibility_samples'][0]==second['feasibility_samples'][0]
    assert first['sample_count']==3 and first['supported_choice_count']==0
    # Unmapped/undelivered clocks cannot enter choice arithmetic, even when
    # raw source records contain numeric mana and cost.
    assert first['feasibility_samples'][1]['mana_after_cost_arithmetic'] is None


def test_whole_source_receipt_change_does_not_change_analytical_features():
    scope,mechanics,sample,cue=inputs()
    def receipt_changed(prefix):
        fact=prefix.fact
        return replace(prefix,fact=replace(fact,source_refs=tuple(replace(s,content_hash='d'*64,artifact_id='changed-full-artifact') for s in fact.source_refs)))
    changed_sample=replace(sample,facts=tuple(receipt_changed(f) for f in sample.facts))
    changed_cue=replace(cue,observation=receipt_changed(cue.observation))
    first=resolve_choice_windows(scope,(sample,),(cue,),semantics=mechanics,
        admission=admission(scope,mechanics,sample,cues=(cue,)))
    second=resolve_choice_windows(scope,(changed_sample,),(changed_cue,),semantics=mechanics,
        admission=admission(scope,mechanics,changed_sample,cues=(changed_cue,)))
    assert first['windows']==second['windows']
    assert first['feasibility_samples'][0]['input_hash']==second['feasibility_samples'][0]['input_hash']


def reviewed_fixture(raters=2):
    from dota_coach.decisions.choice_window import choice_evidence_record
    from dota_coach.validation.contracts import Annotation,FactCheck
    scope,mechanics,sample,cue=inputs()
    scope=replace(scope,dataset_kind='replay')
    record=choice_evidence_record(scope,sample,(cue,),mechanics,replay_sha256='c'*64)
    ids=[f.fact.fact_id for f in sample.facts]+[cue.observation.fact.fact_id,
        'sample:'+content_hash(sample),'cue:'+content_hash(cue),'mechanics:'+content_hash(mechanics)]
    labels=tuple(Annotation(record.decision_id,record.input_hash,record.replay_hash,record.patch,
        'fixture-reviewer:'+str(i),('insufficient_evidence',),'unknown','Synthetic contract review',
        facts_checked=tuple(FactCheck(fid,'correct','available','Fixture exact source') for fid in ids),
        unknowns=('real human and client validation absent',),review_pass='extraction') for i in range(raters))
    return scope,mechanics,sample,cue,record,labels


def test_exact_reviewed_input_derives_conditions_without_authenticating_humans():
    from dota_coach.decisions.choice_window import resolve_reviewed_choice_admission
    scope,mechanics,sample,cue,record,labels=reviewed_fixture()
    registry=resolve_reviewed_choice_admission(scope,(sample,),(cue,),mechanics,
        replay_sha256=record.replay_hash,records=iter((record,)),annotations=iter(labels))
    result=resolve_choice_windows(scope,(sample,),(cue,),semantics=mechanics,admission=registry)
    assert result['supported_choice_count']==1 and result['training_eligible'] is False
    assert result['validation_status']=='conditional_research_not_certified'
    for annotations in (labels[:1],(replace(labels[0],annotator_kind='self_evaluation'),labels[1])):
        registry=resolve_reviewed_choice_admission(scope,(sample,),(cue,),mechanics,
            replay_sha256=record.replay_hash,records=(record,),annotations=annotations)
        result=resolve_choice_windows(scope,(sample,),(cue,),semantics=mechanics,admission=registry)
        assert result['supported_choice_count']==0


def test_foreign_reviewed_clock_or_replay_cannot_reuse_choice_admission():
    from dota_coach.decisions.choice_window import resolve_reviewed_choice_admission
    scope,mechanics,sample,cue,record,labels=reviewed_fixture()
    for sampled,hash_value in ((replace(sample,at=clock(1100)),record.replay_hash),(sample,'e'*64)):
        with pytest.raises(ValueError,match='another'):
            resolve_reviewed_choice_admission(scope,(sampled,),(cue,),mechanics,
                replay_sha256=hash_value,records=(record,),annotations=labels)
