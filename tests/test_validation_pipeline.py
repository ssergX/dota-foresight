from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest

from dota_coach.decisions.contracts import ActionObservation, DecisionBoundary, DecisionInput
from dota_coach.decisions.evaluator import ActivationInput, BOUND_PREDICATES, CONDITIONS
from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, content_hash
from dota_coach.evidence.knowledge import project_knowledge
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState
from dota_coach.validation import (ActionCheck, Annotation, DatasetRecord, FactCheck, Prediction,
                                   audit_splits, blind_case, evaluate_predictions, export_blind_pack,
                                   interrater_report, load_annotations, load_dataset, load_predictions,
                                   validate_annotations, write_annotations, write_dataset)


def record(i=1, *, split="holdout", player=None, dataset_kind="replay"):
    return DatasetRecord(f"d{i}", content_hash(("input", i)), i, content_hash(("replay", i)),
                         player or f"player{i}", "fixture-patch", split, dataset_kind)


def label(r, verdict="good", *, expert="expert1", eligibility="eligible", **kwargs):
    unknowns = ("unverified_cue",) if verdict == "insufficient_evidence" or eligibility == "unknown" else ()
    checks = (FactCheck("f1", "correct", "available", "Checked against blinded prefix"),)
    actions = (ActionCheck("activate", "feasible", ("f1",), "Control available"),
               ActionCheck("hold", "feasible", ("f1",), "Can preserve"))
    return Annotation(r.decision_id, r.input_hash, r.replay_hash, r.patch, expert, (verdict,),
                      eligibility, "Independent blinded rationale", facts_checked=checks,
                      available_actions=actions, decisive_evidence_ids=("f1",),
                      unknowns=unknowns, dataset_kind=r.dataset_kind, **kwargs)


def independent(r, verdict="good", **kwargs):
    return [label(r, verdict, expert=f"expert{i}", **kwargs) for i in (1, 2)]


def prediction(r, verdict):
    return Prediction(r.decision_id, r.input_hash, verdict, "fixture-evaluator.v1")


def safe_input():
    replay = ParsedReplay(1, 0, {0: "Own", 5: "Enemy"}, [ReplayFrame(
        10, {0: UnitState(0, 0, 0, 100, 100, 50, 1, 0, True),
             5: UnitState(5, 9000, 9000, 1, 100, 0, 1, 0, False)})], teams={0: 2, 5: 3})
    return DecisionInput("d1", project_knowledge(replay, 10, 0),
                         DecisionBoundary("b1", TimeRef(10000), "resolved", "expert", ("e1",)),
                         ActionObservation("activation_commit", "activation", "complete", ("e1",)),
                         "defensive_activation.v1", "fixture.v1")


def activation_input():
    time = TimeRef(10000, replay_tick=300, sequence_in_tick=1, uncertainty_ms=0,
                   clock_mapping_version="synthetic.clock.v1", order_status="verified")
    source = SourceRef("blind-prefix", content_hash("prefix"), "fixture", "v1", "raw/hidden-state.json")
    predicates = CONDITIONS + BOUND_PREDICATES
    values = (True, True, True, True, 10, 20, 0, 5)
    facts = tuple(Fact(f"f{i}", "self", predicate, value, "observed", time, time,
                       "screen" if predicate.startswith(("self.", "screen.")) else "public",
                       (source,), observer_ref="self", method_version="fixture.v1")
                  for i, (predicate, value) in enumerate(zip(predicates, values)))
    return ActivationInput("d1", 1, "self", "fixture-patch", "fixture.v1",
                           DecisionBoundary("b1", time, "resolved", "expert", ("e1",)),
                           ActionObservation("activation_commit", "activation", "complete", ("e1",)),
                           facts[:4], facts[4:], "synthetic")


def test_same_match_different_subject_cannot_cross_splits():
    a, b = record(split="development"), record(2)
    b = replace(b, match_id=a.match_id, replay_hash=a.replay_hash)
    audit = audit_splits([a, b])
    assert not audit["valid"]
    assert "match_crosses_splits:1" in audit["issues"]
    assert any(issue.startswith("source_copy_crosses_splits:") for issue in audit["issues"])


def test_source_copy_different_match_id_and_target_leakage_are_detected():
    a, b = record(split="calibration"), record(2, player="player1")
    b = replace(b, replay_hash=a.replay_hash)
    audit = audit_splits([a, b], retrieval_match_ids=[2], training_player_ids=["player1"])
    assert not audit["valid"]
    assert "target_player_crosses_locked_split:player1" in audit["issues"]
    assert "training_or_retrieval_match_leakage:2" in audit["issues"]
    assert any(issue.startswith("source_hash_reused") for issue in audit["issues"])


def test_target_disjoint_is_not_misrepresented_as_all_player_disjoint():
    common = "opponent"
    a = replace(record(split="development"), participants=tuple(["player1", common] + [f"a{i}" for i in range(8)]))
    b = replace(record(2), participants=tuple(["player2", common] + [f"b{i}" for i in range(8)]))
    minimal = audit_splits([a, b])
    assert minimal["valid"] and minimal["independence_scope"] == "target_player_disjoint"
    strict = audit_splits([a, b], require_all_player_disjoint=True)
    assert not strict["valid"]
    assert "participant_crosses_locked_split:opponent" in strict["issues"]


def test_longitudinal_same_player_allowed_without_reusing_matches():
    records = [record(1, split="longitudinal_baseline", player="same"),
               record(2, split="longitudinal_followup", player="same")]
    assert audit_splits(records)["valid"]


def test_synthetic_locked_holdout_is_invalid_and_duplicates_rejected():
    synthetic = record(dataset_kind="synthetic")
    assert not audit_splits([synthetic])["valid"]
    with pytest.raises(ValueError, match="duplicate decision"):
        audit_splits([synthetic, synthetic])


def test_completed_annotations_require_explicit_blinding_and_reasons():
    r = record()
    with pytest.raises(ValueError, match="precede outcome"):
        label(r, outcome_visible=True)
    with pytest.raises(ValueError, match="explicit booleans"):
        label(r, outcome_visible="false")
    with pytest.raises(ValueError, match="unknown eligibility"):
        replace(label(r), eligibility="unknown", unknowns=())
    with pytest.raises(ValueError, match="assessed label"):
        replace(label(r), facts_checked=())
    with pytest.raises(ValueError, match="two checked"):
        replace(label(r, "reasonable_options"), available_actions=label(r).available_actions[:1])
    with pytest.raises(ValueError, match="SHA-256"):
        replace(label(r), input_hash="a guessed hash")


def test_annotation_input_and_revision_chains_are_bound_to_manifest():
    r = record()
    first = label(r)
    second = replace(first, annotation_version=2, previous_annotation_hash=first.annotation_hash,
                     revision_reason="Independent prefix correction", rationale="Rechecked rationale")
    assert validate_annotations([first, second], [r])["record_count"] == 2
    with pytest.raises(ValueError, match="chain"):
        validate_annotations([second], [r])
    with pytest.raises(ValueError, match="chain"):
        validate_annotations([first, replace(second, previous_annotation_hash=content_hash("wrong"))], [r])
    with pytest.raises(ValueError, match="input_hash"):
        validate_annotations([replace(first, input_hash=content_hash("other input"))], [r])
    with pytest.raises(ValueError, match="duplicate annotation"):
        validate_annotations([first, first], [r])


def test_annotation_evidence_must_belong_to_blinded_input():
    decision = safe_input()
    r = replace(record(), input_hash=decision.input_hash)
    a = label(r)
    with pytest.raises(ValueError, match="unknown fact"):
        validate_annotations([a], [r], [decision])
    f = decision.knowledge.facts[0]
    a = replace(a, facts_checked=(FactCheck(f.fact_id, "correct", "available", "Checked"),),
                available_actions=(ActionCheck("activation", "feasible", (f.fact_id,), "Checked"),),
                decisive_evidence_ids=(f.fact_id,))
    validate_annotations([a], [r], [decision])
    with pytest.raises(ValueError, match="outside blinded"):
        validate_annotations([replace(a, decisive_evidence_ids=("future-death",))], [r], [decision])


def test_blind_export_omits_world_state_outcomes_and_raw_artifact_links(tmp_path):
    decision = safe_input()
    r = replace(record(), input_hash=decision.input_hash, dataset_kind="synthetic")
    result = export_blind_pack([decision], [r], tmp_path)
    assert result["case_count"] == 1 and result["validation_status"] == "data_validation_pending"
    text = (tmp_path / "blind-cases.jsonl").read_text(encoding="utf-8")
    assert "9000" not in text and "enemy.hp" not in text
    assert "source_refs" not in text and "locator" not in text
    case = json.loads(text)
    assert not {"verdict", "assessment", "outcome", "deaths", "gold_delta"} & case.keys()
    assert case["input_hash"] == decision.input_hash
    with pytest.raises((ValueError, TypeError), match="template|nonempty"):
        load_annotations(tmp_path / "annotation-template.jsonl")


def test_experimental_activation_blind_pack_retains_only_allowed_fact_payload(tmp_path):
    value = activation_input()
    case = blind_case(value)
    assert case["conditions"][0]["predicate"] == "self.activation_feasible"
    assert "utility_bounds" not in case
    assert case["withheld_derived_assessment"] is True
    assert "criterion.activate_lower" not in json.dumps(case)
    assert "criterion.hold_upper" not in json.dumps(case)
    assert all(type(fact["value"]) is bool for fact in case["conditions"])
    assert "raw/hidden-state.json" not in json.dumps(case)
    r = replace(record(), input_hash=value.input_hash, dataset_kind="synthetic")
    export_blind_pack([value], [r], tmp_path)
    with pytest.raises(ValueError, match="scoped input"):
        export_blind_pack([value], [replace(r, patch="wrong")], tmp_path / "bad")
    with pytest.raises(TypeError, match="typed"):
        blind_case(asdict(value))


def test_blind_pack_rejects_hash_and_population_mismatch_before_writing(tmp_path):
    with pytest.raises(ValueError, match="hash"):
        export_blind_pack([safe_input()], [record()], tmp_path)
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match="exactly one"):
        export_blind_pack([safe_input()], [], tmp_path)


def test_jsonl_roundtrip_and_duplicate_key_rejection(tmp_path):
    r = record()
    dataset_path, annotation_path = tmp_path / "dataset.jsonl", tmp_path / "annotations.jsonl"
    write_dataset(dataset_path, [r])
    write_annotations(annotation_path, [label(r)])
    assert load_dataset(dataset_path) == (r,)
    assert load_annotations(annotation_path) == (label(r),)
    annotation_path.write_text('{"decision_id":"d1","decision_id":"hidden"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_annotations(annotation_path)
    dataset_path.write_text(json.dumps(asdict(r) | {"participants": "player1"}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        load_dataset(dataset_path)


def test_quality_metrics_keep_unknown_and_missing_predictions_in_denominators():
    records = [record(i) for i in range(1, 6)]
    annotations = [*independent(records[0]),
                   *independent(records[1], "confirmed_error_within_criterion"),
                   *independent(records[2], "insufficient_evidence", eligibility="unknown"),
                   *independent(records[3])]
    predictions = [prediction(records[0], "mistake"), prediction(records[1], "insufficient_evidence"),
                   prediction(records[2], "mistake"), prediction(records[4], "mistake")]
    result = evaluate_predictions(predictions, annotations, records)
    metrics = result["metrics"]
    assert metrics["assessment_coverage"]["numerator"] == 1
    assert metrics["assessment_coverage"]["denominator"] == 3
    assert metrics["assessment_coverage"]["unknown_count"] == 2
    assert metrics["false_discovery_among_accusations"]["numerator"] == 2
    assert metrics["false_discovery_among_accusations"]["denominator"] == 2
    assert metrics["false_discovery_among_accusations"]["unknown_count"] == 1
    assert metrics["false_positive_rate"]["numerator"] == 1
    assert metrics["false_positive_rate"]["denominator"] == 2
    assert metrics["missed_assessable_cases"]["numerator"] == 2
    assert metrics["missed_assessable_cases"]["denominator"] == 3
    assert result["cohort"]["match_count"] == 5
    assert result["counts"]["missing_predictions"] == 1
    assert metrics["agreement_with_acceptable_sets"]["confidence_interval"] is None
    assert result["release_gate"] == "not_evaluated"


def test_synthetic_self_labels_and_single_rater_do_not_inflate_real_accuracy():
    real, synthetic, self_only = record(), record(2, dataset_kind="synthetic"), record(3)
    annotations = [label(real), *independent(synthetic),
                   label(self_only, annotator_kind="self_evaluation"),
                   label(self_only, expert="system", annotator_kind="system")]
    predictions = [prediction(r, "good") for r in [real, synthetic, self_only]]
    result = evaluate_predictions(predictions, annotations, [real, synthetic, self_only])
    assert result["cohort"]["expert_reviewed_decision_count"] == 0
    assert result["metrics"]["agreement_with_acceptable_sets"]["rate"] is None
    assert result["metrics"]["assessment_coverage"]["denominator"] == 0
    assert result["excluded_annotations"] == {"non_human": 2, "non_replay": 2}
    assert result["validation_status"] != "validated"
    with pytest.raises(ValueError, match="two raters"):
        evaluate_predictions(predictions, annotations, [real, synthetic, self_only], min_raters=1)


def test_interrater_incompatible_sets_excluded_from_consensus_and_aliases_agree():
    a, b = record(), record(2)
    annotations = [label(a), label(a, "probable_error", expert="expert2"),
                   label(b, "good"), label(b, "good_decision", expert="expert2")]
    report = interrater_report(annotations, [a, b])
    assert report["incompatible_verdict_pairs"] == 1
    assert report["disputed_decision_ids"] == [a.decision_id]
    quality = evaluate_predictions([prediction(a, "probable_error"), prediction(b, "good_decision")],
                                   annotations, [a, b])
    assert quality["counts"]["disputed_reference"] == 1
    assert quality["metrics"]["agreement_with_acceptable_sets"]["rate"] == 1


def test_prediction_hash_duplicate_and_version_pooling_are_rejected(tmp_path):
    a, b = record(), record(2)
    good = prediction(a, "good")
    for bad in ([good, good], [replace(good, input_hash=content_hash("wrong"))],
                [good, replace(prediction(b, "good"), evaluator_version="different")]):
        with pytest.raises(ValueError):
            evaluate_predictions(bad, [], [a, b])
    path = tmp_path / "predictions.jsonl"
    path.write_text(json.dumps(asdict(good)) + "\n", encoding="utf-8")
    assert load_predictions(path) == (good,)


def test_unknown_eligibility_and_warranted_abstention_remain_distinct():
    r = record()
    annotations = independent(r, "insufficient_evidence", eligibility="unknown")
    result = evaluate_predictions([prediction(r, "insufficient_evidence")], annotations, [r])
    assert result["metrics"]["assessment_coverage"]["rate"] is None
    assert result["metrics"]["warranted_abstention"]["rate"] == 1
    assert result["counts"]["eligibility_unknown"] == 1


def test_blinded_labels_cannot_use_withheld_model_utility_as_decisive_evidence():
    value = activation_input()
    r = replace(record(), input_hash=value.input_hash, dataset_kind="synthetic")
    a = replace(label(r), facts_checked=(FactCheck("f0", "correct", "available", "Checked"),),
                available_actions=(ActionCheck("activate", "feasible", ("f0",), "Checked"),),
                decisive_evidence_ids=("f4",))
    with pytest.raises(ValueError, match="outside blinded"):
        validate_annotations([a], [r], [value])
    # A later extraction pass can inspect the withheld judgments, independently
    # of the frozen decision label.
    validate_annotations([replace(a, review_pass="extraction")], [r], [value])


def test_not_actionable_is_exclusion_not_an_assessed_grade():
    r = record()
    annotations = independent(r)
    result = evaluate_predictions([prediction(r, "not_actionable")], annotations, [r])
    assert result["metrics"]["assessment_coverage"]["numerator"] == 0
    assert result["metrics"]["missed_assessable_cases"]["numerator"] == 1
    with pytest.raises(ValueError, match="ineligible"):
        label(r, "not_actionable")


def test_three_raters_can_have_pairwise_overlap_without_a_common_consensus():
    r = record()
    annotations = [replace(label(r, "reasonable_options", expert="expert1"),
                           acceptable_verdicts=("reasonable_options", "good")),
                   replace(label(r, "reasonable_options", expert="expert2"),
                           acceptable_verdicts=("reasonable_options", "probable_error")),
                   replace(label(r, expert="expert3"), acceptable_verdicts=("good", "probable_error"))]
    report = interrater_report(annotations, [r])
    assert report["incompatible_verdict_pairs"] == 0
    assert report["multi_rater_no_common_verdict_decisions"] == 1
    assert report["disputed_decision_ids"] == [r.decision_id]
    quality = evaluate_predictions([prediction(r, "good")], annotations, [r])
    assert quality["metrics"]["agreement_with_acceptable_sets"]["denominator"] == 0
