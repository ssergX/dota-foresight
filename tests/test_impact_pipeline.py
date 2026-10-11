"""Synthetic orchestration fixtures. Testing witnesses never admit real history."""
from dataclasses import asdict, replace

import pytest

from dota_coach.decisions.defensive_impact import VERSION, chosen_action_binding_hash, evaluate_defensive_impact
from dota_coach.decisions.impact_pipeline import (
    CASE_PASSES, RUBRIC_VERSION, CaseAdmission, CaseAssessment, ImpactCaseInput,
    ObservedChoice, assess_impact_case, build_impact_case, impact_case_packet,
    recheck_case_assessment,
)
from dota_coach.evidence.contracts import TimeRef, content_hash
from dota_coach.validation.criterion_gate import evaluate_gate
from tests.test_criterion_gate import fixture as gate_fixture, registry_for
from tests.test_defensive_impact import change, context, portable, review


def ready(*, action='hold', goal_change=None, context_kind='testing'):
    scope, model, goal, facts, source = context()
    # Declared replay tags exercise the real-only path on synthetic fixtures.
    scope = replace(scope, dataset_kind='replay')
    if goal_change:
        goal = replace(goal, **goal_change)
    case = ImpactCaseInput(scope, model, goal, facts, 'f' * 64)
    input_hash = evaluate_defensive_impact(scope, model=model, goal=goal, facts=facts)['input_hash']
    choice_source = replace(source, artifact_id='fixture.own-client-choice', locator='own-command:40')
    case_source = replace(source, artifact_id='fixture.case-review', locator='rubric')
    choice = ObservedChoice(input_hash, scope.subject_ref, scope.observer_ref, scope.item_entity,
        action, 'command_accepted' if action == 'activate' else 'explicit_hold_selected', scope.at, scope.at,
        TimeRef(1050, 11, 1, 0, 'fixture.clock', 'verified'), (choice_source,))
    impact = review(scope, model, goal, facts, source, action)
    impact = replace(impact, chosen_action_sources=choice.source_refs,
        chosen_action_binding_hash=chosen_action_binding_hash(input_hash, action, choice.source_refs))
    gate_args, gate_source = gate_fixture()
    gate_args['identity'] = replace(gate_args['identity'], evaluator_version=VERSION, model_hash=content_hash(model),
        patch=scope.patch, item_id=scope.item_id, threat_id=scope.threat_id)
    gate_args['predictions'] = tuple(replace(p, evaluator_version=VERSION) for p in gate_args['predictions'])
    registry = replace(registry_for(gate_args, gate_source), review_context=context_kind)
    registry = replace(registry, allowed_source_receipt_hashes=registry.allowed_source_receipt_hashes |
        {content_hash(source), content_hash(choice_source), content_hash(case_source)})
    release = evaluate_gate(**gate_args, registry=registry)['release_receipt']
    packet = impact_case_packet(case, release=release, impact_admission=impact, choice=choice)
    admission = CaseAdmission(content_hash(packet), content_hash(release), packet['impact_admission_hash'],
        content_hash(choice), RUBRIC_VERSION, (case_source,), CASE_PASSES)
    return dict(case=case, release=release, registry=registry, impact_admission=impact,
                choice=choice, case_admission=admission)


def recheck(assessment, args, *, registry=None, admissions=None):
    return recheck_case_assessment(assessment, registry=registry or args['registry'],
        current_case_admissions=(args['case_admission'],) if admissions is None else admissions)


@pytest.mark.parametrize('action,goal,verdict', [
    ('hold', None, 'confirmed_error_within_criterion'),
    ('activate', None, 'good'),
    ('hold', {'minimum_hp_after_impact': 0}, 'reasonable_options'),
])
def test_current_release_case_and_own_choice_make_only_operational_verdict(action, goal, verdict):
    args = ready(action=action, goal_change=goal)
    result = assess_impact_case(**args)
    assert isinstance(result, CaseAssessment) and result.verdict == verdict
    assert result.interpretation == 'operational_single_impact_goal_constraints'
    assert result.strategic_quality == 'not_established' and not result.training_eligible
    assert result.alternatives[0].hp_after_impact.minimum == 400
    state = recheck(result, args)
    assert state['active_case_witness'] and state['testing_only']
    assert not state['admitted_for_real_history'] and state['per_history_coaching_scope_required']


def test_external_context_cannot_promote_known_synthetic_case_provenance():
    # Branch test only. The fabricated declarations below are not real reviews.
    args = ready(context_kind='external_review')
    result = assess_impact_case(**args)
    state = recheck(result, args)
    assert not state['admitted_for_real_history'] and state['per_history_coaching_scope_required']
    assert state['known_synthetic_provenance'] and result.review_context == 'testing'
    assert not result.training_eligible and not state['training_eligible']


def test_portable_default_is_unknown_and_exposes_conditional_computed_alternatives():
    case = build_impact_case(portable())
    result = assess_impact_case(case)
    assert result.verdict == 'insufficient_evidence' and result.review_context == 'unadmitted'
    assert len(result.alternatives) == 2 and result.alternatives[0].hp_after_impact.minimum == 400
    assert not result.training_eligible and result.strategic_quality == 'not_established'
    assert all(claim.startswith('conditional:') for claim in result.explanation_claims)
    data = portable()
    data['case_admission'] = {'validated': True}
    with pytest.raises(ValueError):
        build_impact_case(data)


@pytest.mark.parametrize('field', ['release', 'registry', 'impact_admission', 'choice', 'case_admission'])
def test_every_missing_case_or_release_dependency_keeps_verdict_unknown(field):
    args = ready()
    args[field] = None
    result = assess_impact_case(**args)
    assert result.verdict == 'insufficient_evidence'


@pytest.mark.parametrize('field', ['model_hash', 'criterion_id', 'patch', 'item_id', 'threat_id', 'evaluator_version'])
def test_foreign_or_stale_release_identity_cannot_admit_case(field):
    args = ready()
    # An equal-object/cross-identity receipt is unminted as well as mis-scoped.
    changed = 'c' * 64 if field == 'model_hash' else 'foreign.fixture'
    args['release'] = replace(args['release'], identity=replace(args['release'].identity, **{field: changed}))
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


@pytest.mark.parametrize('copy_target', ['assessment', 'release'])
def test_equal_immutable_dto_copies_do_not_retain_minted_witness(copy_target):
    args = ready()
    result = assess_impact_case(**args)
    if copy_target == 'assessment':
        assert not recheck(replace(result), args)['active_case_witness']
    else:
        args['release'] = replace(args['release'])
        assert assess_impact_case(**args).verdict == 'insufficient_evidence'


@pytest.mark.parametrize('dependency', ['review', 'choice', 'facts', 'release'])
def test_current_source_allowlist_revocation_rechecks_previously_issued_case(dependency):
    args = ready()
    result = assess_impact_case(**args)
    if dependency == 'review':
        source = args['case_admission'].review_sources[0]
    elif dependency == 'choice':
        source = args['choice'].source_refs[0]
    elif dependency == 'facts':
        source = args['case'].facts[0].fact.source_refs[0]
    else:
        source = args['registry'].admissions[0].review_sources[0]
    revoked = replace(args['registry'], allowed_source_receipt_hashes=
        args['registry'].allowed_source_receipt_hashes - {content_hash(source)})
    assert not recheck(result, args, registry=revoked)['active_case_witness']
    args['registry'] = revoked
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


def test_current_case_admission_and_release_active_set_revoke_history_witness():
    args = ready()
    result = assess_impact_case(**args)
    assert not recheck(result, args, admissions=())['active_case_witness']
    changed = replace(args['case_admission'], authenticated_passes=CASE_PASSES - {'complete_case_and_single_impact_scope'})
    assert not recheck(result, args, admissions=(changed,))['active_case_witness']
    revoked = replace(args['registry'], admissions=())
    assert not recheck(result, args, registry=revoked)['active_case_witness']


@pytest.mark.parametrize('mutation', ['foreign-actor', 'foreign-item', 'wrong-boundary', 'old-clock', 'future-uncertainty',
                                      'primitive-other-choice', 'different-impact-sources', 'late-real-command'])
def test_own_command_stage_and_impact_choice_receipts_must_bind_exactly(mutation):
    args = ready()
    if mutation == 'foreign-actor':
        args['choice'] = replace(args['choice'], subject_ref='account:99')
    elif mutation == 'foreign-item':
        args['choice'] = replace(args['choice'], item_entity=replace(args['choice'].item_entity, generation=99))
    elif mutation == 'wrong-boundary':
        args['choice'] = replace(args['choice'], decision_at=replace(args['choice'].decision_at, sequence_in_tick=4))
    elif mutation == 'old-clock':
        args['choice'] = replace(args['choice'], observed_at=replace(args['choice'].observed_at, clock_mapping_version='unknown'))
    elif mutation == 'future-uncertainty':
        args['choice'] = replace(args['choice'], observed_at=replace(args['choice'].observed_at, uncertainty_ms=100))
    elif mutation == 'primitive-other-choice':
        args['choice'] = replace(args['choice'], action='activate', command_stage='command_accepted')
    elif mutation == 'late-real-command':
        args['choice'] = replace(args['choice'], command_at=args['choice'].observed_at)
    else:
        impact = args['impact_admission']
        sources = (replace(impact.chosen_action_sources[0], locator='unrelated.choice'),)
        args['impact_admission'] = replace(impact, chosen_action_sources=sources,
            chosen_action_binding_hash=chosen_action_binding_hash(impact.input_hash, 'hold', sources))
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


def test_no_command_or_issued_only_is_not_confirmed_hold_or_completed_choice():
    args = ready()
    with pytest.raises(ValueError):
        replace(args['choice'], command_stage='no_activation_observed')
    with pytest.raises(ValueError):
        replace(args['choice'], action='activate', command_stage='command_issued')


@pytest.mark.parametrize('pass_name', sorted(CASE_PASSES))
def test_each_separate_completeness_alternative_choice_and_rubric_review_is_required(pass_name):
    args = ready()
    args['case_admission'] = replace(args['case_admission'], authenticated_passes=CASE_PASSES - {pass_name})
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


def test_future_facts_do_not_change_prefix_features_packet_alternatives_or_verdict():
    args = ready()
    original = assess_impact_case(**args)
    fact = args['case'].facts[0]
    for value in (-1e9, 1e9):
        future = replace(fact, source_record_index=100, fact=replace(fact.fact, value=value,
            valid_at=TimeRef(2000, 20, 1, 0, 'fixture.clock', 'verified'),
            available_at=TimeRef(2000, 20, 1, 0, 'fixture.clock', 'verified')))
        newargs = {**args, 'case': replace(args['case'], facts=args['case'].facts + (future,))}
        changed = assess_impact_case(**newargs)
        assert (changed.input_hash, changed.case_packet_hash, changed.alternatives, changed.verdict) == (
            original.input_hash, original.case_packet_hash, original.alternatives, original.verdict)


@pytest.mark.parametrize('mutation', ['goal', 'model', 'fact', 'source', 'synthetic'])
def test_any_current_case_mutation_revokes_exact_packet(mutation):
    args = ready()
    case = args['case']
    if mutation == 'goal':
        case = replace(case, goal=replace(case.goal, minimum_hp_after_impact=0))
    elif mutation == 'model':
        case = replace(case, model=replace(case.model, effect_duration_min_ms=199))
    elif mutation == 'fact':
        case = replace(case, facts=change(case.facts, 'self.hp_max', 501))
    elif mutation == 'source':
        f = case.facts[0]
        case = replace(case, facts=(replace(f, fact=replace(f.fact, source_refs=(replace(f.fact.source_refs[0], locator='new'),))),) + case.facts[1:])
    else:
        case = replace(case, scope=replace(case.scope, dataset_kind='synthetic'))
    args['case'] = case
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


def test_unknown_operand_and_both_failing_alternatives_do_not_become_player_error():
    args = ready(goal_change={'minimum_hp_after_impact': 450})
    result = assess_impact_case(**args)
    assert result.verdict == 'insufficient_evidence'
    assert all(a.goal_status == 'robustly_fails' for a in result.alternatives)
    args = ready()
    args['case'] = replace(args['case'], facts=tuple(f for f in args['case'].facts if f.fact.predicate != 'self.hp_max'))
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


@pytest.mark.parametrize('field', ['registry', 'release', 'impact_admission', 'case_admission', 'choice', 'case'])
def test_portable_objects_cannot_supply_typed_admission_or_registry(field):
    args = ready()
    args[field] = asdict(args[field])
    with pytest.raises(TypeError):
        assess_impact_case(**args)


def test_completion_stage_must_be_inside_reviewed_model_bounds_not_merely_after_intent():
    args = ready(action='activate')
    choice = replace(args['choice'], command_stage='activation_completed',
        command_at=TimeRef(1010, 10, 6, 0, 'fixture.clock', 'verified'))
    args['choice'] = choice
    packet = impact_case_packet(args['case'], release=args['release'], impact_admission=args['impact_admission'], choice=choice)
    args['case_admission'] = replace(args['case_admission'], case_packet_hash=content_hash(packet), choice_hash=content_hash(choice))
    result = assess_impact_case(**args)
    assert result.verdict == 'good'
    args['choice'] = replace(choice, command_at=TimeRef(1090, 10, 7, 0, 'fixture.clock', 'verified'))
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


def test_case_cutoff_replay_and_immutable_labels_are_exposed_without_training_promotion():
    args = ready()
    result = assess_impact_case(**args)
    state = recheck(result, args)
    assert result.decision_at == args['case'].scope.at and state['decision_at'] == result.decision_at
    assert state['replay_hash'] == args['case'].replay_hash
    assert content_hash(args['choice'].source_refs[0]) in state['source_receipt_hashes']
    with pytest.raises(ValueError):
        replace(result, training_eligible=True)
    args['case'] = replace(args['case'], replay_hash=None)
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


@pytest.mark.parametrize('mapping', ['legacy', ' fixture.clock ', '\tfixture.clock'])
def test_reserved_or_whitespace_clock_cannot_mint_case_even_when_consistently_reviewed(mapping):
    args = ready()
    case = args['case']
    clock = lambda t: replace(t, clock_mapping_version=mapping)
    case = replace(case, scope=replace(case.scope, at=clock(case.scope.at)),
        model=replace(case.model, available_at=clock(case.model.available_at)),
        goal=replace(case.goal, available_at=clock(case.goal.available_at)),
        facts=tuple(replace(f, fact=replace(f.fact, valid_at=clock(f.fact.valid_at), available_at=clock(f.fact.available_at))) for f in case.facts))
    args['case'] = case
    args['choice'] = replace(args['choice'], decision_at=case.scope.at, command_at=case.scope.at,
                            observed_at=clock(args['choice'].observed_at))
    assert assess_impact_case(**args).verdict == 'insufficient_evidence'


def test_simultaneous_impact_without_event_ordinal_does_not_mint_case_certainty():
    args = ready(action='activate')
    case = args['case']
    # This exact reviewed scenario can have arithmetic, but simultaneous priority
    # is not encoded by a scalar projected time. It must remain inadmissible.
    facts = change(change(case.facts, 'threat.projected_impact_time_min_ms', 1000), 'threat.projected_impact_time_max_ms', 1000)
    args['case'] = replace(case, facts=facts, model=replace(case.model, activation_latency_min_ms=0, activation_latency_max_ms=0))
    result = assess_impact_case(**args)
    assert 'impact_order_not_strictly_after_choice' in result.reason_codes
    assert result.verdict == 'insufficient_evidence'
