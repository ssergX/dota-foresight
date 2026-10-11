"""Explicit, point-bound command-stage bridge over a sealed callback source.

Equal sequence numbers never join messages. Caller-owned reviews are conditional
research inputs; this adapter cannot authenticate a reviewer or a client stream.
No coverage certificate is generated, even when every supplied stage is reviewed.
"""
from collections import Counter
from dataclasses import asdict, dataclass
from fractions import Fraction
import hashlib
import re

from dota_coach.decisions.command_census import CommandEvent, STAGES
from dota_coach.evidence.contracts import EntityRef, SourceRef, TimeRef, canonical_json, content_hash
from dota_coach.ingest.command_binding import SCHEMA, LINK_PROJECTION, _uint, bind_order_observation
from dota_coach.ingest.order_source import CALLBACKS, _load_order_source

VERSION = 'foresight.command-stage-bridge.v1'
REVIEW_CLAIMS = frozenset(('field_semantics', 'actor_action_identity', 'transaction_link',
                          'stage_semantics', 'clock_mapping', 'player_availability'))
BRIDGE_STAGES = (*STAGES, 'cast_started')
ROW_KEYS = frozenset(('t', 'record_index', 'demo_tick', 'net_tick', 'sequence_in_tick',
    'game_time', 'protobuf_type', 'data', 'protobuf_unknown_fields_hex', 'actor_identity',
    'command_stage', 'validation', 'entity_context'))


def _sha(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('exact SHA256 point binding required')


def _text(value):
    if not isinstance(value, str) or not value.strip() or value.strip()!=value or len(value)>512:
        raise ValueError('bounded explicit review identity required')


def _time(value):
    if (not isinstance(value, TimeRef) or value.order_status!='verified'
            or value.game_time_ms is None or value.uncertainty_ms is None
            or not isinstance(value.clock_mapping_version,str)
            or not value.clock_mapping_version.strip()
            or value.clock_mapping_version.strip()!=value.clock_mapping_version
            or value.clock_mapping_version.casefold() in
                ('legacy','legacy/unverified','legacy/unknown','unknown','unavailable','unverified')):
        raise ValueError('verified separately mapped clock required')


def _bounds(value):
    center, width = Fraction(str(value.game_time_ms)), Fraction(str(value.uncertainty_ms))
    return center-width, center+width


def observation_hash(row):
    """A single callback receipt, never the whole-file or suffix hash."""
    if not isinstance(row, dict) or set(row)-ROW_KEYS-{'order_type_schema_name'} or ROW_KEYS-set(row):
        raise ValueError('finite exact command callback projection required')
    if row['t']!='order_message':raise ValueError('command callback required')
    # Enum spelling is not independently reviewed stage semantics.
    return content_hash({key:row[key] for key in sorted(ROW_KEYS)})



def _receipt_features(receipt):
    value=asdict(receipt)
    value.pop('receipt_id')
    value['reviewed_claims']=sorted(receipt.reviewed_claims)
    value['review_sources']=[{key:getattr(ref,key) for key in
        ('provider','schema_version','locator','extractor_version')} for ref in receipt.review_sources]
    return value


@dataclass(frozen=True)
class StageReceipt:
    receipt_id: str
    attempt_id: str
    origin_record_index: int
    origin_sha256: str
    source_record_index: int
    source_sha256: str
    actor_entity: EntityRef
    action_entity: EntityRef
    stage: str
    at: TimeRef
    available_at: TimeRef
    semantic_version: str
    reviewed_claims: frozenset[str]
    review_sources: tuple[SourceRef, ...]

    def __post_init__(self):
        for value in (self.receipt_id,self.attempt_id,self.semantic_version):_text(value)
        if self.semantic_version.casefold() in ('unknown','unavailable','unverified','legacy','legacy/unverified','legacy/unknown'):
            raise ValueError('explicit reviewed stage semantics required')
        for value in (self.origin_record_index,self.source_record_index):_uint(value,2**64-1,'receipt record')
        if self.origin_record_index<2 or self.source_record_index<self.origin_record_index:
            raise ValueError('receipt origin must precede its observation in this source domain')
        for value in (self.origin_sha256,self.source_sha256):_sha(value)
        for entity in (self.actor_entity,self.action_entity):
            if not isinstance(entity,EntityRef):raise TypeError('typed exact actor/action generation required')
            _uint(entity.entity_index,16383,'entity index');_uint(entity.generation,2**31-1,'entity generation')
        if self.stage not in BRIDGE_STAGES:raise ValueError('explicit command stage required')
        for value in (self.at,self.available_at):_time(value)
        if not self.at.definitely_available_before(self.available_at):
            raise ValueError('stage cannot be delivered before its occurrence')
        if type(self.reviewed_claims) is not frozenset or self.reviewed_claims!=REVIEW_CLAIMS:
            raise ValueError('all exact field, transaction, clock and availability claims required')
        if (not isinstance(self.review_sources,tuple) or not 1<=len(self.review_sources)<=32
                or any(not isinstance(r,SourceRef) for r in self.review_sources)):
            raise TypeError('immutable separate review receipts required')
        for ref in self.review_sources:
            _sha(ref.content_hash)
            for key in ('artifact_id','provider','schema_version','locator','extractor_version'):_text(getattr(ref,key))


@dataclass(frozen=True)
class StageRegistry:
    match_id: int
    account_id: int
    replay_sha256: str
    game_build: int
    patch: str
    receipts: tuple[StageReceipt, ...]

    def __post_init__(self):
        _uint(self.match_id,2**64-1,'match');_uint(self.account_id,2**32-1,'account')
        if self.match_id==0 or self.account_id==0 or type(self.game_build) is not int or self.game_build<=0:
            raise ValueError('exact positive match/build required')
        _sha(self.replay_sha256);_text(self.patch)
        if self.patch.strip()!=self.patch or self.patch.casefold() in ('unknown','unavailable','unverified','legacy','legacy/unverified','legacy/unknown'):
            raise ValueError('explicit reviewed historical patch scope required')
        if (not isinstance(self.receipts,tuple) or len(self.receipts)>512
                or any(not isinstance(r,StageReceipt) for r in self.receipts)):
            raise TypeError('bounded immutable typed stage receipts required')


@dataclass(frozen=True)
class StageBridge:
    """Only this in-memory result supplies typed events; JSON is an audit view."""
    events: tuple[CommandEvent, ...]
    cast_started: tuple[StageReceipt, ...]
    document: dict


def bridge_command_stages(path, *, extraction, account_id, cutoff_record_index,
                          cutoff=None, registry=None, max_examples=256):
    """Read the complete sealed file, expose only a strict source-local prefix.

    A root is an own selected-hero raw unit/link association. Its identity is not
    interpreted as agency unless a separate exact StageReceipt supplies all six
    claims. Auxiliary callbacks need that explicit origin; no sequence join.
    """
    _uint(account_id,2**32-1,'account');_uint(cutoff_record_index,2**64-1,'cutoff')
    if account_id==0:raise ValueError('exact positive own account required')
    if cutoff_record_index<2:raise ValueError('cutoff must follow metadata')
    if type(max_examples) is not int or not 0<=max_examples<=256:
        raise ValueError('bounded example count required')
    if cutoff is not None:_time(cutoff)
    if registry is not None:
        if not isinstance(registry,StageRegistry):raise TypeError('separate typed stage registry required')
        if cutoff is None:raise ValueError('reviewed stages require a separately mapped cutoff')
        if (registry.match_id,registry.account_id,registry.replay_sha256)!=(
                extraction.replay.match_id,account_id,extraction.audit['replay_sha256']):
            raise ValueError('foreign stage registry match/account/replay')
    # Filter ordinal and availability before analytical scope/identity checks.
    prior_receipts=tuple(r for r in (registry.receipts if registry else ())
        if r.source_record_index<cutoff_record_index and r.origin_record_index<cutoff_record_index)
    if any(r.available_at.clock_mapping_version!=cutoff.clock_mapping_version for r in prior_receipts):
        raise ValueError('foreign stage availability clock')
    receipts=tuple(r for r in prior_receipts
        if _bounds(r.available_at)[1]<_bounds(cutoff)[0]
        and r.available_at.definitely_available_before(cutoff))
    needed={index for r in receipts for index in (r.origin_record_index,r.source_record_index)}
    points={};roots={};examples=[];counts=Counter();prefix=hashlib.sha256();root_count=0
    def observe(row):
        nonlocal root_count
        digest=observation_hash(row)
        bound=bind_order_observation(row,account_id=account_id)
        if row['record_index']>=cutoff_record_index:return
        prefix.update((canonical_json({k:row[k] for k in sorted(ROW_KEYS)})+'\n').encode('utf-8'))
        counts[row['protobuf_type']]+=1
        if row['record_index'] in needed:points[row['record_index']]=(row,digest)
        if bound['raw_units_selected_hero_association'] and bound['raw_ability_index_link_association']:
            root_count+=1
            root={'source_record_index':row['record_index'],'observation_sha256':digest,
                  'raw_actor_entity':bound['raw_selected_hero_association']['hero'],
                  'raw_action_entity':bound['raw_ability_index_link_association'],
                  'raw_fields':row['data'],'stage':None,'game_time':None}
            if row['record_index'] in needed:roots[row['record_index']]=root
            if len(examples)<max_examples:examples.append(root)
    source=_load_order_source(path,extraction=extraction,schema=SCHEMA,examples_per_type=0,observation_callback=observe)
    if (source['metadata'].get('context_semantics')!='same_callback_current_entity_snapshot_not_gameplay_identity'
            or any(source[part].get('link_projection')!=LINK_PROJECTION for part in ('metadata','footer'))):
        raise ValueError('exact source context/projection required')
    if cutoff_record_index>source['footer']['record_index']:
        raise ValueError('cutoff exceeds sealed callback domain')
    _uint(source['footer'].get('game_build'),2**32-1,'source game build')
    known_build=getattr(extraction.replay.manifest,'game_build',None)
    if known_build is not None:
        if (type(known_build) not in (str,int) or not re.fullmatch('[0-9]+',str(known_build))
                or type(source['footer'].get('game_build')) is not int
                or int(known_build)!=source['footer']['game_build']):
            raise ValueError('known extraction and callback game build disagree')
    if registry is not None:
        if registry.game_build!=source['footer'].get('game_build'):
            raise ValueError('foreign reviewed game build')
        known_patch=getattr(extraction.replay.manifest,'patch',None)
        if known_patch is not None and known_patch!=registry.patch:
            raise ValueError('foreign reviewed historical patch')
    unique={};attempts={};root_transactions={};stage_points=set();attempt_roots=set();events=[];casts=[]
    for receipt in receipts:
        if receipt.receipt_id in unique:
            if unique[receipt.receipt_id]!=receipt:raise ValueError('conflicting stage receipt id')
            continue
        root=roots.get(receipt.origin_record_index)
        origin=points.get(receipt.origin_record_index);point=points.get(receipt.source_record_index)
        if root is None or origin is None or point is None:
            raise ValueError('review must bind an observed own linked root and callback')
        if (origin[1],point[1])!=(receipt.origin_sha256,receipt.source_sha256):
            raise ValueError('damaged exact callback hash binding')
        def entity(raw):return EntityRef(f'match:{source["match_id"]}',raw['entity_index'],raw['generation'])
        actor,action=entity(root['raw_actor_entity']),entity(root['raw_action_entity'])
        if receipt.actor_entity!=actor or receipt.action_entity!=action:
            raise ValueError('foreign actor/action generation in stage receipt')
        if not root['raw_action_entity']['class_name'].startswith(('CDOTA_Item','CDOTA_Ability')):
            raise ValueError('root raw action is not an item or ability candidate')
        identity=(receipt.origin_record_index,actor,action)
        if receipt.attempt_id in attempts and attempts[receipt.attempt_id]!=identity:
            raise ValueError('attempt id cannot join distinct roots or generations')
        if identity in root_transactions and root_transactions[identity]!=receipt.attempt_id:
            raise ValueError('one exact root cannot be relabelled as distinct transactions')
        root_transactions[identity]=receipt.attempt_id
        stage_point=(receipt.attempt_id,receipt.stage,receipt.source_record_index)
        if stage_point in stage_points or (receipt.stage=='attempt' and receipt.attempt_id in attempt_roots):
            raise ValueError('review aliases or duplicate attempt stages cannot create commands')
        stage_points.add(stage_point)
        if receipt.stage=='attempt':attempt_roots.add(receipt.attempt_id)
        attempts[receipt.attempt_id]=identity;unique[receipt.receipt_id]=receipt
    ordered=tuple(sorted(unique.values(),key=lambda r:(r.source_record_index,content_hash(_receipt_features(r)))))
    for receipt in ordered:
        point=SourceRef('orders-point:'+receipt.source_sha256,receipt.source_sha256,'manta',SCHEMA,
                       f'record:{receipt.source_record_index}','foresight-replay/3.1')
        origin=SourceRef('orders-point:'+receipt.origin_sha256,receipt.origin_sha256,'manta',SCHEMA,
                        f'record:{receipt.origin_record_index}','foresight-replay/3.1')
        if receipt.stage=='cast_started':casts.append(receipt);continue
        events.append(CommandEvent('command-stage:'+content_hash(_receipt_features(receipt)),receipt.attempt_id,receipt.stage,
            receipt.source_record_index,receipt.at,receipt.available_at,f'account:{account_id}',
            receipt.action_entity,tuple(dict.fromkeys((origin,point,*receipt.review_sources))),receipt.semantic_version))
    prefix_view={'schema_version':VERSION,'match_id':source['match_id'],'account_id':account_id,
        'replay_sha256':source['replay_sha256'],'source_record_domain':SCHEMA+'.record_index',
        'perspective':'raw_replay_source_not_player_knowledge',
        'cutoff_record_index':cutoff_record_index,'cutoff':asdict(cutoff) if cutoff else None,
        'callback_prefix_sha256':prefix.hexdigest(),'callback_counts':{k:counts[k] for k in CALLBACKS},
        'raw_linked_root_count':root_count,'raw_root_examples':examples,'omitted_root_examples':root_count-len(examples),
        'conditional_stage_counts':{stage:sum(r.stage==stage for r in ordered) for stage in BRIDGE_STAGES},
        'review_patch':registry.patch if ordered else None,
        'stage_ledger':[_receipt_features(r) for r in ordered],
        'attempt_count':None,'attempt_coverage':None,'accepted_count':None,'committed_count':None,
        'validation':'conditional_research_only' if ordered else 'unverified_source_observation',
        'training_eligible':False,'game_opportunity_coverage':None,
        'limitations':['raw_prefix_is_not_player_information_set','no_equal_sequence_or_nearby_message_join','no_source_ordinal_join_to_entity_trace',
            'cast_started_is_not_committed','no_client_attempt_coverage','typed_review_does_not_authenticate_reviewers',
            'raw_callback_order_is_not_simulation_or_screen_order','no_strategic_quality_or_non_use_verdict']}
    prefix_view['input_hash']=content_hash({key:value for key,value in prefix_view.items()
        if key not in ('raw_root_examples','omitted_root_examples')})
    document={'schema_version':VERSION,'prefix':prefix_view,
        'source_provenance':{'source_sha256':source['source_sha256'],'replay_sha256':source['replay_sha256'],
            'game_build':source['footer'].get('game_build'),'sealed_message_count':source['footer']['message_count']},
        'review_receipts':[{**asdict(r),'reviewed_claims':sorted(r.reviewed_claims)} for r in ordered],
        'review_manifest_sha256':content_hash([{**asdict(r),'reviewed_claims':sorted(r.reviewed_claims)} for r in ordered]),
        'training_eligible':False}
    return StageBridge(tuple(events),tuple(casts),document)
