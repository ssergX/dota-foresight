"""Compile a reviewed prefix for one committed, constant-speed projectile.

This finite physical scenario assumes a fixed target, fixed straight path,
constant speed, no acceleration/homing/interception/destruction, no other hits,
healing, regeneration or changing defender state. It is never reconstructed from
future damage, health loss, or the eventual outcome. Screen exposure does not
establish attention. Portable proposals cannot authenticate any source or rule.
"""
from __future__ import annotations

from dataclasses import asdict,dataclass,fields
from fractions import Fraction
import json
import math
from pathlib import Path

from dota_coach.evidence.contracts import EntityRef,Fact,SourceRef,TimeRef,content_hash,canonical_json
from dota_coach.decisions.choice_window import PrefixFact
from dota_coach.decisions.defensive_impact import (
    ASSUMPTIONS,ImpactScope,ImpactGoal,HistoricalImpactModel,
)

VERSION='fixed-target-projectile-prefix.v1'
PHYSICAL_ASSUMPTIONS=(
    'committed_projectile_fixed_target_and_straight_path',
    'constant_verified_speed_no_homing_acceleration_or_target_movement',
    'no_interception_destruction_reflection_or_additional_projectiles',
    'cast_damage_parameters_and_defender_state_remain_stable',
    'no_other_damage_healing_regeneration_or_action_effects',
)
REQUIRED_PASSES=frozenset(('manifest_patch_build_binding','historical_projectile_and_item_mechanics',
    'own_operand_correctness_availability','own_screen_cue_correctness_availability',
    'projectile_commit_fixed_target_and_prefix_order','single_impact_exclusions_and_goal'))


def _text(value):
    if not isinstance(value,str) or not value or len(value)>512:raise ValueError('explicit bounded identity required')


def _sha(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('exact SHA256 required')


def _number(value,positive=False):
    try:valid=type(value) in (int,float) and math.isfinite(value) and value>=0 and (not positive or value>0)
    except OverflowError:valid=False
    if not valid:raise ValueError('finite nonnegative physical operand required')


def _pair(lo,hi,positive=False):
    _number(lo,positive);_number(hi,positive)
    if lo>hi:raise ValueError('ordered physical operand bounds required')


def _refs(value):
    if not isinstance(value,tuple) or not 1<=len(value)<=32 or any(not isinstance(s,SourceRef) for s in value):raise ValueError('immutable bounded source receipts required')
    for source in value:
        _sha(source.content_hash)
        for field in ('artifact_id','provider','schema_version','locator','extractor_version'):_text(getattr(source,field))
    if len({content_hash(s) for s in value})!=len(value):raise ValueError('duplicate source receipt')


def _entity(value,match):
    if (not isinstance(value,EntityRef) or value.replay_id!=f'match:{match}'
            or any(type(v) is not int or v<0 for v in (value.entity_index,value.generation))):raise ValueError('exact replay entity generation required')


def _time(value):
    if value is not None and not isinstance(value,TimeRef):raise TypeError('typed source clocks required')


def _fraction(value):return Fraction(str(value))


def _clock(value):
    return bool(isinstance(value,TimeRef) and value.game_time_ms is not None and value.uncertainty_ms is not None
        and value.replay_tick is not None and value.sequence_in_tick is not None and value.order_status=='verified'
        and isinstance(value.clock_mapping_version,str) and len(value.clock_mapping_version)<=512
        and value.clock_mapping_version==value.clock_mapping_version.strip()
        and value.clock_mapping_version.lower() not in
            ('','unknown','unavailable','unverified','legacy','legacy/unverified','legacy/unknown'))


def _before(value,cutoff,*,inclusive=False):
    if not _clock(value) or not _clock(cutoff) or value.clock_mapping_version!=cutoff.clock_mapping_version:return False
    clock_order=(value.replay_tick,value.sequence_in_tick)<=(cutoff.replay_tick,cutoff.sequence_in_tick) if inclusive else (
        (value.replay_tick,value.sequence_in_tick)<(cutoff.replay_tick,cutoff.sequence_in_tick))
    return bool(clock_order and _fraction(value.game_time_ms)+_fraction(value.uncertainty_ms)
        <=_fraction(cutoff.game_time_ms)-_fraction(cutoff.uncertainty_ms))


def _float_bound(value,lower):
    try:result=float(value)
    except OverflowError as exc:raise ValueError('physical forecast outside finite bounds') from exc
    if not math.isfinite(result):raise ValueError('physical forecast outside finite bounds')
    if (Fraction(result)>value if lower else Fraction(result)<value):result=math.nextafter(result,-math.inf if lower else math.inf)
    if not math.isfinite(result):raise ValueError('physical forecast outside finite bounds')
    return result


def _source_union(*groups):
    return tuple({content_hash(source):source for group in groups for source in group}.values())


def _latest_available(*times):
    # Derived availability is conservative across both clock coordinates. It
    # must never inherit a child's earlier stamp than a causal rule/manifest.
    latest_time=max(_fraction(t.game_time_ms)+_fraction(t.uncertainty_ms) for t in times)
    latest_order=max((t.replay_tick,t.sequence_in_tick) for t in times)
    return TimeRef(_float_bound(latest_time,False),*latest_order,0,times[0].clock_mapping_version,'verified')


@dataclass(frozen=True)
class ImpactPrefixQuery:
    match_id:int
    replay_sha256:str
    patch:str
    game_build:str
    subject_ref:str
    observer_ref:str
    actor_entity:EntityRef
    item_id:str
    item_entity:EntityRef
    threat_id:str
    at:TimeRef
    prefix_record_index:int
    source_record_domain:str
    max_fact_age_ms:float=1000
    dataset_kind:str='unknown'

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id<=0 or type(self.prefix_record_index) is not int or self.prefix_record_index<=0:raise ValueError('exact positive match/cutoff required')
        _sha(self.replay_sha256)
        for value in (self.patch,self.game_build,self.subject_ref,self.observer_ref,self.item_id,self.threat_id,self.source_record_domain):_text(value)
        if self.dataset_kind not in ('replay','synthetic','unknown'):raise ValueError('explicit dataset kind required')
        _entity(self.actor_entity,self.match_id);_entity(self.item_entity,self.match_id);_time(self.at)
        if self.at is None:raise ValueError('typed choice clock required')
        _number(self.max_fact_age_ms)


@dataclass(frozen=True)
class PrefixReplayManifest:
    match_id:int
    replay_sha256:str
    patch:str
    game_build:str
    dataset_kind:str
    source_refs:tuple[SourceRef,...]
    available_at:TimeRef|None

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id<=0:raise ValueError('exact positive manifest match required')
        _sha(self.replay_sha256);_text(self.patch);_text(self.game_build);_refs(self.source_refs);_time(self.available_at)
        if self.dataset_kind not in ('replay','synthetic','unknown'):raise ValueError('explicit manifest dataset kind required')


def _event(value):
    for key in ('event_id','subject_ref','observer_ref','source_record_domain'):_text(getattr(value,key))
    if type(value.source_record_index) is not int or value.source_record_index<0:raise ValueError('exact source callback record required')
    if value.perspective not in ('world','team','screen','public'):raise ValueError('explicit source perspective required')
    _refs(value.source_refs);_time(value.valid_at);_time(value.available_at)


@dataclass(frozen=True)
class PrefixOwnState:
    event_id:str
    subject_ref:str
    observer_ref:str
    actor_entity:EntityRef
    item_entity:EntityRef
    source_record_index:int
    source_record_domain:str
    valid_at:TimeRef|None
    available_at:TimeRef|None
    perspective:str
    hp_min:float
    hp_max:float
    mana_min:float
    mana_max:float
    mana_cost_min:float
    mana_cost_max:float
    baseline_multiplier_min:float
    baseline_multiplier_max:float
    activation_feasible:bool|None
    hold_feasible:bool|None
    single_impact_complete:bool|None
    window_stable:bool|None
    source_refs:tuple[SourceRef,...]

    def __post_init__(self):
        _event(self)
        for lo,hi in ((self.hp_min,self.hp_max),(self.mana_min,self.mana_max),(self.mana_cost_min,self.mana_cost_max),
                (self.baseline_multiplier_min,self.baseline_multiplier_max)):_pair(lo,hi)
        for value in (self.activation_feasible,self.hold_feasible,self.single_impact_complete,self.window_stable):
            if type(value) not in (bool,type(None)):raise ValueError('explicit boolean or unknown upstream operands required')


@dataclass(frozen=True)
class PrefixScreenCue:
    event_id:str
    subject_ref:str
    observer_ref:str
    projectile_entity:EntityRef
    threat_id:str
    source_record_index:int
    source_record_domain:str
    valid_at:TimeRef|None
    available_at:TimeRef|None
    perspective:str
    exposed:bool|None
    source_refs:tuple[SourceRef,...]

    def __post_init__(self):
        _event(self);_text(self.threat_id)
        if type(self.exposed) not in (bool,type(None)):raise ValueError('explicit exposure or unknown; attention is not inferred')


@dataclass(frozen=True)
class CommittedProjectile:
    event_id:str
    subject_ref:str
    observer_ref:str
    projectile_entity:EntityRef
    caster_entity:EntityRef
    target_entity:EntityRef
    threat_id:str
    damage_tag:str
    source_record_index:int
    source_record_domain:str
    valid_at:TimeRef|None
    available_at:TimeRef|None
    launch_at:TimeRef|None
    perspective:str
    committed:bool|None
    in_flight:bool|None
    launch_to_fixed_target_distance_min:float
    launch_to_fixed_target_distance_max:float
    speed_units_per_second_min:float
    speed_units_per_second_max:float
    cast_level:int
    damage_parameter_min:float
    damage_parameter_max:float
    source_refs:tuple[SourceRef,...]

    def __post_init__(self):
        _event(self);_text(self.threat_id);_text(self.damage_tag);_time(self.launch_at)
        for value in (self.committed,self.in_flight):
            if type(value) not in (bool,type(None)):raise ValueError('explicit reviewed commit/in-flight state required')
        _pair(self.launch_to_fixed_target_distance_min,self.launch_to_fixed_target_distance_max)
        _pair(self.speed_units_per_second_min,self.speed_units_per_second_max,True)
        _pair(self.damage_parameter_min,self.damage_parameter_max)
        if type(self.cast_level) is not int or not 1<=self.cast_level<=64:raise ValueError('exact supported cast level required')


@dataclass(frozen=True)
class HistoricalProjectileRule:
    rule_id:str
    patch:str
    game_build:str
    item_id:str
    threat_id:str
    method_version:str
    damage_tag:str
    level_damage_bounds:tuple[tuple[float,float],...]
    parameter_coefficient_min:float
    parameter_coefficient_max:float
    activation_latency_min_ms:float
    activation_latency_max_ms:float
    effect_duration_min_ms:float
    effect_duration_max_ms:float
    protected_damage_multiplier_min:float
    protected_damage_multiplier_max:float
    exempt_tags:tuple[str,...]
    assumptions:tuple[str,...]
    available_at:TimeRef|None
    source_refs:tuple[SourceRef,...]

    def __post_init__(self):
        for key in ('rule_id','patch','game_build','item_id','threat_id','method_version','damage_tag'):_text(getattr(self,key))
        if (not isinstance(self.level_damage_bounds,tuple) or not 1<=len(self.level_damage_bounds)<=64
                or any(not isinstance(pair,tuple) or len(pair)!=2 for pair in self.level_damage_bounds)):raise ValueError('finite immutable cast-level damage table required')
        for lo,hi in self.level_damage_bounds:_pair(lo,hi)
        for lo,hi in ((self.parameter_coefficient_min,self.parameter_coefficient_max),
                (self.activation_latency_min_ms,self.activation_latency_max_ms),
                (self.effect_duration_min_ms,self.effect_duration_max_ms),
                (self.protected_damage_multiplier_min,self.protected_damage_multiplier_max)):_pair(lo,hi)
        if not isinstance(self.exempt_tags,tuple) or len(self.exempt_tags)>64 or len(set(self.exempt_tags))!=len(self.exempt_tags):raise ValueError('finite immutable exemption tags required')
        for value in self.exempt_tags:_text(value)
        if self.assumptions!=PHYSICAL_ASSUMPTIONS or not isinstance(self.assumptions,tuple):raise ValueError('all finite physical exclusions must be explicitly declared')
        _refs(self.source_refs);_time(self.available_at)


@dataclass(frozen=True)
class PrefixRuleAdmission:
    query_hash:str
    manifest_hash:str
    rule_hash:str
    own_state_hash:str
    cue_hash:str
    projectile_hash:str
    goal_hash:str
    authenticated_passes:frozenset[str]
    review_sources:tuple[SourceRef,...]

    def __post_init__(self):
        for key in ('query_hash','manifest_hash','rule_hash','own_state_hash','cue_hash','projectile_hash','goal_hash'):_sha(getattr(self,key))
        if not isinstance(self.authenticated_passes,frozenset) or not self.authenticated_passes<=REQUIRED_PASSES:raise ValueError('explicit caller-owned review passes required')
        _refs(self.review_sources)


@dataclass(frozen=True)
class ImpactPrefixRegistry:
    admissions:tuple[PrefixRuleAdmission,...]
    allowed_source_receipt_hashes:frozenset[str]
    review_context:str='external_review'

    def __post_init__(self):
        if not isinstance(self.admissions,tuple) or len(self.admissions)>128 or any(not isinstance(a,PrefixRuleAdmission) for a in self.admissions):raise TypeError('bounded immutable caller-owned admissions required')
        if not isinstance(self.allowed_source_receipt_hashes,frozenset):raise TypeError('immutable current source receipt allowlist required')
        for digest in self.allowed_source_receipt_hashes:_sha(digest)
        if self.review_context not in ('external_review','testing'):raise ValueError('explicit review context required')


def _event_missing(query,event,name):
    if event is None:return [name+'_missing']
    if event.perspective=='world' or event.subject_ref!=query.subject_ref or event.observer_ref!=query.observer_ref:
        raise ValueError('hidden world/foreign observer prefix event forbidden')
    if event.source_record_domain!=query.source_record_domain:raise ValueError('foreign source record domain forbidden')
    reasons=[]
    if event.source_record_index>=query.prefix_record_index:reasons.append(name+'_outside_prefix')
    if not _before(event.valid_at,query.at) or not _before(event.available_at,query.at):reasons.append(name+'_clock_or_availability_unknown')
    elif _fraction(query.at.game_time_ms)+_fraction(query.at.uncertainty_ms)-_fraction(event.valid_at.game_time_ms)+_fraction(event.valid_at.uncertainty_ms)>_fraction(query.max_fact_age_ms):reasons.append(name+'_stale')
    return reasons


def _proposal(scope,model,goal,facts):
    return json.loads(canonical_json({'schema_version':'foresight.defensive-impact-input.v1','scope':asdict(scope),'model':asdict(model),
        'goal':asdict(goal),'facts':[asdict(f) for f in facts]}))


def compile_impact_prefix(query,*,manifest,own_state=None,cue=None,projectile=None,rules=(),goal,registry=None):
    """Return a portable impact proposal only from an exact reviewed prefix.

    This registry admits source interpretation and this finite forecast. It does
    not admit the downstream criterion, chosen action, coaching or training.
    Recompile with the current registry to honor dependency revocation.
    """
    if not isinstance(query,ImpactPrefixQuery) or not isinstance(manifest,PrefixReplayManifest) or not isinstance(goal,ImpactGoal):raise TypeError('typed exact prefix query, manifest and goal required')
    for event,cls in ((own_state,PrefixOwnState),(cue,PrefixScreenCue),(projectile,CommittedProjectile)):
        if event is not None and not isinstance(event,cls):raise TypeError('typed immutable prefix events required')
    if not isinstance(rules,tuple) or len(rules)>128 or any(not isinstance(r,HistoricalProjectileRule) for r in rules):raise TypeError('bounded immutable historical rulebook required')
    if registry is not None and not isinstance(registry,ImpactPrefixRegistry):raise TypeError('portable registry/grants forbidden')
    if len({r.rule_id for r in rules})!=len(rules):raise ValueError('ambiguous duplicate historical rule identity')
    reasons=[];candidate=None;forecast=None;selected=None;admission=None
    if any(value.strip().lower() in ('unknown','unavailable','unverified','legacy/unverified') for value in
            (query.patch,query.game_build,manifest.patch,manifest.game_build)):
        reasons.append('manifest_historical_patch_or_build_unknown')
    if (manifest.match_id,manifest.replay_sha256,manifest.patch,manifest.game_build,manifest.dataset_kind)!=(query.match_id,query.replay_sha256,query.patch,query.game_build,query.dataset_kind):
        reasons.append('manifest_match_replay_patch_build_dataset_mismatch')
    if not _before(manifest.available_at,query.at):reasons.append('manifest_clock_or_availability_unknown')
    reasons+=_event_missing(query,own_state,'own_state')+_event_missing(query,cue,'cue')+_event_missing(query,projectile,'projectile')
    if own_state is not None:
        _entity(own_state.actor_entity,query.match_id);_entity(own_state.item_entity,query.match_id)
        if own_state.actor_entity!=query.actor_entity or own_state.item_entity!=query.item_entity:reasons.append('own_actor_or_item_generation_mismatch')
        for name in ('activation_feasible','hold_feasible','single_impact_complete','window_stable'):
            if getattr(own_state,name) is None:reasons.append('own_'+name+'_unknown')
        if own_state.single_impact_complete is not True or own_state.window_stable is not True:reasons.append('local_one_impact_or_stability_not_established')
    if cue is not None:
        _entity(cue.projectile_entity,query.match_id)
        if cue.perspective!='screen' or cue.observer_ref!=query.subject_ref:raise ValueError('cue must be the selected subject screen exposure')
        if cue.exposed is not True:reasons.append('own_screen_cue_not_established')
        if cue.threat_id!=query.threat_id:reasons.append('cue_threat_mismatch')
    if projectile is not None:
        for entity in (projectile.projectile_entity,projectile.caster_entity,projectile.target_entity):_entity(entity,query.match_id)
        if projectile.target_entity!=query.actor_entity or projectile.threat_id!=query.threat_id:reasons.append('projectile_target_generation_or_threat_mismatch')
        if cue is not None and cue.projectile_entity!=projectile.projectile_entity:reasons.append('cue_projectile_generation_mismatch')
        if projectile.committed is not True or projectile.in_flight is not True:reasons.append('committed_in_flight_projectile_not_established')
        if not _before(projectile.launch_at,projectile.valid_at,inclusive=True):reasons.append('launch_time_or_order_unknown')
    if not _before(goal.available_at,query.at):reasons.append('goal_not_known_before_choice')
    # Build/patch provenance is resolved before any rule is considered.
    if not reasons:
        matching=tuple(r for r in rules if (r.patch,r.game_build,r.item_id,r.threat_id)==(query.patch,query.game_build,query.item_id,query.threat_id))
        if len(matching)!=1:reasons.append('historical_rule_missing_or_ambiguous')
        else:
            selected=matching[0]
            if not _before(selected.available_at,query.at):reasons.append('historical_rule_not_available_before_choice')
            if selected.damage_tag!=projectile.damage_tag:reasons.append('historical_damage_tag_mismatch')
            if projectile.cast_level>len(selected.level_damage_bounds):reasons.append('cast_level_missing_from_historical_rule')
            if any(len(_source_union(event.source_refs,selected.source_refs if event is projectile else (),manifest.source_refs))>32
                    for event in (own_state,cue,projectile)) or len(_source_union(selected.source_refs,manifest.source_refs))>32:
                reasons.append('derived_forecast_source_receipt_bound_exceeded')
    if not reasons:
        expected=(content_hash(query),content_hash(manifest),content_hash(selected),content_hash(own_state),content_hash(cue),content_hash(projectile),content_hash(goal))
        dependencies=manifest.source_refs+selected.source_refs+own_state.source_refs+cue.source_refs+projectile.source_refs+goal.source_refs
        for proposed in registry.admissions if registry else ():
            if tuple(getattr(proposed,k) for k in ('query_hash','manifest_hash','rule_hash','own_state_hash','cue_hash','projectile_hash','goal_hash'))!=expected or proposed.authenticated_passes!=REQUIRED_PASSES:continue
            if all(content_hash(s) in registry.allowed_source_receipt_hashes for s in dependencies+proposed.review_sources):admission=proposed;break
        if admission is None:reasons.append('independent_exact_prefix_rule_goal_receipt_review_missing_or_revoked')
    if not reasons:
        try:
            distance=(projectile.launch_to_fixed_target_distance_min,projectile.launch_to_fixed_target_distance_max)
            speed=(projectile.speed_units_per_second_min,projectile.speed_units_per_second_max)
            travel=(_fraction(distance[0])/_fraction(speed[1])*1000,_fraction(distance[1])/_fraction(speed[0])*1000)
            arrival=(_fraction(projectile.launch_at.game_time_ms)-_fraction(projectile.launch_at.uncertainty_ms)+travel[0],
                _fraction(projectile.launch_at.game_time_ms)+_fraction(projectile.launch_at.uncertainty_ms)+travel[1])
            base=selected.level_damage_bounds[projectile.cast_level-1]
            damage=(_fraction(base[0])+_fraction(projectile.damage_parameter_min)*_fraction(selected.parameter_coefficient_min),
                _fraction(base[1])+_fraction(projectile.damage_parameter_max)*_fraction(selected.parameter_coefficient_max))
            forecast={'arrival_time_min_ms':_float_bound(arrival[0],True),'arrival_time_max_ms':_float_bound(arrival[1],False),
                'damage_before_resistance_min':_float_bound(damage[0],True),'damage_before_resistance_max':_float_bound(damage[1],False),
                'travel_duration_min_ms':_float_bound(travel[0],True),'travel_duration_max_ms':_float_bound(travel[1],False)}
            if arrival[0]<=_fraction(query.at.game_time_ms)+_fraction(query.at.uncertainty_ms):
                reasons.append('forecast_not_wholly_after_choice');forecast=None
            else:
                scope=ImpactScope(query.match_id,query.subject_ref,query.observer_ref,query.patch,query.item_id,query.item_entity,
                    query.threat_id,query.at,query.prefix_record_index,query.max_fact_age_ms,query.dataset_kind)
                model=HistoricalImpactModel(query.patch,query.item_id,query.threat_id,selected.method_version,
                    selected.activation_latency_min_ms,selected.activation_latency_max_ms,selected.effect_duration_min_ms,selected.effect_duration_max_ms,
                    selected.protected_damage_multiplier_min,selected.protected_damage_multiplier_max,selected.damage_tag,selected.exempt_tags,
                    _source_union(selected.source_refs,manifest.source_refs),
                    _latest_available(selected.available_at,manifest.available_at),ASSUMPTIONS)
                values={'self.hp_min':own_state.hp_min,'self.hp_max':own_state.hp_max,'self.mana_min':own_state.mana_min,'self.mana_max':own_state.mana_max,
                    'item.mana_cost_min':own_state.mana_cost_min,'item.mana_cost_max':own_state.mana_cost_max,
                    'threat.baseline_multiplier_min':own_state.baseline_multiplier_min,'threat.baseline_multiplier_max':own_state.baseline_multiplier_max,
                    'self.activation_feasible':own_state.activation_feasible,'self.hold_feasible':own_state.hold_feasible,
                    'context.single_impact_complete':own_state.single_impact_complete,'context.window_stable':own_state.window_stable,
                    'screen.reaction_cue':True,'threat.committed':True,'threat.damage_tag':selected.damage_tag,
                    'threat.damage_before_resistance_min':forecast['damage_before_resistance_min'],'threat.damage_before_resistance_max':forecast['damage_before_resistance_max'],
                    'threat.projected_impact_time_min_ms':forecast['arrival_time_min_ms'],'threat.projected_impact_time_max_ms':forecast['arrival_time_max_ms']}
                facts=[]
                for predicate,value in sorted(values.items()):
                    event=cue if predicate=='screen.reaction_cue' else projectile if predicate.startswith('threat.') and not predicate.startswith('threat.baseline_') else own_state
                    refs=_source_union(event.source_refs,selected.source_refs if event is projectile else (),manifest.source_refs)
                    causal_times=(event.available_at,manifest.available_at)+(selected.available_at,) if event is projectile else (event.available_at,manifest.available_at)
                    fact=Fact('impact-prefix:'+predicate,query.subject_ref,predicate,value,'derived' if event is projectile else 'observed',
                        event.valid_at,_latest_available(*causal_times),event.perspective,refs,observer_ref=query.observer_ref,method_version=VERSION)
                    facts.append(PrefixFact(fact,event.source_record_index))
                candidate=_proposal(scope,model,goal,tuple(facts))
        except ValueError as exc:
            if 'physical forecast outside finite bounds' not in str(exc):raise
            reasons.append('physical_forecast_overflow');forecast=None
    raw_own=({'hp_min':own_state.hp_min,'hp_max':own_state.hp_max,'mana_min':own_state.mana_min,'mana_max':own_state.mana_max,
        'source_record_index':own_state.source_record_index,'validation':'unverified_raw_candidate'} if own_state is not None
            and own_state.actor_entity==query.actor_entity and own_state.item_entity==query.item_entity
            and not _event_missing(query,own_state,'own_state') else None)
    return {'schema_version':'foresight.impact-prefix-compile.v1','compiler_version':VERSION,'match_id':query.match_id,
        'subject_ref':query.subject_ref,'dataset_kind':query.dataset_kind,'candidate_defensive_impact_input':candidate,'forecast':forecast,
        'raw_own_operand_candidates':raw_own,'status':'reviewed_conditional_prefix_proposal' if candidate else 'unavailable',
        'missing_reasons':sorted(set(reasons)),'selected_rule_hash':content_hash(selected) if selected is not None else None,
        'registry_context':registry.review_context if registry else None,'query_hash':content_hash(query),
        'admission_hash':content_hash({**asdict(admission),'authenticated_passes':sorted(admission.authenticated_passes)}) if admission else None,
        'physical_assumptions':list(PHYSICAL_ASSUMPTIONS),'noticed':'not_established','training_eligible':False,'research_only':True,
        'strategic_quality':'not_established','downstream_case_and_criterion_admission_required':True}


def _exact(data,cls):
    if not isinstance(data,dict) or set(data)!={f.name for f in fields(cls)}:raise ValueError('strict exact prefix DTO fields required')
    return dict(data)


def _dto(data,cls):
    data=_exact(data,cls)
    for key in ('actor_entity','item_entity','projectile_entity','caster_entity','target_entity'):
        if key in data:data[key]=EntityRef(**_exact(data[key],EntityRef))
    for key in ('at','valid_at','available_at','launch_at'):
        if key in data:data[key]=TimeRef(**_exact(data[key],TimeRef)) if data[key] is not None else None
    if 'source_refs' in data:
        if not isinstance(data['source_refs'],list):raise ValueError('portable source receipt list required')
        data['source_refs']=tuple(SourceRef(**_exact(s,SourceRef)) for s in data['source_refs'])
    for key in ('exempt_tags','assumptions','level_damage_bounds'):
        if key in data:
            if not isinstance(data[key],list):raise ValueError('portable immutable list required')
            data[key]=tuple(tuple(p) for p in data[key]) if key=='level_damage_bounds' else tuple(data[key])
    return cls(**data)


def load_impact_prefix_input(source):
    from dota_coach.decisions.batch import strict_json
    if not isinstance(source,dict) and Path(source).stat().st_size>1<<20:raise ValueError('bounded prefix proposal required')
    data=source if isinstance(source,dict) else strict_json(Path(source).read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or set(data)!={'schema_version','query','manifest','own_state','cue','projectile','rules','goal'} or data['schema_version']!='foresight.impact-prefix-input.v1':raise ValueError('strict prefix proposals contain no registry, future outcome or grants')
    try:
        if not isinstance(data['rules'],list) or len(data['rules'])>128:raise ValueError('finite proposed rulebook required')
        return {'query':_dto(data['query'],ImpactPrefixQuery),'manifest':_dto(data['manifest'],PrefixReplayManifest),
            'own_state':_dto(data['own_state'],PrefixOwnState) if data['own_state'] is not None else None,
            'cue':_dto(data['cue'],PrefixScreenCue) if data['cue'] is not None else None,
            'projectile':_dto(data['projectile'],CommittedProjectile) if data['projectile'] is not None else None,
            'rules':tuple(_dto(rule,HistoricalProjectileRule) for rule in data['rules']),'goal':_dto(data['goal'],ImpactGoal)}
    except (TypeError,KeyError,AttributeError,OverflowError) as exc:raise ValueError('malformed typed prefix proposal') from exc
