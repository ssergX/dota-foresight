"""Source-prefix ward planning does not infer visibility or historical intent."""
from copy import deepcopy
from dataclasses import replace

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.learning.ward_plan import (
    build_ward_observations, create_ward_plan, ward_source_context,
)
from tests.test_live_report import sources


def ward_trace(rows=None):
    trace,_=sources()
    callbacks=rows if rows is not None else [
        callback(10,100,time=1), callback(20,101,time=2),
        callback(30,100,op='gone',time=3), callback(40,100,generation=1,time=4),
    ]
    return replace(trace,replay=replace(trace.replay,teams={0:2},
        manifest=replace(trace.replay.manifest,dataset_kind='synthetic')),
        audit=trace.audit|{'ward_timing_provenance':callbacks,'trace_sha256':'b'*64})


def callback(record,entity,*,generation=0,op='placed',time=1,team=2,refs=None):
    return {'record_index':record,'id':entity,'generation':generation,'op':op,
        'kind':'obs','team':team,'x':10.,'y':20.,'prefix_game_time':time,
        'clock_evidence_records':[record-1] if refs is None else refs,
        'retrospective_game_time':9999}


def observations(trace=None):
    return build_ward_observations(trace or ward_trace(),account_id=7,
        resource_slot=0,actor='npc_dota_hero_fixture')


def request(source=None,ward_id=None):
    source=source or observations()
    ward_id=ward_id or source['events'][1]['ward_id']
    return {'schema_version':'foresight.ward-plan-request.v1','ward_id':ward_id,
        'source_context_hash':ward_source_context(source,ward_id)['source_context_hash'],
        'goal_kind':'prepare_objective','goal_description':'Проверить путь команды к объекту',
        'confirmed':True,'alternatives':[]}


def rehash(source):
    source['payload_sha256']=content_hash({k:v for k,v in source.items() if k!='payload_sha256'})
    return source


def test_original_callback_time_and_identity_are_used_without_owner_promotion():
    source=observations()
    context=ward_source_context(source,source['events'][1]['ward_id'])
    assert context['placement_anchor']['game_time']==2
    assert context['placement_anchor']['source_record_index']==20
    assert context['placement_anchor']['source_ref']=='trace:123:record:20'
    assert context['source_binding']['account_id']==7
    assert context['owner']==context['player_availability']=='not_established'
    assert context['choice_boundary']=='not_established'
    assert context['source_binding']['dataset_kind']=='synthetic'


def test_raw_same_team_objects_are_not_attributed_information_or_vision():
    source=observations()
    plan=create_ward_plan(source,request(source))
    assert len(plan['preceding_same_team_objects'])==1
    assert plan['information_review']['status']=='insufficient_evidence'
    assert not plan['information_review']['novel_observation_ids']
    assert plan['utility']=='not_established' and plan['feasibility']=='unknown'
    assert plan['training_eligible'] is False
    assert {c['code']:c['status'] for c in plan['checks']}=={
        'task':'current_user_hypothesis','alignment':'unknown','safety':'unknown',
        'redundancy':'unknown','information':'unknown','alternatives':'unknown'}


def test_future_removal_new_wards_outcomes_and_full_receipts_do_not_change_prefix():
    trace=ward_trace();source=observations(trace)
    ward=source['events'][1]['ward_id']
    changed=replace(trace,audit=trace.audit|{
        'trace_sha256':'c'*64,'radiant_win':True,
        'ward_timing_provenance':trace.audit['ward_timing_provenance']+[
            callback(90,101,op='gone',time=100),callback(100,999,time=200)]},
        replay=replace(trace.replay,manifest=replace(trace.replay.manifest,replay_hash='d'*64),
            frames=[]))
    assert ward_source_context(source,ward)==ward_source_context(observations(changed),ward)


def test_removed_entity_generation_is_not_reused_as_an_active_object():
    source=observations()
    context=ward_source_context(source,source['events'][3]['ward_id'])
    assert [(e['entity_id'],e['generation']) for e in context['preceding_same_team_objects']]==[(101,0)]
    assert context['placement_anchor']['generation']==1


def test_duplicate_placement_prefix_is_conflicted_instead_of_active_vision():
    source=observations(ward_trace([callback(10,100),callback(11,100),callback(20,101)]))
    context=ward_source_context(source,source['events'][2]['ward_id'])
    assert not context['preceding_same_team_objects']
    assert context['lifecycle_conflicts']==['trace:123:record:11']


def test_missing_clock_provenance_does_not_backfill_retrospective_time():
    source=observations(ward_trace([callback(10,100,time=1,refs=[])]))
    row=source['events'][0]
    assert row['game_time'] is None and row['clock_status']=='unknown'
    plan=create_ward_plan(source,request(source,row['ward_id']))
    assert plan['placement_anchor']['game_time'] is None
    assert plan['verdict']=='insufficient_evidence'


@pytest.mark.parametrize('change', ('account','actor','slot','team'))
def test_wrong_planning_subject_or_team_cannot_bind_a_ward(change):
    trace=ward_trace()
    kwargs={'account_id':7,'resource_slot':0,'actor':'npc_dota_hero_fixture'}
    if change=='account':kwargs['account_id']=8
    if change=='actor':kwargs['actor']='npc_dota_hero_wrong'
    if change=='slot':kwargs['resource_slot']=1
    if change=='team':trace=replace(trace,replay=replace(trace.replay,teams={0:None}))
    with pytest.raises(ValueError):
        source=build_ward_observations(trace,**kwargs)
        ward_source_context(source,source['events'][0]['ward_id'])


def test_enemy_ward_is_not_selected_as_subject_team_plan():
    source=observations(ward_trace([callback(10,100,team=3)]))
    with pytest.raises(ValueError,match='another team'):
        ward_source_context(source,source['events'][0]['ward_id'])


@pytest.mark.parametrize('change', ('validation','owner','clock','future_clock','duplicate_record'))
def test_source_cannot_promote_itself_or_unavailable_clock_even_with_recomputed_hash(change):
    source=deepcopy(observations());row=source['events'][0]
    if change=='validation':source['validation']='verified'
    if change=='owner':row['owner']='player:7'
    if change=='clock':row['clock_evidence_records']=[]
    if change=='future_clock':row['clock_evidence_records']=[11]
    if change=='duplicate_record':source['events'].append(deepcopy(row))
    with pytest.raises(ValueError):
        ward_source_context(rehash(source),row['ward_id'])


def test_current_goal_and_proposed_coordinates_never_become_prior_intent_or_feasible_action():
    source=observations();row=request(source)
    row['alternatives']=[{'label':'Другая точка','rationale':'Сравнить путь', 'x':100,'y':-200}]
    plan=create_ward_plan(source,row)
    assert plan['declaration_receipt']['prior_intent']=='not_established'
    alternative=plan['proposed_alternatives'][0]
    assert alternative['origin']=='current_user_proposal'
    assert alternative['feasibility']==alternative['safety']=='unknown'
    assert alternative['benefit']=='not_established'
    assert not plan['information_review']['feasible_alternative_ids']


@pytest.mark.parametrize('change', ('unconfirmed','stale','self_promotion','coordinates'))
def test_declarations_fail_closed_before_any_plan_is_created(change):
    source=observations();row=request(source)
    if change=='unconfirmed':row['confirmed']=False
    if change=='stale':row['source_context_hash']='c'*64
    if change=='self_promotion':row['validation']='verified'
    if change=='coordinates':row['alternatives']=[{'label':'Точка','rationale':'Проверить','x':2,'y':None}]
    with pytest.raises(ValueError):create_ward_plan(source,row)


def test_revision_is_bound_to_previous_payload_and_same_subject():
    source=observations();first=create_ward_plan(source,request(source))
    changed=request(source,source['events'][3]['ward_id']);changed['previous_plan_id']=first['plan_id']
    second=create_ward_plan(source,changed,first)
    assert second['revision']==2 and second['previous_payload_sha256']==first['payload_sha256']
    assert second['comparison_scope']=='scenario_planning_not_behavior_progress'
    changed['previous_plan_id']='d'*64
    with pytest.raises(ValueError):create_ward_plan(source,changed,first)


def test_previous_declared_goal_receipt_must_match_its_receipt_hash():
    source=observations();previous=create_ward_plan(source,request(source))
    previous['declaration_receipt']['goal_description']='Несогласованная замена'
    previous['payload_sha256']=content_hash({k:v for k,v in previous.items() if k!='payload_sha256'})
    row=request(source);row['previous_plan_id']=previous['plan_id']
    with pytest.raises(ValueError):create_ward_plan(source,row,previous)


def test_stale_previous_same_anchor_context_is_rejected():
    source=observations();previous=create_ward_plan(source,request(source))
    source=deepcopy(source);source['events'][0]['x']=999;rehash(source)
    row=request(source);row['previous_plan_id']=previous['plan_id']
    with pytest.raises(ValueError,match='stale'):create_ward_plan(source,row,previous)
