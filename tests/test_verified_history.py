"""Software branch fixtures only: no actual people, matches or certification.

The positive external branch uses fabricated protocol declarations to exercise
current exact bindings. It is not an external review artifact or real history.
"""
from dataclasses import asdict, fields, is_dataclass, replace
import json

import pytest

from dota_coach.decisions.defensive_impact import VERSION, chosen_action_binding_hash, evaluate_defensive_impact
from dota_coach.decisions.impact_pipeline import (
    CASE_PASSES, RUBRIC_VERSION, CaseAdmission, ImpactCaseInput, assess_impact_case, impact_case_packet,
)
from dota_coach.evidence.contracts import EntityRef, SourceRef, TimeRef, content_hash
from dota_coach.learning.study import MatchSource, StudyMatch
from dota_coach.learning.verified_history import (
    HistoryAdmission, HistoryCoachingScope, HistoryContext, HistoryCoverage, HistoryFeature,
    HistoryGoal, HistoryMatch, HistoryOpportunity, HistoryPolicy, StudyEpisode,
    build_verified_history, compare_verified_progress, history_document,
    load_verified_history_input, recheck_history, select_verified_study_episodes,
)
from dota_coach.validation.criterion_gate import evaluate_gate
from tests.test_criterion_gate import fixture as gate_fixture, registry_for
from tests.test_defensive_impact import review
from tests.test_impact_pipeline import ready


def declaration(source):
    return SourceRef('external.protocol.declaration', source.content_hash, 'review-protocol',
                     'declaration.v1', source.locator.replace('fixture', 'declaration'), 'declaration.v1')


def declared(value):
    if isinstance(value, SourceRef):
        return declaration(value)
    if is_dataclass(value):
        return replace(value, **{f.name: declared(getattr(value, f.name)) for f in fields(value)})
    if isinstance(value, tuple):
        return tuple(declared(v) for v in value)
    return value


def case(mid=7, index=0, *, action='hold', account=11, external=True):
    args = ready(action=action)
    original = args['case']
    scope = replace(original.scope, match_id=mid, subject_ref=f'account:{account}', observer_ref=f'account:{account}',
                    item_entity=EntityRef(f'match:{mid}', 44, 7), prefix_record_index=40+index)
    model, goal = original.model, original.goal
    facts = tuple(replace(f, fact=replace(f.fact, subject_ref=scope.subject_ref, observer_ref=scope.observer_ref))
                  for f in original.facts)
    choice = args['choice']
    if external:
        model, goal, facts, choice = declared(model), declared(goal), declared(facts), declared(choice)
    case_kwargs = {'scope': scope, 'model': model, 'goal': goal, 'facts': facts}
    if 'replay_hash' in {f.name for f in fields(ImpactCaseInput)}:
        case_kwargs['replay_hash'] = content_hash(('replay', mid))
    current = ImpactCaseInput(**case_kwargs)
    input_hash = evaluate_defensive_impact(scope, model=model, goal=goal, facts=facts)['input_hash']
    choice = replace(choice, input_hash=input_hash, subject_ref=scope.subject_ref, observer_ref=scope.observer_ref,
                     item_entity=scope.item_entity)
    source = facts[0].fact.source_refs[0]
    impact = review(scope, model, goal, facts, source, action)
    impact = replace(impact, chosen_action_sources=choice.source_refs,
                     chosen_action_binding_hash=chosen_action_binding_hash(input_hash, action, choice.source_refs))
    gate_args, gate_source = gate_fixture()
    if external:
        gate_source = declaration(gate_source)
        gate_args = {k: declared(v) for k, v in gate_args.items()}
    gate_args['identity'] = replace(gate_args['identity'], evaluator_version=VERSION, model_hash=content_hash(model),
                                    patch=scope.patch, item_id=scope.item_id, threat_id=scope.threat_id)
    gate_args['predictions'] = tuple(replace(p, evaluator_version=VERSION) for p in gate_args['predictions'])
    registry = replace(registry_for(gate_args, gate_source), review_context='external_review' if external else 'testing')
    review_source = replace(source, locator='case-protocol-review')
    registry = replace(registry, allowed_source_receipt_hashes=registry.allowed_source_receipt_hashes |
                       {content_hash(source), content_hash(review_source)} |
                       {content_hash(s) for s in choice.source_refs})
    release = evaluate_gate(**gate_args, registry=registry)['release_receipt']
    packet = impact_case_packet(current, release=release, impact_admission=impact, choice=choice)
    case_admission = CaseAdmission(content_hash(packet), content_hash(release), packet['impact_admission_hash'],
                                   content_hash(choice), RUBRIC_VERSION, (review_source,), CASE_PASSES)
    result = assess_impact_case(current, release=release, registry=registry, impact_admission=impact,
                                choice=choice, case_admission=case_admission)
    assert result.verdict == ('confirmed_error_within_criterion' if action == 'hold' else 'good'), result.reason_codes
    return result, registry, case_admission, scope, source


def bundle(*, mids=(7, 8), errors=(2, 2), external=True, start_day=1):
    matches, opportunities, admissions = [], [], []
    registry = None
    for j, mid in enumerate(mids):
        for i in range(3):
            assessment, current_registry, case_admission, scope, source = case(mid, i,
                action='hold' if i < errors[j] else 'activate', external=external)
            admissions.append(case_admission)
            registry = current_registry if registry is None else replace(registry,
                allowed_source_receipt_hashes=registry.allowed_source_receipt_hashes | current_registry.allowed_source_receipt_hashes)
            context = HistoryContext(11, 'account:11', 2, 'position:4', 'verified', 'rank_proxy:70', assessment.criterion_identity,
                                     assessment.minimum_hp_goal, assessment.minimum_mana_goal)
            f = HistoryFeature('own_mana', 150+i*10, 'mana', 0, 1000, 'measured.v1', context.subject_ref,
                               TimeRef(900, 9, 1, 0, 'fixture.clock', 'verified'), (source,))
            opportunities.append(HistoryOpportunity(f'{mid}:{i}', mid, context, scope.at, 'eligible',
                'noticed' if i == 0 else 'observable_attention_unknown', (source,), assessment, (f,), assessment.choice_action))
        replay = SourceRef(f'replay:{mid}', content_hash(('replay', mid)), 'review-protocol', 'replay.v1', f'match:{mid}', 'v1')
        matches.append(HistoryMatch(mid, context, f'2026-01-{start_day+j:02d}T10:00:00Z',
            f'2026-01-{start_day+j:02d}T11:00:00Z', replay.content_hash, 0, 2000, (replay,), 'replay'))
    coverage_source = SourceRef('census.review', 'b'*64, 'review-protocol', 'census.v1', 'full-census', 'v1')
    coverages = tuple(HistoryCoverage(content_hash(m), content_hash(m.context),
        tuple(content_hash(o) for o in opportunities if o.match_id == m.match_id), 0, 2000, 'census.v1', (coverage_source,)) for m in matches)
    goal = HistoryGoal('goal:1', content_hash(context), 'Compare the declared HP and mana goal.',
        'Before this committed threat, compare activate and hold against the scoped HP/mana constraints.',
        'Only this admitted item/threat/patch and observable feasible choice.', 'Criterion violations / all eligible choices.', (coverage_source,))
    coaching = HistoryCoachingScope(content_hash(context), tuple(content_hash(c) for c in coverages),
        tuple(o.assessment.case_packet_hash for o in opportunities), content_hash(goal), content_hash(HistoryPolicy()), (coverage_source,))
    sources = {content_hash(coverage_source)} | {content_hash(s) for m in matches for s in m.source_refs}
    sources |= {content_hash(s) for o in opportunities for s in o.source_refs}
    sources |= {content_hash(s) for o in opportunities for f in o.features for s in f.source_refs}
    admission = HistoryAdmission(frozenset(content_hash(m) for m in matches),
        frozenset(content_hash(c) for c in coverages), frozenset(sources),
        frozenset((content_hash(goal),)), coaching_hashes=frozenset((content_hash(coaching),)))
    return dict(matches=tuple(matches), opportunities=tuple(opportunities), coverages=coverages, account_id=11,
                admission=admission, case_registry=registry, current_case_admissions=tuple(admissions),
                goals=(goal,), coaching_scopes=(coaching,))


def current_args(args):
    return {k: args[k] for k in ('admission', 'case_registry', 'current_case_admissions')}


def test_real_default_keeps_census_denominators_but_has_no_authority():
    args = bundle()
    result = build_verified_history(**{k: v for k, v in args.items() if k not in current_args(args)})
    g = result.groups[0]
    assert g.eligible_count == 6 and g.assessed_count == 0 and g.unknown_count == 6
    assert g.error_rate_among_assessed is None and g.exercise is None
    assert g.complete_match_ids == () and g.action_rates == ()
    assert history_document(result)['portable_authority'] is False


def test_exact_external_branch_counts_full_denominator_counterexamples_and_cross_match_pattern():
    args = bundle()
    result = build_verified_history(**args)
    g = result.groups[0]
    assert g.assessed_count == 6 and g.error_count == 4 and g.unknown_count == 0
    assert g.assessment_coverage == 1 and g.complete_denominator_error_rate == 4/6
    assert len(g.counterexample_ids) == 2 and len(g.example_ids) == 4
    assert g.status == 'criterion_exercise_available' and g.exercise.goal_id == 'goal:1'
    assert g.cue_counts == (('noticed', 2), ('observable_attention_unknown', 4), ('not_observed', 0), ('unreal', 0), ('unknown', 0))
    assert g.action_rates == (('activate', 2, 6, 2/6), ('hold', 4, 6, 4/6))
    assert recheck_history(result, **current_args(args))['active_history_witness']
    assert history_document(result, **current_args(args))['strategic_quality'] == 'not_established'


def test_testing_case_witnesses_never_become_real_habit_even_with_admitted_census():
    args = bundle(external=False)
    g = build_verified_history(**args).groups[0]
    assert g.assessed_count == 0 and g.exercise is None


@pytest.mark.parametrize('field', ['match_hashes', 'coverage_hashes', 'source_hashes', 'goal_hashes', 'coaching_hashes'])
def test_current_history_registry_revocation_closes_cached_profile(field):
    args = bundle()
    result = build_verified_history(**args)
    changed = current_args(args) | {'admission': replace(args['admission'], **{field: frozenset()})}
    assert not recheck_history(result, **changed)['active_history_witness']
    document = history_document(result, **changed)
    assert document['status'] == 'insufficient_evidence' and document['groups'] == []


def test_current_case_release_and_admission_revocation_rechecked():
    args = bundle()
    result = build_verified_history(**args)
    assert not recheck_history(result, **(current_args(args) | {'current_case_admissions': ()}))['active_history_witness']
    registry = replace(args['case_registry'], admissions=())
    assert build_verified_history(**(args | {'case_registry': registry})).groups[0].assessed_count == 0


def test_copied_profiles_and_case_dtos_cannot_retain_witness():
    args = bundle()
    result = build_verified_history(**args)
    assert not recheck_history(replace(result), **current_args(args))['active_history_witness']
    one = replace(args['opportunities'][0], assessment=replace(args['opportunities'][0].assessment))
    altered = args | {'opportunities': (one,)+args['opportunities'][1:]}
    assert build_verified_history(**altered).groups[0].unknown_count == 1


def test_case_relabelled_as_two_opportunities_cannot_inflate_evidence():
    args = bundle()
    copied = replace(args['opportunities'][0], opportunity_id='another-id')
    with pytest.raises(ValueError, match='reused'):
        build_verified_history(**(args | {'opportunities': args['opportunities']+(copied,)}))


def test_mistakes_only_subset_does_not_have_complete_census():
    args = bundle()
    errors = tuple(o for o in args['opportunities'] if o.assessment.verdict == 'confirmed_error_within_criterion')
    g = build_verified_history(**(args | {'opportunities': errors})).groups[0]
    assert g.complete_match_ids == () and g.assessed_count == 0 and g.exercise is None


def test_errors_from_one_match_only_do_not_create_repeated_habit():
    args = bundle(errors=(3, 0))
    g = build_verified_history(**args).groups[0]
    assert g.error_count == 3 and g.assessed_count == 6 and g.exercise is None
    assert 'pattern_not_repeated_across_matches' in g.reason_codes


def test_foreign_account_relabel_and_source_copy_rejected():
    args = bundle()
    with pytest.raises(ValueError, match='subject identity'):
        replace(args['matches'][0].context, account_id=12)
    with pytest.raises(ValueError, match='foreign account'):
        build_verified_history(**(args | {'account_id': 12}))
    copied = replace(args['matches'][1], replay_sha256=args['matches'][0].replay_sha256,
                     source_refs=args['matches'][0].source_refs)
    with pytest.raises(ValueError, match='source copy'):
        build_verified_history(**(args | {'matches': (args['matches'][0], copied)}))


def test_empty_default_is_honest_deterministic_unavailable():
    result = build_verified_history((), (), account_id=11)
    doc = history_document(result)
    assert doc['status'] == 'insufficient_evidence' and not doc['groups']
    assert doc == history_document(result) and 'no_personal_history_supplied' in doc['reason_codes']


def portable(args):
    return json.loads(json.dumps({'schema_version': 'foresight.verified-history-input.v1', 'account_id': 11,
            'matches': [asdict(m) for m in args['matches']],
            'opportunities': [{**asdict(o), 'assessment': None} for o in args['opportunities']],
            'coverages': [asdict(c) for c in args['coverages']], 'goals': [asdict(g) for g in args['goals']]}))


def test_portable_json_never_imports_case_or_coaching_authority():
    args = bundle()
    payload = portable(args)
    loaded = load_verified_history_input(json.dumps(payload))
    result = build_verified_history(**loaded)
    assert result.groups[0].assessed_count == 0 and result.groups[0].exercise is None
    payload['opportunities'][0]['assessment'] = asdict(args['opportunities'][0].assessment)
    with pytest.raises(ValueError, match='portable assessments'):
        load_verified_history_input(payload)


@pytest.mark.parametrize('field', ['admission', 'case_registry', 'coaching_scopes', 'validated'])
def test_portable_authority_fields_are_rejected(field):
    payload = portable(bundle()) | {field: True}
    with pytest.raises(ValueError, match='portable grants'):
        load_verified_history_input(payload)


def test_duplicate_json_keys_and_nonfinite_feature_rejected():
    with pytest.raises(ValueError):
        load_verified_history_input('{"account_id":11,"account_id":12}')
    args = bundle()
    f = args['opportunities'][0].features[0]
    with pytest.raises(ValueError):
        replace(f, value=float('nan'))


def test_progress_requires_disjoint_chronological_comparable_current_measurements():
    baseline_args, followup_args = bundle(), bundle(mids=(9, 10), errors=(1, 1), start_day=5)
    a, b = baseline_args['admission'], followup_args['admission']
    admission = HistoryAdmission(a.match_hashes | b.match_hashes, a.coverage_hashes | b.coverage_hashes,
        a.source_hashes | b.source_hashes, a.goal_hashes | b.goal_hashes, coaching_hashes=a.coaching_hashes | b.coaching_hashes)
    cases = baseline_args['current_case_admissions']+followup_args['current_case_admissions']
    current = current_args(baseline_args) | {'admission': admission, 'current_case_admissions': cases}
    left = build_verified_history(**(baseline_args | current))
    right = build_verified_history(**(followup_args | current))
    result = compare_verified_progress(left, right, **current)
    assert result['status'] == 'comparable_descriptive_measurement'
    assert result['measurements'][0]['rate_delta'] == pytest.approx(-1/3)
    assert 'no_causal_coaching_effect' in result['interpretation']
    assert compare_verified_progress(left, left, **current)['status'] == 'insufficient_evidence'
    assert compare_verified_progress(right, left, **current)['status'] == 'insufficient_evidence'
    assert compare_verified_progress(replace(left), right, **current)['measurements'] == []


def test_study_defaults_unavailable_even_if_study_status_flags_look_verified():
    args = bundle()
    target = args['opportunities'][0]
    assert select_verified_study_episodes(target, ())['status'] == 'unavailable'
    assessment, registry, ca, scope, source = case(20, account=22, action='activate')
    context = replace(target.context, account_id=22, subject_ref='account:22')
    feature = replace(target.features[0], subject_ref='account:22', source_refs=(source,))
    opportunity = HistoryOpportunity('study-choice', 20, context, scope.at, 'eligible', 'noticed',
                                     (source,), assessment, (feature,), 'activate')
    match_source = MatchSource(20, 'https://example.org/matches/20', '2026-01-01T00:00:00Z', 'f'*64, 'verified')
    study = StudyMatch(20, 2, 'position:4', context.criterion.patch, (match_source,), 'available',
        'pro', ('actual-source-required',), ('episode:20',), 'Compare the scoped alternatives.', ('Scope transfer still limited.',), 'real')
    replay_source = replace(source, artifact_id='study-replay:20', content_hash=assessment.replay_hash, locator='replay:20')
    episode = StudyEpisode('episode:20', study, opportunity, (source, replay_source))
    assert select_verified_study_episodes(target, (episode,))['status'] == 'unavailable'
    admission = replace(args['admission'], study_hashes=frozenset((content_hash(episode),)),
                        source_hashes=args['admission'].source_hashes | {content_hash(match_source), content_hash(source), content_hash(replay_source)},
                        study_target_hashes=frozenset((content_hash(target),)))
    selection = select_verified_study_episodes(target, (episode,), admission=admission,
        case_registry=registry, current_case_admissions=args['current_case_admissions']+(ca,))
    assert selection['status'] == 'available'
    assert selection['episodes'][0]['scaled_mean_absolute_distance'] == 0
    changed = replace(feature, scale_max=2000)
    mismatched = replace(episode, opportunity=replace(opportunity, features=(changed,)))
    updated = replace(admission, study_hashes=frozenset((content_hash(mismatched),)))
    assert select_verified_study_episodes(target, (mismatched,), admission=updated, case_registry=registry,
        current_case_admissions=args['current_case_admissions']+(ca,))['status'] == 'unavailable'


def rebind_census(args, opportunities):
    coverages = tuple(replace(c, opportunity_hashes=tuple(content_hash(o) for o in opportunities
        if content_hash(next(m for m in args['matches'] if m.match_id == o.match_id)) == c.match_hash)) for c in args['coverages'])
    admission = replace(args['admission'], coverage_hashes=frozenset(content_hash(c) for c in coverages))
    return args | {'opportunities': opportunities, 'coverages': coverages, 'admission': admission}


def test_complete_ledger_retains_unknown_and_unreal_excluded_cases():
    args = bundle()
    template = args['opportunities'][0]
    unknown = replace(template, opportunity_id='unknown', eligibility='unknown', cue_status='unknown', assessment=None)
    excluded = replace(template, opportunity_id='unreal', eligibility='ineligible', cue_status='unreal', assessment=None)
    rebound = rebind_census(args, args['opportunities']+(unknown, excluded))
    g = build_verified_history(**rebound).groups[0]
    assert g.complete_match_ids == (7, 8)
    assert g.eligible_count == 6 and g.ineligible_count == 1 and g.unknown_count == 1
    assert g.assessed_count == 6 and dict(g.cue_counts)['unreal'] == 1 and dict(g.cue_counts)['unknown'] == 1
    assert g.complete_denominator_error_rate is None and g.exercise is None


@pytest.mark.parametrize('changed', ['clock', 'replay', 'goal'])
def test_actual_case_clock_replay_and_goal_binding_cannot_be_relabelled(changed):
    args = bundle()
    if changed == 'clock':
        first = replace(args['opportunities'][0], at=replace(args['opportunities'][0].at, game_time_ms=1100))
        args = rebind_census(args, (first,)+args['opportunities'][1:])
    elif changed == 'replay':
        first = args['matches'][0]
        source = replace(first.source_refs[0], content_hash='c'*64)
        replaced_match = replace(first, replay_sha256='c'*64, source_refs=(source,))
        coverage = replace(args['coverages'][0], match_hash=content_hash(replaced_match))
        admission = replace(args['admission'],
            match_hashes=frozenset((content_hash(replaced_match), content_hash(args['matches'][1]))),
            coverage_hashes=frozenset((content_hash(coverage), content_hash(args['coverages'][1]))),
            source_hashes=args['admission'].source_hashes | {content_hash(source)})
        args |= {'matches': (replaced_match, args['matches'][1]), 'coverages': (coverage, args['coverages'][1]), 'admission': admission}
    else:
        context = replace(args['matches'][0].context, minimum_hp_goal=150)
        matches = tuple(replace(m, context=context) for m in args['matches'])
        opportunities = tuple(replace(o, context=context) for o in args['opportunities'])
        coverages = tuple(replace(c, match_hash=content_hash(m), context_hash=content_hash(context))
                          for c, m in zip(args['coverages'], matches))
        admission = replace(args['admission'], match_hashes=frozenset(content_hash(m) for m in matches),
                            coverage_hashes=frozenset(content_hash(c) for c in coverages))
        args |= {'matches': matches, 'opportunities': opportunities, 'coverages': coverages, 'admission': admission}
        args = rebind_census(args, opportunities)
    g = build_verified_history(**args).groups[0]
    assert g.assessed_count < 6 and g.unknown_count > 0 and g.exercise is None


@pytest.mark.parametrize('clock', [TimeRef(1000,9,1,1e-14,'fixture.clock','verified'),
                                   TimeRef(1200, 12, 1, 0, 'fixture.clock', 'verified'),
                                   TimeRef(900, 12, 1, 0, 'fixture.clock', 'verified'),
                                   TimeRef(900, 9, 1, None, 'fixture.clock', 'unknown')])
def test_future_or_unknown_feature_availability_is_not_style_measurement(clock):
    args = bundle()
    first = args['opportunities'][0]
    future = replace(first.features[0], value=999, available_at=clock)
    changed = replace(first, features=(future,))
    rebound = rebind_census(args, (changed,)+args['opportunities'][1:])
    g = build_verified_history(**rebound).groups[0]
    assert g.feature_means[0][-1] == 5
    assert g.feature_means[0][-2] < 200


def test_partial_interval_cannot_claim_complete_census_even_exact_registry_hash():
    args = bundle()
    changed = replace(args['coverages'][0], end_ms=1900)
    admission = replace(args['admission'], coverage_hashes=frozenset((content_hash(changed), content_hash(args['coverages'][1]))))
    result = build_verified_history(**(args | {'coverages': (changed, args['coverages'][1]), 'admission': admission}))
    assert result.groups[0].complete_match_ids == (8,) and result.groups[0].exercise is None


@pytest.mark.parametrize('field', ['matches', 'opportunities', 'coverages', 'goals'])
def test_portable_malformed_rows_fail_with_value_error(field):
    payload = portable(bundle())
    payload[field] = [None]
    with pytest.raises(ValueError):
        load_verified_history_input(payload)


def test_declared_style_action_cannot_contradict_the_reviewed_case_choice():
    args=bundle()
    original=args['opportunities'][0]
    with pytest.raises(ValueError,match='contradicts'):
        replace(original,observed_action='activate' if original.observed_action=='hold' else 'hold')


@pytest.mark.parametrize('mapping',['','UNKNOWN',' unknown ','legacy/unknown'])
def test_reserved_clock_cannot_supply_known_style_features(mapping):
    args=bundle()
    original=args['opportunities'][0]
    at=replace(original.at,clock_mapping_version=mapping)
    feature=replace(original.features[0],available_at=replace(original.features[0].available_at,clock_mapping_version=mapping))
    from dota_coach.learning.verified_history import _feature_active
    assert not _feature_active(feature,replace(original,at=at),args['admission'])


def test_malformed_feature_row_is_a_controlled_portable_error():
    payload=portable(bundle())
    payload['opportunities'][0]['features']=[None]
    with pytest.raises(ValueError):load_verified_history_input(payload)


@pytest.mark.parametrize('field,value',[
    ('role_quality','unknown'),('role_quality','estimated'),('role','unknown'),
    ('role',' UNKNOWN '),('opponent_level_proxy','unknown'),('opponent_level_proxy','UNKNOWN'),
])
def test_matching_unknown_contexts_do_not_make_progress_comparable(field,value):
    def rebound(args):
        context=replace(args['matches'][0].context,**{field:value})
        matches=tuple(replace(m,context=context) for m in args['matches'])
        opportunities=tuple(replace(o,context=context) for o in args['opportunities'])
        coverages=tuple(replace(c,match_hash=content_hash(m),context_hash=content_hash(context),
            opportunity_hashes=tuple(content_hash(o) for o in opportunities if o.match_id==m.match_id))
            for c,m in zip(args['coverages'],matches))
        admission=replace(args['admission'],match_hashes=frozenset(content_hash(m) for m in matches),
            coverage_hashes=frozenset(content_hash(c) for c in coverages))
        return args|{'matches':matches,'opportunities':opportunities,'coverages':coverages,'admission':admission}
    baseline,followup=rebound(bundle()),rebound(bundle(mids=(9,10),errors=(1,1),start_day=5))
    a,b=baseline['admission'],followup['admission']
    admission=HistoryAdmission(a.match_hashes|b.match_hashes,a.coverage_hashes|b.coverage_hashes,
        a.source_hashes|b.source_hashes,a.goal_hashes|b.goal_hashes,coaching_hashes=a.coaching_hashes|b.coaching_hashes)
    current=current_args(baseline)|{'admission':admission,'current_case_admissions':baseline['current_case_admissions']+followup['current_case_admissions']}
    left=build_verified_history(**(baseline|current));right=build_verified_history(**(followup|current))
    result=compare_verified_progress(left,right,**current)
    assert result['status']=='insufficient_evidence' and result['measurements']==[]
    assert 'comparable_context_not_verified' in result['reason_codes']
