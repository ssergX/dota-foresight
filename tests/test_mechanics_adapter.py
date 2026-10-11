"""Synthetic bindings check the software; no historical Dota certification."""
from dataclasses import replace

import pytest

from dota_coach.decisions.mechanics_adapter import (
    ClockReceipt, ConstraintClockBinding, HistoricalMechanicsBinding,
    MechanicalReview, MechanicalTruthCoverage, RawMechanicalSample,
    RestrictionRule, evaluate_mechanical_sample, iter_constraint_samples,
    monitor_mechanical_stream, project_constraint_observation, summarize_constraint_mechanics,
    load_constraint_mechanics_summary, validate_constraint_mechanics_summary,
)
from dota_coach.decisions.choice_window import ChoiceScope
from dota_coach.evidence.contracts import EntityRef, content_hash
from tests.test_choice_window import inputs, admission, operand, clock
from tests.test_choice_monitor import stream
from tests.test_constraint_source import source, write


def fixture_binding(scope, semantics, restrictions=None):
    return HistoricalMechanicsBinding(scope.match_id, 'a' * 64, 777, semantics,
        'CDOTA_Item_Fixture', restrictions if restrictions is not None else (
            RestrictionRule('activated', 'action.activated', 'equals_boolean', True),
            RestrictionRule('not_channeling', 'self.channeling', 'equals_boolean', False)),
        (operand('self.alive', True).fact.source_refs[0],))


def fixture_inputs():
    scope, semantics, sample, cue = inputs()
    binding = fixture_binding(scope, semantics)
    raw = RawMechanicalSample(sample, (operand('action.activated', True),), content_hash(binding))
    extra = (operand('self.channeling', False),)
    registry = MechanicalReview(admission(scope, semantics, sample, cues=(cue,)),
        frozenset({content_hash(binding)}), frozenset(f.input_hash for f in (*raw.restrictions, *extra)))
    return scope, binding, raw, cue, extra, registry


def test_finite_restrictions_are_conjoined_only_with_exact_independent_registry():
    scope, binding, raw, _, extra, registry = fixture_inputs()
    result = evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=extra)
    assert result['candidate_feasibility'] == 'feasible'
    assert result['feasibility'] == 'unknown'
    result = evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=extra, review=registry)
    assert result['feasibility'] == 'feasible'
    assert result['training_eligible'] is False
    assert result['strategic_quality'] == 'not_established'


@pytest.mark.parametrize('predicate,value', [('action.activated', False), ('self.channeling', True)])
def test_false_restriction_is_disproof_and_missing_is_unknown(predicate, value):
    scope, binding, raw, _, extra, registry = fixture_inputs()
    changed = operand(predicate, value)
    if predicate == 'action.activated':
        raw = replace(raw, restrictions=(changed,))
    else:
        extra = (changed,)
    registry = replace(registry, restriction_fact_hashes=frozenset(f.input_hash for f in (*raw.restrictions, *extra)))
    assert evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=extra, review=registry)['feasibility'] == 'infeasible'
    raw = replace(raw, restrictions=())
    assert evaluate_mechanical_sample(scope, raw, binding=binding, review=registry)['feasibility'] == 'unknown'


@pytest.mark.parametrize('change', [
    lambda f: replace(f, source_record_index=100),
    lambda f: replace(f, fact=replace(f.fact, subject_ref='account:10')),
    lambda f: replace(f, fact=replace(f.fact, perspective='world')),
])
def test_restriction_future_foreign_world_rejected(change):
    scope, binding, raw, _, extra, registry = fixture_inputs()
    with pytest.raises(ValueError, match='future/world/foreign'):
        evaluate_mechanical_sample(scope, raw, binding=binding, review=registry, extra_operands=(change(extra[0]),))


def test_raw_bits_and_cooldown_cannot_grant_semantics_or_clock():
    scope, binding, raw, _, extra, registry = fixture_inputs()
    registry = replace(registry, historical_binding_hashes=frozenset())
    assert evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=extra, review=registry)['feasibility'] == 'unknown'
    stale = replace(extra[0], fact=replace(extra[0].fact, valid_at=replace(clock(0), game_time_ms=-1000)))
    registry = replace(registry, historical_binding_hashes=frozenset({content_hash(binding)}), restriction_fact_hashes=frozenset({stale.input_hash, raw.restrictions[0].input_hash}))
    assert evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=(stale,), review=registry)['feasibility'] == 'unknown'
    with pytest.raises(TypeError, match='portable'):
        evaluate_mechanical_sample(scope, raw, binding=binding, review={'validated': True})


def test_supplied_engine_time_restriction_has_explicit_clock_operand():
    scope, semantics, sample, cue = inputs()
    binding = fixture_binding(scope, semantics, (RestrictionRule('enable_time', 'action.enable_operand', 'not_after_engine_time'),))
    raw = RawMechanicalSample(sample, (operand('action.enable_operand', 10),), content_hash(binding))
    engine = operand('clock.engine_time', 9)
    from dataclasses import replace
    augmented = replace(sample, facts=(*sample.facts, engine))
    registry = MechanicalReview(admission(scope, semantics, augmented, cues=(cue,)), frozenset({content_hash(binding)}),
        frozenset({engine.input_hash, raw.restrictions[0].input_hash}))
    assert evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=(engine,), review=registry)['feasibility'] == 'infeasible'
    assert evaluate_mechanical_sample(scope, raw, binding=binding, review=registry)['feasibility'] == 'unknown'


def projection_fixture():
    scope, semantics, _, _ = inputs()
    binding = fixture_binding(scope, semantics)
    receipt = {'value': None, 'source_record_index': 40, 'net_tick': 80}
    def fields(values):
        return {k: receipt | {'value': v} for k, v in values.items()}
    state = {'clock': {'paused': False}, 'hero': {'fields': fields({'m_flMana': 100, 'm_lifeState': 0, 'm_nUnitState64': '4'})},
        'inventory': [{'entity_index': 12, 'generation': 3, 'slot': 2, 'class': 'CDOTA_Item_Fixture',
            'relation_status': 'resolved_exact_handle', 'handle_fact': receipt | {'value': str(12 + (3 << 14))},
            'fields': fields({'m_fCooldown': 123, 'm_iManaCost': 50, 'm_bActivated': True})}]}
    row = {'source_record_index': 99, 'net_tick': 100}
    return scope, binding, row, state


def test_raw_projection_preserves_bits_and_cooldown_without_cast_readiness_inference():
    scope, binding, row, state = projection_fixture()
    ref = operand('self.alive', True).fact.source_refs[0]
    raw = project_constraint_observation(row, state, scope=scope, binding=binding, source_ref=ref)
    facts = {f.fact.predicate: f.fact for f in raw.sample.facts}
    assert facts['self.control_bits'].value == '4'
    assert facts['item.cooldown'].value == 123
    assert raw.sample.at.game_time_ms is None and raw.sample.paused is None
    assert facts['item.cooldown'].perspective == 'public'
    assert evaluate_mechanical_sample(scope, raw, binding=binding)['feasibility'] == 'unknown'
    assert 'self.channeling' not in {f.fact.predicate for f in raw.restrictions}


def test_exact_clock_and_pause_receipts_do_not_extrapolate_time_or_pause():
    scope, binding, row, state = projection_fixture()
    ref = operand('self.alive', True).fact.source_refs[0]
    entry = ClockReceipt(99, clock(1000), content_hash(state['clock']), False, (ref,))
    raw = project_constraint_observation(row, state, scope=scope, binding=binding, source_ref=ref, clock_receipts={99: entry})
    assert raw.sample.at == clock(1000) and raw.sample.paused is False
    assert raw.sample.facts[0].fact.valid_at.game_time_ms is None
    state['clock']['paused'] = True
    with pytest.raises(ValueError, match='clock operands changed'):
        project_constraint_observation(row, state, scope=scope, binding=binding, source_ref=ref, clock_receipts={99: entry})
    with pytest.raises(ValueError, match='ordered'):
        ConstraintClockBinding('a' * 64, scope.clock_mapping_version, (entry, entry))


def test_callback_decoder_runs_all_observations_and_keeps_bounded_unknown_summary(tmp_path):
    path, extraction = source(tmp_path)
    out = tmp_path / 'constraints.jsonl'
    census = write(path, extraction, out)
    result = summarize_constraint_mechanics(out, extraction=extraction, account_id=11, limit_examples=2)
    assert result['counts']['projected_samples'] == census['counts']['observations']
    assert result['counts']['unknown_feasibility_samples'] == census['counts']['observations']
    assert result['validated_feasibility_count'] == result['supported_span_count'] == 0
    assert len(result['examples']) == 2 and result['training_eligible'] is False
    assert result['source_file_sha256'] == census['file_sha256']
    with pytest.raises(ValueError, match='account-bound'):
        summarize_constraint_mechanics(out, extraction=extraction, account_id=12)
    out.write_text(out.read_text().rsplit('\n', 2)[0] + '\n')
    with pytest.raises(ValueError):
        summarize_constraint_mechanics(out, extraction=extraction, account_id=11)


def test_historical_stream_loader_requires_exact_replay_build_and_account(tmp_path):
    path, extraction = source(tmp_path)
    out = tmp_path / 'constraints.jsonl'
    census = write(path, extraction, out)
    scope, semantics, _, _ = inputs()
    scope = replace(scope, subject_ref='account:11')
    binding = replace(fixture_binding(scope, semantics), replay_sha256=census['replay_sha256'])
    with pytest.raises(ValueError, match='historical build'):
        tuple(iter_constraint_samples(out, extraction=extraction, scope=scope, binding=binding))


def mechanical_stream():
    scope, semantics, samples, cues, coverage, continuity = stream()
    binding = fixture_binding(scope, semantics, (RestrictionRule('activated', 'action.activated', 'equals_boolean', True),))
    raw = tuple(RawMechanicalSample(s, (operand('action.activated', True),), content_hash(binding)) for s in samples)
    truth = MechanicalTruthCoverage(content_hash(binding), tuple(content_hash(s) for s in raw), (),
        coverage.start, coverage.end, coverage.available_at, coverage.source_record_index, coverage.source_refs)
    review = MechanicalReview(continuity.choice_admission, frozenset({content_hash(binding)}),
        frozenset(f.input_hash for s in raw for f in s.restrictions), frozenset({content_hash(truth)}))
    return scope, binding, raw, cues, coverage, continuity, truth, review


def run_stream(values, **kwargs):
    scope, binding, raw, cues, coverage, continuity, truth, review = values
    return monitor_mechanical_stream(scope, raw, cues, binding=binding, cutoff=clock(2000), cutoff_record_index=200,
        review=review, coverages=(coverage,), continuity_admission=continuity, truth_coverages=(truth,), **kwargs)


def test_complete_independently_bound_finite_truth_stream_integrates_with_monitor():
    result = run_stream(mechanical_stream())
    assert result['supported_span_count'] == 1
    assert result['spans'][0]['interval_ms'] == [1000, 1300]
    assert [t['feasibility'] for t in result['finite_truth_transitions']] == ['feasible', 'infeasible']
    assert result['training_eligible'] is False


@pytest.mark.parametrize('mutation', ['unreviewed', 'missing_sample', 'future_receipt', 'early_end'])
def test_raw_callbacks_and_incomplete_truth_witness_cannot_grant_span(mutation):
    values = list(mechanical_stream())
    truth, review = values[-2:]
    if mutation == 'unreviewed':
        review = replace(review, truth_coverage_hashes=frozenset())
    elif mutation == 'missing_sample':
        truth = replace(truth, sample_hashes=truth.sample_hashes[:1])
    elif mutation == 'future_receipt':
        truth = replace(truth, source_record_index=201)
    else:
        truth = replace(truth, end=clock(1100), sample_hashes=truth.sample_hashes[:1])
    if mutation != 'unreviewed':
        review = replace(review, truth_coverage_hashes=frozenset({content_hash(truth)}))
    values[-2:] = [truth, review]
    if mutation == 'missing_sample':
        with pytest.raises(ValueError, match='omitted'):
            run_stream(values)
    else:
        assert run_stream(values)['supported_span_count'] == 0


def test_later_unknown_guard_does_not_rewrite_first_sample_truth():
    values = list(mechanical_stream())
    first = evaluate_mechanical_sample(values[0], values[2][0], binding=values[1], review=values[-1])
    values[2] = (values[2][0], replace(values[2][1], restrictions=()))
    second = evaluate_mechanical_sample(values[0], values[2][0], binding=values[1], review=values[-1])
    assert first == second


@pytest.mark.parametrize('field,value', [('training_eligible', True), ('validated_feasibility_count', 1),
    ('supported_span_count', True), ('strategic_quality', 'validated'), ('game_opportunity_coverage', 1)])
def test_editable_summary_flags_cannot_open_game_quality_even_after_resealing(tmp_path, field, value):
    path, extraction = source(tmp_path)
    out = tmp_path / 'constraints.jsonl'
    write(path, extraction, out)
    result = summarize_constraint_mechanics(out, extraction=extraction, account_id=11)
    result[field] = value
    result['payload_sha256'] = content_hash({k: v for k, v in result.items() if k != 'payload_sha256'})
    with pytest.raises(ValueError, match='cannot promote'):
        validate_constraint_mechanics_summary(result)


def test_summary_loader_binds_source_and_account_and_rejects_prefix_tampering(tmp_path):
    import json
    path, extraction = source(tmp_path)
    out = tmp_path / 'constraints.jsonl'
    write(path, extraction, out)
    result = summarize_constraint_mechanics(out, extraction=extraction, account_id=11)
    output = tmp_path / 'summary.json'
    output.write_text(json.dumps(result))
    assert load_constraint_mechanics_summary(output, extraction=extraction, constraint_source=out, account_id=11) == json.loads(json.dumps(result))
    with pytest.raises(ValueError, match='foreign'):
        load_constraint_mechanics_summary(output, account_id=12)
    result['examples'][0]['sample']['facts'][0]['source_record_index'] = 999999
    result['payload_sha256'] = content_hash({k: v for k, v in result.items() if k != 'payload_sha256'})
    with pytest.raises(ValueError, match='future'):
        validate_constraint_mechanics_summary(result)


def test_candidate_never_uses_temporally_future_restriction_even_with_earlier_source_record():
    scope, binding, raw, _, extra, review = fixture_inputs()
    future = replace(extra[0], fact=replace(extra[0].fact, available_at=clock(1200)))
    with pytest.raises(ValueError, match='future restriction temporal'):
        evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=(future,), review=review)


def test_item_generation_replacement_cannot_reuse_old_projection_identity_cache():
    scope, binding, row, state = projection_fixture()
    ref = operand('self.alive', True).fact.source_refs[0]
    cache = {}
    first = project_constraint_observation(row, state, scope=scope, binding=binding, source_ref=ref, fact_cache=cache)
    state['inventory'][0]['generation'] = 4
    second = project_constraint_observation(row | {'source_record_index': 100}, state, scope=scope, binding=binding, source_ref=ref, fact_cache=cache)
    f1 = next(f for f in first.sample.facts if f.fact.predicate == 'item.generation')
    f2 = next(f for f in second.sample.facts if f.fact.predicate == 'item.generation')
    assert f1.fact.value == 3 and f2.fact.value is None


def test_bound_unit_target_identity_range_visibility_and_invulnerability_are_all_required():
    scope, semantics, sample, cue = inputs()
    scope = replace(scope, target_entity=EntityRef('match:7', 55, 6))
    semantics = replace(semantics, target_mode='unit', allowed_target_teams=(2,))
    binding = fixture_binding(scope, semantics, (
        RestrictionRule('target_visible', 'target.visible', 'equals_boolean', True),
        RestrictionRule('target_not_invulnerable', 'target.invulnerable', 'equals_boolean', False)))
    raw = RawMechanicalSample(sample, (), content_hash(binding))
    extra = tuple(operand(k, v) for k, v in {'target.distance': 500, 'self.cast_range': 600,
        'target.entity_index': 55, 'target.generation': 6, 'target.team': 2, 'target.alive': True,
        'target.visible': True, 'target.invulnerable': False}.items())
    augmented = replace(sample, facts=(*sample.facts, *(f for f in extra if f.fact.predicate not in ('target.visible', 'target.invulnerable'))))
    review = MechanicalReview(admission(scope, semantics, augmented, cues=(cue,)),
        frozenset({content_hash(binding)}), frozenset(f.input_hash for f in extra))
    assert evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=extra, review=review)['feasibility'] == 'feasible'
    changed = tuple(operand('target.invulnerable', True) if f.fact.predicate == 'target.invulnerable' else f for f in extra)
    review = replace(review, restriction_fact_hashes=frozenset(f.input_hash for f in changed))
    assert evaluate_mechanical_sample(scope, raw, binding=binding, extra_operands=changed, review=review)['feasibility'] == 'infeasible'


def test_owned_ability_uses_explicit_ability_charge_field_selection():
    scope, binding, row, state = projection_fixture()
    binding = replace(binding, linked_kind='abilities', charges_field='m_nAbilityCurrentCharges')
    state['abilities'] = state.pop('inventory')
    state['abilities'][0]['fields']['m_nAbilityCurrentCharges'] = {'value': 2, 'source_record_index': 40, 'net_tick': 80}
    raw = project_constraint_observation(row, state, scope=scope, binding=binding, source_ref=operand('self.alive', True).fact.source_refs[0])
    assert next(f.fact.value for f in raw.sample.facts if f.fact.predicate == 'item.charges') == 2


def test_guard_transition_closes_span_at_observed_truth_time_not_later_callback_sample():
    values = list(mechanical_stream())
    late = operand('action.activated', False, available=1200, record=140)
    values[2] = (values[2][0], replace(values[2][1], restrictions=(late,)))
    values[-2] = replace(values[-2], sample_hashes=tuple(content_hash(s) for s in values[2]))
    values[-1] = replace(values[-1], restriction_fact_hashes=values[-1].restriction_fact_hashes | {late.input_hash},
        truth_coverage_hashes=frozenset({content_hash(values[-2])}))
    result = run_stream(values)
    assert result['spans'][0]['interval_ms'] == [1000, 1200]


def test_removed_guard_without_observed_transition_time_cannot_extend_supported_span():
    values = list(mechanical_stream())
    values[2] = (values[2][0], replace(values[2][1], restrictions=()))
    values[-2] = replace(values[-2], sample_hashes=tuple(content_hash(s) for s in values[2]))
    values[-1] = replace(values[-1], truth_coverage_hashes=frozenset({content_hash(values[-2])}))
    result = run_stream(values)
    assert result['supported_span_count'] == 0
    assert 'extended_guard_transition_time_not_independently_bound' in result['spans'][0]['reason_codes']
