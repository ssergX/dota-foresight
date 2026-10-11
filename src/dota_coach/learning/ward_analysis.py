"""Ward task analysis from callback prefixes and separately reviewed evidence.

Coordinates establish equality of raw coordinates, never vision. Review labels
bind an exact supplied evidence prefix; two declared reviewer IDs do not prove
independent people or client access and never grant production validation.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations
import math
import re

from dota_coach.evidence.contracts import content_hash
from dota_coach.validation.contracts import DatasetRecord
from dota_coach.validation.pipeline import validate_annotations

SCHEMA = 'foresight.ward-analysis.v1'
EVIDENCE_SCHEMA = 'foresight.ward-task-evidence.v1'
_BINDING = ('match_id','account_id','resource_slot','actor','subject_team','dataset_kind')
_KINDS = {'observation','attribution','condition','coverage'}
_FIELDS = {'fact_id','kind','record_index','available_record_index','game_time_ms',
           'entity_ref','predicate','value','perspective','source_ref','source_record_hash',
           'action_id','coverage_start_record','coverage_end_record'}


def _int(value, name):
    if type(value) is not int or not 0 <= value <= 2**53-1:
        raise ValueError(name+': bounded nonnegative integer required')
    return value


def _text(value, name, maximum=2000):
    if type(value) is not str or not value.strip() or len(value)>maximum:
        raise ValueError(name+': bounded nonempty text required')
    return value.strip()


def _hash(value):
    if type(value) is not str or re.fullmatch('[a-f0-9]{64}',value) is None:
        raise ValueError('SHA-256 required')
    return value


def _scalar(value):
    if type(value) not in (str,int,float,bool) or (type(value) in (int,float) and
            (abs(value)>2**53-1 or not math.isfinite(value))):
        raise ValueError('finite scalar evidence required')


def _goal(value):
    from .ward_plan import GOALS
    required={'goal_kind','goal_description','confirmed'}
    if type(value) is not dict or not required<=value.keys() or value.keys()-required-{'information_predicate','entity_refs'}:
        raise ValueError('explicit current task required')
    if value['confirmed'] is not True or value['goal_kind'] not in GOALS:
        raise ValueError('confirmed ward task category required')
    result={'goal_kind':value['goal_kind'],'goal_description':_text(value['goal_description'],'goal'),
            'origin':'current_user_planning_hypothesis','prior_intent':'not_established'}
    if 'information_predicate' in value:
        result['information_predicate']=_text(value['information_predicate'],'requested predicate',200)
    entities=value.get('entity_refs',[])
    if not isinstance(entities,(tuple,list)) or any(type(v) is not str or not v or len(v)>200 for v in entities) or len(set(entities))!=len(entities):
        raise ValueError('unique requested entity references required')
    result['entity_refs']=list(entities)
    return result


def _alternatives(values, ward_id):
    if not isinstance(values,(tuple,list)) or len(values)>4:
        raise ValueError('up to four explicit alternatives required')
    result=[]
    for row in values:
        if type(row) is not dict or not {'label','rationale','x','y'}<=row.keys() or row.keys()-{'label','rationale','x','y','action_id'}:
            raise ValueError('alternative fields invalid')
        label=_text(row['label'],'alternative label',200);reason=_text(row['rationale'],'alternative rationale')
        for key in ('x','y'):
            if row[key] is not None:
                _scalar(row[key])
                if type(row[key]) not in (int,float):raise ValueError('numeric proposed coordinates required')
        if (row['x'] is None)!=(row['y'] is None):raise ValueError('coordinate pair required')
        identity=row.get('action_id') or 'proposal:'+content_hash({'ward_id':ward_id,'label':label,'rationale':reason,'x':row['x'],'y':row['y']})
        result.append({'action_id':_text(identity,'alternative action',200),'label':label,'rationale':reason,
                       'x':row['x'],'y':row['y'],'origin':'current_user_proposal'})
    if len({r['action_id'] for r in result})!=len(result):raise ValueError('duplicate alternative action')
    return result


def _corpus_prefix(source,evidence,cutoff):
    if type(evidence) is not dict or set(evidence)!={'schema_version','source_binding','patch','facts','payload_sha256'} or evidence['schema_version']!=EVIDENCE_SCHEMA:
        raise ValueError('typed ward evidence corpus required')
    if _hash(evidence['payload_sha256'])!=content_hash({k:v for k,v in evidence.items() if k!='payload_sha256'}):
        raise ValueError('ward evidence integrity mismatch')
    binding=evidence['source_binding']
    if type(binding) is not dict or set(binding)!=set(_BINDING)|{'replay_sha256'} or any(binding.get(k)!=source.get(k) for k in binding):
        raise ValueError('ward evidence bound to another account, replay or source')
    patch=_text(evidence['patch'],'evidence patch',200)
    if not isinstance(evidence['facts'],list):raise ValueError('fact array required')
    prefix=[];seen=set()
    for row in evidence['facts']:
        required=_FIELDS-{'action_id','coverage_start_record','coverage_end_record'}
        if type(row) is not dict or not required<=row.keys() or row.keys()-_FIELDS:
            raise ValueError('unknown evidence fields; validation flags do not grant admission')
        ident=_text(row['fact_id'],'fact ID',200)
        if ident in seen:raise ValueError('duplicate evidence fact')
        seen.add(ident)
        record=_int(row['record_index'],'source record')
        available=row['available_record_index']
        if available is not None and _int(available,'availability record')<record:
            raise ValueError('fact cannot be available before its source observation')
        if row['game_time_ms'] is not None:
            _scalar(row['game_time_ms'])
            if type(row['game_time_ms']) is not int:raise ValueError('integer game time required')
        if row['kind'] not in _KINDS or row['perspective'] not in ('team','screen','world','public'):
            raise ValueError('unsupported evidence kind or perspective')
        for key in ('entity_ref','predicate','source_ref'):_text(row[key],key,512)
        _hash(row['source_record_hash']);_scalar(row['value'])
        if 'action_id' in row:_text(row['action_id'],'action reference',200)
        for key in ('coverage_start_record','coverage_end_record'):
            if key in row:_int(row[key],key)
        if row['kind']=='coverage' and (not {'coverage_start_record','coverage_end_record'}<=row.keys() or row['coverage_start_record']>row['coverage_end_record']):
            raise ValueError('explicit complete coverage interval required')
        # Undelivered/future observations cannot affect either hash or analysis.
        if record<=cutoff and available is not None and available<=cutoff:
            prefix.append(dict(row))
    return {'schema_version':EVIDENCE_SCHEMA,'source_binding':{k:binding[k] for k in _BINDING},
            'patch':patch,'cutoff_record_index':cutoff,
            'facts':sorted(prefix,key=lambda r:(r['record_index'],r['fact_id']))}


def ward_evidence_record(source,ward_id,evidence,*,cutoff_record_index=None,split='development'):
    """Manifest to label the exact prefix; no status in the corpus grants review."""
    from .ward_plan import ward_source_context
    context=ward_source_context(source,ward_id)
    cutoff=context['placement_anchor']['source_record_index'] if cutoff_record_index is None else _int(cutoff_record_index,'cutoff')
    if cutoff<context['placement_anchor']['source_record_index']:raise ValueError('review cutoff precedes placement')
    prefix=_corpus_prefix(source,evidence,cutoff)
    return DatasetRecord(f'ward-analysis:{ward_id}:through:{cutoff}',content_hash(prefix),source['match_id'],
        source['replay_sha256'],f"account:{source['account_id']}",prefix['patch'],split,source['dataset_kind'])


def _reviewed(source,ward_id,evidence,cutoff,records,annotations):
    if evidence is None:
        if records or annotations:raise ValueError('review labels require their source corpus')
        return [],set(),[],None
    prefix=_corpus_prefix(source,evidence,cutoff)
    expected=ward_evidence_record(source,ward_id,evidence,cutoff_record_index=cutoff)
    records,annotations=tuple(records),tuple(annotations)
    validate_annotations(annotations,records)
    if not records and not annotations:return prefix['facts'],set(),[],expected.input_hash
    matching=[r for r in records if r.decision_id==expected.decision_id]
    if len(matching)!=1 or any(getattr(matching[0],k)!=getattr(expected,k) for k in
            ('input_hash','replay_hash','match_id','target_player','patch','dataset_kind')):
        raise ValueError('review manifest does not bind ward evidence prefix')
    ids={r['fact_id'] for r in prefix['facts']};latest={}
    for a in annotations:
        if a.decision_id!=expected.decision_id:continue
        if any(f.fact_id not in ids for f in a.facts_checked):raise ValueError('fact review outside supplied prefix')
        if a.annotator_kind!='human_expert' or a.review_pass!='extraction':continue
        if a.annotator_id not in latest or a.annotation_version>latest[a.annotator_id].annotation_version:
            latest[a.annotator_id]=a
    admitted=set();receipts=[]
    for ident in ids:
        votes=[(a,next((f for f in a.facts_checked if f.fact_id==ident),None)) for a in latest.values()]
        votes=[(a,v) for a,v in votes if v is not None]
        if len(votes)>=2 and all(a.adjudication_status!='disputed' and v.correctness=='correct' and v.availability=='available' for a,v in votes):
            admitted.add(ident);receipts.extend(a.annotation_hash for a,v in votes)
    return prefix['facts'],admitted,sorted(set(receipts)),expected.input_hash


def _callback_analysis(source,anchor,cutoff):
    events=[e for e in source['events'] if e['source_record_index']<=cutoff and e['team']==source['subject_team']]
    states={};conflicts=[];orphan=[]
    for row in sorted(events,key=lambda e:e['source_record_index']):
        key=(row['entity_id'],row['generation']);prior=states.get(key)
        if row['operation']=='placed':
            if key in states:conflicts.append(row['source_ref']);states[key]={'state':'conflict','event':row}
            else:states[key]={'state':'placement_without_removal','event':row}
        elif prior is None:
            orphan.append(row['source_ref']);states[key]={'state':'placement_unobserved','event':row}
        elif prior['state']!='placement_without_removal':
            conflicts.append(row['source_ref']);states[key]={'state':'conflict','event':row}
        else:states[key]={'state':'removal_observed','event':prior['event']}
    present=[v['event'] for v in states.values() if v['state']=='placement_without_removal' and v['event']['source_record_index']<anchor['source_record_index']]
    coordinates=[]
    for row in present:
        known=all(row[k] is not None and anchor[k] is not None for k in ('x','y'))
        coordinates.append({'ward_id':row['ward_id'],'same_raw_coordinates':all(row[k]==anchor[k] for k in ('x','y')) if known else None,
                            'status':'raw_coordinate_comparison_not_vision_overlap','source_refs':[row['source_ref'],anchor['source_ref']]})
    return {'scope':'same_team_callback_prefix_not_verified_observation_opportunity_census',
        'cutoff_record_index':cutoff,'callback_count':len(events),'placement_callbacks':sum(e['operation']=='placed' for e in events),
        'removal_callbacks':sum(e['operation']=='gone' for e in events),
        'known_prefix_clock_callbacks':sum(e['game_time'] is not None for e in events),
        'unknown_prefix_clock_callbacks':sum(e['game_time'] is None for e in events),
        'observed_object_states':dict(sorted(Counter(v['state'] for v in states.values()).items())),
        'conflict_source_refs':conflicts,'placement_unobserved_source_refs':orphan,
        'coordinate_comparisons':coordinates,'vision_redundancy':'not_established',
        'active_vision_source_count':None,'opportunity_coverage':None,'geometry':'not_validated'}


def _condition(rows,admitted,action,predicate,anchor):
    facts=[r for r in rows if r['kind']=='condition' and r['fact_id'] in admitted and
        r.get('action_id')==action and r['predicate']==predicate and r['perspective'] in ('team','screen') and
        type(r['value']) is bool and r['available_record_index']<anchor and r['record_index']<anchor]
    values={r['value'] for r in facts}
    return {'value':next(iter(values)) if len(values)==1 else None,
        'status':'conditional_on_reviewed_source' if len(values)==1 else 'conflict' if values else 'unknown',
        'evidence_ids':[r['fact_id'] for r in facts]}


def _information(source,anchor,cutoff,rows,admitted,goal):
    reviewed=[r for r in rows if r['fact_id'] in admitted and r['perspective'] in ('team','screen')]
    coverage=[r for r in reviewed if r['kind']=='coverage' and r['predicate']=='team.observation_prefix_complete' and
        r['value'] is True and r['coverage_start_record']==0 and r['coverage_end_record']==cutoff]
    observations=[r for r in reviewed if r['kind']=='observation' and r['game_time_ms'] is not None]
    obs_ids={r['fact_id'] for r in observations}
    links=[r for r in reviewed if r['kind']=='attribution' and r['predicate']=='team.observation_attributed_to' and
        r['entity_ref'] in obs_ids and r['value']==anchor['ward_id']]
    linked={r['entity_ref'] for r in links}
    # A verified attribution link is required; proximity/raw coordinate equality
    # never assigns the ward a team's observation.
    target=[r for r in observations if r['fact_id'] in linked and r['record_index']>anchor['source_record_index'] and anchor['team']==source['subject_team']]
    result={'status':'reviewed_attribution_without_complete_prior_history' if target else 'attribution_not_established',
        'attributed_observation_ids':[r['fact_id'] for r in target],'novel_observation_ids':[],
        'duplicate_observation_ids':[],'joint_observation_ids':[], 'task_matching_observation_ids':[],
        'novelty_scope':'complete_reviewed_supplied_team_prefix_only','coverage_evidence_ids':[r['fact_id'] for r in coverage],
        'utility':'not_established','geometry':'not_validated','team_visibility_is_not_player_attention':True}
    if not coverage:return result
    times=sorted({r['game_time_ms'] for r in observations});known={}
    for stamp in times:
        group=[r for r in observations if r['game_time_ms']==stamp];updates={}
        for row in group:
            key=(row['entity_ref'],row['predicate']);token=(type(row['value']).__name__,row['value'])
            updates.setdefault(key,set()).add(token)
        if any(len(v)>1 for v in updates.values()):
            result.update(status='simultaneous_observation_conflict',novel_observation_ids=[],duplicate_observation_ids=[],joint_observation_ids=[],task_matching_observation_ids=[])
            return result
        for row in group:
            if row not in target:continue
            key=(row['entity_ref'],row['predicate']);token=(type(row['value']).__name__,row['value'])
            category='duplicate_observation_ids' if known.get(key)==token else 'novel_observation_ids'
            result[category].append(row['fact_id'])
            if any(r['fact_id']!=row['fact_id'] and (r['entity_ref'],r['predicate'],type(r['value']),r['value'])==(row['entity_ref'],row['predicate'],type(row['value']),row['value']) for r in group):
                result['joint_observation_ids'].append(row['fact_id'])
            if row['predicate']==goal.get('information_predicate') and (not goal['entity_refs'] or row['entity_ref'] in goal['entity_refs']):
                result['task_matching_observation_ids'].append(row['fact_id'])
        known.update({k:next(iter(v)) for k,v in updates.items()})
    result['status']='conditional_reviewed_information' if target else 'no_matched_attribution_in_supplied_prefix'
    return result


def analyze_ward_task(source,ward_id,goal,*,alternatives=(),evidence=None,records=(),annotations=(),cutoff_record_index=None):
    """Compute source observations now; require reviewed facts for tactical claims.

    The default cutoff is the placement callback. A later cutoff is explicitly a
    retrospective information review; it cannot feed future facts into placement
    safety. Known booleans mean agreement in exact supplied review records, not
    certified reality, a production grade, attention or counterfactual utility.
    """
    from .ward_plan import ward_source_context
    context=ward_source_context(source,ward_id);anchor=context['placement_anchor']
    cutoff=anchor['source_record_index'] if cutoff_record_index is None else _int(cutoff_record_index,'review cutoff')
    if cutoff<anchor['source_record_index']:raise ValueError('review cutoff precedes selected placement')
    task=_goal(goal);proposals=_alternatives(alternatives,ward_id)
    rows,admitted,receipts,evidence_hash=_reviewed(source,ward_id,evidence,cutoff,records,annotations)
    selected_action='placement:'+ward_id
    options=[{'action_id':selected_action,'label':'Наблюдаемая постановка','origin':'observed_callback',
              'x':anchor['x'],'y':anchor['y']},*proposals]
    for option in options:
        option['feasible']=_condition(rows,admitted,option['action_id'],'placement.feasible',anchor['source_record_index'])
        option['safe']=_condition(rows,admitted,option['action_id'],'placement.safe',anchor['source_record_index'])
        option['route_safe']=_condition(rows,admitted,option['action_id'],'route.safe',anchor['source_record_index'])
        option['utility']='not_established'
    pairs=[]
    for a,b in combinations(options,2):
        pairs.append({'left_action_id':a['action_id'],'right_action_id':b['action_id'],
            'different_declared_coordinates':None if any(o[k] is None for o in (a,b) for k in ('x','y')) else (a['x'],a['y'])!=(b['x'],b['y']),
            'condition_differences':[key for key in ('feasible','safe','route_safe') if a[key]['value'] is not None and b[key]['value'] is not None and a[key]['value']!=b[key]['value']],
            'ranking':'not_established','benefit_difference':None,
            'tradeoff':'Сопоставьте проверенные ограничения и срок нужной информации; различие координат не доказывает лучший обзор.'})
    result={'schema_version':SCHEMA,'source_context_hash':context['source_context_hash'],
        'source_binding':context['source_binding'],'placement_anchor':anchor,'task':task,
        'cutoff_record_index':cutoff,'review_scope':'preplacement_callback_context' if cutoff==anchor['source_record_index'] else 'retrospective_information_prefix',
        'callback_analysis':_callback_analysis(source,anchor,cutoff),
        'information_analysis':_information(source,anchor,cutoff,rows,admitted,task),
        'options':options,'pairwise_alternatives':pairs,
        'reviewed_fact_ids':sorted(admitted),'review_receipt_hashes':receipts,'evidence_prefix_hash':evidence_hash,
        'status':'research_assistance','strategic_verdict':'insufficient_evidence',
        'validation_status':'external_provenance_and_domain_validation_pending','training_eligible':False,
        'limitations':['Raw координаты и lifecycle не устанавливают фактическую геометрию или полезность обзора.',
            'Разметка проверяет точный переданный prefix; независимость людей и доступ к клиенту требуют отдельной сверки.',
            'Текущая цель не доказывает прошлое намерение. Командное наблюдение не доказывает внимание игрока.',
            'Будущие факты информационного разбора не участвуют в условиях постановки; lifetime не является оценкой качества.']}
    result['analysis_hash']=content_hash(result)
    return result


def analyze_ward_prefix(source,ward_id,*,cutoff_record_index=None):
    """Initial report analysis without inventing a confirmed task or observation.

    This computes actual callback/timing/lifecycle/coordinate distinctions; its
    unknowns specifically concern tactical visibility, not absence of raw data.
    """
    from .ward_plan import ward_source_context
    context=ward_source_context(source,ward_id);anchor=context['placement_anchor']
    cutoff=anchor['source_record_index'] if cutoff_record_index is None else _int(cutoff_record_index,'review cutoff')
    if cutoff<anchor['source_record_index']:raise ValueError('review cutoff precedes selected placement')
    result={'schema_version':SCHEMA,'source_context_hash':context['source_context_hash'],
        'source_binding':context['source_binding'],'placement_anchor':anchor,
        'cutoff_record_index':cutoff,'task':None,'task_status':'not_supplied',
        'review_scope':'preplacement_callback_context' if cutoff==anchor['source_record_index'] else 'retrospective_callback_prefix',
        'callback_analysis':_callback_analysis(source,anchor,cutoff),
        'information_analysis':{'status':'attribution_not_established','attributed_observation_ids':[],
            'novel_observation_ids':[],'duplicate_observation_ids':[],'utility':'not_established',
            'reason':'raw_ward_callbacks_are_not_team_observation_or_attribution_evidence'},
        'status':'descriptive_source_analysis','strategic_verdict':'insufficient_evidence',
        'validation_status':'external_provenance_and_domain_validation_pending','training_eligible':False}
    result['analysis_hash']=content_hash(result)
    return result
