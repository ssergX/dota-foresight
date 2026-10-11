"""Synthetic contract checks; these fixtures do not validate Dota mechanics."""
from dataclasses import replace
import json

import pytest

from dota_coach.learning.habits import (
    AssessmentProof, OpportunityRecord, build_habit_evidence,
    build_coaching_plan, compare_progress,
)
from dota_coach.learning.study import MatchSource, StudyMatch, select_study_matches
from dota_coach.learning.builds import (
    BuildRule, ContextFact, PurchaseObservation, describe_purchase_sequence,
    evaluate_build_rule,
)
from dota_coach.learning.portfolio import build_descriptive_portfolio, load_study_catalog


def proof(verdict="confirmed_error_within_criterion", status="validated"):
    return AssessmentProof("assessment-test", verdict, "test-v1", "test-patch", "test-criterion", status,
                           ("test-registry-receipt",), ("test-fact",), "test-evaluator-v1")


def record(i, *, verdict="confirmed_error_within_criterion", eligibility="eligible",
           dataset="replay", status="validated", match_id=None):
    return OpportunityRecord(f"test-opportunity-{i}", match_id or (100 + i), "test-criterion",
                             "support", "test-patch", eligibility, proof(verdict, status), dataset)


def habit(records, *, matches=None, coverage="test-coverage", discovery="validated_complete", **kw):
    return build_habit_evidence(tuple(records), habit_id="test-habit", criterion_id="test-criterion",
                               criterion_version=kw.pop("criterion_version", "test-v1"),
                               role=kw.pop("role", "support"), patch=kw.pop("patch", "test-patch"),
                               match_ids=tuple(matches if matches is not None else sorted({r.match_id for r in records})),
                               coverage_signature=coverage, discovery_status=discovery, **kw)


def test_full_ledger_counts_unknown_ineligible_and_counterexamples():
    h = habit([record(1), record(2, verdict="good"), record(3, verdict="reasonable_options"),
               record(4, verdict="insufficient_evidence"), record(5, eligibility="unknown"),
               record(6, eligibility="ineligible")])
    assert (h.eligible_count, h.ineligible_count, h.assessed_count, h.unknown_count) == (4, 1, 3, 2)
    assert h.assessment_coverage == .75
    assert h.confirmed_error_rate_among_assessed == 1 / 3
    assert h.example_ids == ("test-opportunity-1",)
    assert h.counterexample_ids == ("test-opportunity-2", "test-opportunity-3")


@pytest.mark.parametrize("dataset,status", [("synthetic", "validated"), ("unknown", "validated"),
                                           ("replay", "synthetic"), ("replay", "unverified")])
def test_synthetic_or_unverified_assessments_cannot_train(dataset, status):
    h = habit([record(i, dataset=dataset, status=status) for i in range(1, 7)])
    assert h.assessed_count == 0 and h.unknown_count == 6
    p = build_coaching_plan(h)
    assert p.exercise is None and p.status == "insufficient_evidence"


def test_exercise_requires_repeated_confirmed_errors_and_counterexamples():
    h = habit([record(1), record(2), record(3), record(4, verdict="good"),
               record(5, verdict="reasonable_options")])
    p = build_coaching_plan(h)
    assert p.status == "exercise_available" and p.counterexample_ids
    assert build_coaching_plan(habit([record(i) for i in range(1, 6)])).exercise is None
    one_match = habit([record(i, match_id=100) for i in range(1, 6)])
    assert "pattern_not_observed_across_matches" in build_coaching_plan(one_match).reason_codes


def test_partial_discovery_does_not_turn_selected_errors_into_a_habit():
    h = habit([record(i) for i in range(1, 7)], discovery="partial")
    assert build_coaching_plan(h).status == "insufficient_evidence"
    assert "opportunity_discovery_not_validated_complete" in h.reason_codes


def test_empty_ledger_has_unknown_rates_and_no_exercise():
    h = habit([], matches=(100,), coverage="", discovery="unavailable")
    assert h.assessment_coverage is None and h.confirmed_error_rate_among_assessed is None
    assert build_coaching_plan(h).exercise is None


def test_record_scope_duplicate_and_immutable_checks():
    with pytest.raises(ValueError, match="duplicate"):
        habit([record(1), record(1)])
    with pytest.raises(ValueError, match="outside"):
        habit([replace(record(1), role="carry")])
    with pytest.raises(TypeError, match="immutable"):
        build_habit_evidence([], habit_id="a", criterion_id="c", criterion_version="v",
                             role="r", patch="p", match_ids=(), coverage_signature="")
    with pytest.raises(ValueError):
        replace(record(1), match_id=True)
    with pytest.raises(ValueError, match="validation"):
        replace(proof(), validation_refs=())


def test_progress_disjoint_periods_reports_change_without_causal_claim():
    a = habit([record(1), record(2), record(3, verdict="good")])
    b = habit([record(4, verdict="good"), record(5, verdict="reasonable_options")])
    progress = compare_progress(a, b)
    assert progress.status == "comparable" and progress.rate_delta == -2 / 3
    assert "причинный эффект" in progress.interpretation
    assert "исправление привычки не установлены" in progress.interpretation


def test_progress_overlap_unknown_and_rebaseline_gates():
    a = habit([record(1)])
    assert compare_progress(a, a).rate_delta is None
    assert "overlapping_match_sets" in compare_progress(a, a).reason_codes
    b = habit([record(2)], coverage="changed")
    assert compare_progress(a, b).status == "rebaseline_required"
    b = habit([record(2, verdict="insufficient_evidence")])
    assert compare_progress(a, b).status == "insufficient_evidence"
    b = habit([replace(record(2), assessment=replace(proof(), evaluator_version="test-v2"))])
    assert compare_progress(a, b).status == "rebaseline_required"


def source(mid=8001):
    return MatchSource(mid, f"https://www.opendota.com/matches/{mid}",
                       "2026-10-05T10:00:00Z", "0" * 64, "verified")


def study(mid=8001):
    return StudyMatch(mid, 1, "support", "test-patch", (source(mid),), "available", "high_mmr",
                      ("test-rank-source",), ("test-episode",), "Сравни альтернативы в эпизоде.",
                      ("Проверь различия контекста.",), "real")


def select(catalog):
    return select_study_matches(tuple(catalog), hero_id=1, role="support", patch="test-patch")


def test_no_catalog_returns_unavailable_without_invented_match():
    result = select([])
    assert result.status == "unavailable" and result.matches == ()


def test_study_real_source_link_and_suitable_context_gate():
    result = select([study(8002), study(8001)])
    assert [m.match_id for m in result.matches] == [8001, 8002]
    excluded = select([replace(study(), dataset_kind="synthetic")])
    assert not excluded.matches and "real_match_source_not_verified" in excluded.exclusions[0][1]
    for changed in (replace(study(), role="carry"), replace(study(), patch="other"),
                    replace(study(), replay_availability="unknown"), replace(study(), episode_refs=())):
        assert select([changed]).status == "unavailable"


def test_source_verification_cannot_be_inferred_from_url_alone():
    unverified = MatchSource(8001, "https://www.opendota.com/matches/8001", "", "")
    assert select([replace(study(), sources=(unverified,))]).matches == ()
    for url in ("javascript:alert(8001)", "https://www.opendota.com/matches/8002",
                "https://user:secret@example.com/matches/8001"):
        with pytest.raises(ValueError):
            replace(source(), url=url)
    with pytest.raises(ValueError):
        replace(source(), checked_at="2026-10-05T10:00:00")
    with pytest.raises(ValueError):
        replace(source(), content_sha256="fake")


def test_purchase_sequence_descriptive_not_popularity_optimality():
    a = PurchaseObservation(8001, "item-test-a", 20., source(), "purchase1")
    b = PurchaseObservation(8001, "item-test-b", -1., source(), "purchase2")
    result = describe_purchase_sequence((a, b))
    assert result.purchases == (b, a) and result.temporal_order == "known"
    assert result.optimality == "not_established"
    assert describe_purchase_sequence((a, replace(b, game_time_seconds=None))).temporal_order == "partial"
    assert describe_purchase_sequence((a, replace(b, game_time_seconds=20))).temporal_order == "partial"
    assert describe_purchase_sequence(()).status == "unavailable"


def rule():
    return BuildRule("test-rule", "test-v1", "test-patch", 1, "support",
                     (("goal", "test-goal"),), ("test-option-a", "test-option-b"),
                     ("Test cost versus test benefit.",), ("Recheck when goal changes.",),
                     ("test-mechanics-source",), "validated", ("test-validation",))


def evaluate(r, facts):
    return evaluate_build_rule(r, tuple(facts), patch="test-patch", hero_id=1, role="support")


def test_build_unvalidated_missing_context_and_wrong_scope_abstain():
    fact = ContextFact("goal", "test-goal", "known", ("test-goal-source",))
    assert evaluate(replace(rule(), validation_status="unverified"), [fact]).options == ()
    assert evaluate(rule(), []).status == "insufficient_evidence"
    assert evaluate_build_rule(rule(), (fact,), patch="other", hero_id=1, role="support").options == ()
    assert evaluate(rule(), [replace(fact, value="other")]).status == "not_applicable"


def test_build_conditional_options_include_tradeoffs_and_revisit_without_optimality():
    result = evaluate(rule(), [ContextFact("goal", "test-goal", "known", ("test-goal-source",))])
    assert result.status == "conditional_analysis" and len(result.options) == 2
    assert result.tradeoffs and result.revisit_conditions and "test-goal-source" in result.evidence_refs
    assert result.optimality == "not_established"


def test_context_fact_type_prevents_boolean_numeric_confusion():
    r = replace(rule(), conditions=(("count", 1),))
    assert evaluate(r, [ContextFact("count", True, "known", ("test-source",))]).status == "not_applicable"
    with pytest.raises(ValueError):
        ContextFact("goal", "invented", "unknown", ())
    with pytest.raises(ValueError):
        replace(rule(), mechanics_refs=())


def test_raw_match_portfolio_does_not_equate_lane_role_with_player_role():
    raw = {"match_id": 8001, "patch": 99, "players": [
        {"account_id": 111, "hero_id": 1, "lane_role": 1,
         "purchase_log": [{"key": "test-item", "time": 10}]}]}
    profile = build_descriptive_portfolio(raw, 111)
    assert profile.hero_id == 1 and profile.role == "unknown" and profile.lane_role == 1
    assert profile.patch == "opendota_patch_id:99"
    assert profile.purchases.status == "descriptive"
    assert profile.purchases.purchases[0].source.status == "unverified"
    assert profile.purchases.optimality == "not_established"


def test_raw_match_missing_purchase_log_is_not_empty_confirmed_build():
    raw = {"match_id": 8001, "players": [{"account_id": 111}]}
    profile = build_descriptive_portfolio(raw, 111)
    assert profile.purchases.status == "unavailable" and profile.hero_id is None
    assert "purchase_log_unavailable" in profile.reason_codes
    with pytest.raises(ValueError):
        build_descriptive_portfolio(raw, 222)
    with pytest.raises(ValueError):
        build_descriptive_portfolio({**raw, "players": raw["players"] * 2}, 111)


def test_catalog_import_does_not_trust_external_verified_or_expert_claims():
    raw = {"match_id": 8001, "hero_id": 1, "role": "support", "patch": "test-patch",
           "sources": [{"url": "https://www.opendota.com/matches/8001", "status": "verified",
                        "checked_at": "2026-10-05T10:00:00Z", "content_sha256": "0" * 64}],
           "expertise_status": "pro", "expertise_evidence_refs": ["test-source"],
           "dataset_kind": "real", "replay_availability": "available",
           "episode_refs": ["test-episode"], "learning_task": "Сравни альтернативы."}
    imported = load_study_catalog(json.dumps([raw]))
    match = imported.matches[0]
    assert match.sources[0].status == "unverified" and match.expertise_status == "unknown"
    assert match.dataset_kind == "unknown" and match.replay_availability == "unknown"
    assert imported.warnings and select(imported.matches).status == "unavailable"


@pytest.mark.parametrize("text", [
    '{"schema_version":"other","matches":[]}',
    '[{"match_id":8001,"match_id":8002}]',
    '[{"match_id":8001,"hero_id":1,"role":"support","patch":"p","hidden_payload":{}}]',
    '[{"match_id":true,"hero_id":1,"role":"support","patch":"p"}]',
    '[{"match_id":8001,"hero_id":1,"role":"support","patch":"p","sources":[{"url":"javascript:alert(8001)"}]}]',
    '[{"match_id":NaN}]',
])
def test_catalog_import_rejects_bad_or_ambiguous_input(text):
    with pytest.raises(ValueError):
        load_study_catalog(text)


def test_catalog_import_envelope_and_immutable_arrays():
    text = json.dumps({"schema_version": "study-catalog.v1", "matches": [
        {"match_id": 8001, "hero_id": 1, "role": "support", "patch": "p",
         "episode_refs": ["test-episode"]}]})
    imported = load_study_catalog(text)
    assert isinstance(imported.matches, tuple) and imported.matches[0].episode_refs == ("test-episode",)
