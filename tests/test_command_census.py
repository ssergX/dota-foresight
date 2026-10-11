"""Synthetic contract fixtures do not represent real command/POV validation."""
from dataclasses import asdict, replace
import json

import pytest

from dota_coach.decisions.command_census import (
    CommandCoverage, CommandEvent, CommandReviewRegistry, CommandScope, census_commands,
    load_command_input, command_input_record, resolve_reviewed_command_registry,
)
from dota_coach.evidence.contracts import EntityRef, SourceRef, TimeRef, content_hash


def clock(ms, uncertainty=0):
    return TimeRef(ms, uncertainty_ms=uncertainty, clock_mapping_version='fixture.clock', order_status='verified')


SOURCE = SourceRef('synthetic.commands', 'a'*64, 'synthetic', 'fixture.v1', 'own-command-stream', 'fixture.v1')
SCOPE = CommandScope(7, 'account:9', 'fixture.patch', EntityRef('match:7', 12, 3), 'fixture.clock', SOURCE)
REVIEW = SourceRef('synthetic.review', 'b'*64, 'synthetic_review', 'fixture.v1', 'review:fixture')


def event(stage='attempt', *, command_id='cmd:1', attempt_id='attempt:1', record=20, at=500, available=510):
    return CommandEvent(command_id, attempt_id, stage, record, clock(at), clock(available),
        SCOPE.subject_ref, SCOPE.item_entity, (SOURCE,), 'fixture.command-stage.v1')


def receipt(events=(), **changes):
    value = CommandCoverage('coverage:fixture', SCOPE.match_id, SCOPE.subject_ref, SCOPE.patch,
        SCOPE.item_entity, clock(0), clock(1000), 0, 90, 95, clock(1010), (SOURCE,),
        tuple(content_hash(e) for e in events if e.stage == 'attempt'), paused=False)
    return replace(value, **changes)


def registry(coverage, events=(), *, scope=SCOPE):
    return CommandReviewRegistry(scope, frozenset(content_hash(c) for c in coverage),
        frozenset(content_hash(e) for e in events), (REVIEW,))


def census(events=(), *, scope=SCOPE, coverage=(), reviewed=None, **changes):
    args = dict(interval_start=clock(0), interval_end=clock(1000), cutoff=clock(1200),
        cutoff_record_index=100, coverage=coverage, registry=reviewed)
    args.update(changes)
    return census_commands(scope, events, **args)


def test_empty_supplied_log_is_not_nonuse_without_reviewed_coverage():
    result = census()
    assert result['status'] == 'unknown' and result['completeness'] == 'unknown'
    assert result['unique_attempt_count'] == 0
    assert result['derived_fact']['value'] is None
    assert result['training_eligible'] is False
    cov = receipt()
    assert census(coverage=(cov,))['status'] == 'unknown'


def test_reviewed_complete_empty_is_observed_no_attempts_never_a_strategic_error():
    cov = receipt()
    result = census(coverage=(cov,), reviewed=registry((cov,)))
    assert result['status'] == 'observed_no_attempts'
    assert result['derived_fact']['value'] == 0
    assert result['strategic_quality'] == 'not_established'
    assert result['training_eligible'] is False
    json.dumps(result)


def test_each_stage_remains_separate_and_duplicate_delivery_counts_once():
    attempts = tuple(event(s, command_id='cmd:'+s, at=500+i*10, available=505+i*10, record=20+i)
        for i, s in enumerate(('attempt', 'accepted', 'committed', 'effect', 'rejected')))
    cov = receipt(attempts)
    result = census(attempts + (attempts[0],), coverage=(cov,), reviewed=registry((cov,), attempts))
    assert result['unique_attempt_count'] == 1
    assert result['stage_counts'] == dict.fromkeys(('attempt', 'accepted', 'committed', 'effect', 'rejected'), 1)
    assert result['orphan_stage_count'] == 0
    # Rejection after committed/effect is an inconsistent supplied stage ledger.
    assert result['status'] == 'unknown' and result['unknown_count'] == 5


def test_effect_without_attempt_is_orphan_and_is_not_promoted_to_attempt():
    result = census((event('effect'),))
    assert result['unique_attempt_count'] == 0
    assert result['orphan_stage_count'] == 1 and result['stage_counts']['effect'] == 1
    assert result['status'] == 'unknown'


def test_late_delivery_future_records_and_future_coverage_do_not_change_prefix():
    initial = census((event(),))
    additions = (event(command_id='late', attempt_id='late', available=1500),
        event(command_id='future-record', attempt_id='future-record', record=100),
        event(command_id='future-time', attempt_id='future-time', at=1300, available=1400),
        replace(event(command_id='undelivered'), available_at=None))
    future_coverage = receipt(source_record_index=200, end_record_index=190, available_at=clock(2000))
    result = census((event(), *additions), coverage=(future_coverage,), reviewed=registry((future_coverage,)))
    # A registry itself has no effect when none of its receipts is visible.
    with_registry = census((event(),), reviewed=registry((future_coverage,)))
    assert result['input_hash'] == with_registry['input_hash']
    assert result['input_hash'] == initial['input_hash']
    assert result['unique_attempt_count'] == initial['unique_attempt_count'] == 1
    assert result['stage_counts'] == initial['stage_counts']


@pytest.mark.parametrize('change', [
    {'actor_ref':'account:8'}, {'item_entity':EntityRef('match:8',12,3)},
    {'item_entity':EntityRef('match:7',12,4)},
    {'at':replace(clock(500), clock_mapping_version='foreign')},
    {'available_at':replace(clock(510), clock_mapping_version='foreign')},
    {'stream_kind':'world.combat_log'},
    {'source_refs':(replace(SOURCE,content_hash='c'*64),)},
])
def test_foreign_scope_clocks_world_markers_and_damaged_receipts_are_refused(change):
    with pytest.raises(ValueError):
        census((replace(event(), **change),))


def test_conflicting_command_ids_and_attempt_group_aliases_are_refused():
    with pytest.raises(ValueError, match='duplicate'):
        census((event(), replace(event(),stage='effect')))
    with pytest.raises(ValueError, match='group'):
        census((event(), replace(event(),command_id='cmd:2')))


def test_conflicting_coverage_ids_and_backward_command_clocks_are_refused():
    cov = receipt()
    with pytest.raises(ValueError, match='coverage id'):
        census(coverage=(cov,replace(cov,paused=True)))
    assert census(coverage=(cov,cov))['input_hash'] == census(coverage=(cov,))['input_hash']
    with pytest.raises(ValueError, match='nonmonotonic'):
        census((event(),event('effect',command_id='cmd:2',record=30,at=400,available=450)))


@pytest.mark.parametrize('changes,reason', [
    ({'paused':None},'coverage_pause_context_unknown_or_paused'),
    ({'paused':True},'coverage_pause_context_unknown_or_paused'),
    ({'end':clock(1000,1)},'coverage_interval_or_clock_ambiguous'),
    ({'start':clock(100)},'coverage_does_not_contain_requested_interval'),
    ({'available_at':clock(900)},'coverage_precedes_covered_interval_end'),
])
def test_interval_pause_and_availability_ambiguity_do_not_establish_completeness(changes,reason):
    cov = receipt(**changes)
    result = census(coverage=(cov,), reviewed=registry((cov,)))
    assert result['status'] == 'unknown' and reason in result['reason_codes']


def test_exact_coverage_manifest_detects_missing_and_mutated_commands():
    command = event(); cov = receipt((command,)); review = registry((cov,), (command,))
    for supplied in ((), (replace(command,semantic_stage_version='changed'),)):
        result = census(supplied, coverage=(cov,), reviewed=review)
        assert result['status'] == 'unknown'
        assert 'coverage_manifest_mismatch_or_missing_commands' in result['reason_codes']
    altered = replace(cov, event_hashes=())
    assert census(coverage=(altered,), reviewed=review)['status'] == 'unknown'
    unbound_events = replace(review,event_hashes=frozenset())
    result = census((command,),coverage=(cov,),reviewed=unbound_events)
    assert result['status'] == 'unknown'
    assert 'command_exact_review_binding_missing' in result['reason_codes']


@pytest.mark.parametrize('change', [
    {'match_id':8}, {'subject_ref':'account:8'}, {'patch':'foreign'},
    {'item_entity':EntityRef('match:7',12,4)},
    {'start':replace(clock(0),clock_mapping_version='foreign')},
    {'end':replace(clock(1000),clock_mapping_version='foreign')},
    {'stream_kind':'world.combat_log'},
    {'source_refs':(replace(SOURCE,content_hash='c'*64),)},
])
def test_foreign_and_damaged_coverage_is_refused_even_when_its_hash_is_reviewed(change):
    cov = receipt(**change)
    with pytest.raises(ValueError):
        census(coverage=(cov,),reviewed=registry((cov,)))


def test_coverage_record_span_cannot_exclude_a_supplied_attempt_in_covered_time():
    command = event(); cov = receipt(start_record_index=30)
    result = census((command,),coverage=(cov,),reviewed=registry((cov,),(command,)))
    assert result['status'] == 'unknown'
    assert 'command_record_time_coverage_contradiction' in result['reason_codes']


def test_missing_source_and_portable_flags_cannot_grant_completeness():
    scope = replace(SCOPE, command_source=None); cov = receipt()
    result = census(scope=scope, coverage=(cov,), reviewed=registry((cov,),scope=scope))
    assert result['status'] == 'unknown' and 'missing_command_source' in result['reason_codes']
    with pytest.raises(TypeError,match='portable'):
        census(reviewed={'validated':True})
    with pytest.raises(ValueError,match='registry'):
        census(reviewed=registry((cov,),scope=replace(SCOPE,patch='foreign')))


def test_ambiguous_query_command_and_unknown_stage_never_create_empty_certainty():
    cov = receipt()
    assert census(coverage=(cov,), reviewed=registry((cov,)), interval_end=clock(1000,1))['status'] == 'unknown'
    for command in (replace(event(),at=clock(500,None)),
                    replace(event(),semantic_stage_version='unknown'),
                    replace(event(),at=clock(990,20),available_at=clock(1020))):
        cov = receipt((command,))
        assert census((command,),coverage=(cov,),reviewed=registry((cov,),(command,)))['status'] == 'unknown'


def test_whole_file_receipts_do_not_enter_analytical_prefix_hashes():
    command = event(); cov = receipt((command,))
    first = census((command,),coverage=(cov,),reviewed=registry((cov,),(command,)))
    new_source = replace(SOURCE,artifact_id='future-extended-file',content_hash='c'*64)
    scope = replace(SCOPE,command_source=new_source)
    command = replace(command,source_refs=(new_source,))
    cov = replace(cov,source_refs=(new_source,),event_hashes=(content_hash(command),))
    second = census((command,),scope=scope,coverage=(cov,),reviewed=registry((cov,),(command,),scope=scope))
    assert first['input_hash'] == second['input_hash']
    assert first['provenance'] != second['provenance']


def portable(events=(), coverage=()):
    return json.loads(json.dumps({'schema_version':'foresight.command-input.v1',
        'scope':asdict(SCOPE), 'events':[asdict(e) for e in events],
        'coverage':[asdict(c) for c in coverage], 'interval_start':asdict(clock(0)),
        'interval_end':asdict(clock(1000)), 'cutoff':asdict(clock(1200)), 'cutoff_record_index':100}))


def test_portable_loader_roundtrip_and_duplicate_json_keys(tmp_path):
    command = event(); cov = receipt((command,))
    value = load_command_input(portable((command,),(cov,)))
    assert value['events'] == (command,) and value['coverage'] == (cov,)
    assert census_commands(**value)['status'] == 'unknown'
    path = tmp_path/'command.json'; path.write_text(json.dumps(portable()),encoding='utf-8')
    assert load_command_input(path)['scope'] == SCOPE
    path.write_text('{"schema_version":"a","schema_version":"b"}',encoding='utf-8')
    with pytest.raises(ValueError,match='duplicate'):
        load_command_input(path)


@pytest.mark.parametrize('key',['registry','admission','validated','outcome','training_eligible'])
def test_loader_forbids_portable_registry_outcome_and_validation_fields(key):
    payload = portable()
    with pytest.raises(ValueError):
        load_command_input(payload | {key:True})
    payload['scope'][key] = True
    with pytest.raises(ValueError):
        load_command_input(payload)


def declared_review_fixture(events=(), *, raters=2):
    """Contract-only replay declarations; no real source or human labels exist."""
    from dota_coach.validation.contracts import Annotation,FactCheck
    cov = receipt(events)
    value = load_command_input(portable(events,(cov,)))
    record = command_input_record(value,replay_sha256='d'*64)
    ids = ['command-context:'+record.input_hash,'command-coverage:'+content_hash(cov)]
    ids += ['command-event:'+content_hash(e) for e in events]
    labels = tuple(Annotation(record.decision_id,record.input_hash,record.replay_hash,record.patch,
        'synthetic-reviewer:'+str(i),('insufficient_evidence',),'unknown','Synthetic review contract',
        facts_checked=tuple(FactCheck(fid,'correct','available','Synthetic exact binding') for fid in ids),
        unknowns=('No real human or client verification',),review_pass='extraction') for i in range(raters))
    return value,record,labels


def test_two_declared_reviewers_bind_exact_context_coverage_and_attempts():
    value,record,labels = declared_review_fixture((event(),))
    reviewed = resolve_reviewed_command_registry(value,replay_sha256=record.replay_hash,
        records=iter((record,)),annotations=iter(labels))
    result = census_commands(**value,registry=reviewed)
    assert result['status'] == 'observed_attempts' and result['training_eligible'] is False
    assert result['validation'] == 'conditional_research_only'
    empty,record,labels = declared_review_fixture()
    reviewed = resolve_reviewed_command_registry(empty,replay_sha256=record.replay_hash,
        records=(record,),annotations=labels)
    assert census_commands(**empty,registry=reviewed)['status'] == 'observed_no_attempts'


def test_single_reviewer_self_evaluation_and_context_missing_do_not_admit():
    value,record,labels = declared_review_fixture()
    variants = (labels[:1],(replace(labels[0],annotator_kind='self_evaluation'),labels[1]),
        tuple(replace(a,facts_checked=tuple(c for c in a.facts_checked if not c.fact_id.startswith('command-context:'))) for a in labels))
    for variant in variants:
        reviewed = resolve_reviewed_command_registry(value,replay_sha256=record.replay_hash,
            records=(record,),annotations=variant)
        assert reviewed is None and census_commands(**value,registry=reviewed)['status'] == 'unknown'


def test_reviewed_context_rejects_wrong_replay_and_changed_prefix():
    value,record,labels = declared_review_fixture((event(),))
    for changed,digest in ((value,'e'*64),(value | {'events':(replace(event(),semantic_stage_version='changed'),)},record.replay_hash)):
        with pytest.raises(ValueError,match='another'):
            resolve_reviewed_command_registry(changed,replay_sha256=digest,records=(record,),annotations=labels)


@pytest.mark.parametrize('target',['command-context:','command-coverage:','command-event:'])
def test_latest_review_revision_revokes_each_exact_binding(target):
    value,record,labels = declared_review_fixture((event(),))
    original = labels[0]
    revision = replace(original,annotation_version=2,previous_annotation_hash=original.annotation_hash,
        revision_reason='Synthetic correction',facts_checked=tuple(replace(c,correctness='incorrect')
            if c.fact_id.startswith(target) else c for c in original.facts_checked))
    reviewed = resolve_reviewed_command_registry(value,replay_sha256=record.replay_hash,
        records=(record,),annotations=(*labels,revision))
    assert census_commands(**value,registry=reviewed)['status'] == 'unknown'


def test_historical_review_manifest_excludes_future_and_undelivered_commands():
    value,record,labels = declared_review_fixture((event(),))
    future = event(command_id='future',attempt_id='future',record=100,at=1300,available=1500)
    late = event(command_id='late',attempt_id='late',available=1500)
    future_coverage = receipt(coverage_id='future',source_record_index=150,available_at=clock(1500))
    changed = value | {'events':(*value['events'],future,late), 'coverage':(*value['coverage'],future_coverage)}
    assert command_input_record(changed,replay_sha256=record.replay_hash) == record
    reviewed = resolve_reviewed_command_registry(changed,replay_sha256=record.replay_hash,records=(record,),annotations=labels)
    assert content_hash(future) not in reviewed.event_hashes and content_hash(late) not in reviewed.event_hashes
    assert census_commands(**changed,registry=reviewed)['status'] == 'observed_attempts'


def tick_clock(ms,tick,sequence=0):
    return replace(clock(ms),replay_tick=tick,sequence_in_tick=sequence)


def test_reviewed_empty_coverage_with_future_end_tick_never_claims_no_attempts():
    cov = receipt(start=tick_clock(0,0),end=tick_clock(1000,200),available_at=tick_clock(1010,101))
    result = census(coverage=(cov,),reviewed=registry((cov,)),
        interval_start=tick_clock(0,0),interval_end=tick_clock(1000,100),cutoff=tick_clock(1200,120))
    assert result['status'] == 'unknown' and result['derived_fact']['value'] is None
    assert 'coverage_precedes_covered_interval_end' in result['reason_codes']


def test_reviewed_coverage_reversed_start_end_ticks_is_unknown():
    cov = receipt(start=tick_clock(0,200),end=tick_clock(1000,100),available_at=tick_clock(1010,101))
    result = census(coverage=(cov,),reviewed=registry((cov,)),cutoff=tick_clock(1200,120))
    assert result['status'] == 'unknown'
    assert 'coverage_interval_or_clock_ambiguous' in result['reason_codes']


@pytest.mark.parametrize('first,last,cutoff', [
    (tick_clock(0,200),tick_clock(1000,100),tick_clock(1200,120)),
    (tick_clock(0,0),tick_clock(1000,200),tick_clock(1200,120)),
    (tick_clock(0,0),tick_clock(1300,130),tick_clock(1200,120)),
    (tick_clock(0,10,4),tick_clock(1000,10,3),tick_clock(1200,120)),
])
def test_tick_sequence_reversal_or_future_query_interval_never_grants_empty_completeness(first,last,cutoff):
    cov = receipt()
    result = census(coverage=(cov,),reviewed=registry((cov,)),
        interval_start=first,interval_end=last,cutoff=cutoff)
    assert result['status'] == 'unknown' and result['derived_fact']['value'] is None
    assert 'query_interval_or_clock_ambiguous' in result['reason_codes']


@pytest.mark.parametrize('at1,delivery1,at2,delivery2', [
    (tick_clock(500,50),tick_clock(510,51),tick_clock(600,40),tick_clock(610,41)),
    (tick_clock(500,40),tick_clock(510,80),tick_clock(600,50),tick_clock(610,60)),
    (tick_clock(500,50,4),tick_clock(510,51),tick_clock(600,50,3),tick_clock(610,52)),
    (tick_clock(500,40),tick_clock(510,80,4),tick_clock(600,50),tick_clock(610,80,3)),
])
def test_record_ordered_backward_ticks_and_sequences_are_rejected_despite_increasing_seconds(at1,delivery1,at2,delivery2):
    first = replace(event(),at=at1,available_at=delivery1)
    second = replace(event(command_id='cmd:2',attempt_id='attempt:2',record=30),at=at2,available_at=delivery2)
    cov = receipt((first,second))
    with pytest.raises(ValueError,match='nonmonotonic'):
        census((first,second),coverage=(cov,),reviewed=registry((cov,),(first,second)),cutoff=tick_clock(1200,120))


def test_ambiguous_same_tick_event_order_blocks_completeness_and_counts_ledger_unknowns():
    first = replace(event(),at=tick_clock(500,50,None),available_at=tick_clock(510,51))
    second = replace(event(command_id='cmd:2',attempt_id='attempt:2',record=30),
        at=tick_clock(600,50,None),available_at=tick_clock(610,52))
    cov = receipt((first,second))
    result = census((first,second),coverage=(cov,),reviewed=registry((cov,),(first,second)),cutoff=tick_clock(1200,120))
    assert result['status'] == 'unknown' and result['unique_attempt_count'] == 2
    assert result['unknown_count'] == 2 and 'command_clock_order_unknown' in result['reason_codes']


def test_ambiguous_query_keeps_supplied_ledger_in_unknown_denominator():
    result = census((event(),),interval_start=tick_clock(0,200),interval_end=tick_clock(1000,100))
    assert result['unknown_count'] == 1 and result['status'] == 'unknown'


def test_accepted_before_attempt_and_orphan_effect_never_certify_stage_ledger():
    accepted = event('accepted',record=10,at=400,available=410)
    attempted = event(command_id='cmd:2')
    cov = receipt((accepted,attempted))
    result = census((accepted,attempted),coverage=(cov,),reviewed=registry((cov,),(accepted,attempted)))
    assert result['status'] == 'unknown' and result['unknown_count'] == 2
    assert 'command_stage_order_inconsistent_or_incomplete' in result['reason_codes']
    orphan = event('effect'); cov = receipt()
    result = census((orphan,),coverage=(cov,),reviewed=registry((cov,),(orphan,)))
    assert result['status'] == 'unknown' and result['unknown_count'] == result['orphan_stage_count'] == 1


def test_ordered_attempt_rejection_remains_separate_and_can_cover_attempt_stream():
    attempted = event()
    rejected = event('rejected',command_id='rejected',record=30,at=600,available=610)
    cov = receipt((attempted,rejected))
    result = census((attempted,rejected),coverage=(cov,),reviewed=registry((cov,),(attempted,rejected)))
    assert result['status'] == 'observed_attempts' and result['unknown_count'] == 0
    assert result['stage_counts']['attempt'] == result['stage_counts']['rejected'] == 1


def test_command_tick_outside_query_or_coverage_boundary_cannot_be_counted_complete():
    command = replace(event(),at=tick_clock(500,150),available_at=tick_clock(510,151))
    cov = receipt((command,),start=tick_clock(0,0),end=tick_clock(1000,100),available_at=tick_clock(1010,101))
    result = census((command,),coverage=(cov,),reviewed=registry((cov,),(command,)),
        interval_start=tick_clock(0,0),interval_end=tick_clock(1000,100),cutoff=tick_clock(1200,200))
    assert result['status'] == 'unknown' and result['unknown_count'] == 1
    assert result['unique_attempt_count'] == 0
    assert 'command_clock_contradicts_coverage_interval' in result['reason_codes']


def test_command_delivery_tick_after_coverage_receipt_prevents_full_grant():
    command = replace(event(),at=tick_clock(500,50),available_at=tick_clock(510,151))
    cov = receipt((command,),start=tick_clock(0,0),end=tick_clock(1000,100),available_at=tick_clock(1010,101))
    result = census((command,),coverage=(cov,),reviewed=registry((cov,),(command,)),
        interval_start=tick_clock(0,0),interval_end=tick_clock(1000,100),cutoff=tick_clock(1200,200))
    assert result['status'] == 'unknown'
    assert 'command_delivery_not_ordered_before_coverage_receipt' in result['reason_codes']

@pytest.mark.parametrize('boundary',['query_start','query_end','coverage_start','coverage_end'])
def test_tiny_decimal_uncertainty_cannot_become_exact_coverage(boundary):
    base=1e16
    cov=receipt(start=clock(base-100),end=clock(base+200),available_at=clock(base+210))
    args={'interval_start':clock(base),'interval_end':clock(base+100),'cutoff':clock(base+300)}
    if boundary.startswith('query_'):
        field='interval_start' if boundary.endswith('start') else 'interval_end'
        args[field]=replace(args[field],uncertainty_ms=1e-7)
    else:
        field='start' if boundary.endswith('start') else 'end'
        cov=replace(cov,**{field:replace(getattr(cov,field),uncertainty_ms=1e-7)})
    result=census(coverage=(cov,),reviewed=registry((cov,)),**args)
    assert result['status']=='unknown' and result['derived_fact']['value'] is None
