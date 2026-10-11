"""Sealed projectile callback census and strictly prior source-local brackets.

Raw target/source references have two candidates until independently interpreted.
A projectile pool handle is never an EntityRef. Creation/destruction messages
are not hit/damage/visibility evidence; callback prefixes are not player knowledge.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import math
from pathlib import Path
from dota_coach.decisions.batch import strict_json
from dota_coach.evidence.contracts import canonical_json, content_hash

SCHEMA='replay-projectiles.v1'
CONTEXT='raw_index_and_handle_candidates_same_callback.v1'
PREFIX='dota.CDOTAUserMsg_'
CALLBACKS=tuple(PREFIX+n for n in ('TE_Projectile','TE_ProjectileLoc','TE_DestroyProjectile',
    'CreateLinearProjectile','DestroyLinearProjectile','DodgeTrackingProjectiles','UpdateLinearProjectileCPData'))
STEAM_BASE=76561197960265728
MAX_RECORD_BYTES=1<<20
I32=(-2**31,2**31-1);U32=(0,2**32-1)
ENTITY_FIELDS=frozenset(('m_iHealth','m_iMaxHealth','m_flMana','m_flMaxMana','m_iTeamNum','m_iPlayerID',
    'm_lifeState','m_bIsIllusion','CBodyComponent.m_cellX','CBodyComponent.m_cellY','CBodyComponent.m_cellZ',
    'CBodyComponent.m_vecX','CBodyComponent.m_vecY','CBodyComponent.m_vecZ'))
COMMON={'target':U32,'source':U32,'move_speed':I32,'particle_system_handle':'i64',
    'dodgeable':'bool','is_attack':'bool','expire_time':'float','target_loc':'vec3','colorgemcolor':U32,
    'launch_tick':I32,'handle':I32,'source_attachment':I32,'particle_cp_data':'cp',
    'additional_particle_system_handle':'i64','original_move_speed':I32}
WIRE={
    CALLBACKS[0]:{**COMMON,'maximpacttime':'float','ability':U32,'target_projectile_handle':I32},
    CALLBACKS[1]:{**COMMON,'source_loc':'vec3'},
    CALLBACKS[2]:{'handle':I32},
    CALLBACKS[3]:{'origin':'vec3','velocity':'vec2','entindex':I32,'particle_index':'u64','handle':I32,
        'acceleration':'vec2','max_speed':'float','fow_radius':'float','sticky_fow_reveal':'bool',
        'distance':'float','colorgemcolor':U32,'particle_cp_data':'cp'},
    CALLBACKS[4]:{'handle':I32},CALLBACKS[5]:{'entindex':I32,'attacks_only':'bool'},
    CALLBACKS[6]:{'handle':I32,'control_point':I32,'vector':'vec3'},
}
LIMITATIONS=(
    'source_callbacks_not_damage_hit_or_action_commit',
    'index_and_handle_interpretations_not_independently_verified',
    'projectile_pool_handle_not_entity_handle',
    'bracket_closure_not_impact_or_dodge_success',
    'raw_world_observations_not_team_screen_or_attention',
    'raw_ticks_and_launch_tick_not_verified_game_clock',
    'speed_not_damage_rule_and_target_may_move',
    'prefix_record_domain_not_entity_trace_or_orders',
    'entity_snapshot_may_precede_same_packet_entity_update_not_current_simulation_state',
)
COMMON_ROW=frozenset(('t','record_index','demo_tick','net_tick','sequence_in_tick','game_time','available_to_player_at','validation'))
ROW_FIELDS={
    'meta':COMMON_ROW|{'schema_version','extractor_name','extractor_version','manta_version','replay_sha256','replay_bytes','source_callbacks','context_semantics','completeness','timebase_version','sequence_semantics','warnings'},
    'projectile_message':COMMON_ROW|{'protobuf_type','data','protobuf_unknown_fields_hex','entity_context','impact_time','damage','screen_cue'},
    'projectiles_end':COMMON_ROW|{'schema_version','extractor_name','extractor_version','manta_version','replay_sha256','replay_bytes','counts','message_count','parser_completed','game_build'},
}

def _int(value,bounds=U32):
    return type(value) is int and bounds[0]<=value<=bounds[1]
def _float(value):
    if isinstance(value,str):return value in ('NaN','Infinity','-Infinity')
    try:return type(value) in (int,float) and math.isfinite(value) and abs(value)<=3.4028235e38
    except OverflowError:return False
def _decimal(value,signed):
    if not isinstance(value,str) or not value or len(value)>20:return False
    try:n=int(value)
    except ValueError:return False
    return str(n)==value and ((-2**63<=n<2**63) if signed else (0<=n<2**64))
def _wire(data,spec):
    if not isinstance(data,dict) or set(data)-set(spec):raise ValueError('projectile protobuf fields outside pinned wire schema')
    for key,v in data.items():
        rule=spec[key]
        if isinstance(rule,tuple):valid=_int(v,rule)
        elif rule=='float':valid=_float(v)
        elif rule=='bool':valid=type(v) is bool
        elif rule in ('i64','u64'):valid=_decimal(v,rule=='i64')
        elif rule in ('vec3','vec2'):
            valid=isinstance(v,dict) and not set(v)-set('xyz' if rule=='vec3' else 'xy') and all(_float(n) for n in v.values())
        else:
            valid=isinstance(v,list) and len(v)<=1024
            if valid:
                for cp in v:_wire(cp,{'control_point':I32,'vector':'vec3'})
        if not valid:raise ValueError('projectile protobuf value outside pinned wire type')

def _entity(value,fields=False):
    keys={'entity_index','generation','class_name'}|({'fields','field_types'} if fields else set())
    if (not isinstance(value,dict) or set(value)!=keys or not _int(value.get('entity_index'),(0,16383))
            or not _int(value.get('generation'),(0,2**32-1)) or not isinstance(value.get('class_name'),str)
            or not 1<=len(value['class_name'])<=256):raise ValueError('exact current entity receipt required')
    if fields:
        data,types=value['fields'],value['field_types']
        if not isinstance(data,dict) or not isinstance(types,dict) or set(data)!=set(types) or set(data)-ENTITY_FIELDS:
            raise ValueError('bounded raw entity field projection required')
        for key,v in data.items():
            kind=types[key]
            if kind=='bool':valid=type(v) is bool
            elif kind in ('float32','float64'):
                try:valid=type(v) in (int,float) and math.isfinite(v)
                except OverflowError:valid=False
            elif kind=='uint64':valid=_decimal(v,False)
            elif kind=='int64':valid=_decimal(v,True)
            elif kind=='uint32':valid=_int(v,U32)
            elif kind=='int32':valid=_int(v,I32)
            else:valid=False
            if not valid:raise ValueError('raw entity field/type receipt mismatch')
    return value

def _identity(e):return (e['entity_index'],e['generation'],e['class_name'])
def _context(row):
    data=row['data'];ctx=row.get('entity_context')
    if not isinstance(ctx,dict) or set(ctx)!={'semantics','field_references','selected_heroes'} or ctx['semantics']!=CONTEXT:
        raise ValueError('same-callback projectile context required')
    refs=ctx['field_references'];sels=ctx['selected_heroes']
    expected={k for k in ('source','target','ability','entindex') if k in data and data[k]>=0}
    if not isinstance(refs,dict) or set(refs)!=expected or not isinstance(sels,list) or len(sels)>256:
        raise ValueError('projectile reference projection mismatch')
    identities=set();entities_by_index={}
    for key,c in refs.items():
        raw=data[key]
        if not isinstance(c,dict) or set(c)!={'raw_value','index_candidate','handle_candidate'} or type(c['raw_value']) is not int or c['raw_value']!=raw:
            raise ValueError('projectile reference raw value mismatch')
        for mode in ('index_candidate','handle_candidate'):
            e=c[mode]
            if e is None:continue
            _entity(e,True)
            if mode=='index_candidate':valid=raw<=16383 and e['entity_index']==raw
            else:valid=e['entity_index']==raw&16383 and e['generation']==raw>>14
            if not valid:raise ValueError('projectile entity candidate differs from raw index/handle')
            previous=entities_by_index.setdefault(e['entity_index'],e)
            if previous!=e:raise ValueError('conflicting row-global entity identity or operands')
            identities.add(_identity(e))
        if c['index_candidate'] and c['handle_candidate'] and _identity(c['index_candidate'])==_identity(c['handle_candidate']) and c['index_candidate']!=c['handle_candidate']:
            raise ValueError('conflicting same-callback entity operands')
    seen=set();cores={index:_identity(entity) for index,entity in entities_by_index.items()}
    for s in sels:
        keys={'resource','resource_slot','selected_handle','selected_property','steam_id','steam_property','hero'}
        if not isinstance(s,dict) or set(s)!=keys:raise ValueError('exact selection receipt required')
        r=_entity(s['resource']);hero=_entity(s['hero']);slot=s['resource_slot'];h=s['selected_handle']
        if (r['class_name']!='CDOTA_PlayerResource' or not hero['class_name'].startswith('CDOTA_Unit_Hero_')
                or not _int(slot,(0,63)) or not _int(h,(0,2**64-1)) or (h&16383,h>>14)!=(hero['entity_index'],hero['generation'])
                or _identity(hero) not in identities or s['selected_property']!=f'm_vecPlayerTeamData.{slot:04d}.m_hSelectedHero'
                or s['steam_property']!=f'm_vecPlayerData.{slot:04d}.m_iPlayerSteamID'
                or (s['steam_id'] is not None and not _int(s['steam_id'],(0,2**64-1)))):
            raise ValueError('projectile selected player/entity receipt mismatch')
        for entity in (r,hero):
            if cores.setdefault(entity['entity_index'],_identity(entity))!=_identity(entity):
                raise ValueError('conflicting row-global selection identity')
        identity=(_identity(r),slot)
        if identity in seen:raise ValueError('duplicate selected player receipt')
        seen.add(identity)
    return ctx

class _Brackets:
    def __init__(self):self.open={};self.counts=Counter()
    def observe(self,row):
        kind=row['protobuf_type'][len(PREFIX):];h=row['data'].get('handle')
        if type(h) is not int or h<0:
            self.counts['unkeyed_messages']+=1;return
        family='tracking' if kind.startswith('TE_') else 'linear'
        if kind in ('TE_Projectile','TE_ProjectileLoc','CreateLinearProjectile'):
            key=(family,h)
            if key in self.open:self.counts['creation_without_prior_closure']+=1
            if key not in self.open and len(self.open)>=32768:raise ValueError('projectile bracket state exceeds bounded limit')
            self.open[key]={'family':family,'pool_handle':h,'creation_record_index':row['record_index'],
                'creation_callback':row['protobuf_type'],'raw_creation_data':row['data'],
                'last_update_record_index':None,'status':'source_message_bracket_only'}
            self.counts['creations']+=1
        elif kind in ('TE_DestroyProjectile','DestroyLinearProjectile'):
            if self.open.pop((family,h),None) is None:self.counts['closure_without_prior_creation']+=1
            else:self.counts['matched_message_closures']+=1
        elif kind=='UpdateLinearProjectileCPData':
            entry=self.open.get(('linear',h))
            if entry:entry['last_update_record_index']=row['record_index']
            else:self.counts['update_without_prior_creation']+=1


def load_projectile_source(path,*,extraction,account_id,examples_per_type=2,cutoff_record_index=None):
    """Validate every byte/footer; project only records strictly before cutoff.

    The full source digest is provenance, never an input to prefix feature hash.
    All summaries remain retrospective and cannot grant prefix/case admission.
    """
    if not _int(account_id,(1,2**32-1)) or not _int(examples_per_type,(0,20)):raise ValueError('bounded player/example count required')
    if cutoff_record_index is not None and not _int(cutoff_record_index,(1,2**64-1)):raise ValueError('positive source-local cutoff required')
    manifest=extraction.replay.manifest;expected=extraction.audit['replay_sha256']
    if manifest is None or manifest.replay_hash!=expected or manifest.match_id!=extraction.replay.match_id:
        raise ValueError('extraction manifest and audit replay mismatch')
    counts=Counter();examples={k:[] for k in CALLBACKS};roles=Counter();prefix_counts=Counter();own_examples=[]
    whole=hashlib.sha256();prefix=hashlib.sha256();brackets=_Brackets();meta=footer=None
    records=0;prev_tick=prev_sequence=None
    with Path(path).open('rb') as stream:
        while raw:=stream.readline(MAX_RECORD_BYTES+1):
            if len(raw)>MAX_RECORD_BYTES:raise ValueError('projectile record exceeds byte limit')
            whole.update(raw)
            if not raw.strip():raise ValueError('blank projectile source record')
            row=strict_json(raw.decode('utf-8-sig'));records+=1
            if not isinstance(row,dict) or footer is not None:raise ValueError('projectile source invalid/trailing record')
            if row.get('t') not in ROW_FIELDS or set(row)-ROW_FIELDS[row['t']]:raise ValueError('unexpected projectile source fields')
            if type(row.get('record_index')) is not int or row['record_index']!=records:raise ValueError('contiguous projectile record indices required')
            for key in ('demo_tick','net_tick','sequence_in_tick'):
                if not _int(row.get(key),(1 if key=='sequence_in_tick' else 0,2**64-1 if key=='sequence_in_tick' else 2**32-1)):
                    raise ValueError('raw projectile clock/counter required')
            sequence=prev_sequence+1 if prev_tick==row['demo_tick'] else 1
            if row['sequence_in_tick']!=sequence:raise ValueError('projectile callback sequence altered')
            prev_tick,prev_sequence=row['demo_tick'],row['sequence_in_tick']
            if (row.get('validation')!='unverified_source_observation' or row.get('game_time','missing') is not None
                    or row.get('available_to_player_at','missing') is not None or row.get('training_eligible',False) is not False):
                raise ValueError('raw projectile observation cannot grant game clock/availability/validation')
            for key in ('damage','impact_time','screen_cue','hit','committed','admission'):
                if key in row and row[key] is not None:raise ValueError('raw projectile observation cannot grant gameplay evidence')
            if records==1:
                meta=row
                if row.get('t')!='meta' or row.get('schema_version')!=SCHEMA or row.get('replay_sha256')!=expected:
                    raise ValueError('projectile metadata replay/schema mismatch')
                if (row.get('source_callbacks')!=list(CALLBACKS) or row.get('context_semantics')!=CONTEXT
                        or row.get('completeness')!='registered_source_callback_census_only'
                        or row.get('timebase_version')!='raw-demo-net-ticks.v1'
                        or row.get('sequence_semantics')!='callback_stream_order_not_verified_simulation_order'):
                    raise ValueError('projectile metadata semantics mismatch')
                if row.get('extractor_name')!='manta' or row.get('extractor_version')!='foresight-replay/3.1' or row.get('manta_version')!='v1.5.0' or not _int(row.get('replay_bytes'),(1,2**63-1)):
                    raise ValueError('projectile extractor version/bytes mismatch')
            elif row.get('t')=='projectile_message':
                kind=row.get('protobuf_type')
                if kind not in CALLBACKS:raise ValueError('unregistered projectile callback')
                _wire(row.get('data'),WIRE[kind]);ctx=_context(row)
                wire=row.get('protobuf_unknown_fields_hex')
                if not isinstance(wire,str) or len(wire)%2 or any(c not in '0123456789abcdef' for c in wire):raise ValueError('exact unknown protobuf wire bytes required')
                counts[kind]+=1
                if len(examples[kind])<examples_per_type:examples[kind].append(row)
                if cutoff_record_index is None or records<cutoff_record_index:
                    prefix_counts[kind]+=1;prefix.update((canonical_json(row)+'\n').encode());brackets.observe(row)
                    selection=[s for s in ctx['selected_heroes'] if s['steam_id']==STEAM_BASE+account_id]
                    # Multiple resources/slots remain ambiguous, even if hero matches.
                    if len(selection)==1:
                        hero=_identity(selection[0]['hero']);matches={}
                        for key,c in ctx['field_references'].items():
                            modes=[mode for mode in ('index_candidate','handle_candidate') if c[mode] is not None and _identity(c[mode])==hero]
                            if modes:roles[key]+=1;matches[key]=modes
                        if matches and len(own_examples)<20:
                            own_examples.append({'source_record_index':records,'protobuf_type':kind,'raw_data':row['data'],
                                'selected_hero':selection[0],'raw_selected_reference_associations':matches,
                                'validation':'unverified_source_observation','game_time':None,'screen_cue':None})
            elif row.get('t')=='projectiles_end':footer=row
            else:raise ValueError('unexpected projectile source record kind')
    if meta is None or footer is None or footer.get('parser_completed') is not True:raise ValueError('complete projectile footer required')
    for key in ('schema_version','replay_sha256','replay_bytes','extractor_name','extractor_version','manta_version'):
        if footer.get(key)!=meta.get(key):raise ValueError('projectile footer metadata mismatch')
    claimed=footer.get('counts')
    if not isinstance(claimed,dict) or set(claimed)!=set(CALLBACKS) or any(type(v) is not int or v!=counts[k] for k,v in claimed.items()):raise ValueError('projectile footer census mismatch')
    if type(footer.get('message_count')) is not int or footer['message_count']!=sum(counts.values()):raise ValueError('projectile message count mismatch')
    build=footer.get('game_build')
    if not _int(build,(0,2**32-1)) or (manifest.game_build is not None and str(build)!=str(manifest.game_build)):raise ValueError('projectile game build receipt mismatch')
    if cutoff_record_index is not None and cutoff_record_index>records:raise ValueError('projectile cutoff outside sealed source')
    result={'schema_version':'foresight.projectile-source-summary.v1','match_id':extraction.replay.match_id,
        'account_id':account_id,'replay_sha256':expected,'source_sha256':whole.hexdigest(),'source_record_domain':'projectiles',
        'metadata':meta,'footer':footer,'callback_counts':dict(claimed),'examples':examples,
        'prefix':{'cutoff_record_index':cutoff_record_index,'boundary':'strictly_before_source_record',
            'callback_counts':dict(prefix_counts),'raw_callback_prefix_hash':prefix.hexdigest(),
            'selected_reference_association_counts':dict(roles),'selected_reference_examples':own_examples,
            'bracket_counts':dict(brackets.counts),'open_message_bracket_count':len(brackets.open),
            'open_message_bracket_examples':list(brackets.open.values())[:20],
            'bracket_examples_truncated':len(brackets.open)>20,'player_knowledge_established':False},
        'damage':None,'impact_time':None,'screen_cue':None,'validation':'unverified_source_observation',
        'training_eligible':False,'limitations':list(LIMITATIONS)}
    result['payload_sha256']=content_hash(result)
    return result
