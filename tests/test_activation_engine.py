from dataclasses import asdict, replace
import json
import pytest

from dota_coach.decisions.contracts import ActionObservation, DecisionBoundary
from dota_coach.decisions.evaluator import (ActivationInput, CriterionScope, CONDITIONS,
    BOUND_PREDICATES, REQUIRED_CAPABILITIES, evaluate_activation, explain_evaluation)
from dota_coach.decisions.batch import read_batch, evaluate_batch, write_batch_report
from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef


def activation(kind="observed_no_activation", bounds=(5, 7, 1, 3)):
    clock = TimeRef(1000, 30, 1, 0, "synthetic.clock.v1", "verified")
    source = SourceRef("synthetic-projection", "a" * 64, "synthetic", "v1", "decision@1000")
    predicates = CONDITIONS + BOUND_PREDICATES
    facts = tuple(Fact(str(n), "player:0", p, v, "derived", clock, clock,
                      "screen", (source,), observer_ref="player:0", method_version="test.rubric.v1")
                  for n, (p, v) in enumerate(zip(predicates, (True, True, True, True) + bounds)))
    return ActivationInput("decision:1", 1, "player:0", "synthetic-patch", "test.rubric.v1",
        DecisionBoundary("choice:1", clock, "resolved", "synthetic-clock", ("event:1",)),
        ActionObservation(kind, "defense", "complete", ("event:1",)), facts[:4], facts[4:], "synthetic")


def scope(mode="experimental"):
    return CriterionScope("synthetic-patch", "test.rubric.v1", REQUIRED_CAPABILITIES,
                          ("synthetic-rubric",), mode, acceptable_floor=0)


@pytest.mark.parametrize("kind,bounds,verdict", [
    ("observed_no_activation", (5, 7, 1, 3), "mistake"),
    ("activation_commit", (5, 7, 1, 3), "good_decision"),
    ("activation_commit", (1, 3, 5, 7), "mistake"),
    ("observed_no_activation", (1, 3, 5, 7), "good_decision"),
    ("activation_commit", (1, 5, 3, 7), "reasonable_alternative"),
    ("observed_no_activation", (3, 5, 1, 3), "reasonable_alternative"),
])
def test_bounded_dominance(kind, bounds, verdict):
    result = evaluate_activation(activation(kind, bounds), scope())
    assert result.verdict == verdict
    assert result.validation_status == "unverified" and result.training_eligible is False
    assert result.claims[0].evidence_ids
    assert explain_evaluation(result)


def test_default_gate_and_self_promotion():
    assert evaluate_activation(activation(), scope("disabled")).verdict == "insufficient_evidence"
    with pytest.raises(ValueError):
        replace(scope(), mode="validated")


@pytest.mark.parametrize("index", range(8))
def test_remove_evidence_abstains(index):
    value = activation()
    fs = list(value.conditions + value.utility_bounds)
    fs[index] = replace(fs[index], status="unknown", value=None, unknown_reason="missing", source_refs=())
    value = replace(value, conditions=tuple(fs[:4]), utility_bounds=tuple(fs[4:]))
    assert evaluate_activation(value, scope()).verdict == "insufficient_evidence"


def test_team_cue_future_world_and_nested_rejected():
    value = activation()
    for changed in (replace(value.conditions[2], perspective="team"),
                    replace(value.conditions[2], available_at=TimeRef(1001, uncertainty_ms=0)),
                    replace(value.conditions[2], perspective="world")):
        with pytest.raises(ValueError):
            replace(value, conditions=value.conditions[:2] + (changed,) + value.conditions[3:])
    with pytest.raises(ValueError):
        replace(value.utility_bounds[0], value={"enemy_position": 1})


def test_command_is_not_activation_and_infeasible_not_error():
    value = activation("accepted_command")
    assert evaluate_activation(value, scope()).verdict == "insufficient_evidence"
    value = activation()
    value = replace(value, conditions=(replace(value.conditions[0], value=False),) + value.conditions[1:])
    assert evaluate_activation(value, scope()).verdict == "not_actionable"
    conflict = replace(value, action=replace(value.action, kind="activation_commit"))
    assert evaluate_activation(conflict, scope()).verdict == "insufficient_evidence"


def test_stable_window_and_player_cue_required():
    for index in (2, 3):
        value = activation()
        fs = list(value.conditions)
        fs[index] = replace(fs[index], value=False)
        assert evaluate_activation(replace(value, conditions=tuple(fs)), scope()).verdict == "insufficient_evidence"


def test_same_tick_future_and_uncertain_anchor_rejected():
    value = activation()
    with pytest.raises(ValueError):
        replace(value, conditions=(replace(value.conditions[0], available_at=
            replace(value.boundary.anchor, sequence_in_tick=2)),) + value.conditions[1:])
    for anchor in (replace(value.boundary.anchor, uncertainty_ms=1),
                   replace(value.boundary.anchor, order_status="unknown")):
        with pytest.raises(ValueError):
            replace(value, boundary=replace(value.boundary, anchor=anchor))


def test_overlapping_intervals_do_not_establish_reasonableness():
    value = activation(bounds=(1, 5, 3, 7))
    assert evaluate_activation(value, replace(scope(), acceptable_floor=None)).verdict == "insufficient_evidence"
    assert evaluate_activation(value, replace(scope(), acceptable_floor=2)).verdict == "insufficient_evidence"


def batch_dict():
    return {"schema_version": "foresight.activation-batch.v1", "scope": {
        "patch": "synthetic-patch", "criterion_version": "test.rubric.v1",
        "capabilities": list(REQUIRED_CAPABILITIES), "rubric_source_ids": ["synthetic-rubric"]},
        "discovery_status": "partial", "decisions": [asdict(activation())], "exclusions": [
            {"opportunity_id": "unknown:1", "match_id": 1, "eligibility": "unknown", "reason_codes": ["gap"]},
            {"opportunity_id": "ineligible:1", "match_id": 1, "eligibility": "ineligible", "reason_codes": ["disable"]}]}


def test_full_supplied_ledger_and_reproducibility(tmp_path):
    batch = read_batch(json.dumps(batch_dict()), experimental=True)
    result = evaluate_batch(batch)
    assert (result["supplied_opportunities"], result["experimental_assessed"],
            result["unknown"], result["ineligible"]) == (3, 1, 1, 1)
    assert result["validated_assessed"] == 0 and result["population_coverage"] is None
    assert write_batch_report(batch, str(tmp_path)) == result
    assert (tmp_path / "index.html").exists()
    disabled = read_batch(json.dumps(batch_dict()))
    assert evaluate_batch(disabled)["unknown"] == 2


def test_batch_cannot_accept_outcome_or_claim_complete():
    d = batch_dict()
    d["decisions"][0]["radiant_win"] = True
    with pytest.raises(ValueError):
        read_batch(json.dumps(d), True)
    del d["decisions"][0]["radiant_win"]
    d["discovery_status"] = "complete"
    with pytest.raises(ValueError):
        read_batch(json.dumps(d), True)
    with pytest.raises(ValueError):
        read_batch('{"schema_version":"a","schema_version":"b"}')


@pytest.mark.parametrize("field,value", [("opportunity_id", 17), ("reason_codes", "gap"),
                                         ("reason_codes", [17])])
def test_exclusion_types_rejected_at_import(field, value):
    d = batch_dict()
    d["exclusions"][0][field] = value
    with pytest.raises(ValueError):
        read_batch(json.dumps(d))


def test_boundary_references_cannot_be_a_string():
    d = batch_dict()
    d["decisions"][0]["boundary"]["resolution_evidence_ids"] = "event:1"
    with pytest.raises(ValueError):
        read_batch(json.dumps(d))


def test_changed_rubric_provenance_invalidates_assessment_revision():
    value = activation()
    before = evaluate_activation(value, scope())
    revised_scope = replace(scope(), rubric_source_ids=("revised-synthetic-rubric",))
    after = evaluate_activation(value, revised_scope)
    assert before.input_hash == after.input_hash
    assert before.verdict == after.verdict
    assert before.scope_hash != after.scope_hash
    assert before.assessment_hash != after.assessment_hash
