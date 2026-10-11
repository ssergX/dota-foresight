"""Report-bound ward questions; world positions and current goals are not vision.

Only original ward callbacks enter a source prefix. Retrospectively backfilled
display clocks, hero paths, removal outcomes and full-file hashes are excluded.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import math
import re

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.trace import TraceResult
from dota_coach.learning.ward_review import review_ward_information

SCHEMA = 'foresight.ward-observations.v1'
REQUEST_SCHEMA = 'foresight.ward-plan-request.v1'
PLAN_SCHEMA = 'foresight.ward-plan.v1'
GOALS = {'protect_route':'Проверить маршрут перед движением команды',
         'prepare_objective':'Подготовить подход к выбранному объекту',
         'protect_resource':'Проверить доступ к выбранному ресурсу',
         'support_action':'Дать сведения для конкретного действия команды'}


def _number(value, name, *, nullable=True):
    if value is None and nullable:
        return None
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and abs(value) <= 2**53-1
    except (TypeError, OverflowError):
        valid = False
    if not valid:
        raise ValueError(name + ': finite bounded number required')
    return value


def _integer(value, name, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= 2**53-1:
        raise ValueError(name + ': bounded integer required')
    return value


def _text(value, name, maximum=2000):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(name + ': bounded nonempty text required')
    return value.strip()


def _hash(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('SHA-256 required')
    return value


def build_ward_observations(extraction: TraceResult, *, account_id: int,
                            resource_slot: int, actor: str) -> dict:
    """Bind raw callback observations to the planning subject, never the placer."""
    _integer(account_id, 'account', positive=True)
    if type(resource_slot) is not int or not 0 <= resource_slot <= 9:
        raise ValueError('resource slot required')
    _text(actor, 'actor', 200)
    identity = extraction.audit.get('resource_identities', {}).get(str(resource_slot), {})
    if identity.get('m_iPlayerSteamID') != str(76561197960265728+account_id):
        raise ValueError('ward planning subject does not bind replay account')
    wire = extraction.replay.heroes.get(resource_slot)
    expected = actor.removeprefix('npc_dota_hero_').replace('_', '').lower()
    if not wire or wire.removeprefix('CDOTA_Unit_Hero_').replace('_', '').lower() != expected:
        raise ValueError('ward planning subject does not bind replay hero')
    manifest = extraction.replay.manifest
    if manifest is None:
        raise ValueError('ward observations require replay manifest')
    rows = extraction.audit.get('ward_timing_provenance', [])
    if not isinstance(rows, list):
        raise ValueError('raw ward callbacks must be an array')
    events = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError('ward callback object required')
        rid = _integer(raw.get('record_index'), 'ward callback record')
        entity, generation = _integer(raw.get('id'), 'ward entity'), _integer(raw.get('generation'), 'ward generation')
        op = raw.get('op')
        if op not in ('placed', 'gone') or raw.get('kind') not in ('obs', 'sentry'):
            raise ValueError('unknown ward callback operation or kind')
        refs = raw.get('clock_evidence_records', [])
        if not isinstance(refs, (list, tuple)) or any(type(r) is not int or not 0 <= r <= rid for r in refs):
            raise ValueError('ward clock references unavailable callback records')
        time = _number(raw.get('prefix_game_time'), 'ward prefix clock')
        if not refs:
            time = None
        events.append({'ward_id':f'ward:{extraction.replay.match_id}:{entity}:{generation}:record:{rid}',
            'entity_id':entity, 'generation':generation, 'operation':op, 'kind':raw['kind'],
            'team':raw.get('team') if type(raw.get('team')) is int and raw['team'] in (2,3) else None,
            'x':_number(raw.get('x'), 'ward x'), 'y':_number(raw.get('y'), 'ward y'),
            'game_time':time, 'source_record_index':rid, 'clock_evidence_records':sorted(set(refs)),
            'clock_status':'raw_prefix_unverified' if time is not None else 'unknown',
            'source_ref':f'trace:{extraction.replay.match_id}:record:{rid}',
            'owner':'not_established', 'player_availability':'not_established'})
    if len({e['source_record_index'] for e in events}) != len(events):
        raise ValueError('duplicate ward callback record')
    result = {'schema_version':SCHEMA, 'match_id':extraction.replay.match_id,
        'account_id':account_id, 'resource_slot':resource_slot, 'actor':actor,
        'subject_team':extraction.replay.teams.get(resource_slot),
        'dataset_kind':manifest.dataset_kind, 'replay_sha256':manifest.replay_hash,
        'trace_sha256':extraction.audit.get('trace_sha256'), 'events':sorted(events,key=lambda e:e['source_record_index']),
        'validation':'unverified', 'ward_owner_attribution':'not_established',
        'coordinate_system':'raw_replay_world_not_validated_map_geometry'}
    result['payload_sha256']=content_hash(result)
    validate_ward_observations(result)
    return result


def validate_ward_observations(source: dict) -> None:
    if type(source) is not dict or source.get('schema_version') != SCHEMA or source.get('validation') != 'unverified':
        raise ValueError('typed unverified ward source required')
    if _hash(source.get('payload_sha256')) != content_hash({k:v for k,v in source.items() if k!='payload_sha256'}):
        raise ValueError('ward source payload integrity mismatch')
    _integer(source.get('match_id'), 'match', positive=True)
    _integer(source.get('account_id'), 'account', positive=True)
    if type(source.get('resource_slot')) is not int or not 0 <= source['resource_slot'] <= 9:
        raise ValueError('ward source slot required')
    _text(source.get('actor'), 'source actor', 200)
    if source.get('dataset_kind') not in ('replay','synthetic','unknown'):
        raise ValueError('ward source kind required')
    if source.get('subject_team') is not None and (type(source['subject_team']) is not int or source['subject_team'] not in (2,3)):
        raise ValueError('ward source team invalid')
    _hash(source.get('replay_sha256'))
    if not isinstance(source.get('events'), list):
        raise ValueError('ward source events required')
    seen=set()
    for e in source['events']:
        if not isinstance(e,dict):
            raise ValueError('ward source event required')
        rid=_integer(e.get('source_record_index'),'ward record')
        if rid in seen:
            raise ValueError('duplicate ward record')
        seen.add(rid)
        entity=_integer(e.get('entity_id'),'ward entity');generation=_integer(e.get('generation'),'ward generation')
        if e.get('ward_id')!=f"ward:{source['match_id']}:{entity}:{generation}:record:{rid}" or e.get('source_ref')!=f"trace:{source['match_id']}:record:{rid}":
            raise ValueError('ward event identity binding mismatch')
        if e.get('operation') not in ('placed','gone') or e.get('kind') not in ('obs','sentry'):
            raise ValueError('ward event operation invalid')
        if e.get('team') is not None and (type(e['team']) is not int or e['team'] not in (2,3)):
            raise ValueError('ward event team invalid')
        refs=e.get('clock_evidence_records')
        if not isinstance(refs,list) or any(type(r) is not int or not 0<=r<=rid for r in refs):
            raise ValueError('invalid ward clock provenance')
        time=_number(e.get('game_time'),'ward game time')
        if time is not None and (not refs or e.get('clock_status')!='raw_prefix_unverified'):
            raise ValueError('ward time cannot grant unavailable clock provenance')
        if e.get('owner')!='not_established' or e.get('player_availability')!='not_established':
            raise ValueError('raw ward callback cannot establish owner or player availability')
        for key in ('x','y'):
            _number(e.get(key),'ward '+key)


def ward_source_context(source: dict, ward_id: str) -> dict:
    validate_ward_observations(source)
    _text(ward_id,'selected ward',200)
    selected=[e for e in source['events'] if e['ward_id']==ward_id and e['operation']=='placed']
    if len(selected)!=1:
        raise ValueError('selected placement absent or ambiguous')
    anchor=selected[0];team=source['subject_team']
    if team is None or anchor['team'] not in (team,None):
        raise ValueError('planning subject team unknown or selected ward belongs to another team')
    # Never use removal, display-time backfill or enemy world positions to
    # characterize information at this placement anchor.
    preceding={};conflicts=[]
    for e in sorted(source['events'],key=lambda e:e['source_record_index']):
        if e['source_record_index']>=anchor['source_record_index']:
            break
        if e['team']!=team:
            continue
        key=(e['entity_id'],e['generation'])
        prior=preceding.get(key)
        if e['operation']=='placed':
            if key in preceding:
                conflicts.append(e['source_ref'])
                preceding[key]=None
            else:
                preceding[key]=e
        elif e['operation']=='gone':
            preceding[key]=None
    present=[e for e in preceding.values() if e is not None]
    # Same callback tick may have unresolved simultaneous ordering. Retain
    # ordinal prefix as observed objects, never convert it to team knowledge.
    result={'schema_version':'foresight.ward-source-context.v1',
        'source_binding':{key:source[key] for key in ('match_id','account_id','resource_slot','actor','subject_team','dataset_kind')},
        'placement_anchor':{key:anchor[key] for key in ('ward_id','entity_id','generation','kind','team','x','y','game_time','source_record_index','clock_evidence_records','clock_status','source_ref')},
        'preceding_same_team_objects':present, 'lifecycle_conflicts':conflicts,
        'object_count_scope':'observed_callback_prefix_not_verified_active_vision_sources',
        'owner':'not_established', 'player_availability':'not_established',
        'choice_boundary':'not_established', 'temporal_order':'callback_order_not_verified_simulation_order'}
    result['source_context_hash']=content_hash(result)
    return result


def create_ward_plan(source: dict, request: dict, previous: dict | None=None) -> dict:
    required={'schema_version','ward_id','source_context_hash','goal_kind','goal_description','confirmed'}
    optional={'alternatives','previous_plan_id'}
    if type(request) is not dict or not required<=request.keys() or request.keys()-(required|optional):
        raise ValueError('ward planning request fields invalid')
    if request['schema_version']!=REQUEST_SCHEMA or request['confirmed'] is not True:
        raise ValueError('explicit confirmed ward planning goal required')
    goal=_text(request['goal_kind'],'ward goal',100)
    if goal not in GOALS:
        raise ValueError('ward goal category unknown')
    description=_text(request['goal_description'],'ward goal description')
    context=ward_source_context(source,request['ward_id'])
    if _hash(request['source_context_hash'])!=context['source_context_hash']:
        raise ValueError('stale ward context: reload the report')
    alternatives=request.get('alternatives',[])
    if not isinstance(alternatives,list) or len(alternatives)>4:
        raise ValueError('up to four proposed alternatives required')
    declared=[]
    for alternative in alternatives:
        if type(alternative) is not dict or set(alternative)!={'label','rationale','x','y'}:
            raise ValueError('explicit alternative label, rationale and coordinate pair required')
        x,y=(_number(alternative[key],'proposed '+key) for key in ('x','y'))
        if (x is None)!=(y is None):
            raise ValueError('both alternative coordinates or neither required')
        declared.append({'label':_text(alternative['label'],'alternative label',200),
            'rationale':_text(alternative['rationale'],'alternative rationale'), 'x':x,'y':y,
            'origin':'current_user_proposal', 'feasibility':'unknown','safety':'unknown',
            'coordinate_system':'unverified_replay_world', 'benefit':'not_established'})
    predecessor=request.get('previous_plan_id')
    previous_hash=None;revision=1
    if previous is None:
        if predecessor is not None:
            raise ValueError('previous ward plan missing')
    else:
        if type(previous) is not dict or previous.get('schema_version')!=PLAN_SCHEMA:
            raise ValueError('typed previous ward plan required')
        identity_keys=('source_context_hash','declaration_receipt_hash','revision','previous_plan_id','previous_payload_sha256')
        if any(k not in previous for k in identity_keys) or not isinstance(previous.get('placement_anchor'),dict):
            raise ValueError('previous ward plan identity fields missing')
        if _hash(predecessor)!=previous.get('plan_id'):
            raise ValueError('previous ward plan identity mismatch')
        previous_hash=content_hash({k:v for k,v in previous.items() if k!='payload_sha256'})
        if previous.get('payload_sha256')!=previous_hash:
            raise ValueError('previous ward plan integrity mismatch')
        if previous.get('plan_id')!=content_hash({k:previous[k] for k in identity_keys}):
            raise ValueError('previous ward plan identity integrity mismatch')
        if not isinstance(previous.get('declaration_receipt'),dict) or previous.get('declaration_receipt_hash')!=content_hash(previous['declaration_receipt']):
            raise ValueError('previous ward declaration receipt integrity mismatch')
        if previous.get('source_binding')!=context['source_binding']:
            raise ValueError('previous ward plan subject differs')
        prior_context=ward_source_context(source,previous['placement_anchor'].get('ward_id'))
        if previous.get('source_context_hash')!=prior_context['source_context_hash']:
            raise ValueError('previous ward context is stale')
        if type(previous.get('revision')) is not int or not 1<=previous['revision']<10000:
            raise ValueError('invalid previous ward revision')
        if previous.get('placement_anchor',{}).get('ward_id')==request['ward_id'] and previous.get('source_context_hash')!=context['source_context_hash']:
            raise ValueError('previous ward context is stale')
        revision=previous['revision']+1
    # The attribution engine is connected, but receives no invented validated
    # observations or historical goal from this current player declaration.
    anchor=context['placement_anchor']
    time=anchor['game_time']
    reviewed=asdict(review_ward_information(request['ward_id'],team=source['subject_team'],
        cutoff_ms=int(time*1000) if time is not None else 0,observations=(),stream_completeness='unknown'))
    receipt={'schema_version':'foresight.ward-goal-declaration.v1','goal_kind':goal,
        'goal_description':description,'confirmed':True,'alternatives':declared,
        'origin':'explicit_current_user_planning_input','prior_intent':'not_established'}
    from dota_coach.learning.ward_analysis import analyze_ward_task
    task_analysis=analyze_ward_task(source,request['ward_id'],
        {'goal_kind':goal,'goal_description':description,'confirmed':True},
        alternatives=[{k:a[k] for k in ('label','rationale','x','y')} for a in declared])
    checks=[{'code':'task','title':'Задача обзора','status':'current_user_hypothesis','question':description},
        {'code':'alignment','title':'Связь с действием команды','status':'unknown','question':'Какое конкретное действие команда планирует и какие сведения нужны до его начала?'},
        {'code':'safety','title':'Возможность безопасной постановки','status':'unknown','question':'Проверь путь, доступную угрозу, ресурс и команду постановки до выбранного момента.'},
        {'code':'redundancy','title':'Дублирование обзора','status':'unknown','question':'Сверь реальные источники видимости и уже известные команде сведения; близость координат не доказывает дублирование.'},
        {'code':'information','title':'Информация от варда','status':'unknown','question':'Назови новое наблюдение, время и источник его связи с этим вардом; время жизни не доказывает полезность.'},
        {'code':'alternatives','title':'Доступные альтернативы','status':'unknown','question':'Проверь другую точку или отсрочку по доступности, безопасности и сроку командного действия.'}]
    plan={'schema_version':PLAN_SCHEMA,'revision':revision,'previous_plan_id':predecessor,
        'previous_payload_sha256':previous_hash,'source_context_hash':context['source_context_hash'],
        'source_binding':context['source_binding'],'placement_anchor':anchor,
        'preceding_same_team_objects':context['preceding_same_team_objects'],
        'declaration_receipt':receipt,'declaration_receipt_hash':content_hash(receipt),
        'checks':checks,'proposed_alternatives':declared,'information_review':reviewed,
        'task_analysis':task_analysis,
        'status':'research_assistance','verdict':'insufficient_evidence','utility':'not_established',
        'feasibility':'unknown','training_eligible':False,
        'comparison_scope':'scenario_planning_not_behavior_progress',
        'recorded_at':datetime.now(timezone.utc).isoformat(),
        'limitations':['Аккаунт задаёт предмет планирования, а не установленного владельца варда.',
            'Цель сформулирована сейчас; намерение при прошлой постановке не установлено.',
            'Предшествующие объекты — наблюдения callback, не доказательство активного обзора.',
            'Отсутствуют проверенная геометрия, attribution stream, pre-choice POV и выполнимость альтернатив.']}
    plan['plan_id']=content_hash({k:plan[k] for k in ('source_context_hash','declaration_receipt_hash','revision','previous_plan_id','previous_payload_sha256')})
    plan['payload_sha256']=content_hash(plan)
    return plan
