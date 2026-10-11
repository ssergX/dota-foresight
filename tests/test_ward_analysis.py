"""Executable ward analytics distinguishes raw objects from attributed knowledge."""
from copy import deepcopy
from dataclasses import replace

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.learning.ward_analysis import (
    analyze_ward_prefix,analyze_ward_task,ward_evidence_record,
)
from dota_coach.validation.contracts import Annotation,FactCheck
from tests.test_ward_plan import observations,ward_trace,callback,rehash


def goal(**changes):
    return {'goal_kind':'prepare_objective','goal_description':'Проверить маршрут до начала командного действия',
        'confirmed':True,'information_predicate':'enemy.position',**changes}


def fact(identity,record,*,kind='observation',predicate='enemy.position',value='crossing',
         entity='enemy:1',available=None,perspective='team',action=None,time=None,**changes):
    row={'fact_id':identity,'kind':kind,'record_index':record,
        'available_record_index':record if available is None else available,
        'game_time_ms':record*100 if time is None else time,'entity_ref':entity,
        'predicate':predicate,'value':value,'perspective':perspective,
        'source_ref':f'client-prefix:123:record:{record}',
        'source_record_hash':content_hash({'record':record,'value':value}),**changes}
    if action is not None:row['action_id']=action
    return row


def corpus(source,rows):
    result={'schema_version':'foresight.ward-task-evidence.v1',
        'source_binding':{k:source[k] for k in ('match_id','account_id','resource_slot','actor',
            'subject_team','dataset_kind','replay_sha256')},'patch':'fixture-patch','facts':rows}
    result['payload_sha256']=content_hash(result)
    return result


def labels(source,ward,proof,*,cutoff=50,raters=2):
    record=ward_evidence_record(source,ward,proof,cutoff_record_index=cutoff)
    prefix=[r for r in proof['facts'] if r['record_index']<=cutoff and
        r['available_record_index'] is not None and r['available_record_index']<=cutoff]
    annotations=tuple(Annotation(record.decision_id,record.input_hash,record.replay_hash,record.patch,
        f'reviewer:{i}',('insufficient_evidence',),'unknown','Review exact supplied source records',
        facts_checked=tuple(FactCheck(r['fact_id'],'correct','available','Checked prefix reference') for r in prefix),
        unknowns=('independent client access not established',),review_pass='extraction',
        dataset_kind=record.dataset_kind) for i in range(raters))
    return (record,),annotations


def information_fixture():
    source=observations();ward=source['events'][1]['ward_id']
    rows=[fact('earlier',15),fact('same',21),
        fact('link-same',22,kind='attribution',predicate='team.observation_attributed_to',value=ward,entity='same'),
        fact('changed',23,value='leaving'),
        fact('link-changed',24,kind='attribution',predicate='team.observation_attributed_to',value=ward,entity='changed'),
        fact('complete',50,kind='coverage',predicate='team.observation_prefix_complete',value=True,
             entity='team:2',coverage_start_record=0,coverage_end_record=50)]
    proof=corpus(source,rows);records,annotations=labels(source,ward,proof)
    return source,ward,proof,records,annotations


def test_real_computation_is_available_without_a_fabricated_confirmed_goal():
    source=observations();ward=source['events'][1]['ward_id']
    result=analyze_ward_prefix(source,ward)
    raw=result['callback_analysis']
    assert result['task'] is None and result['task_status']=='not_supplied'
    assert raw['callback_count']==2 and raw['placement_callbacks']==2
    assert raw['known_prefix_clock_callbacks']==2
    assert raw['coordinate_comparisons'][0]['same_raw_coordinates'] is True
    assert raw['vision_redundancy']=='not_established' and raw['active_vision_source_count'] is None
    assert result['training_eligible'] is False


def test_distinct_raw_coordinates_are_not_radius_geometry_or_information_overlap():
    source=observations();source['events'][0]['x']=11;rehash(source)
    raw=analyze_ward_prefix(source,source['events'][1]['ward_id'])['callback_analysis']
    assert raw['coordinate_comparisons'][0]['same_raw_coordinates'] is False
    assert raw['geometry']=='not_validated'
    assert 'radius' not in raw and 'utility' not in raw


def test_duplicate_generations_or_orphan_removals_are_counted_as_source_conflicts():
    source=observations(ward_trace([callback(1,9,op='gone'),callback(10,100),
        callback(11,100),callback(20,101)]))
    raw=analyze_ward_prefix(source,source['events'][-1]['ward_id'])['callback_analysis']
    assert raw['observed_object_states']=={'conflict':1,'placement_unobserved':1,'placement_without_removal':1}
    assert raw['conflict_source_refs']==['trace:123:record:11']
    assert raw['placement_unobserved_source_refs']==['trace:123:record:1']
    assert not raw['coordinate_comparisons']


def test_unknown_original_clock_stays_unknown_in_measured_callback_coverage():
    source=observations(ward_trace([callback(10,100,refs=[]),callback(20,101)]))
    raw=analyze_ward_prefix(source,source['events'][1]['ward_id'])['callback_analysis']
    assert raw['known_prefix_clock_callbacks']==1 and raw['unknown_prefix_clock_callbacks']==1
    assert raw['opportunity_coverage'] is None


def test_future_callbacks_receipts_frames_and_outcomes_do_not_change_prefix_analysis():
    source=observations();ward=source['events'][1]['ward_id']
    changed=deepcopy(source);changed['replay_sha256']='c'*64;changed['trace_sha256']='d'*64
    changed['radiant_win']=True
    new=deepcopy(changed['events'][2]);new.update(source_record_index=100,
        source_ref='trace:123:record:100',ward_id='ward:123:100:0:record:100',game_time=100,
        clock_evidence_records=[99]);changed['events'].append(new);rehash(changed)
    assert analyze_ward_prefix(source,ward)==analyze_ward_prefix(changed,ward)


def test_reviewed_matching_attribution_and_prior_history_compute_duplicates_and_new_information():
    source,ward,proof,records,annotations=information_fixture()
    result=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
    info=result['information_analysis']
    assert info['status']=='conditional_reviewed_information'
    assert info['duplicate_observation_ids']==['same']
    assert info['novel_observation_ids']==['changed']
    assert info['task_matching_observation_ids']==['same','changed']
    assert info['utility']=='not_established'
    assert result['validation_status']=='external_provenance_and_domain_validation_pending'
    assert result['training_eligible'] is False


def test_one_reviewer_and_unreviewed_corpus_cannot_establish_received_information():
    source,ward,proof,_,_=information_fixture()
    for records,annotations in (((),()),labels(source,ward,proof,raters=1)):
        result=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
        assert not result['reviewed_fact_ids']
        assert result['information_analysis']['status']=='attribution_not_established'


def test_coordinate_proximity_without_reviewed_attribution_does_not_credit_ward():
    source,ward,proof,_,_=information_fixture()
    proof=corpus(source,[r for r in proof['facts'] if r['kind']!='attribution'])
    records,annotations=labels(source,ward,proof)
    result=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
    assert not result['information_analysis']['attributed_observation_ids']
    assert not result['information_analysis']['novel_observation_ids']


def test_attribution_without_complete_history_does_not_call_information_novel():
    source,ward,proof,_,_=information_fixture()
    proof=corpus(source,[r for r in proof['facts'] if r['kind']!='coverage'])
    records,annotations=labels(source,ward,proof)
    result=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
    info=result['information_analysis']
    assert info['attributed_observation_ids']==['same','changed']
    assert info['status']=='reviewed_attribution_without_complete_prior_history'
    assert not info['novel_observation_ids']


def test_simultaneous_disagreement_is_not_resolved_by_callback_order():
    source,ward,proof,_,_=information_fixture()
    proof=corpus(source,proof['facts']+[fact('contradiction',25,value='elsewhere',time=2300)])
    records,annotations=labels(source,ward,proof)
    info=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)['information_analysis']
    assert info['status']=='simultaneous_observation_conflict'
    assert not info['novel_observation_ids'] and not info['duplicate_observation_ids']


def test_future_or_undelivered_knowledge_never_enters_review_prefix_or_hash():
    source,ward,proof,records,annotations=information_fixture()
    changed=corpus(source,proof['facts']+[fact('future',100,value='dead'),fact('late-delivered',45,available=90)])
    first=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
    second=analyze_ward_task(source,ward,goal(),evidence=changed,records=records,annotations=annotations,cutoff_record_index=50)
    assert first==second


@pytest.mark.parametrize('field,value', (('account_id',8),('replay_sha256','c'*64),('actor','other'),('subject_team',3)))
def test_foreign_evidence_binding_is_rejected_even_after_rehash(field,value):
    source,ward,proof,_,_=information_fixture()
    proof['source_binding'][field]=value
    proof['payload_sha256']=content_hash({k:v for k,v in proof.items() if k!='payload_sha256'})
    with pytest.raises(ValueError,match='another account, replay or source'):
        analyze_ward_task(source,ward,goal(),evidence=proof,cutoff_record_index=50)


def test_forged_verified_flags_cannot_replace_source_reviews():
    source,ward,proof,_,_=information_fixture()
    proof['facts'][0]['validation_status']='verified'
    proof['payload_sha256']=content_hash({k:v for k,v in proof.items() if k!='payload_sha256'})
    with pytest.raises(ValueError,match='validation flags'):
        analyze_ward_task(source,ward,goal(),evidence=proof,cutoff_record_index=50)


def test_system_reviewers_cannot_supply_the_admission_pair():
    source,ward,proof,records,annotations=information_fixture()
    annotations=tuple(replace(a,annotator_kind='system') for a in annotations)
    result=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
    assert not result['reviewed_fact_ids']


def test_reviewed_preplacement_booleans_keep_false_and_pairwise_constraints_without_utility():
    source=observations();ward=source['events'][1]['ward_id'];action='placement:'+ward
    alternatives=[{'action_id':'proposal:route','label':'Другая точка','rationale':'Другой маршрут','x':50,'y':60}]
    proof=corpus(source,[fact('selected-safe',11,kind='condition',predicate='placement.safe',value=False,action=action),
        fact('selected-feasible',12,kind='condition',predicate='placement.feasible',value=True,action=action),
        fact('other-safe',13,kind='condition',predicate='placement.safe',value=True,action='proposal:route')])
    records,annotations=labels(source,ward,proof,cutoff=20)
    result=analyze_ward_task(source,ward,goal(),alternatives=alternatives,evidence=proof,records=records,annotations=annotations)
    assert result['options'][0]['safe']['value'] is False
    assert result['options'][0]['feasible']['value'] is True
    assert result['options'][1]['safe']['value'] is True
    assert result['options'][1]['feasible']['value'] is None
    assert result['pairwise_alternatives'][0]['condition_differences']==['safe']
    assert result['pairwise_alternatives'][0]['ranking']=='not_established'
    assert result['pairwise_alternatives'][0]['benefit_difference'] is None


def test_future_or_world_safety_proof_cannot_describe_preplacement_available_route():
    source=observations();ward=source['events'][1]['ward_id'];action='placement:'+ward
    proof=corpus(source,[fact('future-safe',30,kind='condition',predicate='placement.safe',value=True,action=action),
        fact('world-feasible',12,kind='condition',predicate='placement.feasible',value=True,action=action,perspective='world')])
    records,annotations=labels(source,ward,proof)
    result=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
    assert result['options'][0]['safe']['value'] is None
    assert result['options'][0]['feasible']['value'] is None


def test_goal_change_changes_task_alignment_without_rewriting_historical_intent():
    source,ward,proof,records,annotations=information_fixture()
    first=analyze_ward_task(source,ward,goal(),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
    second=analyze_ward_task(source,ward,goal(information_predicate='enemy.resource',goal_description='Иной вопрос'),evidence=proof,records=records,annotations=annotations,cutoff_record_index=50)
    assert first['source_context_hash']==second['source_context_hash']
    assert first['evidence_prefix_hash']==second['evidence_prefix_hash']
    assert second['task']['prior_intent']=='not_established'
    assert not second['information_analysis']['task_matching_observation_ids']


def test_review_cutoff_and_invalid_goal_are_rejected_instead_of_using_a_dummy_goal():
    source=observations();ward=source['events'][1]['ward_id']
    with pytest.raises(ValueError):analyze_ward_prefix(source,ward,cutoff_record_index=10)
    with pytest.raises(ValueError):analyze_ward_task(source,ward,goal(confirmed=False))
    with pytest.raises(ValueError):analyze_ward_task(source,ward,None)
