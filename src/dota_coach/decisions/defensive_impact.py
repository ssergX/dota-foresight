"""Conditional single-impact HP/mana arithmetic, never a Dota quality verdict.

Damage is supplied before defender resistance. Historical protected multipliers
replace the baseline multiplier for this one scoped damage tag. Protection is
[activation completion, completion + duration); partial timing takes the union
of protected and untreated damage. HP is an unclamped balance, not a death
forecast. All other damage, healing, regeneration and action effects are excluded
by explicit local assumptions. A separate caller-owned registry admits receipts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from fractions import Fraction
import math
from pathlib import Path

from dota_coach.evidence.contracts import EntityRef, Fact, SourceRef, TimeRef, content_hash
from .choice_window import PrefixFact

VERSION='defensive-single-impact.v1'
ASSUMPTIONS=(
    'one_committed_impact_no_other_damage_healing_or_regeneration',
    'activation_and_hold_change_only_declared_mana_and_damage_multiplier',
    'declared_multiplier_fully_models_this_damage_tag_and_exemptions',
    'defender_item_and_threat_parameters_stable_until_impact',
)
PAIRS={
    'hp':('self.hp_min','self.hp_max'),
    'mana':('self.mana_min','self.mana_max'),
    'cost':('item.mana_cost_min','item.mana_cost_max'),
    'damage':('threat.damage_before_resistance_min','threat.damage_before_resistance_max'),
    'baseline':('threat.baseline_multiplier_min','threat.baseline_multiplier_max'),
    'impact':('threat.projected_impact_time_min_ms','threat.projected_impact_time_max_ms'),
}
BOOLS=frozenset(('self.activation_feasible','self.hold_feasible','screen.reaction_cue',
    'context.single_impact_complete','context.window_stable','threat.committed'))
PREDICATES=frozenset(p for pair in PAIRS.values() for p in pair)|BOOLS|{'threat.damage_tag'}


def _finite(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:return False


def _number(value):
    if not _finite(value) or value<0:raise ValueError('finite nonnegative model/goal operand required')


def _text(value):
    if not isinstance(value,str) or not value or len(value)>512:raise ValueError('explicit bounded identity required')


def _sha(value):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('exact SHA256 receipt binding required')


def _refs(value):
    if not isinstance(value,tuple) or not value or len(value)>32 or any(not isinstance(s,SourceRef) for s in value):
        raise ValueError('immutable bounded source receipts required')
    for source in value:
        _sha(source.content_hash)
        for name in ('artifact_id','provider','schema_version','locator','extractor_version'):_text(getattr(source,name))


@dataclass(frozen=True)
class ImpactScope:
    match_id:int
    subject_ref:str
    observer_ref:str
    patch:str
    item_id:str
    item_entity:EntityRef
    threat_id:str
    at:TimeRef
    prefix_record_index:int
    max_fact_age_ms:float=1000
    dataset_kind:str='unknown'

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id<=0 or type(self.prefix_record_index) is not int or self.prefix_record_index<=0:
            raise ValueError('exact positive match/prefix required')
        for v in (self.subject_ref,self.observer_ref,self.patch,self.item_id,self.threat_id):_text(v)
        if (not isinstance(self.item_entity,EntityRef) or self.item_entity.replay_id!=f'match:{self.match_id}'
                or any(type(v) is not int or v<0 for v in (self.item_entity.entity_index,self.item_entity.generation))):
            raise ValueError('exact item entity generation belongs to scope match')
        if not isinstance(self.at,TimeRef) or self.dataset_kind not in ('replay','synthetic','unknown'):
            raise ValueError('typed choice clock/dataset required')
        _number(self.max_fact_age_ms)


@dataclass(frozen=True)
class ImpactGoal:
    minimum_hp_after_impact:float
    minimum_mana_after_action:float
    source_refs:tuple[SourceRef,...]
    available_at:TimeRef|None

    def __post_init__(self):
        _number(self.minimum_hp_after_impact);_number(self.minimum_mana_after_action);_refs(self.source_refs)
        if self.available_at is not None and not isinstance(self.available_at,TimeRef):raise TypeError('typed goal availability required')


@dataclass(frozen=True)
class HistoricalImpactModel:
    patch:str
    item_id:str
    threat_id:str
    method_version:str
    activation_latency_min_ms:float
    activation_latency_max_ms:float
    effect_duration_min_ms:float
    effect_duration_max_ms:float
    protected_damage_multiplier_min:float
    protected_damage_multiplier_max:float
    damage_tag:str
    exempt_tags:tuple[str,...]
    source_refs:tuple[SourceRef,...]
    available_at:TimeRef|None
    assumptions:tuple[str,...]

    def __post_init__(self):
        for v in (self.patch,self.item_id,self.threat_id,self.method_version,self.damage_tag):_text(v)
        for left,right in ((self.activation_latency_min_ms,self.activation_latency_max_ms),
                (self.effect_duration_min_ms,self.effect_duration_max_ms),
                (self.protected_damage_multiplier_min,self.protected_damage_multiplier_max)):
            _number(left);_number(right)
            if left>right:raise ValueError('ordered historical model bounds required')
        if not isinstance(self.exempt_tags,tuple) or len(self.exempt_tags)>64 or len(set(self.exempt_tags))!=len(self.exempt_tags):
            raise ValueError('immutable distinct exemption tags required')
        for tag in self.exempt_tags:_text(tag)
        _refs(self.source_refs)
        if self.available_at is not None and not isinstance(self.available_at,TimeRef):raise TypeError('typed model availability required')
        if not isinstance(self.assumptions,tuple) or self.assumptions!=ASSUMPTIONS:
            raise ValueError('explicit full local single-impact assumptions required')


@dataclass(frozen=True)
class ImpactAdmission:
    """Separate caller-owned research registry; never read from portable JSON."""
    scope_hash:str
    input_hash:str
    model_hash:str
    goal_hash:str
    fact_hashes:frozenset[str]
    review_sources:tuple[SourceRef,...]
    chosen_action_binding_hash:str|None=None
    chosen_action_sources:tuple[SourceRef,...]=()

    def __post_init__(self):
        for v in (self.scope_hash,self.input_hash,self.model_hash,self.goal_hash):_sha(v)
        if not isinstance(self.fact_hashes,frozenset):raise TypeError('immutable exact admitted fact hashes required')
        for v in self.fact_hashes:_sha(v)
        _refs(self.review_sources)
        if self.chosen_action_binding_hash is not None:
            _sha(self.chosen_action_binding_hash);_refs(self.chosen_action_sources)
        elif self.chosen_action_sources:
            raise ValueError('chosen source receipts require exact action binding')


def chosen_action_binding_hash(input_hash,action,source_refs):
    """Caller review binds postchoice action receipts outside prefix features."""
    _sha(input_hash);_refs(source_refs)
    if action not in ('activate','hold'):raise ValueError('exact separately witnessed action required')
    return content_hash({'input_hash':input_hash,'action':action,'action_source_refs':[asdict(s) for s in source_refs]})


def _fraction(value):
    # Proposal numbers have their canonical JSON decimal value. Avoid granting
    # rounded binary arithmetic at goal/timing boundaries; publish outward
    # rounded finite float bounds only after exact decimal rational arithmetic.
    return Fraction(str(value))


def _clock(time):
    return (isinstance(time,TimeRef) and time.order_status=='verified' and time.game_time_ms is not None
        and time.uncertainty_ms is not None and time.replay_tick is not None and time.sequence_in_tick is not None
        and isinstance(time.clock_mapping_version,str) and time.clock_mapping_version.lower() not in
            ('','legacy/unverified','unknown','unavailable','unverified','legacy/unknown'))


def _before(time,cutoff):
    return bool(_clock(time) and _clock(cutoff) and time.clock_mapping_version==cutoff.clock_mapping_version
        and _fraction(time.game_time_ms)+_fraction(time.uncertainty_ms)
            <=_fraction(cutoff.game_time_ms)-_fraction(cutoff.uncertainty_ms)
        and (time.replay_tick,time.sequence_in_tick)<(cutoff.replay_tick,cutoff.sequence_in_tick))


def _visible(scope,observation):
    fact=observation.fact
    if fact.subject_ref!=scope.subject_ref or fact.observer_ref!=scope.observer_ref or fact.perspective not in ('team','screen','public'):
        raise ValueError('hidden world/foreign observer defensive impact context forbidden')
    if fact.predicate=='screen.reaction_cue' and (fact.perspective!='screen' or fact.observer_ref!=scope.subject_ref):
        raise ValueError('reaction cue requires selected subject screen perspective')
    if fact.predicate not in PREDICATES:raise ValueError('exact defensive impact operand allowlist required')
    if observation.source_record_index>=scope.prefix_record_index:return False
    if not _before(fact.valid_at,scope.at) or not _before(fact.available_at,scope.at):return False
    if (_fraction(scope.at.game_time_ms)+_fraction(scope.at.uncertainty_ms)
            -_fraction(fact.valid_at.game_time_ms)+_fraction(fact.valid_at.uncertainty_ms)>_fraction(scope.max_fact_age_ms)):
        return False
    return True


def _features(value):
    """Keep field locators; exclude artifact-wide IDs/digests from analytical hash."""
    if isinstance(value,dict):
        return {k:([{'provider':s['provider'],'schema_version':s['schema_version'],'locator':s['locator'],
            'extractor_version':s['extractor_version']} for s in v] if k=='source_refs' else _features(v)) for k,v in value.items()
                if k not in ('fact_id','derived_from')}
    if isinstance(value,(tuple,list)):return [_features(v) for v in value]
    return value


def _bound(values):
    output={}
    for name,value in zip(('minimum','maximum'),values):
        try:rounded=float(value)
        except OverflowError as exc:raise ValueError('impact arithmetic outside finite bounds') from exc
        if not math.isfinite(rounded):raise ValueError('impact arithmetic outside finite bounds')
        exact=Fraction(rounded)
        if name=='minimum' and exact>value:rounded=math.nextafter(rounded,-math.inf)
        if name=='maximum' and exact<value:rounded=math.nextafter(rounded,math.inf)
        if not math.isfinite(rounded):raise ValueError('impact arithmetic outside finite bounds')
        output[name]=rounded
    return output


def _arithmetic(scope,model,goal,prefix):
    reasons=[];values={}
    for predicate in sorted(PREDICATES):
        observation=prefix.get(predicate)
        fact=observation.fact if observation else None
        if fact is None or fact.status not in ('observed','derived') or fact.value is None:
            reasons.append('unknown:'+predicate);continue
        _refs(fact.source_refs)
        value=fact.value
        if predicate in BOOLS:
            if type(value) is not bool:raise ValueError('explicit boolean defensive impact operands required')
        elif predicate=='threat.damage_tag':_text(value)
        elif not _finite(value) or (value<0 and predicate not in PAIRS['impact']):
            raise ValueError('finite nonnegative defensive impact operands required')
        values[predicate]=value
    if reasons:return None,reasons
    pairs={}
    for name,(left,right) in PAIRS.items():
        if values[left]>values[right]:raise ValueError('ordered defensive impact bounds required')
        pairs[name]=(_fraction(values[left]),_fraction(values[right]))
    for flag in ('screen.reaction_cue','context.single_impact_complete','context.window_stable','threat.committed'):
        if not values[flag]:reasons.append('not_established:'+flag)
    if model.damage_tag!=values['threat.damage_tag']:reasons.append('historical_damage_tag_mismatch')
    at=(_fraction(scope.at.game_time_ms)-_fraction(scope.at.uncertainty_ms),_fraction(scope.at.game_time_ms)+_fraction(scope.at.uncertainty_ms))
    if pairs['impact'][0]<at[1]:reasons.append('impact_forecast_not_wholly_after_choice')
    if reasons:return None,reasons
    start=(at[0]+_fraction(model.activation_latency_min_ms),at[1]+_fraction(model.activation_latency_max_ms))
    end=(start[0]+_fraction(model.effect_duration_min_ms),start[1]+_fraction(model.effect_duration_max_ms))
    impact=pairs['impact']
    exempt=values['threat.damage_tag'] in model.exempt_tags
    full=(model.effect_duration_min_ms>0 and impact[0]>=start[1] and impact[1]<end[0])
    possible=(model.effect_duration_max_ms>0 and impact[1]>=start[0] and impact[0]<end[1])
    coverage='exempt' if exempt else 'full' if full else 'partial' if possible else 'none'
    protected=(_fraction(model.protected_damage_multiplier_min),_fraction(model.protected_damage_multiplier_max))
    multiplier=pairs['baseline'] if coverage in ('none','exempt') else protected if coverage=='full' else (
        min(pairs['baseline'][0],protected[0]),max(pairs['baseline'][1],protected[1]))
    alternatives={}
    hp,mana,cost,damage=pairs['hp'],pairs['mana'],pairs['cost'],pairs['damage']
    for action in ('activate','hold'):
        feasible=values['self.activation_feasible' if action=='activate' else 'self.hold_feasible']
        entry={'feasibility':feasible,'hp_after_impact':None,'mana_after_action':None,'goal_status':'infeasible' if not feasible else 'uncertain'}
        if feasible:
            if action=='activate' and mana[0]<cost[1]:
                entry['feasibility']=None;entry['reason']='activation_feasibility_conflicts_with_mana_bounds'
            else:
                mult=multiplier if action=='activate' else pairs['baseline']
                dealt=(damage[0]*mult[0],damage[1]*mult[1])
                after_hp=(hp[0]-dealt[1],hp[1]-dealt[0])
                after_mana=(mana[0]-cost[1],mana[1]-cost[0]) if action=='activate' else mana
                hp_goal=_fraction(goal.minimum_hp_after_impact);mana_goal=_fraction(goal.minimum_mana_after_action)
                status='robustly_meets' if after_hp[0]>=hp_goal and after_mana[0]>=mana_goal else (
                    'robustly_fails' if after_hp[1]<hp_goal or after_mana[1]<mana_goal else 'uncertain')
                entry.update(hp_after_impact=_bound(after_hp),mana_after_action=_bound(after_mana),goal_status=status)
        alternatives[action]=entry
    return {'alternatives':alternatives,'timing_coverage':coverage,'protection_start_bounds_ms':_bound(start),
        'protection_end_bounds_ms':_bound(end),'assumptions':list(model.assumptions),
        'hp_semantics':'unclamped_hp_balance_not_death_forecast',
        'interpretation':'unreviewed_assumptions_conditional_scenario',
        'goal':{'minimum_hp_after_impact':goal.minimum_hp_after_impact,'minimum_mana_after_action':goal.minimum_mana_after_action},
        'exemption_reason':'declared_damage_tag_exempt_from_item' if exempt else None},[]


def evaluate_defensive_impact(scope,*,facts,model=None,goal,admission=None,chosen_action=None):
    if (not isinstance(scope,ImpactScope) or not isinstance(goal,ImpactGoal) or not isinstance(facts,tuple)
            or len(facts)>128 or any(not isinstance(f,PrefixFact) for f in facts)):
        raise TypeError('typed immutable bounded defensive impact input required')
    if chosen_action not in (None,'activate','hold'):raise ValueError('chosen action must be separately activate/hold/unknown')
    if model is not None and (not isinstance(model,HistoricalImpactModel) or
            (model.patch,model.item_id,model.threat_id)!=(scope.patch,scope.item_id,scope.threat_id)):
        raise ValueError('foreign historical item/threat/patch model')
    if admission is not None and not isinstance(admission,ImpactAdmission):raise TypeError('portable admission forbidden')
    prefix={}
    for observation in facts:
        if _visible(scope,observation):
            key=observation.fact.predicate
            if key in prefix:raise ValueError('ambiguous current impact operand')
            prefix[key]=observation
    known_model=bool(model and _before(model.available_at,scope.at))
    known_goal=_before(goal.available_at,scope.at)
    ordered=tuple(prefix[key] for key in sorted(prefix))
    analytical={'scope':asdict(scope),'facts':[_features(asdict(f)) for f in ordered],
        'model':_features(asdict(model)) if known_model else None,'goal':_features(asdict(goal)) if known_goal else None}
    input_hash=content_hash(analytical)
    reasons=[];candidate=None
    if not known_model:reasons.append('historical_model_not_known_before_choice')
    if not known_goal:reasons.append('goal_not_known_before_choice')
    if known_model and known_goal:
        try:candidate,reasons=_arithmetic(scope,model,goal,prefix)
        except ValueError as exc:
            if 'arithmetic outside finite bounds' not in str(exc):raise
            reasons=['arithmetic_overflow_or_nonfinite_result']
    bound=bool(admission and admission.scope_hash==content_hash(scope) and admission.input_hash==input_hash
        and model is not None and admission.model_hash==content_hash(model) and admission.goal_hash==content_hash(goal)
        and admission.fact_hashes==frozenset(f.input_hash for f in ordered))
    if not bound:reasons.append('independent_exact_scope_input_model_goal_fact_receipt_review_missing')
    verdict='unknown'
    choice_bound=bool(bound and chosen_action is not None and admission.chosen_action_sources
        and admission.chosen_action_binding_hash==chosen_action_binding_hash(input_hash,chosen_action,admission.chosen_action_sources))
    if candidate and bound:
        statuses={a:v['goal_status'] for a,v in candidate['alternatives'].items()}
        if all(s=='robustly_meets' for s in statuses.values()):verdict='both_actions_meet_goal'
        elif all(s=='robustly_fails' for s in statuses.values()):verdict='both_actions_fail_goal'
        elif choice_bound and statuses[chosen_action]=='robustly_fails' and statuses['hold' if chosen_action=='activate' else 'activate']=='robustly_meets':
            verdict='chosen_action_violates_declared_constraints_alternative_robustly_meets'
        elif any(s=='infeasible' for s in statuses.values()):verdict='action_excluded_in_reviewed_feasibility'
        elif 'robustly_meets' in statuses.values() and 'robustly_fails' in statuses.values():
            verdict='alternative_robustly_meets_declared_goal'
        else:verdict='overlapping_or_incomplete_bounds_abstain'
    explanation=['Расчёт ограничен одним заранее известным воздействием и объявленными порогами HP/маны.']
    if candidate:
        for action,entry in candidate['alternatives'].items():
            if entry['hp_after_impact'] is not None:
                h,m=entry['hp_after_impact'],entry['mana_after_action']
                explanation.append(f"{action}: баланс HP {h['minimum']}…{h['maximum']}; мана {m['minimum']}…{m['maximum']}; {entry['goal_status']}.")
        explanation.append('Баланс HP не прогноз смерти; другие попадания, лечение и стратегическая цена ресурса исключены предположениями.')
    result={'schema_version':'foresight.defensive-impact-review.v1','criterion_version':VERSION,'status':verdict,'verdict':verdict,
        'match_id':scope.match_id,'subject_ref':scope.subject_ref,'observer_ref':scope.observer_ref,'dataset_kind':scope.dataset_kind,
        'scope':asdict(scope),'candidate_arithmetic':candidate,'reason_codes':reasons,'explanation':explanation,
        'input_hash':input_hash,'chosen_action':chosen_action,'chosen_action_status':'separately_reviewed_receipts' if choice_bound else 'supplied_scenario_action_not_observed_choice',
        'chosen_binding_hash':admission.chosen_action_binding_hash if choice_bound else None,
        'evidence_refs':[f.fact.fact_id for f in ordered],'research_only':True,'training_eligible':False,
        'strategic_quality':'not_established','validation_status':'conditional_research_not_certified'}
    result['payload_sha256']=content_hash(result)
    return result


def _exact(data,cls):
    if not isinstance(data,dict) or set(data)!={f.name for f in fields(cls)}:raise ValueError('strict exact DTO fields required')
    return dict(data)


def load_defensive_impact_input(source):
    """Portable proposals contain no outcomes, utility, chosen action or grants."""
    from .batch import strict_json,read_fact
    if not isinstance(source,dict) and Path(source).stat().st_size>1<<20:raise ValueError('bounded impact proposal required')
    data=source if isinstance(source,dict) else strict_json(Path(source).read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or set(data)!={'schema_version','scope','facts','model','goal'} or data['schema_version']!='foresight.defensive-impact-input.v1':
        raise ValueError('strict impact proposal required; admission/outcome/utility is not portable')
    try:
        scope=_exact(data['scope'],ImpactScope);scope['at']=TimeRef(**_exact(scope['at'],TimeRef));scope['item_entity']=EntityRef(**_exact(scope['item_entity'],EntityRef))
        goal=_exact(data['goal'],ImpactGoal);goal['source_refs']=tuple(SourceRef(**_exact(r,SourceRef)) for r in goal['source_refs'])
        goal['available_at']=TimeRef(**_exact(goal['available_at'],TimeRef)) if goal['available_at'] is not None else None
        model=data['model']
        if model is not None:
            model=_exact(model,HistoricalImpactModel);model['source_refs']=tuple(SourceRef(**_exact(r,SourceRef)) for r in model['source_refs'])
            model['available_at']=TimeRef(**_exact(model['available_at'],TimeRef)) if model['available_at'] is not None else None
            for key in ('exempt_tags','assumptions'):
                if not isinstance(model[key],list):raise ValueError('portable immutable lists required')
                model[key]=tuple(model[key])
            model=HistoricalImpactModel(**model)
        if not isinstance(data['facts'],list) or len(data['facts'])>128 or any(not isinstance(f,dict) or set(f)!={'fact','source_record_index'} for f in data['facts']):
            raise ValueError('bounded exact immutable prefix facts required')
        return {'scope':ImpactScope(**scope),'facts':tuple(PrefixFact(read_fact(f['fact']),f['source_record_index']) for f in data['facts']),
            'model':model,'goal':ImpactGoal(**goal)}
    except (TypeError,KeyError,AttributeError,OverflowError) as exc:raise ValueError('malformed typed impact proposal') from exc
