"""Derive defensive feasibility and cue windows from ordered source operands.

There is no outcome, chosen action, utility, or validation switch in this API.
Portable evidence proposes mechanics; only a separately supplied caller-owned
registry can admit exact evidence hashes for conditional research calculations.
No result certifies a Dota mechanic or contributes to training eligibility.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

from dota_coach.evidence.contracts import EntityRef, Fact, SourceRef, TimeRef, content_hash
from dota_coach.evidence.clock_math import verified_bounds, decimal, numeric_interval

VERSION = 'defensive-choice-window.v1'
PREDICATES = frozenset(('self.mana', 'self.alive', 'self.life_state', 'self.control_bits', 'item.entity_index',
    'item.generation', 'item.slot', 'item.mana_cost', 'item.cooldown', 'item.cooldown_frozen',
    'item.cooldown_indefinite', 'item.requires_charges', 'item.charges', 'clock.engine_time',
    'self.cast_range', 'target.distance', 'target.alive', 'target.entity_index', 'target.generation',
    'target.team', 'screen.reaction_cue', 'team.reaction_cue'))


def _finite(value, name, *, nonnegative=True):
    if type(value) not in (int, float) or not math.isfinite(value) or (nonnegative and value < 0):
        raise ValueError(name + ': finite numeric operand required')
    return value


@dataclass(frozen=True)
class PrefixFact:
    fact: Fact
    source_record_index: int

    def __post_init__(self):
        if not isinstance(self.fact, Fact) or type(self.source_record_index) is not int or self.source_record_index < 0:
            raise ValueError('typed fact and exact nonnegative source record required')

    @property
    def input_hash(self):
        return content_hash(self)


@dataclass(frozen=True)
class ChoiceScope:
    match_id: int
    subject_ref: str
    patch: str
    item_id: str
    item_entity: EntityRef | None
    clock_mapping_version: str
    reaction_min_ms: float = 150
    reaction_max_ms: float = 1500
    max_fact_age_ms: float = 1000
    target_entity: EntityRef | None = None
    dataset_kind: str = 'unknown'

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id <= 0 or not all(isinstance(s, str) and s for s in
                (self.subject_ref, self.patch, self.item_id, self.clock_mapping_version)):
            raise ValueError('explicit source subject/item/patch/clock scope required')
        for entity in (self.item_entity, self.target_entity):
            if entity is not None and (not isinstance(entity, EntityRef) or entity.replay_id != f'match:{self.match_id}'):
                raise ValueError('exact entity belongs to another replay')
            if entity is not None and (type(entity.entity_index) is not int or type(entity.generation) is not int):
                raise ValueError('exact integer entity generation required')
        for value in (self.reaction_min_ms, self.reaction_max_ms, self.max_fact_age_ms):
            _finite(value, 'window policy')
        if self.reaction_max_ms < self.reaction_min_ms or self.dataset_kind not in ('replay', 'synthetic', 'unknown'):
            raise ValueError('invalid reaction interval or source kind')


@dataclass(frozen=True)
class ChoiceSample:
    sample_id: str
    at: TimeRef
    prefix_record_index: int
    facts: tuple[PrefixFact, ...]
    paused: bool | None = None
    stable_until: TimeRef | None = None

    def __post_init__(self):
        if not self.sample_id or not isinstance(self.at, TimeRef) or type(self.prefix_record_index) is not int or self.prefix_record_index < 0:
            raise ValueError('sample identity/time/source prefix required')
        if not isinstance(self.facts, tuple) or any(not isinstance(f, PrefixFact) for f in self.facts):
            raise ValueError('immutable typed source facts required')
        if type(self.paused) not in (bool, type(None)) or (self.stable_until is not None and not isinstance(self.stable_until, TimeRef)):
            raise ValueError('explicit pause/stability evidence required')


@dataclass(frozen=True)
class ChoiceCue:
    observation: PrefixFact
    expires_at: TimeRef | None = None
    paused: bool | None = None
    expiry_available_at: TimeRef | None = None
    expiry_source_record_index: int | None = None

    def __post_init__(self):
        if not isinstance(self.observation, PrefixFact) or type(self.paused) not in (bool, type(None)) or (
                self.expires_at is not None and not isinstance(self.expires_at, TimeRef)):
            raise ValueError('typed cue prefix and clock context required')
        if self.expiry_available_at is not None and not isinstance(self.expiry_available_at,TimeRef):
            raise ValueError('typed expiry availability required')
        if self.expiry_source_record_index is not None and (type(self.expiry_source_record_index) is not int or self.expiry_source_record_index<0):
            raise ValueError('exact expiry source record required')


def _known_expiry(cue, sample, scope):
    return bool(cue.expires_at is not None and cue.expiry_available_at is not None
        and cue.expiry_source_record_index is not None and cue.expiry_source_record_index<sample.prefix_record_index
        and cue.expiry_available_at.order_status=='verified'
        and cue.expiry_available_at.clock_mapping_version==scope.clock_mapping_version
        and cue.expiry_available_at.definitely_available_before(sample.at))


@dataclass(frozen=True)
class MechanicalSemantics:
    patch: str
    item_id: str
    method_version: str
    cooldown_encoding: str
    activation_block_mask: int
    target_mode: str
    allowed_slots: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
    allowed_target_teams: tuple[int, ...] = ()
    alive_life_state: int = 0

    def __post_init__(self):
        if not all(isinstance(v, str) and v for v in (self.patch, self.item_id, self.method_version)):
            raise ValueError('versioned mechanic scope required')
        if self.cooldown_encoding not in ('remaining_duration', 'absolute_engine_end_time') or self.target_mode not in ('self', 'unit', 'point'):
            raise ValueError('explicit cooldown/target interpretation required')
        if type(self.activation_block_mask) is not int or self.activation_block_mask < 0:
            raise ValueError('nonnegative interpreted control mask required')
        if type(self.alive_life_state) is not int or self.alive_life_state < 0:
            raise ValueError('explicit interpreted life state required')
        for values in (self.allowed_slots, self.allowed_target_teams):
            if not isinstance(values, tuple) or any(type(v) is not int or v < 0 for v in values) or len(set(values)) != len(values):
                raise ValueError('immutable distinct mechanic values required')


@dataclass(frozen=True)
class EvidenceAdmission:
    """Caller registry, never deserialized from a choice-evidence document.

    Hashes must come from independent review against actual source receipts.
    Even this binding admits only a conditional research calculation; it does
    not implement signatures, a certification authority, or production grants.
    """
    match_id: int
    subject_ref: str
    patch: str
    item_id: str
    fact_hashes: frozenset[str]
    semantic_hashes: frozenset[str]
    review_sources: tuple[SourceRef, ...]
    sample_hashes: frozenset[str] = frozenset()
    cue_hashes: frozenset[str] = frozenset()

    def __post_init__(self):
        if any(not isinstance(h, frozenset) for h in (self.fact_hashes, self.semantic_hashes, self.sample_hashes, self.cue_hashes)):
            raise TypeError('independent registry must contain immutable exact hashes')
        for h in self.fact_hashes | self.semantic_hashes | self.sample_hashes | self.cue_hashes:
            if not isinstance(h, str) or len(h) != 64 or any(c not in '0123456789abcdef' for c in h):
                raise ValueError('exact content digest required')
        if not isinstance(self.review_sources, tuple) or not self.review_sources or any(not isinstance(s, SourceRef) for s in self.review_sources):
            raise ValueError('independent source review receipts required')


def _bounds(t, clock):
    return verified_bounds(t,clock)


def _readable_fact(fact,at,clock):
    return bool(fact.status in ('observed','derived')
        and _bounds(at,clock) and _bounds(fact.valid_at,clock) and _bounds(fact.available_at,clock)
        and fact.valid_at.definitely_available_before(at)
        and fact.available_at.definitely_available_before(at)
        and fact.valid_at.definitely_available_before(fact.available_at))


def _registry(scope, admission):
    if admission is None:
        return None
    if not isinstance(admission, EvidenceAdmission):
        raise TypeError('portable strings/dictionaries cannot grant evidence admission')
    if (admission.match_id, admission.subject_ref, admission.patch, admission.item_id) != (
            scope.match_id, scope.subject_ref, scope.patch, scope.item_id):
        raise ValueError('foreign admission registry scope')
    return admission


def _sample_facts(scope, sample):
    result = {}
    for observation in sample.facts:
        fact = observation.fact
        if fact.subject_ref != scope.subject_ref or fact.observer_ref != scope.subject_ref or fact.perspective == 'world':
            raise ValueError('world/foreign subject or observer forbidden')
        if fact.predicate not in PREDICATES or fact.predicate in ('screen.reaction_cue', 'team.reaction_cue'):
            raise ValueError('feasibility operand allowlist required')
        if fact.predicate in result:
            raise ValueError('duplicate source operand')
        if observation.source_record_index >= sample.prefix_record_index:
            raise ValueError('future or equal-prefix source fact forbidden')
        available, at = _bounds(fact.available_at, scope.clock_mapping_version), _bounds(sample.at, scope.clock_mapping_version)
        valid = _bounds(fact.valid_at, scope.clock_mapping_version)
        if at and any(b and b[0] > at[1] for b in (available, valid)):
            raise ValueError('future temporal observation contradicts prefix')
        # Ambiguous future availability does not enter candidate arithmetic.
        readable = _readable_fact(fact,sample.at,scope.clock_mapping_version)
        result[fact.predicate] = (observation, readable)
    return result


def _prefix_projection(value):
    result=asdict(value)
    # Whole-artifact digests are retained in the evidence registry. Analytical
    # features bind only the source locator and the observed prefix operand.
    result['fact'].pop('fact_id',None)
    result['fact'].pop('derived_from',None)
    result['fact']['source_refs']=[{k:s[k] for k in ('provider','schema_version','locator','extractor_version')}
        for s in result['fact']['source_refs']]
    return result


def _sample_projection(value):
    result=asdict(value)
    result.pop('sample_id',None)
    result['facts']=[_prefix_projection(f) for f in value.facts
        if _readable_fact(f.fact,value.at,value.at.clock_mapping_version)]
    result['stable_until']=None  # an unproven later endpoint is not a prefix feature
    return result


def _cue_projection(value, sample=None, scope=None):
    result=asdict(value)
    result['observation']=_prefix_projection(value.observation)
    if sample is not None and scope is not None and not _readable_fact(value.observation.fact,sample.at,scope.clock_mapping_version):
        fact=value.observation.fact
        return {'observation':{'source_record_index':value.observation.source_record_index,
            'fact':{key:getattr(fact,key) for key in ('subject_ref','predicate','perspective','observer_ref')}},
            'status':'temporally_unreadable_cue'}
    if sample is not None and not _known_expiry(value,sample,scope):
        for key in ('expires_at','expiry_available_at','expiry_source_record_index'):result[key]=None
    return result


def derive_feasibility(scope: ChoiceScope, sample: ChoiceSample, *, semantics: MechanicalSemantics | None = None,
                       admission: EvidenceAdmission | None = None) -> dict:
    """Compute conjunction/disproof from operands; no precomputed feasible flag."""
    if not isinstance(scope, ChoiceScope) or not isinstance(sample, ChoiceSample):
        raise TypeError('typed scope/sample required')
    registry = _registry(scope, admission)
    if semantics is not None and (not isinstance(semantics, MechanicalSemantics) or
            (semantics.patch, semantics.item_id) != (scope.patch, scope.item_id)):
        raise ValueError('mechanics belong to another historical scope')
    facts = _sample_facts(scope, sample)
    mechanic_admitted = bool(registry and semantics and content_hash(semantics) in registry.semantic_hashes)
    at_bounds = _bounds(sample.at, scope.clock_mapping_version)
    def raw(predicate):
        row = facts.get(predicate)
        return row[0].fact.value if row and row[1] else None
    def number(predicate):
        value = raw(predicate)
        return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
    def integer(predicate):
        value = raw(predicate)
        if isinstance(value, str) and value.isdecimal():
            value = int(value)
        return value if type(value) is int and value >= 0 else None
    def boolean(predicate):
        value = raw(predicate)
        return value if type(value) is bool else None
    def admitted(predicate):
        row = facts.get(predicate)
        if not registry or not row or not row[1] or row[0].input_hash not in registry.fact_hashes or not at_bounds:
            return False
        fact = row[0].fact
        valid = _bounds(fact.valid_at, scope.clock_mapping_version)
        return bool(valid and sample.at.order_status == 'verified' and fact.valid_at.order_status == 'verified'
            and fact.valid_at.definitely_available_before(sample.at)
            and fact.available_at is not None and fact.available_at.order_status == 'verified'
            and fact.available_at.definitely_available_before(sample.at)
            and fact.valid_at.definitely_available_before(fact.available_at)
            and 0 <= at_bounds[1] - valid[0] <= decimal(scope.max_fact_age_ms))
    conditions = []
    def condition(name, predicates, candidate, *, interpreted=False):
        refs = [facts[p][0] for p in predicates if p in facts and facts[p][1]]
        accepted = bool(registry and content_hash(sample) in registry.sample_hashes
            and all(admitted(p) for p in predicates) and (not interpreted or mechanic_admitted))
        conditions.append({'code': name, 'candidate_value': candidate, 'value': candidate if accepted else None,
            'status': 'conditional_research_admitted' if accepted and candidate is not None else 'unknown',
            'operand_fact_ids': [f.fact.fact_id for f in refs], 'source_record_indices': [f.source_record_index for f in refs],
            'reason_codes': [] if accepted and candidate is not None else [
                'mechanic_not_independently_bound' if interpreted and not mechanic_admitted else 'operand_missing_stale_unavailable_or_unreviewed']})
    index, generation = integer('item.entity_index'), integer('item.generation')
    exact = None if scope.item_entity is None or index is None or generation is None else (
        index, generation) == (scope.item_entity.entity_index, scope.item_entity.generation)
    condition('exact_item_generation', ('item.entity_index', 'item.generation'), exact)
    alive = boolean('self.alive')
    life_state = integer('self.life_state')
    alive_predicates = ('self.alive',) if 'self.alive' in facts else ('self.life_state',)
    if 'self.alive' not in facts and life_state is not None and semantics:
        alive = life_state == semantics.alive_life_state
    condition('subject_alive', alive_predicates, alive, interpreted='self.alive' not in facts)
    mana, cost = number('self.mana'), number('item.mana_cost')
    condition('mana_covers_exact_item_cost', ('self.mana', 'item.mana_cost'), mana >= cost if mana is not None and cost is not None else None)
    slot = integer('item.slot')
    condition('interpreted_inventory_slot', ('item.slot',), slot in semantics.allowed_slots if slot is not None and semantics else None, interpreted=True)
    bits = integer('self.control_bits')
    condition('interpreted_control_allows_activation', ('self.control_bits',), bits & semantics.activation_block_mask == 0 if bits is not None and semantics else None, interpreted=True)
    cooldown, engine = number('item.cooldown'), number('clock.engine_time')
    ready = None
    cooldown_predicates = ('item.cooldown', 'item.cooldown_frozen', 'item.cooldown_indefinite')
    if semantics and cooldown is not None:
        if semantics.cooldown_encoding == 'remaining_duration':
            ready = cooldown <= 0
        else:
            cooldown_predicates += ('clock.engine_time',)
            ready = cooldown <= engine if engine is not None else None
    frozen, indefinite = boolean('item.cooldown_frozen'), boolean('item.cooldown_indefinite')
    if ready is not None:
        ready = False if frozen is True or indefinite is True else (ready if frozen is False and indefinite is False else None)
    condition('interpreted_cooldown_allows_activation', cooldown_predicates, ready, interpreted=True)
    requires, charges = boolean('item.requires_charges'), integer('item.charges')
    charge_predicates = ('item.requires_charges',) + (('item.charges',) if requires is True else ())
    charge_ready = True if requires is False else charges > 0 if requires is True and charges is not None else None
    condition('interpreted_charges_available', charge_predicates, charge_ready, interpreted=True)
    target_predicates, target_ready = (), None
    if semantics and semantics.target_mode == 'self':
        target_predicates, target_ready = alive_predicates, alive
    elif semantics and semantics.target_mode in ('unit', 'point'):
        distance, cast_range = number('target.distance'), number('self.cast_range')
        target_predicates = ('target.distance', 'self.cast_range')
        target_ready = distance <= cast_range if distance is not None and cast_range is not None else None
        if semantics.target_mode == 'unit':
            target_predicates += ('target.entity_index', 'target.generation', 'target.alive', 'target.team')
            target = scope.target_entity
            target_checks = (None if target is None or integer('target.entity_index') is None or integer('target.generation') is None else (integer('target.entity_index'), integer('target.generation')) ==
                             (target.entity_index, target.generation), boolean('target.alive'),
                             integer('target.team') in semantics.allowed_target_teams if integer('target.team') is not None else None)
            if False in target_checks:
                target_ready = False
            elif target_ready is None or None in target_checks:
                target_ready = None
    condition('interpreted_target_constraints', target_predicates, target_ready, interpreted=True)
    def aggregate(key):
        values = [c[key] for c in conditions]
        return 'infeasible' if False in values else 'feasible' if all(v is True for v in values) else 'unknown'
    status = aggregate('value')
    references = tuple(dict.fromkeys(s for row, readable in facts.values() if readable for s in row.fact.source_refs))
    derived = Fact('choice-feasibility:' + content_hash((asdict(scope), sample.sample_id, conditions)),
        scope.subject_ref, 'self.activation_feasible', True if status == 'feasible' else False if status == 'infeasible' else None,
        'derived' if status != 'unknown' else 'unknown', sample.at, sample.at if status != 'unknown' else None,
        'screen', references if status != 'unknown' else (), tuple(f.fact.fact_id for f, readable in facts.values() if readable),
        scope.subject_ref, VERSION, ('conditional_research_not_certified',),
        'source_operands_or_independent_semantic_review_missing' if status == 'unknown' else None)
    result = {'schema_version': 'foresight.derived-feasibility.v1', 'sample_id': sample.sample_id,
        'feasibility': status, 'candidate_feasibility': aggregate('candidate_value'), 'conditions': conditions,
        'mana_after_cost_arithmetic': mana - cost if mana is not None and cost is not None else None,
        'derived_fact': asdict(derived), 'semantic_hash': content_hash(semantics) if semantics else None,
        'validation_status': 'conditional_research_not_certified', 'training_eligible': False,
        'reason_codes': sorted({r for c in conditions for r in c['reason_codes']})}
    result['input_hash'] = content_hash({'scope': asdict(scope), 'sample': _sample_projection(sample),
        'semantics': asdict(semantics) if semantics else None, 'admitted_operand_hashes': sorted(
            content_hash(_prefix_projection(f)) for f, _ in facts.values() if admitted(f.fact.predicate)), 'mechanic_admitted': mechanic_admitted})
    return result


def resolve_choice_windows(scope: ChoiceScope, samples: tuple[ChoiceSample, ...], cues: tuple[ChoiceCue, ...], *,
                           semantics: MechanicalSemantics | None = None, admission: EvidenceAdmission | None = None) -> dict:
    """Resolve sampled choice regions without assuming stability between samples."""
    registry = _registry(scope, admission)
    if not isinstance(samples, tuple) or not isinstance(cues, tuple) or any(not isinstance(c, ChoiceCue) for c in cues):
        raise TypeError('immutable typed samples/cues required')
    if len({s.sample_id for s in samples}) != len(samples) or any(
            a.prefix_record_index >= b.prefix_record_index for a, b in zip(samples, samples[1:])):
        raise ValueError('distinct monotonically ordered sample prefixes required')
    for a, b in zip(samples, samples[1:]):
        left, right = _bounds(a.at, scope.clock_mapping_version), _bounds(b.at, scope.clock_mapping_version)
        if left and right and left[0] > right[1]:
            raise ValueError('sample clock regressed across supplied stream')
    normalized_cues = []
    for cue in cues:
        f = cue.observation.fact
        if f.subject_ref != scope.subject_ref or f.observer_ref != scope.subject_ref or f.perspective == 'world':
            raise ValueError('foreign/world cue forbidden')
        if f.predicate not in ('screen.reaction_cue', 'team.reaction_cue') or f.perspective not in ('screen', 'team'):
            raise ValueError('own screen/team cue allowlist required')
        if f.status not in ('unknown', 'conflict') and type(f.value) is not bool:
            raise ValueError('cue observation must be boolean or unknown')
        if (f.predicate == 'screen.reaction_cue') != (f.perspective == 'screen'):
            raise ValueError('team fact cannot self-promote into screen cue')
        normalized_cues.append(cue)
    if len({c.observation.fact.fact_id for c in cues}) != len(cues):
        raise ValueError('distinct cue identities required')
    windows, summaries = [], []
    for sample in samples:
        feasibility = derive_feasibility(scope, sample, semantics=semantics, admission=registry)
        summaries.append(feasibility)
        at = _bounds(sample.at, scope.clock_mapping_version)
        visible = [c for c in normalized_cues if c.observation.source_record_index < sample.prefix_record_index
            and at and _bounds(c.observation.fact.available_at,scope.clock_mapping_version)
            and c.observation.fact.available_at.definitely_available_before(sample.at)]
        if not visible:
            windows.append({'window_id': 'choice:' + content_hash((asdict(scope), _sample_projection(sample), 'cue_missing')),
                'sample_id': sample.sample_id, 'cue_id': None, 'status': 'unknown',
                'reason_codes': ['sample_clock_unresolved_or_unverified' if not at else 'reaction_cue_not_observed_in_prefix'], 'feasibility': feasibility['feasibility'],
                'guaranteed_interval_ms': None, 'possible_interval_ms': None, 'training_eligible': False})
        for cue in visible:
            f = cue.observation.fact
            readable_cue=_readable_fact(f,sample.at,scope.clock_mapping_version)
            cue_value=f.value if readable_cue else None
            available = _bounds(f.available_at, scope.clock_mapping_version) if readable_cue else None
            valid = _bounds(f.valid_at, scope.clock_mapping_version)
            expiry_known = _known_expiry(cue,sample,scope)
            expiry = _bounds(cue.expires_at, scope.clock_mapping_version) if expiry_known else None
            possible = guaranteed = None
            reasons = []
            if available:
                possible = [available[0] + decimal(scope.reaction_min_ms), available[1] + decimal(scope.reaction_max_ms)]
                guaranteed = [available[1] + decimal(scope.reaction_min_ms), available[0] + decimal(scope.reaction_max_ms)]
                if expiry:
                    possible[1], guaranteed[1] = min(possible[1], expiry[1]), min(guaranteed[1], expiry[0])
                if expiry_known and expiry is None:
                    reasons.append('cue_expiry_clock_unresolved')
                if not expiry_known:
                    reasons.append('cue_expiry_not_known_in_prefix')
            else:
                reasons.append('cue_availability_clock_unresolved')
            temporal = 'unknown'
            if at and possible:
                if at[1] < possible[0] or at[0] > possible[1]:
                    temporal = 'excluded'
                    reasons.append('outside_possible_reaction_interval')
                elif guaranteed and at[0] >= guaranteed[0] and at[1] <= guaranteed[1] and guaranteed[0] <= guaranteed[1]:
                    temporal = 'inside_guaranteed_interval'
                else:
                    reasons.append('clock_uncertainty_overlaps_choice_boundary')
            if cue_value is not True or f.status not in ('observed', 'derived'):
                reasons.append('cue_absent_unknown_or_conflicting')
            if f.perspective != 'screen':
                reasons.append('team_knowledge_does_not_establish_screen_cue')
            if not valid or not at or not f.valid_at.definitely_available_before(sample.at):
                reasons.append('cue_validity_not_established_before_sample')
            if f.valid_at.order_status != 'verified' or (expiry_known and cue.expires_at.order_status != 'verified'):
                reasons.append('cue_validity_or_expiry_order_unverified')
            if sample.paused is not False or cue.paused is not False:
                reasons.append('paused_or_unknown_clock_cannot_measure_reaction_latency')
            cue_admitted = bool(registry and readable_cue and cue.observation.input_hash in registry.fact_hashes
                and content_hash(cue) in registry.cue_hashes and content_hash(sample) in registry.sample_hashes
                and f.perspective == 'screen' and f.available_at is not None and f.available_at.order_status == 'verified'
                and f.valid_at.order_status == 'verified'
                and at and available and valid and f.valid_at.definitely_available_before(sample.at)
                and f.available_at.definitely_available_before(sample.at)
                and f.valid_at.definitely_available_before(f.available_at))
            if not cue_admitted:
                reasons.append('cue_not_independently_bound')
            state = 'unknown'
            temporal_admissible = sample.paused is False and cue.paused is False and not any(r in reasons for r in (
                'cue_expiry_clock_unresolved','cue_expiry_not_known_in_prefix','cue_validity_or_expiry_order_unverified'))
            if cue_admitted and ((temporal == 'excluded' and temporal_admissible) or f.value is False or feasibility['feasibility'] == 'infeasible'):
                state = 'excluded'
            elif cue_admitted and temporal == 'inside_guaranteed_interval' and not reasons and feasibility['feasibility'] == 'feasible':
                state = 'supported_choice'
            if feasibility['feasibility'] == 'unknown':
                reasons.append('feasibility_requirements_unresolved')
            # This is a supported sampled step, never an inferred uninterrupted window.
            windows.append({'window_id': 'choice:' + content_hash((asdict(scope), _sample_projection(sample), _cue_projection(cue,sample,scope), feasibility['input_hash'])),
                'sample_id': sample.sample_id, 'cue_id': f.fact_id, 'status': state,
                'temporal_status': temporal, 'reason_codes': sorted(set(reasons)),
                'feasibility': feasibility['feasibility'], 'candidate_feasibility': feasibility['candidate_feasibility'],
                'guaranteed_interval_ms': numeric_interval(guaranteed,guaranteed=True),
                'possible_interval_ms': numeric_interval(possible,guaranteed=False),
                'stability': 'sampled_step_only_not_interpolated', 'training_eligible': False})
    result = {'schema_version': 'foresight.choice-windows.v1', 'scope': asdict(scope), 'policy_status': 'explicit_research_policy',
        'sample_count': len(samples), 'cue_count': len(cues), 'feasibility_samples': summaries, 'windows': windows,
        'supported_choice_count': sum(w['status'] == 'supported_choice' for w in windows),
        'excluded_count': sum(w['status'] == 'excluded' for w in windows),
        'unknown_count': sum(w['status'] == 'unknown' for w in windows),
        'game_opportunity_coverage': None, 'validation_status': 'conditional_research_not_certified',
        'training_eligible': False, 'strategic_quality': 'not_established'}
    result['payload_sha256'] = content_hash(result)
    return result


def load_choice_evidence(source: str | Path | dict) -> dict:
    """Load portable proposals. Admission and outcome/utility fields are forbidden."""
    from dota_coach.decisions.batch import strict_json
    payload = source if isinstance(source, dict) else strict_json(Path(source).read_text(encoding='utf-8-sig'))
    required = {'schema_version', 'scope', 'semantics', 'cues'}
    if not isinstance(payload, dict) or not required <= payload.keys() or payload.keys()-required-{'samples'} or payload['schema_version'] != 'foresight.choice-evidence.v1':
        raise ValueError('strict choice evidence schema required; caller admission is not portable')
    def time(value):
        return TimeRef(**value) if value is not None else None
    def prefix(value):
        if not isinstance(value,dict) or set(value) != {'fact', 'source_record_index'}:
            raise ValueError('strict prefix-fact schema required')
        f = dict(value['fact'])
        f['valid_at'], f['available_at'] = time(f['valid_at']), time(f.get('available_at'))
        f['source_refs'] = tuple(SourceRef(**s) for s in f['source_refs'])
        for key in ('derived_from', 'quality_flags'):
            f[key] = tuple(f.get(key, ()))
        return PrefixFact(Fact(**f), value['source_record_index'])
    if not isinstance(payload['scope'],dict) or not isinstance(payload['cues'],list) or payload['semantics'] is not None and not isinstance(payload['semantics'],dict):
        raise ValueError('typed scope, cue array and mechanic proposal required')
    scope = dict(payload['scope'])
    for key in ('item_entity', 'target_entity'):
        if scope.get(key) is not None:
            scope[key] = EntityRef(**scope[key])
    mechanics = payload['semantics']
    if mechanics is not None:
        mechanics = dict(mechanics)
        for key in ('allowed_slots', 'allowed_target_teams'):
            if key in mechanics:
                mechanics[key] = tuple(mechanics[key])
        mechanics = MechanicalSemantics(**mechanics)
    cues = []
    for cue in payload['cues']:
        if not isinstance(cue,dict) or set(cue) - {'observation', 'expires_at', 'paused','expiry_available_at','expiry_source_record_index'} or 'observation' not in cue:
            raise ValueError('strict cue schema required')
        cues.append(ChoiceCue(prefix(cue['observation']), time(cue.get('expires_at')), cue.get('paused'),
            time(cue.get('expiry_available_at')),cue.get('expiry_source_record_index')))
    result = {'scope': ChoiceScope(**scope), 'semantics': mechanics, 'cues': tuple(cues)}
    if 'samples' in payload:
        if not isinstance(payload['samples'], list):
            raise ValueError('typed sample array required')
        samples=[]
        for sample in payload['samples']:
            if not isinstance(sample,dict) or not {'sample_id','at','prefix_record_index','facts'} <= sample.keys() or sample.keys()-{'sample_id','at','prefix_record_index','facts','paused','stable_until'}:
                raise ValueError('strict source sample schema required')
            samples.append(ChoiceSample(sample['sample_id'],time(sample['at']),sample['prefix_record_index'],
                tuple(prefix(f) for f in sample['facts']),sample.get('paused'),time(sample.get('stable_until'))))
        result['samples']=tuple(samples)
    return result


def choice_evidence_record(scope, sample, cues, semantics, *, replay_sha256, split='development'):
    """Exact reviewed input: only cues from earlier callback records are included."""
    from dota_coach.validation.contracts import DatasetRecord
    prefix=tuple(c for c in cues if c.observation.source_record_index<sample.prefix_record_index)
    digest=content_hash({'scope':asdict(scope),'sample':asdict(sample),
        'cues':[asdict(c) for c in prefix],'semantics':asdict(semantics) if semantics else None})
    return DatasetRecord(sample.sample_id,digest,scope.match_id,replay_sha256,
        scope.subject_ref,scope.patch,split,scope.dataset_kind,(scope.subject_ref,))


def resolve_reviewed_choice_admission(scope, samples, cues, semantics, *, replay_sha256, records, annotations):
    """Bind extraction consensus to exact inputs, never a portable verified flag.

    Fact checks also cover the sampled clock/pause context, cue expiry and
    historical interpretation. Declared human identities do not certify people
    or their client access; the resulting calculations remain research.
    """
    from dota_coach.validation.pipeline import validate_annotations
    records,annotations=tuple(records),tuple(annotations)
    validate_annotations(annotations,records)
    by_id={r.decision_id:r for r in records}
    latest={}
    for label in annotations:
        if label.review_pass!='extraction':
            continue
        key=(label.decision_id,label.annotator_id)
        if key not in latest or label.annotation_version>latest[key].annotation_version:
            latest[key]=label
    facts=set();mechanics=set();sample_hashes=set();cue_hashes=set();review_refs={}
    for sample in samples:
        record=by_id.get(sample.sample_id)
        if record is None:
            continue
        expected=choice_evidence_record(scope,sample,cues,semantics,replay_sha256=replay_sha256,split=record.split)
        if record!=expected:
            raise ValueError('choice review bound to another sample, replay, patch or subject')
        labels=[a for (decision,_),a in latest.items() if decision==sample.sample_id and a.dataset_kind=='replay' and a.annotator_kind=='human_expert']
        def agreed(fid):
            votes=[c for a in labels for c in a.facts_checked if c.fact_id==fid]
            return len(votes)>=2 and all(c.correctness=='correct' and c.availability=='available' for c in votes)
        for f in sample.facts:
            if agreed(f.fact.fact_id):facts.add(f.input_hash)
        sh=content_hash(sample)
        if agreed('sample:'+sh):sample_hashes.add(sh)
        if semantics is not None and agreed('mechanics:'+content_hash(semantics)):
            mechanics.add(content_hash(semantics))
        for cue in cues:
            if cue.observation.source_record_index>=sample.prefix_record_index:
                continue
            ch=content_hash(cue)
            if agreed(cue.observation.fact.fact_id):facts.add(cue.observation.input_hash)
            if agreed('cue:'+ch):cue_hashes.add(ch)
        for a in labels:
            h=a.annotation_hash
            review_refs[h]=SourceRef('review:'+h,h,'declared_independent_extraction_review',
                a.schema_version,a.decision_id+':'+a.annotator_id,'exact-choice-input-review.v1')
    if not review_refs:
        return None
    return EvidenceAdmission(scope.match_id,scope.subject_ref,scope.patch,scope.item_id,
        frozenset(facts),frozenset(mechanics),tuple(review_refs.values()),
        frozenset(sample_hashes),frozenset(cue_hashes))


def resolve_resource_choice_windows(action_states: dict, extraction, *, scope: ChoiceScope | None = None,
                                   cues: tuple[ChoiceCue, ...] = (), semantics: MechanicalSemantics | None = None,
                                   admission: EvidenceAdmission | None = None,
                                   item_id: str = 'item_black_king_bar') -> dict:
    """Adapt all existing own inventory frames, preserving raw source limitations.

    Default reaction/freshness numbers are labelled research policy, never replay
    observations. Missing clock uncertainty, cue, semantic review and cast target
    retain unknown. No combat success or future outcome participates in selection.
    """
    from dota_coach.decisions.opportunity_discovery import discover_resource_opportunities
    discovery = discover_resource_opportunities(action_states, extraction)
    binding = discovery['source_binding']
    subject = f"account:{binding['account_id']}"
    timeline = action_states['timeline']
    if scope is None:
        # A first matching member found later in the whole trace cannot define
        # the identity of an earlier decision. Exact intended entity is supplied
        # with a reviewed choice scope; raw samples retain their own operands.
        scope = ChoiceScope(binding['match_id'], subject, 'unknown', item_id, None,
            'trace.prefix_clock/unverified', dataset_kind=binding['dataset_kind'])
    if (scope.match_id, scope.subject_ref, scope.item_id, scope.dataset_kind) != (
            binding['match_id'], subject, item_id, binding['dataset_kind']):
        raise ValueError('choice scope does not bind the actual own source')
    samples = []
    raw_map = {'self.mana': 'm_flMana', 'self.life_state': 'm_lifeState', 'self.control_bits': 'm_nUnitState64'}
    item_map = {'item.mana_cost': 'm_iManaCost', 'item.cooldown': 'm_fCooldown',
        'item.cooldown_frozen': 'm_bFrozenCooldown', 'item.cooldown_indefinite': 'm_bInIndefiniteCooldown',
        'item.requires_charges': 'm_bRequiresCharges', 'item.charges': 'm_iCurrentCharges'}
    for raw_sample, discovered in zip(timeline, discovery['samples']):
        game_time = raw_sample.get('game_time')
        at = TimeRef(game_time * 1000 if game_time is not None else None,
                     raw_sample.get('sampled_net_tick'), uncertainty_ms=None,
                     clock_mapping_version=scope.clock_mapping_version, order_status='unknown')
        facts = []
        def add(predicate, raw_fact):
            value, rid = raw_fact.get('value'), raw_fact.get('source_record_index')
            if value is None or raw_fact.get('status') != 'raw_observed' or type(rid) is not int:
                return
            projection_hash = content_hash({'match_id': scope.match_id, 'subject': subject,
                'predicate': predicate, 'raw_fact': {k: raw_fact.get(k) for k in ('value', 'status', 'source_record_index', 'net_tick')},
                'item_entity': asdict(scope.item_entity) if predicate.startswith('item.') and scope.item_entity else None})
            source = SourceRef('own-prefix:' + projection_hash, projection_hash, 'replay_own_resource_prefix',
                'foresight.action-states.v1', f'record:{rid}/{predicate}', 'raw-field-projection/unverified')
            fact = Fact(discovered['sample_id'] + ':' + predicate, subject, predicate, value, 'observed',
                at, at, 'team', (source,), observer_ref=subject, method_version='raw-field-projection/unverified',
                quality_flags=('extraction_and_screen_availability_unverified',))
            facts.append(PrefixFact(fact, rid))
        own = (raw_sample.get('hero') or {}).get('fields', {})
        for predicate, key in raw_map.items():
            add(predicate, own.get(key, {}))
        candidates = [i for i in raw_sample.get('inventory', []) if i.get('item_id') == scope.item_id
            and i.get('relation_status') == 'resolved_exact_handle']
        if len(candidates) == 1:
            member = candidates[0]
            for predicate, key in item_map.items():
                add(predicate, member.get('fields', {}).get(key, {}))
            handle_fact = member.get('handle_fact', {})
            for predicate, key in (('item.entity_index', 'entity_index'), ('item.generation', 'generation'), ('item.slot', 'slot')):
                add(predicate, handle_fact | {'value': member.get(key)})
        samples.append(ChoiceSample(discovered['sample_id'], at, raw_sample['cutoff_record_index'],
            tuple(facts), raw_sample.get('clock', {}).get('paused')))
    result = resolve_choice_windows(scope, tuple(samples), cues, semantics=semantics, admission=admission)
    result['source_binding'] = binding
    result['source_receipts'] = discovery['source_receipts']
    result['clock_status'] = 'raw_prefix_clock_uncertainty_not_independently_measured'
    result['continuous_window_status'] = 'constraint_transition_stream_not_supplied'
    result['command_attempt_status'] = 'command_channel_not_supplied'
    result['payload_sha256'] = content_hash({k: v for k, v in result.items() if k != 'payload_sha256'})
    return result
