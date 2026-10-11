from collections import Counter
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from dota_coach.ingest.trace import parse_trace
from dota_coach.ingest.unit_control import build_unit_control_source


def ent(index, generation=1, cn='CDOTA_Unit_Hero_Axe', fields=None, *, full=True, op=9, removed=()):
    return {'t':'entity','entity_index':index,'generation':generation,'class':cn,
        'fields':fields or {},'field_types':{k:'uint64' if isinstance(v,str) else 'bool' if type(v) is bool else 'uint32' for k,v in (fields or {}).items()},
        'removed_fields':list(removed),'full_snapshot':full,'op_bits':op,'op':'test'}


def rows():
    return [{'t':'meta','schema_version':'replay-trace.v3','replay_sha256':'a'*64},
        ent(9,cn='CDOTA_PlayerResource',fields={
            'm_vecPlayerData.0005.m_iPlayerSteamID':'76561197960265739',
            'm_vecPlayerTeamData.0005.m_hSelectedHero':str(1+(1<<14))}),
        ent(1,fields={'m_iPlayerID':0,'m_bIsIllusion':False}),
        ent(2,cn='CDOTA_BaseNPC_Creep',fields={'m_iIsControllableByPlayer64':'1','m_bIsIllusion':False}),
        ent(3,fields={'m_iPlayerID':1,'m_bIsIllusion':True}),
        {'t':'file_info','data':{'game_info':{'dota':{'match_id':'7'}}}},
        {'t':'trace_end','parser_completed':True,'game_build':1}]


def write(tmp_path, values):
    values = deepcopy(values)
    for i,row in enumerate(values):
        row.update(record_index=i+1,net_tick=i,demo_tick=i,sequence_in_tick=0)
        if row['t']=='entity':
            row['field_types']={k:'uint64' if isinstance(v,str) else 'bool' if type(v) is bool else 'float64' if type(v) is float else 'int32' if type(v) is int and v<0 else 'uint32' for k,v in row['fields'].items()}
    values[-1]['counts'] = dict(Counter(r['t'] for r in values))
    path=tmp_path/'units.jsonl'
    path.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in values),encoding='utf-8')
    return path,parse_trace(path,7)


def build(tmp_path, values=None, cutoffs=()):
    path,result=write(tmp_path, values or rows())
    return build_unit_control_source(path,extraction=result,account_id=11,cutoff_record_indices=cutoffs)


def nodes(graph): return {n['entity_index']:n for n in graph['nodes']}


def test_mask_uses_selected_hero_player_id_not_resource_slot(tmp_path):
    graph=build(tmp_path)['final_observation']; n=nodes(graph)
    assert graph['binding']['resource_slot']==5 and graph['raw_player_id']==0
    assert set(n)=={1,2} and n[2]['associations']['raw_control_bit_set'] is True
    assert n[2]['control_available'] is None and n[2]['player_visibility'] is None
    assert n[1]['illusion_raw']['value'] is False and graph['training_eligible'] is False


def test_raw_illusion_is_independent_of_hero_class_and_selected_primary(tmp_path):
    values=rows();values[4]['fields']['m_iPlayerID']=0
    n=nodes(build(tmp_path,values)['final_observation'])
    assert n[3]['illusion_raw']['value'] is True
    assert n[3]['classification']=='raw_associated_unit_kind_unverified'
    assert n[3]['associations']['selected_hero'] is False


def test_owner_handle_chain_retains_all_edge_receipts_without_granting_control(tmp_path):
    values=rows();values[3]=ent(2,cn='CDOTA_BaseNPC_Creep',fields={'m_hOwnerNPC':1+(1<<14)})
    values.insert(5,ent(4,cn='CDOTA_BaseNPC_Creep',fields={'m_hOwnerEntity':2+(1<<14)}))
    n=nodes(build(tmp_path,values)['final_observation'])
    path=n[4]['associations']['raw_owner_path']['path']
    assert [e['to']['entity_index'] for e in path]==[2,1]
    assert n[4]['associations']['raw_control_bit_set'] is None and n[4]['control_available'] is None


def test_deleted_owner_generation_cannot_be_replaced_by_same_index(tmp_path):
    values=rows();values[3]=ent(2,cn='CDOTA_BaseNPC_Creep',fields={'m_hOwnerEntity':1+(1<<14)})
    values[5:5]=[ent(1,full=False,op=20),ent(1,2,fields={'m_iPlayerID':0})]
    graph=build(tmp_path,values)['final_observation']
    assert graph['binding']['selected_hero'] is None and graph['nodes']==[]


def test_delayed_old_delete_does_not_remove_new_lifetime(tmp_path):
    values=rows();values[5:5]=[ent(2,2,cn='CDOTA_BaseNPC_Creep',fields={'m_iIsControllableByPlayer64':'1'}),
        ent(2,1,cn='CDOTA_BaseNPC_Creep',full=False,op=20)]
    assert nodes(build(tmp_path,values)['final_observation'])[2]['generation']==2


def test_left_suppresses_state_until_entered_and_is_not_player_fow(tmp_path):
    values=rows();values[5:5]=[ent(2,cn='CDOTA_BaseNPC_Creep',full=False,op=16),
        ent(2,cn='CDOTA_BaseNPC_Creep',full=False,op=2),ent(2,cn='CDOTA_BaseNPC_Creep',full=False,op=10)]
    result=build(tmp_path,values,(7,8,9))
    assert 2 not in nodes(result['snapshots'][0]) and 2 not in nodes(result['snapshots'][1])
    assert 2 in nodes(result['snapshots'][2])


def test_retired_full_snapshot_cannot_resurrect_a_deleted_lifetime(tmp_path):
    values=rows();values[5:5]=[ent(2,cn='CDOTA_BaseNPC_Creep',full=False,op=20),
        ent(2,cn='CDOTA_BaseNPC_Creep',fields={'m_iIsControllableByPlayer64':'1'})]
    result=build(tmp_path,values)
    assert 2 not in nodes(result['final_observation'])
    assert result['source_operations']['retired_lifetime_ignored']==1


def test_missing_player_id_does_not_fall_back_to_slot_or_owner_id(tmp_path):
    values=rows();values[2]['fields']={'m_nPlayerOwnerID':0}
    graph=build(tmp_path,values)['final_observation']
    assert graph['raw_player_id'] is None and set(nodes(graph))=={1}


def test_missing_control_bit_is_unknown_while_explicit_zero_is_false(tmp_path):
    values=rows();values[3]['fields']={'m_iPlayerID':0,'m_iIsControllableByPlayer64':'0'}
    values[4]['fields']={'m_iPlayerID':0}
    n=nodes(build(tmp_path,values)['final_observation'])
    assert n[2]['associations']['raw_control_bit_set'] is False
    assert n[3]['associations']['raw_control_bit_set'] is None


@pytest.mark.parametrize('value',['-1','01','18446744073709551616',True,1.0,None])
def test_invalid_raw_mask_never_yields_control_candidate(tmp_path,value):
    values=rows();values[3]['fields']['m_iIsControllableByPlayer64']=value
    if value is None:
        assert 2 not in nodes(build(tmp_path,values)['final_observation'])
    else:
        with pytest.raises(ValueError,match='wire value'): build(tmp_path,values)


def test_ambiguous_live_resources_do_not_select_an_own_hero(tmp_path):
    values=rows();values.insert(5,ent(10,cn='CDOTA_PlayerResource',fields=values[1]['fields']))
    graph=build(tmp_path,values)['final_observation']
    assert graph['binding_status']=='ambiguous_resources' and graph['binding'] is None and graph['nodes']==[]


@pytest.mark.parametrize('mode',['full-replace','remove-selected','remove-steam','resource-delete'])
def test_removed_resource_operand_never_reuses_old_identity(tmp_path,mode):
    values=rows()
    if mode=='full-replace': change=ent(9,cn='CDOTA_PlayerResource')
    elif mode=='resource-delete': change=ent(9,cn='CDOTA_PlayerResource',full=False,op=20)
    else: change=ent(9,cn='CDOTA_PlayerResource',full=False,op=2,removed=[
        'm_vecPlayerTeamData.0005.m_hSelectedHero' if mode=='remove-selected' else 'm_vecPlayerData.0005.m_iPlayerSteamID'])
    values.insert(5,change)
    assert build(tmp_path,values)['final_observation']['nodes']==[]


def test_prefix_excludes_equal_boundary_and_future_identity_or_hidden_metadata(tmp_path):
    values=rows();a=build(tmp_path,values,(4,))['snapshots'][0]
    values[3]['fields']={'m_iIsControllableByPlayer64':'18446744073709551615'}
    values[4]=ent(1,2,fields={'m_iPlayerID':5})
    values[-2]['data']['future_winner']=True
    b=build(tmp_path,values,(4,))['snapshots'][0]
    assert a==b and set(nodes(a))=={1}


def test_receipts_strictly_precede_boundary_and_return_value_not_shared(tmp_path):
    result=build(tmp_path,cutoffs=(3,4,5))
    assert result['snapshots'][0]['binding']['selected_hero'] is None
    assert [s['associated_unit_count'] for s in result['snapshots']]==[0,1,2]
    result['final_observation']['nodes'][0]['fields']['m_iPlayerID']['value']=42
    assert result['snapshots'][1]['nodes'][0]['fields']['m_iPlayerID']['value']==0


@pytest.mark.parametrize('cutoffs',[(0,),(-1,),(True,),(4,3),(3,3),[3],(999999,)])
def test_bad_cutoffs_rejected(tmp_path,cutoffs):
    path,result=write(tmp_path,rows())
    with pytest.raises(ValueError):build_unit_control_source(path,extraction=result,account_id=11,cutoff_record_indices=cutoffs)


def test_replay_hash_binding_and_byte_mutation_are_checked(tmp_path):
    path,result=write(tmp_path,rows());path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError,match='source differs'):build_unit_control_source(path,extraction=result,account_id=11)


def test_truncated_trace_never_publishes_prefix(tmp_path):
    path,result=write(tmp_path,rows());path.write_text('\n'.join(path.read_text().splitlines()[:-1])+'\n')
    with pytest.raises(ValueError):build_unit_control_source(path,extraction=result,account_id=11,cutoff_record_indices=(3,))


def test_owner_cycle_is_bounded_and_cannot_manufacture_selected_hero(tmp_path):
    values=rows();values[3]['fields']={'m_iPlayerID':0,'m_hOwnerEntity':3+(1<<14)}
    values[4]['fields']={'m_hOwnerEntity':2+(1<<14)}
    graph=build(tmp_path,values)['final_observation']
    assert nodes(graph)[2]['associations']['raw_owner_path']['status']=='cycle_or_unresolved'


def test_foreign_extraction_identity_refused(tmp_path):
    path,result=write(tmp_path,rows());result.audit['match_id']=8
    with pytest.raises(ValueError,match='binding'):build_unit_control_source(path,extraction=result,account_id=11)


@pytest.mark.parametrize('mutation',['conflict','wrong-type','missing-type','duplicate-removal'])
def test_malformed_go_field_projection_cannot_create_association(tmp_path,mutation):
    path,_=write(tmp_path,rows())
    values=[json.loads(r) for r in path.read_text().splitlines()]
    row=values[3]
    if mutation=='conflict': row['removed_fields']=['m_iIsControllableByPlayer64']
    elif mutation=='wrong-type': row['field_types']['m_iIsControllableByPlayer64']='bool'
    elif mutation=='missing-type': row['field_types'].pop('m_iIsControllableByPlayer64')
    else: row['removed_fields']=['absent','absent']
    path.write_text(''.join(json.dumps(r)+'\n' for r in values),encoding='utf-8')
    r=parse_trace(path,7)
    with pytest.raises(ValueError):build_unit_control_source(path,extraction=r,account_id=11)
