"""Synthetic protocol fixtures, never independent humans or real certification.

Replay tags below exercise the replay-only branch. Registry review_context is
testing, so an active fixture receipt cannot enable real inference.
"""
from dataclasses import asdict, replace

import pytest

from dota_coach.evidence.contracts import SourceRef, content_hash
from dota_coach.validation.contracts import ActionCheck, Annotation, DatasetRecord, FactCheck, Prediction
from dota_coach.validation.criterion_gate import (
    REQUIRED_PASSES, CallerRegistry, CriterionIdentity, ExplanationBinding,
    FactRequirement, GateAdmission, GateCohort, ReleasePolicy, ReleaseReceipt,
    check_inference, evaluate_gate,
)
from dota_coach.validation.pipeline import evaluate_predictions


def fixture():
    source = SourceRef('synthetic.protocol.fixture', 'a' * 64, 'synthetic', 'fixture.v1', 'review', 'fixture.v1')
    identity = CriterionIdentity('single_known_impact', 'fixture.patch', 'fixture.item',
                                 'fixture.threat', 'fixture.evaluator.v1', 'b' * 64)
    policy = ReleasePolicy('fixture.policy.v1', 2, 2, 2, 1, 0, 0, 2, 0, 1, 1, 1,
                           (source,), '2026-01-01T00:00:00Z')
    cohort = GateCohort(seal_source_refs=(source,), sealed_at='2026-01-02T00:00:00Z')
    records = tuple(DatasetRecord('decision:' + str(i), content_hash(('input', i)), i,
        content_hash(('replay', i)), 'player:' + str(i), identity.patch, 'holdout', 'replay',
        ('player:' + str(i),) + tuple('participant:' + str(i) + ':' + str(j) for j in range(9))) for i in (1, 2))
    predictions = tuple(Prediction(r.decision_id, r.input_hash,
        'good' if r.match_id == 1 else 'probable_error', identity.evaluator_version) for r in records)
    annotations = tuple(Annotation(r.decision_id, r.input_hash, r.replay_hash, r.patch,
        'fixture-human:' + str(j), ('good' if r.match_id == 1 else 'probable_error',), 'eligible', 'Synthetic protocol fixture, no real human review.',
        (FactCheck('fact:1', 'correct', 'available', 'Fixture only'),),
        (ActionCheck('activate', 'feasible', ('fact:1',), 'Fixture only'),),
        ('fact:1',), adjudication_status='agreed') for r in records for j in (1, 2))
    requirements = tuple(FactRequirement(r.decision_id, r.input_hash, ('fact:1',)) for r in records)
    explanations = tuple(ExplanationBinding(r.decision_id, r.input_hash,
        content_hash(('fixture explanation', r.decision_id)), (source,)) for r in records)
    return dict(identity=identity, policy=policy, records=records, predictions=predictions,
                annotations=annotations, cohort=cohort, fact_requirements=requirements,
                explanation_bindings=explanations), source


def registry_for(args, source, *, passes=REQUIRED_PASSES):
    proposal = evaluate_gate(**args)
    approval = GateAdmission(proposal['package_hash'], args['identity'], proposal['policy_hash'],
        proposal['report_hash'], (source,), passes)
    sources = (source,) + args['policy'].source_refs + args['cohort'].seal_source_refs + tuple(
        s for e in args['explanation_bindings'] for s in e.source_refs)
    return CallerRegistry((approval,), frozenset(content_hash(s) for s in sources), 'testing')


def test_proposal_recomputes_raw_typed_data_and_never_grants_itself():
    args, _ = fixture()
    result = evaluate_gate(**args)
    assert result['computed_report'] == evaluate_predictions(args['predictions'], args['annotations'], args['records'])
    assert result['software_metrics_pass'] and result['status'] == 'closed'
    assert result['release_receipt'] is None and not result['training_eligible']


def test_exact_testing_admission_yields_typed_receipt_but_never_real_certification():
    args, source = fixture()
    registry = registry_for(args, source)
    result = evaluate_gate(**args, registry=registry)
    assert result['status'] == 'testing_receipt_only'
    receipt = result['release_receipt']
    assert isinstance(receipt, ReleaseReceipt)
    allowed = check_inference(args['identity'], receipt, registry)
    assert allowed['active_exact_receipt'] and not allowed['criterion_available']
    assert allowed['per_case_admission_required'] and allowed['per_case_unknown_must_abstain']
    assert not allowed['impact_review_promoted'] and not allowed['global_coaching_certified']


def test_external_branch_remains_limited_and_requires_current_exact_case_separate_gate():
    # This is a branch test with synthetic declarations, not a real review receipt.
    args, source = fixture()
    registry = replace(registry_for(args, source), review_context='external_review')
    receipt = evaluate_gate(**args, registry=registry)['release_receipt']
    state = check_inference(args['identity'], receipt, registry)
    assert state['criterion_available'] and state['per_case_admission_required']
    assert not state['impact_review_promoted'] and not state['training_eligible']


@pytest.mark.parametrize('field,value', [
    ('model_hash', 'c' * 64), ('patch', 'different.patch'), ('item_id', 'different.item'),
    ('threat_id', 'different.threat'), ('evaluator_version', 'different.version'),
    ('criterion_id', 'different.criterion'),
])
def test_identity_mutations_revoke_old_release_and_packet(field, value):
    args, source = fixture()
    registry = registry_for(args, source)
    receipt = evaluate_gate(**args, registry=registry)['release_receipt']
    identity = replace(args['identity'], **{field: value})
    assert not check_inference(identity, receipt, registry)['active_exact_receipt']
    args['identity'] = identity
    assert evaluate_gate(**args, registry=registry)['release_receipt'] is None


@pytest.mark.parametrize('mutation', ['policy', 'policy-source', 'cohort-seal', 'cohort-player',
                                      'annotation', 'explanation', 'prediction', 'inventory'])
def test_exact_packet_covers_all_values_receipts_and_labels(mutation):
    args, source = fixture()
    registry = registry_for(args, source)
    old = evaluate_gate(**args, registry=registry)
    if mutation == 'policy':
        args['policy'] = replace(args['policy'], version='fixture.policy.v2')
    elif mutation == 'policy-source':
        args['policy'] = replace(args['policy'], source_refs=(replace(source, locator='other'),))
    elif mutation == 'cohort-seal':
        args['cohort'] = replace(args['cohort'], seal_source_refs=(replace(source, content_hash='d' * 64),))
    elif mutation == 'cohort-player':
        args['cohort'] = replace(args['cohort'], training_player_ids=('unrelated.player',))
    elif mutation == 'annotation':
        args['annotations'] = (replace(args['annotations'][0], rationale='Changed full label.'),) + args['annotations'][1:]
    elif mutation == 'explanation':
        args['explanation_bindings'] = (replace(args['explanation_bindings'][0], explanation_hash='c' * 64),) + args['explanation_bindings'][1:]
    elif mutation == 'prediction':
        args['predictions'] = (replace(args['predictions'][0], verdict='probable_error'),) + args['predictions'][1:]
    else:
        args['fact_requirements'] = (replace(args['fact_requirements'][0], fact_ids=('fact:1', 'fact:2')), ) + args['fact_requirements'][1:]
    new = evaluate_gate(**args, registry=registry)
    assert new['package_hash'] != old['package_hash'] and new['release_receipt'] is None


@pytest.mark.parametrize('mutation', ['remove-admission', 'remove-source', 'receipt-change', 'pass-change'])
def test_current_registry_revokes_existing_receipt(mutation):
    args, source = fixture()
    registry = registry_for(args, source)
    receipt = evaluate_gate(**args, registry=registry)['release_receipt']
    if mutation == 'remove-admission':
        changed = replace(registry, admissions=())
    elif mutation == 'remove-source':
        changed = replace(registry, allowed_source_receipt_hashes=frozenset())
    elif mutation == 'receipt-change':
        changed = replace(registry, admissions=(replace(registry.admissions[0], review_sources=(replace(source, locator='mutated'),)),))
    else:
        changed = replace(registry, admissions=(replace(registry.admissions[0], authenticated_passes=REQUIRED_PASSES - {'human_identity_independence'}),))
    assert not check_inference(args['identity'], receipt, changed)['active_exact_receipt']
    assert evaluate_gate(**args, registry=changed)['release_receipt'] is None


@pytest.mark.parametrize('field', ['training_match_ids', 'retrieval_match_ids', 'training_player_ids', 'retrieval_player_ids'])
def test_external_training_retrieval_match_and_all_participant_leaks_close(field):
    args, source = fixture()
    value = (args['records'][0].match_id,) if 'match' in field else (args['records'][0].participants[-1],)
    args['cohort'] = replace(args['cohort'], **{field: value})
    result = evaluate_gate(**args, registry=registry_for(args, source))
    assert not result['software_metrics_pass'] and result['release_receipt'] is None
    assert 'split_leakage_or_incomplete_rosters' in result['reason_codes']


def test_development_copy_and_incomplete_roster_cannot_become_holdout():
    args, source = fixture()
    first = args['records'][0]
    args['records'] += (replace(first, decision_id='copy', input_hash='e' * 64, split='development'),)
    result = evaluate_gate(**args, registry=registry_for(args, source))
    assert result['release_receipt'] is None
    args, source = fixture()
    args['records'] = (replace(args['records'][0], participants=()),) + args['records'][1:]
    assert evaluate_gate(**args, registry=registry_for(args, source))['release_receipt'] is None


@pytest.mark.parametrize('mutation', ['zero', 'silence', 'unknown-label', 'dissent', 'unreviewed',
    'unavailable', 'unverifiable', 'not-reviewed', 'one-rater', 'self-review', 'no-inventory', 'disputed', 'declared-unknown',
    'no-explanation', 'fake-decisive', 'synthetic', 'all-error-reference'])
def test_unknown_denominators_silence_and_unreviewed_data_remain_closed_even_if_packet_approved(mutation):
    args, source = fixture()
    if mutation == 'zero':
        for name in ('records', 'predictions', 'annotations', 'fact_requirements', 'explanation_bindings'):
            args[name] = ()
    elif mutation == 'silence':
        args['predictions'] = ()
        args['explanation_bindings'] = ()
    elif mutation == 'unknown-label':
        args['annotations'] = tuple(replace(a, eligibility='unknown', acceptable_verdicts=('insufficient_evidence',), unknowns=('fixture unknown',)) for a in args['annotations'])
    elif mutation == 'dissent':
        args['annotations'] = (replace(args['annotations'][0], acceptable_verdicts=('probable_error',)),) + args['annotations'][1:]
    elif mutation == 'unreviewed':
        args['annotations'] = tuple(replace(a, adjudication_status='unreviewed') for a in args['annotations'])
    elif mutation == 'disputed':
        args['annotations'] = tuple(replace(a, adjudication_status='disputed') for a in args['annotations'])
    elif mutation == 'declared-unknown':
        args['annotations'] = tuple(replace(a, unknowns=('Unresolved fixture uncertainty',)) for a in args['annotations'])
    elif mutation in ('unavailable', 'unverifiable'):
        check = replace(args['annotations'][0].facts_checked[0], **({'availability': 'not_available'} if mutation == 'unavailable' else {'correctness': 'unverifiable'}))
        args['annotations'] = tuple(replace(a, facts_checked=(check,)) for a in args['annotations'])
    elif mutation == 'not-reviewed':
        args['fact_requirements'] = tuple(replace(f, fact_ids=('fact:1', 'unreviewed.fact')) for f in args['fact_requirements'])
    elif mutation == 'one-rater':
        args['annotations'] = tuple(a for a in args['annotations'] if a.annotator_id.endswith(':1'))
    elif mutation == 'self-review':
        args['annotations'] = tuple(replace(a, annotator_kind='self_evaluation') for a in args['annotations'])
    elif mutation == 'no-inventory':
        args['fact_requirements'] = ()
    elif mutation == 'no-explanation':
        args['explanation_bindings'] = ()
    elif mutation == 'fake-decisive':
        args['annotations'] = tuple(replace(a, decisive_evidence_ids=('not.reviewed',)) for a in args['annotations'])
    elif mutation == 'synthetic':
        args['records'] = tuple(replace(r, dataset_kind='synthetic') for r in args['records'])
        args['annotations'] = tuple(replace(a, dataset_kind='synthetic') for a in args['annotations'])
    else:
        args['annotations'] = tuple(replace(a, acceptable_verdicts=('probable_error',)) for a in args['annotations'])
    result = evaluate_gate(**args, registry=registry_for(args, source))
    assert not result['software_metrics_pass'] and result['release_receipt'] is None


def test_full_annotation_history_and_nonqualifying_revisions_are_bound():
    args, source = fixture()
    a = args['annotations'][0]
    extraction = replace(a, review_pass='extraction')
    args['annotations'] += (extraction,)
    registry = registry_for(args, source)
    old = evaluate_gate(**args, registry=registry)
    assert old['release_receipt']
    revision = replace(extraction, annotation_version=2, previous_annotation_hash=extraction.annotation_hash,
                       revision_reason='Fixture correction', rationale='Changed extraction rationale')
    args['annotations'] += (revision,)
    new = evaluate_gate(**args, registry=registry)
    assert new['computed_report'] == old['computed_report']
    assert new['package_hash'] != old['package_hash'] and new['release_receipt'] is None
    args['annotations'] = args['annotations'][:-2] + (revision,)
    with pytest.raises(ValueError, match='chain'):
        evaluate_gate(**args)


def test_policy_must_precede_bound_cohort_seal_and_unknown_seal_never_grants():
    args, source = fixture()
    for cohort in (GateCohort(), replace(args['cohort'], sealed_at=args['policy'].declared_at)):
        mutated = {**args, 'cohort': cohort}
        result = evaluate_gate(**mutated, registry=registry_for(mutated, source))
        assert 'prespecified_policy_or_bound_cohort_seal_missing' in result['reason_codes']
        assert result['release_receipt'] is None


def test_source_allowlist_binds_complete_receipt_including_packet_policy_and_text():
    args, source = fixture()
    changed = replace(source, locator='new.policy')
    args['policy'] = replace(args['policy'], source_refs=(changed,))
    registry = registry_for(args, source)
    registry = replace(registry, allowed_source_receipt_hashes=frozenset({content_hash(source)}))
    assert evaluate_gate(**args, registry=registry)['release_receipt'] is None


@pytest.mark.parametrize('value', [float('inf'), float('nan'), -0.1, 1.1, True, 10**400])
def test_policy_rejects_nonfinite_or_invalid_probability_inputs(value):
    args, _ = fixture()
    with pytest.raises(ValueError):
        replace(args['policy'], false_positive_ceiling=value)


def test_portable_admission_registry_receipt_and_precomputed_reports_forbidden():
    args, source = fixture()
    registry = registry_for(args, source)
    receipt = evaluate_gate(**args, registry=registry)['release_receipt']
    with pytest.raises(TypeError, match='portable'):
        evaluate_gate(**args, registry=asdict(registry))
    with pytest.raises(TypeError, match='portable'):
        check_inference(args['identity'], asdict(receipt), registry)
    with pytest.raises(TypeError):
        evaluate_gate(**{**args, 'predictions': (evaluate_gate(**args)['computed_report'],)})
    with pytest.raises(TypeError):
        CallerRegistry((asdict(registry.admissions[0]),), frozenset())


def test_forged_receipt_report_or_flags_cannot_admit():
    args, source = fixture()
    registry = registry_for(args, source)
    receipt = evaluate_gate(**args, registry=registry)['release_receipt']
    assert not check_inference(args['identity'], replace(receipt, report_hash='c' * 64), registry)['active_exact_receipt']
    assert not check_inference(args['identity'], replace(receipt), registry)['active_exact_receipt']
    with pytest.raises(ValueError):
        replace(receipt, training_eligible=True)
    with pytest.raises(ValueError):
        replace(receipt, global_coaching_certified=True)


def test_approved_packet_with_failed_metrics_cannot_mint_receipt_by_hand():
    args, source = fixture()
    args['predictions'] = ()
    args['explanation_bindings'] = ()
    registry = registry_for(args, source)
    result = evaluate_gate(**args, registry=registry)
    assert not result['software_metrics_pass'] and result['release_receipt'] is None
    admission = registry.admissions[0]
    payload = asdict(admission)
    payload['authenticated_passes'] = sorted(admission.authenticated_passes)
    fake = ReleaseReceipt(admission.identity, admission.package_hash, admission.policy_hash,
        admission.report_hash, content_hash(payload), registry.review_context)
    assert not check_inference(args['identity'], fake, registry)['active_exact_receipt']


@pytest.mark.parametrize('dependency', ['policy', 'seal', 'explanation'])
def test_inference_revokes_each_packet_source_dependency_even_when_approval_source_remains(dependency):
    args, source = fixture()
    other = replace(source, locator='independent.' + dependency)
    if dependency == 'policy':
        args['policy'] = replace(args['policy'], source_refs=(other,))
    elif dependency == 'seal':
        args['cohort'] = replace(args['cohort'], seal_source_refs=(other,))
    else:
        args['explanation_bindings'] = tuple(replace(e, source_refs=(other,)) for e in args['explanation_bindings'])
    registry = registry_for(args, source)
    receipt = evaluate_gate(**args, registry=registry)['release_receipt']
    assert check_inference(args['identity'], receipt, registry)['active_exact_receipt']
    revoked = replace(registry, allowed_source_receipt_hashes=registry.allowed_source_receipt_hashes - {content_hash(other)})
    assert content_hash(source) in revoked.allowed_source_receipt_hashes
    assert not check_inference(args['identity'], receipt, revoked)['active_exact_receipt']
    assert evaluate_gate(**args, registry=revoked)['release_receipt'] is None


def test_extra_unbound_facts_cannot_inflate_minimum_review_denominator():
    args, source = fixture()
    args['annotations'] = tuple(replace(a, facts_checked=a.facts_checked +
        (FactCheck('invented.extra', 'correct', 'available', 'Fixture only'),)) for a in args['annotations'])
    args['policy'] = replace(args['policy'], minimum_fact_reviews=4)
    result = evaluate_gate(**args, registry=registry_for(args, source))
    assert result['computed_report']['fact_review']['known_consensus_facts'] == 4
    assert 'reviewed_fact_outside_bound_case_inventory' in result['reason_codes']
    assert result['release_receipt'] is None


@pytest.mark.parametrize('verdict,metric', [('good', 'agreement_with_acceptable_sets'),
                                         ('probable_error', 'false_positive_rate')])
def test_constant_predictions_cannot_pass_mixed_reference_cohort(verdict, metric):
    args, source = fixture()
    args['predictions'] = tuple(replace(p, verdict=verdict) for p in args['predictions'])
    result = evaluate_gate(**args, registry=registry_for(args, source))
    assert 'policy_threshold_failed:' + metric in result['reason_codes']
    assert result['release_receipt'] is None


def test_one_sided_nonerror_reference_cannot_open_even_perfect_metrics():
    args, source = fixture()
    args['annotations'] = tuple(replace(a, acceptable_verdicts=('good',)) for a in args['annotations'])
    args['predictions'] = tuple(replace(p, verdict='good') for p in args['predictions'])
    result = evaluate_gate(**args, registry=registry_for(args, source))
    assert result['computed_report']['metrics']['agreement_with_acceptable_sets']['rate'] == 1
    assert 'insufficient_reference_error_cases' in result['reason_codes']
    assert result['release_receipt'] is None


def test_known_nondeterminative_fact_errors_are_measured_against_prespecified_ceiling():
    args, source = fixture()
    args['fact_requirements'] = tuple(replace(f, fact_ids=('fact:1', 'fact:2')) for f in args['fact_requirements'])
    args['annotations'] = tuple(replace(a, facts_checked=a.facts_checked +
        (FactCheck('fact:2', 'incorrect', 'available', 'Fixture extraction error'),)) for a in args['annotations'])
    result = evaluate_gate(**args, registry=registry_for(args, source))
    assert result['computed_report']['fact_review']['factual_error_rate']['value'] == 0.5
    assert 'policy_threshold_failed:fact_error_rate' in result['reason_codes']
    assert result['release_receipt'] is None
