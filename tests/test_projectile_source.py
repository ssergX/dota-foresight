import copy
from types import SimpleNamespace
import pytest
from tests.test_order_source import write
from dota_coach.ingest.projectile_source import CALLBACKS,CONTEXT,SCHEMA,STEAM_BASE,load_projectile_source

def fixture(tmp_path):
    hero={'entity_index':42,'generation':3,'class_name':'CDOTA_Unit_Hero_Kez'}
    resource={'entity_index':10,'generation':9,'class_name':'CDOTA_PlayerResource'}
    selection={'resource':resource,'resource_slot':0,'selected_handle':3*16384+42,
        'selected_property':'m_vecPlayerTeamData.0000.m_hSelectedHero','steam_property':'m_vecPlayerData.0000.m_iPlayerSteamID',
        'steam_id':STEAM_BASE+11,'hero':hero}
    entity={**hero,'fields':{'m_iHealth':500,'m_flMana':150.0},'field_types':{'m_iHealth':'int32','m_flMana':'float32'}}
    def message(kind,data,role=None):
        refs={}
        if role:refs[role]={'raw_value':42,'index_candidate':copy.deepcopy(entity),'handle_candidate':None}
        return {'t':'projectile_message','protobuf_type':CALLBACKS[kind],'data':data,
            'entity_context':{'semantics':CONTEXT,'field_references':refs,'selected_heroes':[copy.deepcopy(selection)] if role else []},
            'protobuf_unknown_fields_hex':'a00101','damage':None,'impact_time':None,'screen_cue':None}
    meta={'t':'meta','schema_version':SCHEMA,'replay_sha256':'a'*64,'replay_bytes':12,
        'extractor_name':'manta','extractor_version':'foresight-replay/3.1','manta_version':'v1.5.0',
        'source_callbacks':list(CALLBACKS),'context_semantics':CONTEXT,
        'completeness':'registered_source_callback_census_only','timebase_version':'raw-demo-net-ticks.v1',
        'sequence_semantics':'callback_stream_order_not_verified_simulation_order'}
    footer={k:meta[k] for k in ('schema_version','replay_sha256','replay_bytes','extractor_name','extractor_version','manta_version')}
    footer.update(t='projectiles_end',parser_completed=True,game_build=6943,message_count=4,
        counts={k:int(i in (0,1,2,3)) for i,k in enumerate(CALLBACKS)})
    rows=[meta,message(0,{'target':42,'handle':9,'move_speed':1000,'is_attack':False},'target'),
        message(2,{'handle':9}),message(3,{'entindex':42,'handle':9,'velocity':{'x':1000,'y':0}},'entindex'),
        message(1,{'target':42,'handle':9,'source_loc':{'x':0,'y':0,'z':0}},'target'),footer]
    for i,row in enumerate(rows):row.update(record_index=i+1,demo_tick=10,net_tick=20,sequence_in_tick=i+1,
        game_time=None,available_to_player_at=None,validation='unverified_source_observation')
    extraction=SimpleNamespace(audit={'replay_sha256':'a'*64},replay=SimpleNamespace(match_id=7,
        manifest=SimpleNamespace(match_id=7,replay_hash='a'*64,game_build='6943')))
    path=tmp_path/'projectiles.jsonl';write(path,rows)
    return path,extraction,rows

def load(path,extraction,**kw):return load_projectile_source(path,extraction=extraction,account_id=11,**kw)

def test_complete_census_preserves_zero_false_and_remains_unknown(tmp_path):
    path,e,rows=fixture(tmp_path);r=load(path,e)
    assert sum(r['callback_counts'].values())==4
    assert r['prefix']['selected_reference_association_counts']=={'target':2,'entindex':1}
    assert r['prefix']['bracket_counts']['matched_message_closures']==1
    assert r['prefix']['open_message_bracket_count']==2
    assert r['examples'][CALLBACKS[0]][0]['data']['is_attack'] is False
    assert r['examples'][CALLBACKS[1]][0]['data']['source_loc']['x']==0
    assert r['damage'] is r['impact_time'] is r['screen_cue'] is None
    assert not r['training_eligible'] and not r['prefix']['player_knowledge_established']

def test_prefix_excludes_boundary_and_future_closure(tmp_path):
    path,e,rows=fixture(tmp_path);r=load(path,e,cutoff_record_index=3)
    assert sum(r['prefix']['callback_counts'].values())==1
    assert r['prefix']['open_message_bracket_count']==1
    assert not r['prefix']['bracket_counts'].get('matched_message_closures')
    assert r['prefix']['open_message_bracket_examples'][0]['creation_record_index']==2

def test_future_mutation_changes_source_receipt_not_prefix(tmp_path):
    path,e,rows=fixture(tmp_path);before=load(path,e,cutoff_record_index=3)
    rows[3]['data']['velocity']['x']=1234;write(path,rows);after=load(path,e,cutoff_record_index=3)
    assert before['source_sha256']!=after['source_sha256']
    assert before['prefix']==after['prefix']

def test_index_and_handle_interpretation_not_guessed(tmp_path):
    path,e,rows=fixture(tmp_path)
    c=rows[1]['entity_context']['field_references']['target'];c['handle_candidate']=copy.deepcopy(c['index_candidate'])
    c['handle_candidate']['generation']=0;write(path,rows)
    with pytest.raises(ValueError,match='row-global'):load(path,e,cutoff_record_index=3)

def test_pool_handle_never_resolves_entity(tmp_path):
    path,e,rows=fixture(tmp_path);rows[1]['data']['handle']=42;write(path,rows)
    r=load(path,e,cutoff_record_index=3)
    assert set(r['examples'][CALLBACKS[0]][0]['entity_context']['field_references'])=={'target'}
    assert r['prefix']['open_message_bracket_examples'][0]['pool_handle']==42

def test_duplicate_resources_do_not_grant_own_association(tmp_path):
    path,e,rows=fixture(tmp_path);s=copy.deepcopy(rows[1]['entity_context']['selected_heroes'][0]);s['resource']['entity_index']=9
    rows[1]['entity_context']['selected_heroes'].append(s);write(path,rows)
    assert not load(path,e,cutoff_record_index=3)['prefix']['selected_reference_association_counts']

def test_foreign_account_not_user_history(tmp_path):
    path,e,rows=fixture(tmp_path)
    r=load_projectile_source(path,extraction=e,account_id=12,cutoff_record_index=3)
    assert r['prefix']['selected_reference_examples']==[]

@pytest.mark.parametrize('mutate',[
    lambda r:r.pop(),lambda r:r.append(copy.deepcopy(r[-1])),lambda r:r[0].update(replay_sha256='b'*64),
    lambda r:r[-1].update(parser_completed=False),lambda r:r[-1].update(game_build=9999),
    lambda r:r[-1].update(message_count=True),lambda r:r[-1]['counts'].update({CALLBACKS[0]:0}),
    lambda r:r[1].update(game_time=0),lambda r:r[1].update(available_to_player_at=0),
    lambda r:r[1].update(damage=500),lambda r:r[1].update(impact_time=1),lambda r:r[1].update(screen_cue=True),
    lambda r:r[1].update(training_eligible=True),lambda r:r[1].update(admission={'approved':True}),
    lambda r:r[1].update(record_index=True),lambda r:r[1].update(sequence_in_tick=3),
    lambda r:r[1].update(net_tick=True),lambda r:r[1].update(protobuf_unknown_fields_hex='GG'),
    lambda r:r[1]['data'].update(ability=2**32),lambda r:r[1]['data'].update(target=True),
    lambda r:r[1]['data'].update(dodgeable=1),lambda r:r[1]['data'].update(move_speed=2**31),
    lambda r:r[1]['data'].update(particle_system_handle=123),lambda r:r[1]['data'].update(particle_system_handle='01'),
    lambda r:r[1]['data'].update(expire_time=10**600),lambda r:r[1]['data'].update(forecast=0),
    lambda r:r[1]['entity_context']['field_references']['target']['index_candidate'].update(entity_index=43),
    lambda r:r[1]['entity_context']['field_references']['target'].update(raw_value=43),
    lambda r:r[1]['entity_context']['selected_heroes'][0].update(selected_handle=42),
    lambda r:r[1]['entity_context']['selected_heroes'][0].update(steam_id=True),
    lambda r:r[1]['entity_context']['field_references']['target']['index_candidate']['fields'].update(hidden_world_position=0),
])
def test_invalid_or_promoted_receipts_rejected(tmp_path,mutate):
    path,e,rows=fixture(tmp_path);mutate(rows);write(path,rows)
    with pytest.raises(ValueError):load(path,e)

@pytest.mark.parametrize('cutoff',[0,True,7,-1])
def test_invalid_cutoff_rejected(tmp_path,cutoff):
    path,e,rows=fixture(tmp_path)
    with pytest.raises(ValueError):load(path,e,cutoff_record_index=cutoff)

def test_no_messages_valid_but_does_not_establish_absent_threat(tmp_path):
    path,e,rows=fixture(tmp_path);rows=[rows[0],rows[-1]];rows[-1].update(record_index=2,sequence_in_tick=2,message_count=0,counts={k:0 for k in CALLBACKS});write(path,rows)
    r=load(path,e)
    assert r['prefix']['open_message_bracket_count']==0 and r['damage'] is None

def test_explicit_nonfinite_wire_float_kept_as_raw_unknown(tmp_path):
    path,e,rows=fixture(tmp_path);rows[1]['data']['expire_time']='NaN';write(path,rows)
    assert load(path,e)['examples'][CALLBACKS[0]][0]['data']['expire_time']=='NaN'

@pytest.mark.parametrize('change',['health','generation','class'])
def test_same_callback_cross_field_entity_conflict_rejected(tmp_path,change):
    path,e,rows=fixture(tmp_path);row=rows[1];row['data']['source']=42
    c=copy.deepcopy(row['entity_context']['field_references']['target'])
    if change=='health':c['index_candidate']['fields']['m_iHealth']=499
    if change=='generation':c['index_candidate']['generation']=4
    if change=='class':c['index_candidate']['class_name']='CDOTA_Unit_Hero_Other'
    row['entity_context']['field_references']['source']=c;write(path,rows)
    with pytest.raises(ValueError,match='row-global'):load(path,e)

@pytest.mark.parametrize('position',[0,1,-1])
def test_extra_future_fields_not_allowed_in_any_record(tmp_path,position):
    path,e,rows=fixture(tmp_path);rows[position]['arbitrary_future_outcome']='enemy_dies_at_2000';write(path,rows)
    with pytest.raises(ValueError,match='unexpected projectile source fields'):load(path,e)

def test_valid_generation_zero_dual_candidates_remain_raw_interpretations(tmp_path):
    path,e,rows=fixture(tmp_path);row=rows[1];c=row['entity_context']['field_references']['target']
    c['index_candidate']['generation']=0;c['handle_candidate']=copy.deepcopy(c['index_candidate'])
    s=row['entity_context']['selected_heroes'][0];s['hero']['generation']=0;s['selected_handle']=42
    write(path,rows);r=load(path,e,cutoff_record_index=3)
    assert r['prefix']['selected_reference_examples'][0]['raw_selected_reference_associations']=={'target':['index_candidate','handle_candidate']}
    assert r['screen_cue'] is r['damage'] is None
