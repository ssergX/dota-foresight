import copy
import hashlib
from dataclasses import replace

import pytest

from tests.test_order_source import fixture as order_fixture, write
from dota_coach.ingest.command_binding import (
    SCHEMA,LINK_PROJECTION,STEAM_BASE,OrderFieldReview,bind_order_observation,load_command_binding_source,
)
from dota_coach.ingest.order_source import load_order_source


def fixture(tmp_path):
    path,extraction,rows=order_fixture(tmp_path)
    rows[0]['schema_version']=rows[-1]['schema_version']=SCHEMA
    rows[0]['context_semantics']='same_callback_current_entity_snapshot_not_gameplay_identity'
    rows[0]['link_projection']=rows[-1]['link_projection']=LINK_PROJECTION
    rows[-1]['game_build']=6943
    hero={'entity_index':42,'generation':3,'class_name':'CDOTA_Unit_Hero_Kez'}
    item={'entity_index':44,'generation':7,'class_name':'CDOTA_Item_BlackKingBar'}
    resource={'entity_index':10,'generation':9,'class_name':'CDOTA_PlayerResource'}
    rows[1]['data'].update(units=[42])
    rows[1]['entity_context']={'semantics':'raw_index_candidate_and_exact_handle_links_only',
        'field_entities':{'entindex':None,'ability_id':item,'units.0':hero},
        'selected_heroes':[{'resource':resource,'resource_slot':0,'selected_handle':3*16384+42,
            'selected_property':'m_vecPlayerTeamData.0000.m_hSelectedHero',
            'steam_property':'m_vecPlayerData.0000.m_iPlayerSteamID','steam_id':STEAM_BASE+11,
            'hero':hero,'links':[{'property':'m_hItems.0000','raw_handle':7*16384+44,'entity':item}]}]}
    return path,extraction,rows


def test_exact_raw_associations_remain_unverified(tmp_path):
    path,extraction,rows=fixture(tmp_path);write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=11)
    counts=result['association_counts']
    assert counts['raw_selected_hero_association']==counts['raw_units_selected_hero_association']==1
    assert counts['raw_ability_index_link_association']==1
    assert counts['actor_entity']==counts['ability_entity']==0
    example=result['examples'][0]
    assert example['raw_ability_index_link_association']['generation']==7
    assert example['raw_order_fields']['ability_id']==44
    assert result['association_examples']['raw_ability_index_link_association']==[example]
    assert result['linked_class_counts']=={'CDOTA_Item_BlackKingBar':1}
    assert result['raw_order_type_counts_by_linked_class']=={'CDOTA_Item_BlackKingBar':{'None':1}}
    assert example['command_stage'] is example['game_time'] is example['attempt_coverage'] is None
    assert example['training_eligible'] is False
    with pytest.raises(ValueError):load_order_source(path,extraction=extraction)


def review(path):
    return OrderFieldReview(hashlib.sha256(path.read_bytes()).hexdigest(),'a'*64,6943,
                           'external-client-field-review:fixture-only',True,True)


def test_scoped_review_interprets_fields_but_never_command_stage(tmp_path):
    path,extraction,rows=fixture(tmp_path);write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=11,field_review=review(path))
    assert result['association_counts']['actor_entity']==result['association_counts']['ability_entity']==1
    assert result['examples'][0]['binding_status']=='conditional_field_review'
    assert result['attempt_count'] is result['accepted_count'] is result['committed_count'] is None
    assert result['training_eligible'] is False


@pytest.mark.parametrize('field,value',[('source_sha256','b'*64),('replay_sha256','b'*64),('game_build',9999)])
def test_foreign_review_cannot_bind(tmp_path,field,value):
    path,extraction,rows=fixture(tmp_path);write(path,rows)
    with pytest.raises(ValueError,match='review.*mismatch'):
        load_command_binding_source(path,extraction=extraction,account_id=11,field_review=replace(review(path),**{field:value}))


def test_json_flag_is_not_review(tmp_path):
    path,extraction,rows=fixture(tmp_path);write(path,rows)
    with pytest.raises(TypeError):
        load_command_binding_source(path,extraction=extraction,account_id=11,field_review={'validated':True})


@pytest.mark.parametrize('mutation',[
    lambda c:c['field_entities']['ability_id'].update(generation=8),
    lambda c:c['field_entities']['units.0'].update(entity_index=55),
    lambda c:c['selected_heroes'][0].update(selected_handle=42),
    lambda c:c['selected_heroes'][0].update(resource_slot=True),
    lambda c:c['selected_heroes'][0].update(selected_property='m_vecPlayerTeamData.0001.m_hSelectedHero'),
    lambda c:c['selected_heroes'][0]['links'].append(copy.deepcopy(c['selected_heroes'][0]['links'][0])),
    lambda c:c['field_entities'].update(hud_order_id={'entity_index':42,'generation':3,'class_name':'CDOTA_Unit_Hero_Kez'}),
    lambda c:c['selected_heroes'][0]['hero'].update(class_name='CDOTA_Item_BlackKingBar'),
])
def test_forged_generation_identity_or_out_of_projection_rejected(tmp_path,mutation):
    path,extraction,rows=fixture(tmp_path);mutation(rows[1]['entity_context']);write(path,rows)
    with pytest.raises(ValueError):load_command_binding_source(path,extraction=extraction,account_id=11)


def test_account_and_multi_resource_ambiguity_no_own_binding(tmp_path):
    path,extraction,rows=fixture(tmp_path);write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=12)
    assert not any(result['association_counts'].values())
    selection=copy.deepcopy(rows[1]['entity_context']['selected_heroes'][0])
    selection['resource']['entity_index']=9
    rows[1]['entity_context']['selected_heroes'].append(selection);write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=11,field_review=review(path))
    assert not any(result['association_counts'].values())


def test_catalog_id_is_not_linked_ability_entity(tmp_path):
    path,extraction,rows=fixture(tmp_path)
    rows[1]['data']['ability_id']=116
    rows[1]['entity_context']['field_entities']['ability_id']=None
    rows[1]['entity_context']['selected_heroes'][0]['links']=[]
    write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=11,field_review=review(path))
    assert result['association_counts']['actor_entity']==1
    assert result['association_counts']['ability_entity']==0


def test_partial_field_review_does_not_bind_ability(tmp_path):
    path,extraction,rows=fixture(tmp_path);write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=11,
        field_review=replace(review(path),ability_id_is_entity_index=False))
    assert result['association_counts']['actor_entity']==1
    assert result['association_counts']['ability_entity']==0


def test_corrupt_raw_handle_to_controller_is_not_an_ability(tmp_path):
    path,extraction,rows=fixture(tmp_path)
    rows[1]['entity_context']['field_entities']['ability_id']['class_name']='CDOTAPlayerController'
    write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=11,field_review=review(path))
    assert result['association_counts']['raw_ability_index_link_association']==1
    assert result['association_counts']['actor_entity']==1
    assert result['association_counts']['ability_entity']==0


@pytest.mark.parametrize('raw_property',['m_vecAbilities.0002','m_hAbilities.0002'])
def test_actual_ability_vector_and_distinct_raw_alias_preserve_property(tmp_path,raw_property):
    path,extraction,rows=fixture(tmp_path)
    context=rows[1]['entity_context']
    context['field_entities']['ability_id']['class_name']='CDOTA_Ability_Kez_FalconRush'
    context['selected_heroes'][0]['links'][0]['property']=raw_property
    write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=11,field_review=review(path))
    assert result['association_counts']['ability_entity']==1
    assert result['examples'][0]['raw_ability_link_receipts'][0]['property']==raw_property


def test_vector_and_alias_are_distinct_receipts_without_equivalence_claim(tmp_path):
    path,extraction,rows=fixture(tmp_path)
    links=rows[1]['entity_context']['selected_heroes'][0]['links']
    links[0]['property']='m_vecAbilities.0002'
    alias=copy.deepcopy(links[0]);alias['property']='m_hAbilities.0002';links.append(alias)
    write(path,rows)
    result=load_command_binding_source(path,extraction=extraction,account_id=11)
    assert result['association_counts']['raw_ability_index_link_association']==1
    assert {r['property'] for r in result['examples'][0]['raw_ability_link_receipts']}=={'m_vecAbilities.0002','m_hAbilities.0002'}


@pytest.mark.parametrize('metadata_part',[0,-1])
def test_missing_projection_boundary_rejected(tmp_path,metadata_part):
    path,extraction,rows=fixture(tmp_path);rows[metadata_part].pop('link_projection');write(path,rows)
    with pytest.raises(ValueError,match='projection'):load_command_binding_source(path,extraction=extraction,account_id=11)


def test_unrelated_inventory_handle_outside_projection_rejected(tmp_path):
    path,extraction,rows=fixture(tmp_path)
    links=rows[1]['entity_context']['selected_heroes'][0]['links']
    other=copy.deepcopy(links[0]);other['property']='m_hItems.0001';other['raw_handle']=7*16384+45;other['entity']['entity_index']=45;links.append(other)
    write(path,rows)
    with pytest.raises(ValueError,match='projection'):load_command_binding_source(path,extraction=extraction,account_id=11)

@pytest.mark.parametrize('place',['field','resource','link'])
def test_same_callback_conflicting_generation_or_class_rejected(tmp_path,place):
    path,extraction,rows=fixture(tmp_path)
    context=rows[1]['entity_context']
    if place=='field':
        rows[1]['data']['entindex']=42
        context['field_entities']['entindex']={**context['field_entities']['units.0'],'generation':99}
    elif place=='resource':
        context['selected_heroes'][0]['resource']['entity_index']=42
    else:
        context['selected_heroes'][0]['links'][0]['entity']={**context['field_entities']['ability_id'],'generation':8}
        context['selected_heroes'][0]['links'][0]['raw_handle']=8*16384+44
    write(path,rows)
    with pytest.raises(ValueError,match='contradictory'):load_command_binding_source(path,extraction=extraction,account_id=11)
