"""Prefix-safe census of supplied own-player commands, not a non-use verdict.

An effect marker is never promoted into an attempt. Completeness requires an
exact caller-owned review binding to a bounded command stream. Review bindings
are research inputs, not authentication of reviewers or client verification.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from fractions import Fraction

from dota_coach.evidence.contracts import EntityRef, Fact, SourceRef, TimeRef, content_hash

VERSION = 'command-census.v1'
STAGES = ('attempt', 'accepted', 'committed', 'effect', 'rejected')


def _text(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(name + ' must be explicit')


def _record(value):
    if type(value) is not int or value < 0:
        raise ValueError('exact nonnegative source record required')


def _refs(value):
    if not isinstance(value, tuple) or not value or any(not isinstance(r, SourceRef) for r in value):
        raise ValueError('immutable exact source receipts required')


def _hashes(value):
    if not isinstance(value, frozenset):
        raise TypeError('review hashes must be immutable')
    if any(not isinstance(h, str) or len(h) != 64 or any(c not in '0123456789abcdef' for c in h) for h in value):
        raise ValueError('exact SHA256 review binding required')


@dataclass(frozen=True)
class CommandScope:
    match_id: int
    subject_ref: str
    patch: str
    item_entity: EntityRef
    clock_mapping_version: str
    command_source: SourceRef | None = None

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id <= 0:
            raise ValueError('exact match required')
        for value in (self.subject_ref, self.patch, self.clock_mapping_version):
            _text(value, 'scope')
        if not isinstance(self.item_entity, EntityRef) or self.item_entity.replay_id != f'match:{self.match_id}':
            raise ValueError('item belongs to another replay')
        if any(type(v) is not int for v in (self.item_entity.entity_index, self.item_entity.generation)):
            raise ValueError('exact integer item generation required')
        if self.command_source is not None and not isinstance(self.command_source, SourceRef):
            raise TypeError('typed command source required')


@dataclass(frozen=True)
class CommandEvent:
    command_id: str
    attempt_id: str
    stage: str
    source_record_index: int
    at: TimeRef
    available_at: TimeRef | None
    actor_ref: str
    item_entity: EntityRef
    source_refs: tuple[SourceRef, ...]
    semantic_stage_version: str
    stream_kind: str = 'command_attempts'

    def __post_init__(self):
        for value in (self.command_id, self.attempt_id, self.actor_ref, self.semantic_stage_version, self.stream_kind):
            _text(value, 'command identity/semantics')
        if self.stage not in STAGES:
            raise ValueError('explicit attempt/accepted/committed/effect/rejected stage required')
        _record(self.source_record_index)
        if not isinstance(self.at, TimeRef) or (self.available_at is not None and not isinstance(self.available_at, TimeRef)):
            raise TypeError('typed command clocks required')
        if not isinstance(self.item_entity, EntityRef):
            raise TypeError('typed item identity required')
        _refs(self.source_refs)


@dataclass(frozen=True)
class CommandCoverage:
    coverage_id: str
    match_id: int
    subject_ref: str
    patch: str
    item_entity: EntityRef
    start: TimeRef
    end: TimeRef
    start_record_index: int
    end_record_index: int
    source_record_index: int
    available_at: TimeRef | None
    source_refs: tuple[SourceRef, ...]
    event_hashes: tuple[str, ...]
    stream_kind: str = 'command_attempts'
    paused: bool | None = None

    def __post_init__(self):
        for value in (self.coverage_id, self.subject_ref, self.patch, self.stream_kind):
            _text(value, 'coverage scope')
        if type(self.match_id) is not int or self.match_id <= 0 or not isinstance(self.item_entity, EntityRef):
            raise ValueError('exact coverage match/item required')
        for t in (self.start, self.end):
            if not isinstance(t, TimeRef):
                raise TypeError('typed coverage interval required')
        if self.available_at is not None and not isinstance(self.available_at, TimeRef):
            raise TypeError('typed coverage availability required')
        for r in (self.start_record_index, self.end_record_index, self.source_record_index):
            _record(r)
        if self.end_record_index < self.start_record_index:
            raise ValueError('reversed source coverage interval')
        if type(self.paused) not in (bool, type(None)):
            raise TypeError('explicit pause context required')
        _refs(self.source_refs)
        if not isinstance(self.event_hashes, tuple) or len(set(self.event_hashes)) != len(self.event_hashes):
            raise TypeError('immutable distinct coverage manifest required')
        _hashes(frozenset(self.event_hashes))


@dataclass(frozen=True)
class CommandReviewRegistry:
    """Not a portable validated flag; supplied separately by a review caller."""
    scope: CommandScope
    coverage_hashes: frozenset[str]
    event_hashes: frozenset[str]
    review_sources: tuple[SourceRef, ...]

    def __post_init__(self):
        if not isinstance(self.scope, CommandScope):
            raise TypeError('typed registry scope required')
        _hashes(self.coverage_hashes)
        _hashes(self.event_hashes)
        _refs(self.review_sources)


def _bounds(t, clock):
    if (not isinstance(t, TimeRef) or t.clock_mapping_version != clock or t.order_status != 'verified'
            or t.game_time_ms is None or t.uncertainty_ms is None):
        return None
    center, width = Fraction(str(t.game_time_ms)), Fraction(str(t.uncertainty_ms))
    return center-width, center+width


def _clock_order(first, last, clock):
    """Order all supplied clock coordinates; increasing seconds alone is insufficient."""
    left, right = _bounds(first, clock), _bounds(last, clock)
    if not left or not right:
        return 'unknown'
    if left[0] > right[1]:
        return 'contradiction'
    if first.replay_tick is not None and last.replay_tick is not None:
        if first.replay_tick > last.replay_tick:
            return 'contradiction'
        if (first.replay_tick == last.replay_tick and first.sequence_in_tick is not None
                and last.sequence_in_tick is not None and first.sequence_in_tick > last.sequence_in_tick):
            return 'contradiction'
    return 'ordered' if first.definitely_available_before(last) else 'unknown'


def _visible(record, available, cutoff_record, cutoff):
    # Foreign clocks are rejected after record-prefix filtering. Ambiguous or
    # undelivered observations are omitted, including from analytical hashes.
    if record >= cutoff_record or available is None:
        return False
    if available.clock_mapping_version != cutoff.clock_mapping_version:
        raise ValueError('foreign availability clock')
    bound = _bounds(available, cutoff.clock_mapping_version)
    limit = _bounds(cutoff, cutoff.clock_mapping_version)
    return bool(bound and limit and bound[1] < limit[0]
                and available.definitely_available_before(cutoff))


def _source_key(ref):
    return {k: getattr(ref, k) for k in ('provider', 'schema_version', 'locator', 'extractor_version')}


def _projection(value):
    row = asdict(value)
    row['source_refs'] = [_source_key(r) for r in value.source_refs]
    # Coverage membership receipts bind review, not analytical prefix features.
    if isinstance(value, CommandCoverage):
        row.pop('event_hashes')
    return row


def _scope_projection(scope):
    row = asdict(scope)
    row['command_source'] = _source_key(scope.command_source) if scope.command_source else None
    return row


def _check_scope(scope, actor, item, source_refs, clock):
    if actor != scope.subject_ref or item != scope.item_entity:
        raise ValueError('foreign actor/replay/item generation')
    if clock != scope.clock_mapping_version:
        raise ValueError('foreign command clock')
    if scope.command_source is not None and scope.command_source not in source_refs:
        raise ValueError('damaged exact command source binding')


def census_commands(scope: CommandScope, events: tuple[CommandEvent, ...], *,
                    interval_start: TimeRef, interval_end: TimeRef,
                    cutoff: TimeRef, cutoff_record_index: int,
                    coverage: tuple[CommandCoverage, ...] = (),
                    registry: CommandReviewRegistry | None = None) -> dict:
    """Census a half-open time interval using a strictly earlier source prefix.

    Counts describe supplied command records. ``observed_no_attempts`` is only
    available when a reviewed, source-bound coverage interval contains the whole
    requested interval and its exact attempt manifest matches supplied records.
    It is neither a strategic mistake nor a claim about an entire match.
    """
    if not isinstance(scope, CommandScope) or not isinstance(events, tuple) or any(not isinstance(e, CommandEvent) for e in events):
        raise TypeError('typed scope and immutable commands required')
    if not isinstance(coverage, tuple) or any(not isinstance(c, CommandCoverage) for c in coverage):
        raise TypeError('immutable typed coverage required')
    if any(not isinstance(t, TimeRef) for t in (interval_start, interval_end, cutoff)):
        raise TypeError('typed query clocks required')
    _record(cutoff_record_index)
    if any(t.clock_mapping_version != scope.clock_mapping_version for t in (interval_start, interval_end, cutoff)):
        raise ValueError('foreign query clock')
    if registry is not None:
        if not isinstance(registry, CommandReviewRegistry):
            raise TypeError('portable validated flags cannot grant review')
        if registry.scope != scope:
            raise ValueError('foreign review registry scope')
    start, end = _bounds(interval_start, scope.clock_mapping_version), _bounds(interval_end, scope.clock_mapping_version)
    if start and end and start[0] > end[1]:
        raise ValueError('reversed query time interval')
    exact_interval = bool(start and end and start[0] == start[1] and end[0] == end[1] and start[0] < end[0]
        and _clock_order(interval_start, interval_end, scope.clock_mapping_version) == 'ordered'
        and _clock_order(interval_end, cutoff, scope.clock_mapping_version) == 'ordered')
    visible = {}
    for event in events:
        if not _visible(event.source_record_index, event.available_at, cutoff_record_index, cutoff):
            continue
        _check_scope(scope, event.actor_ref, event.item_entity, event.source_refs, event.at.clock_mapping_version)
        if event.stream_kind != 'command_attempts':
            raise ValueError('world/combat markers are not command attempts')
        valid = _bounds(event.at, scope.clock_mapping_version)
        limit = _bounds(cutoff, scope.clock_mapping_version)
        if limit and valid and valid[0] >= limit[0]:
            continue
        available = _bounds(event.available_at, scope.clock_mapping_version)
        if valid and (available[0] < valid[1] or not event.at.definitely_available_before(event.available_at)):
            raise ValueError('command delivered before its observed occurrence')
        if event.command_id in visible and visible[event.command_id] != event:
            raise ValueError('conflicting duplicate command id')
        visible[event.command_id] = event
    ordered = tuple(sorted(visible.values(), key=lambda e: (e.source_record_index, e.command_id)))
    previous_event = None
    uncertain_order_ids = set()
    for event in ordered:
        if previous_event is not None and previous_event.source_record_index < event.source_record_index:
            orders = (_clock_order(previous_event.at, event.at, scope.clock_mapping_version),
                      _clock_order(previous_event.available_at, event.available_at, scope.clock_mapping_version))
            if 'contradiction' in orders:
                raise ValueError('nonmonotonic command clock contradicts source order')
            if 'unknown' in orders:
                uncertain_order_ids.update((previous_event.command_id, event.command_id))
        elif previous_event is not None:
            uncertain_order_ids.update((previous_event.command_id, event.command_id))
        if _clock_order(event.at, event.available_at, scope.clock_mapping_version) != 'ordered':
            uncertain_order_ids.add(event.command_id)
        previous_event = event
    attempt_groups = {}
    for event in ordered:
        if event.stage == 'attempt':
            if event.attempt_id in attempt_groups:
                raise ValueError('conflicting attempt group identities')
            attempt_groups[event.attempt_id] = event
    interval_events = []
    boundary_events = []
    if exact_interval:
        for event in ordered:
            bounds = _bounds(event.at, scope.clock_mapping_version)
            if bounds is None:
                boundary_events.append(event)
            elif start[0] <= bounds[0] and bounds[1] < end[0]:
                if (_clock_order(interval_start, event.at, scope.clock_mapping_version) == 'ordered'
                        and _clock_order(event.at, interval_end, scope.clock_mapping_version) == 'ordered'):
                    interval_events.append(event)
                else:
                    boundary_events.append(event)
            elif bounds[1] >= start[0] and bounds[0] < end[0]:
                boundary_events.append(event)
    else:
        # Delivered ledger rows cannot disappear from the unknown denominator
        # merely because the requested clock interval itself is ambiguous.
        boundary_events.extend(ordered)
    stages = {stage: sum(e.stage == stage for e in interval_events) for stage in STAGES}
    orphan_events = tuple(e for e in interval_events if e.stage != 'attempt' and e.attempt_id not in attempt_groups)
    unknown_events = tuple(e for e in interval_events if e.semantic_stage_version in ('unknown', 'legacy/unverified'))
    stage_order_ids = set()
    groups = {}
    for event in ordered:
        groups.setdefault(event.attempt_id, []).append(event)
    ranks = {'attempt': 0, 'accepted': 1, 'committed': 2, 'effect': 3}
    for group in groups.values():
        previous_rank = -1
        previous_stage = None
        inconsistent = False
        seen = set()
        for event in group:
            if event.stage in ranks:
                if ranks[event.stage] < previous_rank or previous_stage == 'rejected':
                    inconsistent = True
                previous_rank = ranks[event.stage]
            if event.stage == 'rejected' and seen.intersection(('committed', 'effect')):
                inconsistent = True
            seen.add(event.stage)
            previous_stage = event.stage
        if inconsistent or 'attempt' not in seen:
            stage_order_ids.update(e.command_id for e in group)
    relevant_ids = {e.command_id for e in (*interval_events, *boundary_events)}
    uncertain_order_ids &= relevant_ids
    stage_order_ids &= relevant_ids
    reasons = []
    if not exact_interval:
        reasons.append('query_interval_or_clock_ambiguous')
    if scope.command_source is None:
        reasons.append('missing_command_source')
    if boundary_events:
        reasons.append('command_time_crosses_interval_boundary')
    if unknown_events:
        reasons.append('command_stage_semantics_unknown')
    if uncertain_order_ids:
        reasons.append('command_clock_order_unknown')
    if stage_order_ids:
        reasons.append('command_stage_order_inconsistent_or_incomplete')
    visible_coverage = []
    complete_coverage = []
    coverage_ids = {}
    for receipt in coverage:
        if not _visible(receipt.source_record_index, receipt.available_at, cutoff_record_index, cutoff):
            continue
        _check_scope(scope, receipt.subject_ref, receipt.item_entity, receipt.source_refs, receipt.start.clock_mapping_version)
        if (receipt.match_id, receipt.patch) != (scope.match_id, scope.patch) or receipt.end.clock_mapping_version != scope.clock_mapping_version:
            raise ValueError('foreign coverage replay/patch/clock')
        if receipt.stream_kind != 'command_attempts':
            raise ValueError('coverage is not a command attempt stream')
        if receipt.coverage_id in coverage_ids:
            if coverage_ids[receipt.coverage_id] != receipt:
                raise ValueError('conflicting duplicate coverage id')
            continue
        coverage_ids[receipt.coverage_id] = receipt
        visible_coverage.append(receipt)
        if registry is None:
            reasons.append('missing_review_registry')
        if registry is None or content_hash(receipt) not in registry.coverage_hashes:
            reasons.append('coverage_exact_review_binding_missing')
            continue
        first, last = _bounds(receipt.start, scope.clock_mapping_version), _bounds(receipt.end, scope.clock_mapping_version)
        if (not first or not last or first[0] != first[1] or last[0] != last[1] or first[0] >= last[0]
                or _clock_order(receipt.start, receipt.end, scope.clock_mapping_version) != 'ordered'):
            reasons.append('coverage_interval_or_clock_ambiguous')
            continue
        if receipt.paused is not False:
            reasons.append('coverage_pause_context_unknown_or_paused')
            continue
        delivered = _bounds(receipt.available_at, scope.clock_mapping_version)
        if (delivered[0] < last[1] or receipt.end_record_index > receipt.source_record_index
                or _clock_order(receipt.end, receipt.available_at, scope.clock_mapping_version) != 'ordered'
                or _clock_order(receipt.end, cutoff, scope.clock_mapping_version) != 'ordered'):
            reasons.append('coverage_precedes_covered_interval_end')
            continue
        covered_events = tuple(e for e in ordered if e.stage == 'attempt' and _bounds(e.at, scope.clock_mapping_version)
            and first[0] <= _bounds(e.at, scope.clock_mapping_version)[0]
            and _bounds(e.at, scope.clock_mapping_version)[1] < last[0]
            and receipt.start_record_index <= e.source_record_index < receipt.end_record_index)
        if any(_clock_order(receipt.start, e.at, scope.clock_mapping_version) != 'ordered'
                or _clock_order(e.at, receipt.end, scope.clock_mapping_version) != 'ordered' for e in covered_events):
            reasons.append('command_clock_contradicts_coverage_interval')
            continue
        if any(_clock_order(e.available_at, receipt.available_at, scope.clock_mapping_version) != 'ordered'
                for e in covered_events):
            reasons.append('command_delivery_not_ordered_before_coverage_receipt')
            continue
        if frozenset(content_hash(e) for e in covered_events) != frozenset(receipt.event_hashes):
            reasons.append('coverage_manifest_mismatch_or_missing_commands')
            continue
        if not frozenset(receipt.event_hashes) <= registry.event_hashes:
            reasons.append('command_exact_review_binding_missing')
            continue
        outside_records = any(e.stage == 'attempt' and _bounds(e.at, scope.clock_mapping_version) and first[0] <= _bounds(e.at, scope.clock_mapping_version)[0]
            and _bounds(e.at, scope.clock_mapping_version)[1] < last[0]
            and not receipt.start_record_index <= e.source_record_index < receipt.end_record_index for e in ordered)
        if outside_records:
            reasons.append('command_record_time_coverage_contradiction')
            continue
        if (exact_interval and first[0] <= start[0] and last[0] >= end[0]
                and _clock_order(receipt.start, interval_start, scope.clock_mapping_version) == 'ordered'
                and _clock_order(interval_end, receipt.end, scope.clock_mapping_version) == 'ordered'):
            complete_coverage.append(receipt)
        else:
            reasons.append('coverage_does_not_contain_requested_interval')
    if not visible_coverage:
        reasons.append('no_delivered_command_coverage')
    complete = bool(complete_coverage and exact_interval and scope.command_source and not boundary_events
        and not unknown_events and not uncertain_order_ids and not stage_order_ids)
    attempts = tuple(e for e in interval_events if e.stage == 'attempt')
    status = ('observed_attempts' if attempts else 'observed_no_attempts') if complete else 'unknown'
    # Hash only available prefix operands and their current admission results.
    input_hash = content_hash({'version': VERSION, 'scope': _scope_projection(scope),
        'interval_start': asdict(interval_start), 'interval_end': asdict(interval_end),
        'cutoff': asdict(cutoff), 'cutoff_record_index': cutoff_record_index,
        'commands': [_projection(e) for e in ordered],
        'coverage': [_projection(c) for c in sorted(visible_coverage, key=lambda c: (c.source_record_index, c.coverage_id))],
        'complete_coverage_ids': sorted(c.coverage_id for c in complete_coverage), 'reasons': sorted(set(reasons))})
    refs = tuple(dict.fromkeys(r for e in interval_events for r in e.source_refs))
    refs += tuple(r for c in complete_coverage for r in c.source_refs if r not in refs)
    fact = Fact('command-census:' + input_hash, scope.subject_ref, 'commands.attempt_count',
        len(attempts) if complete else None, 'derived' if complete else 'unknown', interval_end,
        cutoff, 'screen', refs, derived_from=tuple(e.command_id for e in attempts),
        observer_ref=scope.subject_ref, method_version=VERSION,
        quality_flags=('conditional_research_only', 'supplied_command_stream_only', 'client_verification_not_established'),
        unknown_reason=None if complete else ';'.join(sorted(set(reasons))) or 'command_completeness_unknown')
    return {'schema_version': VERSION, 'scope': asdict(scope), 'input_hash': input_hash,
        'status': status, 'completeness': 'complete_for_requested_interval' if complete else 'unknown',
        'unique_attempt_count': len(attempts), 'stage_counts': stages,
        'orphan_stage_count': len(orphan_events), 'unknown_stage_count': len(unknown_events),
        'unknown_count': len({e.command_id for e in (*unknown_events, *boundary_events)} | uncertain_order_ids | stage_order_ids),
        'boundary_ambiguous_count': len(boundary_events),
        'attempt_ids': [e.attempt_id for e in attempts],
        'orphan_command_ids': [e.command_id for e in orphan_events],
        'reason_codes': sorted(set(reasons)), 'derived_fact': asdict(fact),
        'provenance': {'events': [asdict(e) for e in ordered], 'coverage': [asdict(c) | {'event_hashes': sorted(c.event_hashes)} for c in visible_coverage],
            'review_sources': [asdict(r) for r in registry.review_sources] if registry else []},
        'strategic_quality': 'not_established', 'training_eligible': False,
        'validation': 'conditional_research_only', 'game_opportunity_coverage': None}


def load_command_input(source: dict | str | Path) -> dict:
    """Read portable command evidence, never a portable review grant."""
    from dota_coach.decisions.batch import _keys, read_time, strict_json
    value = source if isinstance(source, dict) else strict_json(Path(source).read_text(encoding='utf-8-sig'))
    fields = ('schema_version', 'scope', 'events', 'coverage', 'interval_start',
              'interval_end', 'cutoff', 'cutoff_record_index')
    _keys(value, fields)
    if value['schema_version'] != 'foresight.command-input.v1':
        raise ValueError('unsupported command input schema')

    def entity(row):
        _keys(row, ('replay_id', 'entity_index', 'generation'))
        if type(row['entity_index']) is not int or type(row['generation']) is not int:
            raise ValueError('exact integer command entity required')
        return EntityRef(**row)

    def ref(row):
        _keys(row, ('artifact_id', 'content_hash', 'provider', 'schema_version', 'locator'), ('extractor_version',))
        if any(not isinstance(x, str) for x in row.values()):
            raise ValueError('source receipt fields must be strings')
        return SourceRef(**row)

    def refs(rows):
        if not isinstance(rows, list):
            raise ValueError('source receipt array required')
        return tuple(ref(row) for row in rows)

    _keys(value['scope'], ('match_id', 'subject_ref', 'patch', 'item_entity', 'clock_mapping_version'), ('command_source',))
    scope = dict(value['scope'])
    scope['item_entity'] = entity(scope['item_entity'])
    if scope.get('command_source') is not None:
        scope['command_source'] = ref(scope['command_source'])
    if not isinstance(value['events'], list) or not isinstance(value['coverage'], list):
        raise ValueError('command event and coverage arrays required')
    events = []
    for row in value['events']:
        _keys(row, ('command_id', 'attempt_id', 'stage', 'source_record_index', 'at', 'available_at',
                    'actor_ref', 'item_entity', 'source_refs', 'semantic_stage_version'), ('stream_kind',))
        fields = dict(row)
        fields['at'] = read_time(row['at'])
        fields['available_at'] = read_time(row['available_at']) if row['available_at'] is not None else None
        fields['item_entity'] = entity(row['item_entity'])
        fields['source_refs'] = refs(row['source_refs'])
        events.append(CommandEvent(**fields))
    coverage = []
    for row in value['coverage']:
        _keys(row, ('coverage_id', 'match_id', 'subject_ref', 'patch', 'item_entity', 'start', 'end',
                    'start_record_index', 'end_record_index', 'source_record_index', 'available_at',
                    'source_refs', 'event_hashes'), ('stream_kind', 'paused'))
        fields = dict(row)
        for name in ('start', 'end'):
            fields[name] = read_time(row[name])
        fields['available_at'] = read_time(row['available_at']) if row['available_at'] is not None else None
        fields['item_entity'] = entity(row['item_entity'])
        fields['source_refs'] = refs(row['source_refs'])
        if not isinstance(row['event_hashes'], list):
            raise ValueError('exact command manifest array required')
        fields['event_hashes'] = tuple(row['event_hashes'])
        coverage.append(CommandCoverage(**fields))
    result = {'scope': CommandScope(**scope), 'events': tuple(events), 'coverage': tuple(coverage),
        'interval_start': read_time(value['interval_start']), 'interval_end': read_time(value['interval_end']),
        'cutoff': read_time(value['cutoff']), 'cutoff_record_index': value['cutoff_record_index']}
    # Run structural/prefix scope validation without granting review.
    census_commands(**result)
    return result


def _input_kwargs(value):
    if isinstance(value, dict) and 'schema_version' in value:
        return load_command_input(value)
    required = {'scope', 'events', 'coverage', 'interval_start', 'interval_end', 'cutoff', 'cutoff_record_index'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('strict command input kwargs required; registry is separate')
    census_commands(**value)
    return value


def command_input_record(value, *, replay_sha256, split='development'):
    """Bind an exact delivered prefix for declared extraction review.

    A replay-kind review manifest is a source declaration; it does not certify
    that the supplied stream came from a client or that reviewers are people.
    """
    from dota_coach.validation.contracts import DatasetRecord
    value = _input_kwargs(value)
    result = census_commands(**value)
    scope = value['scope']
    context = {'scope': asdict(scope), **{k: asdict(value[k]) for k in ('interval_start', 'interval_end', 'cutoff')},
        'cutoff_record_index': value['cutoff_record_index'],
        'events': result['provenance']['events'], 'coverage': result['provenance']['coverage']}
    digest = content_hash(context)
    identity = content_hash({'scope': _scope_projection(scope),
        **{k: asdict(value[k]) for k in ('interval_start', 'interval_end', 'cutoff')},
        'cutoff_record_index': value['cutoff_record_index']})
    return DatasetRecord('command-input:' + identity, digest, scope.match_id, replay_sha256,
        scope.subject_ref, scope.patch, split, 'replay', (scope.subject_ref,))


def resolve_reviewed_command_registry(value, *, replay_sha256, records, annotations):
    """Require exact context and two latest declared human extraction checks.

    Neither declarations nor consensus authenticate people/client access. Every
    resulting census remains conditional research and ineligible for training.
    """
    from dota_coach.validation.pipeline import validate_annotations
    value = _input_kwargs(value)
    records, annotations = tuple(records), tuple(annotations)
    validate_annotations(annotations, records)
    expected = command_input_record(value, replay_sha256=replay_sha256)
    record = next((r for r in records if r.decision_id == expected.decision_id), None)
    if record is None:
        return None
    if record != command_input_record(value, replay_sha256=replay_sha256, split=record.split):
        raise ValueError('command review bound to another prefix, replay, patch or subject')
    latest = {}
    for label in annotations:
        if label.decision_id != record.decision_id or label.review_pass != 'extraction':
            continue
        previous = latest.get(label.annotator_id)
        if previous is None or label.annotation_version > previous.annotation_version:
            latest[label.annotator_id] = label
    labels = tuple(a for a in latest.values() if a.annotator_kind == 'human_expert' and a.dataset_kind == 'replay')

    def agreed(fact_id):
        votes = [check for a in labels for check in a.facts_checked if check.fact_id == fact_id]
        return len(votes) >= 2 and all(check.correctness == 'correct' and check.availability == 'available' for check in votes)

    if not agreed('command-context:' + record.input_hash):
        return None
    result = census_commands(**value)
    visible_event_hashes = {content_hash(e) for e in result['provenance']['events']}
    coverage_ids = {c['coverage_id'] for c in result['provenance']['coverage']}
    events = tuple(e for e in value['events'] if content_hash(e) in visible_event_hashes)
    coverage = tuple(c for c in value['coverage'] if c.coverage_id in coverage_ids
        and _visible(c.source_record_index, c.available_at, value['cutoff_record_index'], value['cutoff']))
    event_hashes = frozenset(content_hash(e) for e in events if agreed('command-event:' + content_hash(e)))
    coverage_hashes = frozenset(content_hash(c) for c in coverage if agreed('command-coverage:' + content_hash(c)))
    refs = tuple(SourceRef('review:' + a.annotation_hash, a.annotation_hash,
        'declared_extraction_review', a.schema_version, a.decision_id + ':' + a.annotator_id,
        'exact-command-input-review.v1') for a in labels)
    return CommandReviewRegistry(value['scope'], coverage_hashes, event_hashes, refs)
