"""Source-local finite mechanical checks. No portable validation or game grants.

Historical rules and clock receipts are caller-owned review inputs. Raw replay
operands never prove their own interpretation, persistence, screen visibility,
or absence of channel restrictions. Every result remains conditional research.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import math
from pathlib import Path

from dota_coach.evidence.clock_math import decimal, numeric_interval, numeric_bound
from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, content_hash
from dota_coach.ingest.constraint_source import MAX_RECORD_BYTES, _apply_changes, inspect_constraint_source
from .batch import strict_json
from .choice_window import ChoiceSample, ChoiceScope, EvidenceAdmission, MechanicalSemantics, PrefixFact, PREDICATES, _bounds, _readable_fact, _prefix_projection, derive_feasibility
from .choice_monitor import monitor_choice_stream

VERSION = 'source-mechanics-adapter.v1'
_VERIFIED_SIDECARS = {}
EXTRA_PREDICATES = frozenset(('action.activated', 'action.enabled', 'action.hidden',
    'action.in_ability_phase', 'self.channeling', 'target.visible', 'target.invulnerable',
    'target.magic_immune', 'target.targetable', 'action.mute_operand',
    'action.enable_operand'))


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


@dataclass(frozen=True)
class RestrictionRule:
    """A finite supplied rule, never an inferred Dota patch default."""
    code: str
    predicate: str
    operator: str
    expected: bool | None = None

    def __post_init__(self):
        if not self.code or self.predicate not in EXTRA_PREDICATES or self.operator not in ('equals_boolean', 'not_after_engine_time', 'nonpositive_numeric'):
            raise ValueError('explicit finite restriction rule required')
        if (self.operator == 'equals_boolean' and type(self.expected) is not bool) or (
                self.operator != 'equals_boolean' and self.expected is not None):
            raise ValueError('typed restriction operand required')


@dataclass(frozen=True)
class HistoricalMechanicsBinding:
    match_id: int
    replay_sha256: str
    game_build: int
    mechanics: MechanicalSemantics
    linked_class: str
    restrictions: tuple[RestrictionRule, ...]
    review_sources: tuple[SourceRef, ...]
    linked_kind: str = 'inventory'
    control_field: str = 'm_nUnitState64'
    charges_field: str = 'm_iCurrentCharges'

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id <= 0 or not _digest(self.replay_sha256) or type(self.game_build) is not int or self.game_build < 0:
            raise ValueError('exact historical match/replay/build binding required')
        if not isinstance(self.mechanics, MechanicalSemantics) or not self.linked_class or self.linked_kind not in ('inventory', 'abilities'):
            raise ValueError('typed mechanics and exact linked class required')
        if self.control_field not in ('m_nUnitState64', 'm_nUnitState') or self.charges_field not in ('m_iCurrentCharges', 'm_nAbilityCurrentCharges'):
            raise ValueError('finite decoded field interpretation required')
        if not isinstance(self.restrictions, tuple) or any(not isinstance(r, RestrictionRule) for r in self.restrictions) or len({r.code for r in self.restrictions}) != len(self.restrictions):
            raise ValueError('immutable distinct restriction rules required')
        if not isinstance(self.review_sources, tuple) or not self.review_sources or any(not isinstance(r, SourceRef) for r in self.review_sources):
            raise ValueError('historical review source receipts required')


@dataclass(frozen=True)
class ClockReceipt:
    source_record_index: int
    at: TimeRef
    clock_operand_hash: str
    paused: bool | None
    source_refs: tuple[SourceRef, ...]

    def __post_init__(self):
        if type(self.source_record_index) is not int or self.source_record_index < 0 or not isinstance(self.at, TimeRef) or not _digest(self.clock_operand_hash):
            raise ValueError('exact clock receipt required')
        if type(self.paused) not in (bool, type(None)) or not isinstance(self.source_refs, tuple) or not self.source_refs or any(not isinstance(r, SourceRef) for r in self.source_refs):
            raise ValueError('clock review sources and explicit pause required')


@dataclass(frozen=True)
class ConstraintClockBinding:
    replay_sha256: str
    mapping_version: str
    receipts: tuple[ClockReceipt, ...]

    def __post_init__(self):
        if not _digest(self.replay_sha256) or not self.mapping_version or not isinstance(self.receipts, tuple) or any(not isinstance(r, ClockReceipt) for r in self.receipts):
            raise ValueError('typed caller-owned clock registry required')
        if any(a.source_record_index >= b.source_record_index for a, b in zip(self.receipts, self.receipts[1:])):
            raise ValueError('ordered unique clock receipts required')
        if any(r.at.clock_mapping_version != self.mapping_version for r in self.receipts):
            raise ValueError('foreign clock mapping')
        if any(a.at.order_status == b.at.order_status == 'verified' and not a.at.definitely_available_before(b.at)
               for a, b in zip(self.receipts, self.receipts[1:])):
            raise ValueError('clock regressed or ordering unresolved')


@dataclass(frozen=True)
class RawMechanicalSample:
    sample: ChoiceSample
    restrictions: tuple[PrefixFact, ...]
    historical_binding_hash: str

    def __post_init__(self):
        if not isinstance(self.sample, ChoiceSample) or not isinstance(self.restrictions, tuple) or any(not isinstance(f, PrefixFact) for f in self.restrictions) or not _digest(self.historical_binding_hash):
            raise ValueError('typed raw mechanical sample required')


@dataclass(frozen=True)
class MechanicalReview:
    """A caller registry, with no loader from editable evidence JSON."""
    choice_admission: EvidenceAdmission
    historical_binding_hashes: frozenset[str]
    restriction_fact_hashes: frozenset[str]
    truth_coverage_hashes: frozenset[str] = frozenset()

    def __post_init__(self):
        if not isinstance(self.choice_admission, EvidenceAdmission) or any(not isinstance(h, frozenset) for h in (self.historical_binding_hashes, self.restriction_fact_hashes, self.truth_coverage_hashes)):
            raise TypeError('caller-owned typed mechanical review required')
        if any(not _digest(h) for h in self.historical_binding_hashes | self.restriction_fact_hashes | self.truth_coverage_hashes):
            raise ValueError('exact reviewed hashes required')


@dataclass(frozen=True)
class MechanicalTruthCoverage:
    """Review witness for all finite interpreted guard and pause transitions.

    This is never generated from callback counts. A separate reviewer binds
    exact projected samples, supplied extra operands and the historical rules.
    The underlying choice monitor still requires its own cue/base coverage.
    """
    historical_binding_hash: str
    sample_hashes: tuple[str, ...]
    extra_operand_hashes: tuple[str, ...]
    start: TimeRef
    end: TimeRef
    available_at: TimeRef
    source_record_index: int
    source_refs: tuple[SourceRef, ...]
    mode: str = 'complete_finite_guard_truth_and_pause_transitions'

    def __post_init__(self):
        if not _digest(self.historical_binding_hash) or any(not isinstance(v, tuple) for v in (self.sample_hashes, self.extra_operand_hashes)) or any(not _digest(h) for h in (*self.sample_hashes, *self.extra_operand_hashes)):
            raise ValueError('exact immutable finite guard witness required')
        if any(not isinstance(t, TimeRef) for t in (self.start, self.end, self.available_at)) or type(self.source_record_index) is not int or self.source_record_index < 0:
            raise ValueError('typed coverage clocks and record required')
        if not isinstance(self.source_refs, tuple) or not self.source_refs or any(not isinstance(r, SourceRef) for r in self.source_refs) or self.mode != 'complete_finite_guard_truth_and_pause_transitions':
            raise ValueError('reviewed truth transition source receipts required')


def _unknown_time(scope, tick=None):
    return TimeRef(None, tick, None, None, scope.clock_mapping_version, 'unknown')


def project_constraint_observation(row, state, *, scope, binding, source_ref, clock_receipts=None, fact_cache=None):
    """Project an already decoded, validated raw observation; no time guessing.

    Targets, channel state, cast range and engine time are intentionally absent
    if this own-state projection does not supply independently bound operands.
    """
    if not isinstance(scope, ChoiceScope) or binding is not None and not isinstance(binding, HistoricalMechanicsBinding):
        raise TypeError('typed scope and historical binding required')
    if binding and (scope.match_id, scope.patch, scope.item_id) != (binding.match_id, binding.mechanics.patch, binding.mechanics.item_id):
        raise ValueError('historical binding differs from choice scope')
    rid = row['source_record_index']
    if type(rid) is not int or rid < 0:
        raise ValueError('exact source record required')
    clocks = {} if clock_receipts is None else clock_receipts
    receipt = clocks.get(rid)
    if receipt and (not isinstance(receipt, ClockReceipt) or receipt.source_record_index != rid or receipt.at.clock_mapping_version != scope.clock_mapping_version):
        raise ValueError('typed exact source clock mapping required')
    if receipt and (receipt.clock_operand_hash != content_hash(state['clock']) or receipt.paused != state['clock'].get('paused')):
        raise ValueError('reviewed clock operands changed')
    at = receipt.at if receipt else _unknown_time(scope, row.get('net_tick'))
    hero = state.get('hero') or {}
    exact = scope.item_entity
    selected = [v for v in state.get(binding.linked_kind if binding else 'inventory', ()) if exact and
        (v.get('entity_index'), v.get('generation')) == (exact.entity_index, exact.generation)
        and (binding is None or v.get('class') == binding.linked_class) and v.get('relation_status') == 'resolved_exact_handle']
    if len(selected) > 1:
        raise ValueError('ambiguous exact linked entity')
    item = selected[0] if selected else {}
    facts, extras = [], []
    def add(predicate, raw, destination=facts):
        raw = raw or {}
        value, record = raw.get('value'), raw.get('source_record_index')
        if record is not None and (type(record) is not int or record < 0 or record > rid):
            raise ValueError('future source operand')
        known = value is not None and type(value) in (str, int, float, bool) and record is not None
        mapped = clocks.get(record) if known else None
        if mapped and (not isinstance(mapped, ClockReceipt) or mapped.source_record_index != record or mapped.at.clock_mapping_version != scope.clock_mapping_version):
            raise ValueError('foreign operand clock receipt')
        key = (type(value), value if type(value) in (str, int, float, bool, type(None)) else None,
               record, raw.get('net_tick'), mapped.at if mapped else None,
               scope.match_id, scope.subject_ref, scope.clock_mapping_version, source_ref)
        cached = fact_cache.get(predicate) if fact_cache is not None else None
        if cached and cached[0] == key:
            destination.append(cached[1])
            return
        t = mapped.at if mapped else _unknown_time(scope, raw.get('net_tick'))
        fid = VERSION + ':' + content_hash((scope.match_id, scope.subject_ref, predicate, record, value))
        fact = Fact(fid, scope.subject_ref, predicate, value if known else None, 'observed' if known else 'unknown',
            t, t if known else None, 'public', (source_ref,) if known else (), observer_ref=scope.subject_ref,
            method_version=VERSION, quality_flags=('raw_semantics_and_availability_require_independent_review',),
            unknown_reason=None if known else 'source_operand_missing')
        observation = PrefixFact(fact, record if record is not None else rid)
        # Missing receipts use the current prefix; never reuse that locator.
        if fact_cache is not None and record is not None:
            fact_cache[predicate] = (key, observation)
        destination.append(observation)
    hf, fields = hero.get('fields', {}), item.get('fields', {})
    for predicate, field in (('self.mana', 'm_flMana'), ('self.life_state', 'm_lifeState'), ('self.control_bits', binding.control_field if binding else 'm_nUnitState64')):
        add(predicate, hf.get(field))
    for predicate, field in (('item.mana_cost', 'm_iManaCost'), ('item.cooldown', 'm_fCooldown'),
            ('item.cooldown_frozen', 'm_bFrozenCooldown'), ('item.cooldown_indefinite', 'm_bInIndefiniteCooldown'),
            ('item.requires_charges', 'm_bRequiresCharges'), ('item.charges', binding.charges_field if binding else 'm_iCurrentCharges')):
        add(predicate, fields.get(field))
    identity_receipt = item.get('handle_fact', {})
    for predicate, key in (('item.entity_index', 'entity_index'), ('item.generation', 'generation'), ('item.slot', 'slot')):
        add(predicate, identity_receipt | {'value': item.get(key)})
    for predicate, field in (('action.activated', 'm_bActivated'), ('action.enabled', 'm_bItemEnabled'),
            ('action.hidden', 'm_bHidden'), ('action.in_ability_phase', 'm_bInAbilityPhase'),
            ('action.mute_operand', 'm_flAbilityMuteDuration'), ('action.enable_operand', 'm_flEnableTime')):
        add(predicate, fields.get(field), extras)
    sample = ChoiceSample(f'raw-mechanics:{scope.match_id}:{rid}', at, rid + 1, tuple(facts), receipt.paused if receipt else None)
    return RawMechanicalSample(sample, tuple(extras), content_hash(binding))


def iter_constraint_samples(path, *, extraction, scope, binding, clock=None):
    """Validate the complete sidecar first, then stream exact delta projections.

    The second pass is hash-checked too. Consumers must exhaust it before using
    the stream as a completed artifact; yielded samples still grant no quality.
    """
    if not isinstance(binding, HistoricalMechanicsBinding) or not isinstance(scope, ChoiceScope):
        raise TypeError('typed historical mechanics and scope required')
    summary = _verified_sidecar(path, extraction)
    if summary['match_id'] != scope.match_id or summary['replay_sha256'] != binding.replay_sha256:
        raise ValueError('foreign sidecar historical binding')
    if extraction.replay.manifest.game_build != str(binding.game_build):
        raise ValueError('historical build differs from extraction manifest')
    if summary.get('expected_account_id') is None or scope.subject_ref != f"account:{summary['expected_account_id']}":
        raise ValueError('exact account-bound sidecar required')
    if clock is not None and (not isinstance(clock, ConstraintClockBinding) or clock.replay_sha256 != binding.replay_sha256 or clock.mapping_version != scope.clock_mapping_version):
        raise ValueError('foreign caller clock binding')
    receipts = {r.source_record_index: r for r in clock.receipts} if clock else {}
    ref = SourceRef('raw-constraints:' + summary['file_sha256'], summary['file_sha256'],
        'replay_own_raw_operands', summary['schema_version'], 'record_index_domain:' + summary['record_index_domain'], VERSION)
    state, digest, fact_cache = None, hashlib.sha256(), {}
    with Path(path).open('rb') as stream:
        while raw := stream.readline(MAX_RECORD_BYTES + 1):
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError('oversized raw constraint record')
            digest.update(raw)
            row = strict_json(raw.decode('utf-8'))
            if row['t'] != 'raw_constraint_observation':
                continue
            if 'projection' in row:
                state = row['projection']
            else:
                _apply_changes(state, row['projection_changes'])
            yield project_constraint_observation(row, state, scope=scope, binding=binding, source_ref=ref, clock_receipts=receipts, fact_cache=fact_cache)
    if digest.hexdigest() != summary['file_sha256']:
        raise ValueError('sidecar changed during projection')


def evaluate_mechanical_sample(scope, raw, *, binding, review=None, extra_operands=()):
    """Conjoin base feasibility and every explicitly supplied restriction rule."""
    if not isinstance(raw, RawMechanicalSample) or not isinstance(binding, HistoricalMechanicsBinding) or raw.historical_binding_hash != content_hash(binding):
        raise ValueError('exact typed historical sample binding required')
    if (scope.match_id, scope.patch, scope.item_id) != (binding.match_id, binding.mechanics.patch, binding.mechanics.item_id):
        raise ValueError('historical binding differs from choice scope')
    if review is not None and not isinstance(review, MechanicalReview):
        raise TypeError('portable validation cannot grant mechanical admission')
    if not isinstance(extra_operands, tuple) or any(not isinstance(f, PrefixFact) for f in extra_operands):
        raise TypeError('typed immutable extra operands required')
    predicates = {}
    base_extra = []
    for f in (*raw.restrictions, *extra_operands):
        if f.fact.predicate in predicates or f.fact.predicate not in EXTRA_PREDICATES | (PREDICATES - {'screen.reaction_cue', 'team.reaction_cue'}):
            raise ValueError('duplicate or nonfinite restriction operand')
        if f.source_record_index >= raw.sample.prefix_record_index or f.fact.subject_ref != scope.subject_ref or f.fact.observer_ref != scope.subject_ref or f.fact.perspective == 'world':
            raise ValueError('future/world/foreign restriction operand')
        sample_bounds = _bounds(raw.sample.at, scope.clock_mapping_version)
        temporal = [_bounds(t, scope.clock_mapping_version) for t in (f.fact.valid_at, f.fact.available_at)]
        if sample_bounds and any(t and t[0] > sample_bounds[1] for t in temporal):
            raise ValueError('future restriction temporal receipt')
        predicates[f.fact.predicate] = f
        if f.fact.predicate not in EXTRA_PREDICATES:
            base_extra.append(f)
    if base_extra:
        from dataclasses import replace
        if {f.fact.predicate for f in base_extra} & {f.fact.predicate for f in raw.sample.facts}:
            raise ValueError('cannot replace raw own operands with supplied facts')
        calculation_sample = replace(raw.sample, facts=raw.sample.facts + tuple(base_extra))
    else:
        calculation_sample = raw.sample
    base = derive_feasibility(scope, calculation_sample, semantics=binding.mechanics, admission=review.choice_admission if review else None)
    conditions = []
    for rule in binding.restrictions:
        operand = predicates.get(rule.predicate)
        value = operand.fact.value if operand and _readable_fact(operand.fact,raw.sample.at,scope.clock_mapping_version) else None
        if operand and (at_bounds := _bounds(raw.sample.at, scope.clock_mapping_version)) and any(
                (b := _bounds(t, scope.clock_mapping_version)) and b[1] > at_bounds[0]
                for t in (operand.fact.valid_at, operand.fact.available_at)):
            value = None
        required = [operand] if operand else []
        if rule.operator == 'equals_boolean':
            candidate = value is rule.expected if type(value) is bool else None
        elif rule.operator == 'nonpositive_numeric':
            candidate = value <= 0 if type(value) in (int, float) and math.isfinite(value) else None
        else:
            engine = predicates.get('clock.engine_time')
            required += [engine] if engine else []
            e = engine.fact.value if engine and _readable_fact(engine.fact,raw.sample.at,scope.clock_mapping_version) else None
            if engine and (at_bounds := _bounds(raw.sample.at, scope.clock_mapping_version)) and any(
                    (b := _bounds(t, scope.clock_mapping_version)) and b[1] > at_bounds[0]
                    for t in (engine.fact.valid_at, engine.fact.available_at)):
                e = None
            candidate = value <= e if all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (value, e)) else None
        accepted = bool(review and content_hash(binding) in review.historical_binding_hashes
            and content_hash(calculation_sample) in review.choice_admission.sample_hashes and operand
            and len(required) == (2 if rule.operator == 'not_after_engine_time' else 1))
        for f in required:
            t, available = f.fact.valid_at, f.fact.available_at
            accepted = bool(accepted and f.input_hash in review.restriction_fact_hashes and t.order_status == 'verified'
                and available is not None and available.order_status == 'verified' and raw.sample.at.order_status == 'verified'
                and t.definitely_available_before(raw.sample.at) and available.definitely_available_before(raw.sample.at)
                and t.definitely_available_before(available)
                and t.game_time_ms is not None and t.uncertainty_ms is not None and raw.sample.at.game_time_ms is not None
                and raw.sample.at.uncertainty_ms is not None and _bounds(raw.sample.at,scope.clock_mapping_version) is not None
                and _bounds(t,scope.clock_mapping_version) is not None
                and 0 <= _bounds(raw.sample.at,scope.clock_mapping_version)[1] - _bounds(t,scope.clock_mapping_version)[0] <= decimal(scope.max_fact_age_ms))
        conditions.append({'code': rule.code, 'candidate_value': candidate, 'value': candidate if accepted else None,
            'operand_fact_ids': [f.fact.fact_id for f in required if _readable_fact(f.fact,raw.sample.at,scope.clock_mapping_version)], 'reason_codes': [] if accepted and candidate is not None else ['restriction_semantics_operand_or_clock_unreviewed_or_missing']})
    def conjunction(status, values):
        return 'infeasible' if status == 'infeasible' or False in values else 'feasible' if status == 'feasible' and all(v is True for v in values) else 'unknown'
    result = {'schema_version': 'foresight.mechanical-feasibility.v1', 'sample_id': raw.sample.sample_id,
        'feasibility': conjunction(base['feasibility'], [c['value'] for c in conditions]),
        'candidate_feasibility': conjunction(base['candidate_feasibility'], [c['candidate_value'] for c in conditions]),
        'base': base, 'restrictions': conditions, 'historical_binding_hash': content_hash(binding),
        'validation_status': 'conditional_research_not_certified', 'strategic_quality': 'not_established', 'training_eligible': False}
    if not review or content_hash(binding) not in review.historical_binding_hashes:
        result['feasibility'] = 'unknown'
    result['prefix_feature_hash'] = content_hash({'base_input_hash': base['input_hash'],
        'rules': [asdict(r) for r in binding.restrictions],
        'restriction_operands': [_prefix_projection(f) for f in (*raw.restrictions, *extra_operands)
            if _readable_fact(f.fact,raw.sample.at,scope.clock_mapping_version)]})
    result['payload_sha256'] = content_hash(result)
    return result


def _verified_sidecar(path, extraction):
    """Reuse source verification only inside this process, never editable JSON.

    Each consuming pass still hashes every byte against the verified digest.
    File metadata is a cache invalidation hint, not an integrity authority.
    """
    source = Path(path).resolve()
    stat = source.stat()
    key = (str(source), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
           content_hash(asdict(extraction)))
    if key not in _VERIFIED_SIDECARS:
        result = inspect_constraint_source(source, extraction=extraction)
        if len(_VERIFIED_SIDECARS) >= 4:
            _VERIFIED_SIDECARS.pop(next(iter(_VERIFIED_SIDECARS)))
        _VERIFIED_SIDECARS[key] = result
    return _VERIFIED_SIDECARS[key]


def summarize_constraint_mechanics(path, *, extraction, account_id,
                                   item_id='item_black_king_bar', limit_examples=3):
    """Bounded default adapter run; no fictitious historical or clock rules.

    All observations are decoded. A linked raw item class/handle is not an
    independently reviewed historical item binding. Examples retain exact
    prefix receipts without expanding the report into a second large sidecar.
    """
    from collections import Counter
    from dota_coach.evidence.contracts import EntityRef
    if type(account_id) is not int or account_id <= 0 or not isinstance(item_id, str) or not item_id:
        raise ValueError('explicit positive account and item required')
    if type(limit_examples) is not int or not 0 <= limit_examples <= 20:
        raise ValueError('bounded example policy required')
    summary = _verified_sidecar(path, extraction)
    if summary.get('expected_account_id') != account_id:
        raise ValueError('mechanical summary requires exact account-bound sidecar')
    source = SourceRef('raw-constraints:' + summary['file_sha256'], summary['file_sha256'],
        'replay_own_raw_operands', summary['schema_version'], summary['record_index_domain'], VERSION)
    counts, examples, state, whole, fact_cache = Counter(), [], None, hashlib.sha256(), {}
    with Path(path).open('rb') as stream:
        while raw := stream.readline(MAX_RECORD_BYTES + 1):
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError('oversized raw constraint record')
            whole.update(raw)
            row = strict_json(raw.decode('utf-8'))
            if row['t'] != 'raw_constraint_observation':
                continue
            if 'projection' in row:
                state = row['projection']
            else:
                _apply_changes(state, row['projection_changes'])
            counts['observations'] += 1
            selected = [v for v in state.get('inventory', ()) if v.get('item_id') == item_id
                and v.get('relation_status') == 'resolved_exact_handle']
            if len(selected) > 1:
                counts['multiple_candidate_item_entities'] += 1
            item = selected[0] if len(selected) == 1 else None
            entity = EntityRef(f"match:{summary['match_id']}", item['entity_index'], item['generation']) if item else None
            scope = ChoiceScope(summary['match_id'], f'account:{account_id}', 'unknown', item_id,
                entity, 'source-mechanics-clock/unverified', dataset_kind=extraction.replay.manifest.dataset_kind)
            sample = project_constraint_observation(row, state, scope=scope, binding=None, source_ref=source, fact_cache=fact_cache)
            counts['projected_samples'] += 1
            counts['raw_exact_linked_item_samples'] += item is not None
            counts['unknown_feasibility_samples'] += 1
            counts['unknown_clock_samples'] += sample.sample.at.game_time_ms is None
            if len(examples) < limit_examples and item:
                examples.append({'source_record_index': row['source_record_index'], 'item_entity': asdict(entity),
                    'sample': asdict(sample.sample), 'restriction_operands': [asdict(f) for f in sample.restrictions],
                    'feasibility': 'unknown', 'clock_status': 'unknown'})
    if whole.hexdigest() != summary['file_sha256']:
        raise ValueError('sidecar changed during mechanical summary')
    result = {'schema_version': 'foresight.constraint-mechanics-summary.v1', 'method_version': VERSION,
        'match_id': summary['match_id'], 'account_id': account_id, 'item_id': item_id,
        'source_file_sha256': summary['file_sha256'], 'trace_sha256': summary['trace_sha256'],
        'replay_sha256': summary['replay_sha256'], 'game_build': extraction.replay.manifest.game_build,
        'counts': dict(counts), 'examples': examples, 'reason_codes': [
            'historical_mechanics_not_independently_bound', 'clock_pause_mapping_not_independently_bound',
            'raw_operand_callbacks_not_certified_truth_transitions', 'channel_target_and_screen_operands_unavailable'],
        'validated_feasibility_count': 0, 'supported_span_count': 0,
        'validation_status': 'conditional_research_not_certified', 'training_eligible': False,
        'strategic_quality': 'not_established', 'game_opportunity_coverage': None}
    result['payload_sha256'] = content_hash(result)
    validate_constraint_mechanics_summary(result)
    return result


def validate_constraint_mechanics_summary(payload):
    """Reject portable promotion of this explicitly unknown default artifact."""
    expected = {'schema_version', 'method_version', 'match_id', 'account_id', 'item_id',
        'source_file_sha256', 'trace_sha256', 'replay_sha256', 'game_build', 'counts', 'examples',
        'reason_codes', 'validated_feasibility_count', 'supported_span_count', 'validation_status',
        'training_eligible', 'strategic_quality', 'game_opportunity_coverage', 'payload_sha256'}
    if not isinstance(payload, dict) or set(payload) != expected or payload.get('schema_version') != 'foresight.constraint-mechanics-summary.v1' or payload.get('method_version') != VERSION:
        raise ValueError('strict mechanical summary schema required')
    if any(not _digest(payload[k]) for k in ('source_file_sha256', 'trace_sha256', 'replay_sha256', 'payload_sha256')) or content_hash({k: v for k, v in payload.items() if k != 'payload_sha256'}) != payload['payload_sha256']:
        raise ValueError('mechanical summary digest mismatch')
    if any(type(payload[k]) is not int or payload[k] <= 0 for k in ('match_id', 'account_id')) or not isinstance(payload['item_id'], str) or not payload['item_id']:
        raise ValueError('mechanical summary scope invalid')
    if any(type(payload[k]) is not int or payload[k] != 0 for k in ('validated_feasibility_count', 'supported_span_count')) or payload['training_eligible'] is not False or payload['validation_status'] != 'conditional_research_not_certified' or payload['strategic_quality'] != 'not_established' or payload['game_opportunity_coverage'] is not None:
        raise ValueError('raw mechanical summary cannot promote game quality')
    counts = payload['counts']
    required = {'observations', 'projected_samples', 'unknown_feasibility_samples', 'unknown_clock_samples'}
    if not isinstance(counts, dict) or not required <= counts.keys() or set(counts) - required - {'raw_exact_linked_item_samples', 'multiple_candidate_item_entities'} or any(type(v) is not int or v < 0 for v in counts.values()) or len({counts[k] for k in required}) != 1:
        raise ValueError('unknown projection counts invalid')
    if any(counts.get(k, 0) > counts['observations'] for k in ('raw_exact_linked_item_samples', 'multiple_candidate_item_entities')):
        raise ValueError('raw mechanical summary census invalid')
    if not isinstance(payload['examples'], list) or len(payload['examples']) > 20:
        raise ValueError('bounded mechanical examples required')
    if payload['reason_codes'] != ['historical_mechanics_not_independently_bound', 'clock_pause_mapping_not_independently_bound', 'raw_operand_callbacks_not_certified_truth_transitions', 'channel_target_and_screen_operands_unavailable']:
        raise ValueError('raw mechanical limitations cannot be removed')
    last = -1
    for example in payload['examples']:
        if not isinstance(example, dict) or set(example) != {'source_record_index', 'item_entity', 'sample', 'restriction_operands', 'feasibility', 'clock_status'} or example['feasibility'] != 'unknown' or example['clock_status'] != 'unknown':
            raise ValueError('raw mechanical example cannot promote feasibility')
        rid = example['source_record_index']
        sample, entity = example['sample'], example['item_entity']
        if type(rid) is not int or rid <= last or not isinstance(entity, dict) or set(entity) != {'replay_id', 'entity_index', 'generation'} or entity['replay_id'] != f"match:{payload['match_id']}" or any(type(entity[k]) is not int or entity[k] < 0 for k in ('entity_index', 'generation')):
            raise ValueError('exact ordered example entity/prefix required')
        last = rid
        if not isinstance(sample, dict) or set(sample) != {'sample_id', 'at', 'prefix_record_index', 'facts', 'paused', 'stable_until'} or sample['prefix_record_index'] != rid + 1 or sample['paused'] is not None or sample['stable_until'] is not None or TimeRef(**sample['at']).game_time_ms is not None:
            raise ValueError('raw mechanical example clock/pause cannot be verified')
        for observation in (*sample['facts'], *example['restriction_operands']):
            if not isinstance(observation, dict) or set(observation) != {'fact', 'source_record_index'} or type(observation['source_record_index']) is not int or not 0 <= observation['source_record_index'] <= rid:
                raise ValueError('mechanical example future operand')
            fact = dict(observation['fact'])
            fact['valid_at'] = TimeRef(**fact['valid_at'])
            fact['available_at'] = TimeRef(**fact['available_at']) if fact['available_at'] else None
            fact['source_refs'] = tuple(SourceRef(**r) for r in fact['source_refs'])
            fact['derived_from'] = tuple(fact['derived_from'])
            fact['quality_flags'] = tuple(fact['quality_flags'])
            typed = Fact(**fact)
            if typed.subject_ref != f"account:{payload['account_id']}" or typed.observer_ref != typed.subject_ref or typed.perspective != 'public' or typed.method_version != VERSION or typed.predicate not in EXTRA_PREDICATES | (PREDICATES - {'screen.reaction_cue', 'team.reaction_cue'}) or typed.valid_at.game_time_ms is not None or typed.available_at and typed.available_at.game_time_ms is not None:
                raise ValueError('raw mechanical example cannot promote source/clock/perspective')
            if any(r.content_hash != payload['source_file_sha256'] or r.provider != 'replay_own_raw_operands' or r.extractor_version != VERSION for r in typed.source_refs):
                raise ValueError('raw mechanical example has foreign source receipt')
    return payload


def load_constraint_mechanics_summary(path, *, extraction=None, constraint_source=None, account_id=None):
    result = validate_constraint_mechanics_summary(strict_json(Path(path).read_text(encoding='utf-8-sig')))
    if account_id is not None and result['account_id'] != account_id:
        raise ValueError('foreign mechanical summary account')
    if extraction is not None and (result['match_id'] != extraction.replay.match_id or result['replay_sha256'] != extraction.audit['replay_sha256'] or result['trace_sha256'] != extraction.audit['trace_sha256'] or result['game_build'] != extraction.replay.manifest.game_build):
        raise ValueError('mechanical summary bound to another extraction')
    if constraint_source is not None:
        if extraction is None:
            raise ValueError('extraction required for complete source verification')
        verified = _verified_sidecar(constraint_source, extraction)
        if result['source_file_sha256'] != verified['file_sha256'] or result['counts']['observations'] != verified['counts']['observations'] or result['account_id'] != verified['expected_account_id']:
            raise ValueError('mechanical summary bound to another sidecar')
    return result


def monitor_mechanical_stream(scope, raw_samples, cues, *, binding, cutoff, cutoff_record_index,
                              review=None, extra_operands=(), coverages=(), continuity_admission=None,
                              truth_coverages=(), minimum_duration_ms=150):
    """Invoke the choice monitor and apply finite restrictions conservatively.

    Raw callback completeness cannot prove truth continuity. Additional guard
    spans require an independently admitted exact truth coverage witness.
    This API never manufactures either kind of continuity witness.
    """
    if not isinstance(raw_samples, tuple) or any(not isinstance(s, RawMechanicalSample) for s in raw_samples):
        raise TypeError('immutable typed mechanical stream required')
    if not isinstance(truth_coverages, tuple) or any(not isinstance(c, MechanicalTruthCoverage) for c in truth_coverages):
        raise TypeError('typed immutable guard truth coverages required')
    selected = tuple(s for s in raw_samples if s.sample.prefix_record_index < cutoff_record_index)
    from dataclasses import replace
    calculation_samples = tuple(replace(s.sample, facts=s.sample.facts + tuple(f for f in extra_operands if f.fact.predicate in PREDICATES)) for s in selected)
    result = monitor_choice_stream(scope, calculation_samples, cues, cutoff=cutoff,
        cutoff_record_index=cutoff_record_index, semantics=binding.mechanics, coverages=coverages,
        admission=continuity_admission, minimum_duration_ms=minimum_duration_ms)
    selected_ids={row['sample_id'] for row in result['sampled']['feasibility_samples']}
    selected=tuple(s for s in selected if s.sample.sample_id in selected_ids)
    checks = [evaluate_mechanical_sample(scope, s, binding=binding, review=review,
        extra_operands=extra_operands) for s in selected]
    by_id = {c['sample_id']: c for c in checks}
    admitted = []
    for c in truth_coverages:
        if c.source_record_index >= cutoff_record_index or not c.available_at.definitely_available_before(cutoff):
            continue
        if c.historical_binding_hash != content_hash(binding):
            raise ValueError('guard truth coverage has foreign historical binding')
        if any(t.order_status != 'verified' or t.clock_mapping_version != scope.clock_mapping_version or t.game_time_ms is None or t.uncertainty_ms is None for t in (c.start, c.end, c.available_at)):
            continue
        if not c.start.definitely_available_before(c.end) or not c.end.definitely_available_before(c.available_at) or not c.end.definitely_available_before(cutoff):
            continue
        witnesses = tuple(content_hash(s) for s in selected if s.sample.at.game_time_ms is not None
            and _bounds(s.sample.at,scope.clock_mapping_version) is not None
            and _bounds(c.start,scope.clock_mapping_version)[0] <= _bounds(s.sample.at,scope.clock_mapping_version)[0] <= _bounds(c.end,scope.clock_mapping_version)[1])
        if witnesses != c.sample_hashes or tuple(f.input_hash for f in extra_operands) != c.extra_operand_hashes:
            raise ValueError('guard truth coverage omitted or changed an operand transition')
        if review and content_hash(c) in review.truth_coverage_hashes:
            admitted.append(c)
    for span in result['spans']:
        guard = by_id[span['sample_id']]
        span['mechanical_decision_start_hash'] = content_hash((span['decision_start_hash'], guard['prefix_feature_hash']))
        sample = next(s for s in selected if s.sample.sample_id == span['sample_id'])
        matches = [c for c in admitted if span['interval_ms'] and _bounds(c.start,scope.clock_mapping_version)[1] <= decimal(span['interval_ms'][0])
            and decimal(span['interval_ms'][0]) < _bounds(c.end,scope.clock_mapping_version)[0]]
        if guard['feasibility'] != 'feasible' or binding.restrictions and not matches:
            span.update(status='unknown', interval_ms=None, duration_ms=None, coverage_id=None)
            span['reason_codes'] = sorted(set(span['reason_codes']) | {'extended_constraint_truth_transition_review_missing'})
        elif binding.restrictions and span['interval_ms']:
            bound_end = max(_bounds(c.end,scope.clock_mapping_version)[0] for c in matches)
            used = {fid for c in guard['restrictions'] for fid in c['operand_fact_ids']}
            fresh = [_bounds(f.fact.valid_at,scope.clock_mapping_version)[0] + decimal(scope.max_fact_age_ms)
                for f in (*sample.restrictions, *extra_operands) if f.fact.fact_id in used]
            index = selected.index(sample)
            material_end = decimal(span['interval_ms'][1])
            if index + 1 < len(selected):
                next_sample = selected[index + 1]
                original = {f.fact.predicate: f for f in (*sample.restrictions, *extra_operands)}
                following = {f.fact.predicate: f for f in (*next_sample.restrictions, *extra_operands)}
                guard_predicates = {r.predicate for r in binding.restrictions}
                if any(r.operator == 'not_after_engine_time' for r in binding.restrictions):
                    guard_predicates.add('clock.engine_time')
                altered = [following.get(p) for p in guard_predicates if p not in original or p not in following
                    or (original[p].fact.value, original[p].fact.status) != (following[p].fact.value, following[p].fact.status)]
                invalid = [f for f in altered if f is None or not review or f.input_hash not in review.restriction_fact_hashes
                    or f.fact.valid_at.order_status != 'verified' or f.fact.available_at is None
                    or not f.fact.valid_at.definitely_available_before(next_sample.sample.at)
                    or not f.fact.available_at.definitely_available_before(cutoff)
                    or _bounds(f.fact.valid_at, scope.clock_mapping_version) is None]
                if invalid:
                    span.update(status='unknown', interval_ms=None, duration_ms=None, coverage_id=None)
                    span['reason_codes'].append('extended_guard_transition_time_not_independently_bound')
                    continue
                if altered:
                    material_end = min(material_end, *(_bounds(f.fact.valid_at, scope.clock_mapping_version)[0] for f in altered))
            end = min(decimal(span['interval_ms'][1]), bound_end, material_end, *fresh)
            span['interval_ms'] = numeric_interval((decimal(span['interval_ms'][0]),end),guaranteed=True)
            duration = decimal(span['interval_ms'][1])-decimal(span['interval_ms'][0])
            span['duration_ms'] = numeric_bound(duration,upper=False)
            if duration < decimal(minimum_duration_ms):
                span.update(status='unknown', interval_ms=None, duration_ms=None, coverage_id=None)
                span['reason_codes'].append('extended_guard_duration_or_freshness_insufficient')
    transitions = []
    previous = None
    for sample, check in zip(selected, checks):
        truth = (check['feasibility'], tuple((r['code'], r['value']) for r in check['restrictions']), sample.sample.paused)
        if truth != previous:
            transitions.append({'sample_id': sample.sample.sample_id, 'prefix_record_index': sample.sample.prefix_record_index,
                'at': asdict(sample.sample.at), 'feasibility': check['feasibility'],
                'restriction_truths': dict(truth[1]), 'paused': sample.sample.paused})
        previous = truth
    result.update(schema_version='foresight.mechanical-monitor.v1', mechanical_samples=checks, finite_truth_transitions=transitions,
        supported_span_count=sum(s['status'] == 'supported_constraint_span' for s in result['spans']),
        unknown_span_count=sum(s['status'] == 'unknown' for s in result['spans']))
    result['prefix_feature_hash'] = content_hash((result['prefix_feature_hash'], [c['prefix_feature_hash'] for c in checks]))
    result.pop('payload_sha256', None)
    result['payload_sha256'] = content_hash(result)
    return result
