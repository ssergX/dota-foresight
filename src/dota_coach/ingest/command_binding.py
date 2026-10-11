"""Same-callback raw entity associations, with separately scoped field review.

An entity receipt resolves a candidate index at the observed callback; it does
not validate what that integer means in a spectator message. No command stage
or clock mapping is manufactured here, including when field review is supplied.
"""
from collections import Counter
from dataclasses import dataclass
import re

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.order_source import CALLBACKS, _load_order_source

SCHEMA = 'replay-orders-context.v1'
LINK_PROJECTION = 'raw_ability_id_index_matches_only_not_inventory_census'
STEAM_BASE = 76561197960265728


@dataclass(frozen=True)
class OrderFieldReview:
    """Caller-owned conditional research input; never deserialize as admission."""
    source_sha256: str
    replay_sha256: str
    game_build: int
    review_receipt: str
    units_are_ordered_entity_indices: bool
    ability_id_is_entity_index: bool

    def __post_init__(self):
        for value in (self.source_sha256, self.replay_sha256):
            if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
                raise ValueError('exact source/replay SHA256 review binding required')
        if type(self.game_build) is not int or self.game_build <= 0:
            raise ValueError('exact positive game build review required')
        if not isinstance(self.review_receipt, str) or not self.review_receipt:
            raise ValueError('separate field semantics review receipt required')
        if any(type(v) is not bool for v in (self.units_are_ordered_entity_indices,self.ability_id_is_entity_index)):
            raise TypeError('explicit field semantics review required')


def _uint(value, maximum, name):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(name + ' requires an exact unsigned integer')


def _entity(value):
    if not isinstance(value, dict) or set(value) != {'entity_index','generation','class_name'}:
        raise ValueError('exact finite entity receipt required')
    _uint(value['entity_index'],16383,'entity index')
    _uint(value['generation'],2**31-1,'entity generation')
    if not isinstance(value['class_name'],str) or not value['class_name'] or len(value['class_name'])>256:
        raise ValueError('bounded source entity class required')


def _handle(handle, entity):
    _uint(handle,2**64-1,'source handle')
    if entity is not None:
        _entity(entity)
        if (handle & 16383,handle>>14) != (entity['entity_index'],entity['generation']):
            raise ValueError('handle index/generation receipt mismatch')


def _context(row):
    context = row.get('entity_context')
    if (not isinstance(context,dict) or set(context)!={'field_entities','selected_heroes','semantics'}
            or context['semantics']!='raw_index_candidate_and_exact_handle_links_only'):
        raise ValueError('same-callback raw context receipt required')
    fields, selected = context['field_entities'], context['selected_heroes']
    if not isinstance(fields,dict) or not isinstance(selected,list) or len(selected)>64:
        raise ValueError('bounded entity fields and selected resource slots required')
    data=row['data']
    expected = {}
    if row['protobuf_type']==CALLBACKS[0]:
        expected={key:data[key] for key in ('entindex','target_index','ability_id') if key in data}
        expected.update({f'units.{i}':index for i,index in enumerate(data.get('units',[]))})
    if set(fields)!=set(expected):
        raise ValueError('raw field receipt keys mismatch')
    for key,value in fields.items():
        if value is not None:
            _entity(value)
            if value['entity_index']!=expected[key]:
                raise ValueError('raw field and entity index disagree')
    entities={}
    def consistent(entity):
        if entity is None:return
        _entity(entity)
        index=entity['entity_index']
        if index in entities and entities[index]!=entity:
            raise ValueError('contradictory same-callback entity receipts')
        entities[index]=entity
    for value in fields.values():consistent(value)
    duplicates=set()
    for selection in selected:
        if (not isinstance(selection,dict) or set(selection)!={'resource','resource_slot','selected_handle',
                'selected_property','steam_id','steam_property','hero','links'}):
            raise ValueError('finite selected hero receipt required')
        consistent(selection['resource'])
        if selection['resource']['class_name']!='CDOTA_PlayerResource':
            raise ValueError('selection resource class mismatch')
        slot=selection['resource_slot'];_uint(slot,63,'resource slot')
        identity=(selection['resource']['entity_index'],selection['resource']['generation'],slot)
        if identity in duplicates:raise ValueError('duplicate selected resource slot')
        duplicates.add(identity)
        if selection['selected_property']!=f'm_vecPlayerTeamData.{slot:04d}.m_hSelectedHero' or selection['steam_property']!=f'm_vecPlayerData.{slot:04d}.m_iPlayerSteamID':
            raise ValueError('resource slot/property disagreement')
        hero=selection['hero'];_handle(selection['selected_handle'],hero);consistent(hero)
        if not hero['class_name'].startswith('CDOTA_Unit_Hero_') or hero not in fields.values():
            raise ValueError('selected hero must match an exact current raw field entity')
        if selection['steam_id'] is not None:_uint(selection['steam_id'],2**64-1,'Steam receipt')
        links=selection['links']
        if not isinstance(links,list) or len(links)>83:raise ValueError('bounded source handle links required')
        seen=set()
        for link in links:
            if not isinstance(link,dict) or set(link)!={'property','raw_handle','entity'}:
                raise ValueError('exact source handle link required')
            prop=link['property'];match=re.fullmatch(r'(m_hItems|m_vecAbilities|m_hAbilities)\.([0-9]{4})',prop) if isinstance(prop,str) else None
            if match is None or int(match[2]) >= (19 if match[1]=='m_hItems' else 32) or prop in seen:
                raise ValueError('invalid/duplicate finite link property')
            seen.add(prop);_handle(link['raw_handle'],link['entity']);consistent(link['entity'])
            if 'ability_id' not in data or link['raw_handle'] & 16383 != data['ability_id']:
                raise ValueError('link outside declared raw ability_id index projection')
    return context


def bind_order_observation(row, *, account_id, field_review=None):
    """Bind raw references only; field review may conditionally interpret units.

    Call through load_command_binding_source for replay/source/build validation.
    This helper never produces a CommandEvent or attempt coverage certificate.
    """
    _uint(account_id,2**32-1,'account id')
    if account_id==0:raise ValueError('exact positive own account required')
    if field_review is not None and not isinstance(field_review,OrderFieldReview):
        raise TypeError('separately supplied typed field review required')
    context=_context(row)
    candidates=[s for s in context['selected_heroes'] if s['steam_id']==STEAM_BASE+account_id]
    association=candidates[0] if len(candidates)==1 else None
    units=[v for k,v in context['field_entities'].items() if k.startswith('units.') and v is not None]
    unit_associated=association is not None and association['hero'] in units
    ability=context['field_entities'].get('ability_id')
    linked=[link for link in association['links'] if link['entity'] is not None and link['entity']==ability] if association else []
    # Multiple links can refer to the same entity: preserve every source path.
    linked_entity=ability if linked else None
    actor=association['hero'] if unit_associated and field_review is not None and field_review.units_are_ordered_entity_indices else None
    ability_class = linked_entity is not None and linked_entity['class_name'].startswith(('CDOTA_Item','CDOTA_Ability'))
    item=linked_entity if actor is not None and field_review.ability_id_is_entity_index and ability_class else None
    return {
        'source_record_index':row['record_index'], 'demo_tick':row['demo_tick'], 'net_tick':row['net_tick'],
        'sequence_in_tick':row['sequence_in_tick'],'protobuf_type':row['protobuf_type'],
        'raw_order_fields':row['data'],
        'source_record_domain':SCHEMA+'.record_index', 'raw_selected_hero_association':association,
        'raw_units_selected_hero_association':unit_associated,
        'raw_ability_index_link_association':linked_entity,'raw_ability_link_receipts':linked,
        'actor_entity':actor,'ability_entity':item,'command_stage':None,'game_time':None,
        'binding_status':'conditional_field_review' if actor else 'unverified_raw_entity_association',
        'review_receipt':field_review.review_receipt if actor else None,
        'attempt_coverage':None,'training_eligible':False,'validation':'unverified_source_observation',
        'limitations':['callback_order_is_not_simulation_order','spectator_order_is_not_attempt_acceptance_or_commit',
                       'raw_ability_id_is_not_catalog_id','no_verified_game_time_or_screen_visibility'],
    }


def load_command_binding_source(path, *, extraction, account_id, field_review=None, examples=3):
    """Validate every observation and summarize source-local own associations.

    Review identity is verified against the finished file hash and footer build;
    no results are returned if those separate bindings disagree.
    """
    if type(examples) is not int or not 0<=examples<=20:raise ValueError('bounded example count required')
    _uint(account_id,2**32-1,'account id')
    if account_id==0:raise ValueError('exact positive own account required')
    if field_review is not None and not isinstance(field_review,OrderFieldReview):
        raise TypeError('separately supplied typed field review required')
    counts=Counter();samples=[]
    linked_classes=Counter();linked_orders=Counter()
    association_examples={name:[] for name in ('raw_selected_hero_association','raw_units_selected_hero_association',
                                              'raw_ability_index_link_association')}
    def observe(row):
        result=bind_order_observation(row,account_id=account_id,field_review=field_review)
        for name in ('raw_selected_hero_association','raw_units_selected_hero_association',
                     'raw_ability_index_link_association','actor_entity','ability_entity'):
            if result[name]:
                counts[name]+=1
                if name in association_examples and len(association_examples[name])<examples:
                    association_examples[name].append(result)
        if result['raw_selected_hero_association'] and len(samples)<examples:samples.append(result)
        linked=result['raw_ability_index_link_association']
        if linked is not None:
            name=linked['class_name'];order=str(result['raw_order_fields'].get('order_type'))
            linked_classes[name]+=1;linked_orders[(name,order)]+=1
            if len(linked_classes)>512 or len(linked_orders)>4096:
                raise ValueError('linked class/order cardinality exceeds finite summary projection')
    source=_load_order_source(path,extraction=extraction,schema=SCHEMA,examples_per_type=0,observation_callback=observe)
    if source['metadata'].get('context_semantics')!='same_callback_current_entity_snapshot_not_gameplay_identity':
        raise ValueError('explicit source-local context semantics required')
    if any(source[part].get('link_projection')!=LINK_PROJECTION for part in ('metadata','footer')):
        raise ValueError('explicit bounded ability-id link projection required')
    if field_review is not None and (field_review.source_sha256!=source['source_sha256']
            or field_review.replay_sha256!=source['replay_sha256'] or field_review.game_build!=source['footer'].get('game_build')):
        raise ValueError('field review source/replay/build mismatch')
    result={
        'schema_version':'foresight.command-binding-summary.v1','match_id':source['match_id'],
        'replay_sha256':source['replay_sha256'],'source_sha256':source['source_sha256'],
        'account_id':account_id,'source_record_domain':SCHEMA+'.record_index',
        'link_projection':LINK_PROJECTION,
        'metadata':source['metadata'],'footer':source['footer'],'callback_counts':source['callback_counts'],
        'association_counts':{name:counts[name] for name in ('raw_selected_hero_association','raw_units_selected_hero_association',
            'raw_ability_index_link_association','actor_entity','ability_entity')},'examples':samples,
        'association_examples':association_examples,
        'linked_class_counts':dict(linked_classes),
        'raw_order_type_counts_by_linked_class':{name:{order:count for (cls,order),count in linked_orders.items() if cls==name}
                                                for name in linked_classes},
        'attempt_count':None,'accepted_count':None,'committed_count':None,'attempt_coverage':None,
        'validation':'unverified_source_observation','training_eligible':False,
        'limitations':['raw_field_meaning_requires_separate_exact_scoped_review',
            'source_local_entity_association_is_not_gameplay_actor_admission',
            'command_stage_and_game_time_remain_unknown','attempt_channel_coverage_unknown',
            'missing_projected_link_is_unknown_not_disproof_of_ownership'],
    }
    result['payload_sha256']=content_hash(result)
    return result
