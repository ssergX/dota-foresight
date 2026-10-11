"""Review UI tests use synthetic fixtures; no fixture is written to a real pack."""
import json

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.validation.pipeline import load_annotations
from dota_coach.validation.review_workspace import append_review, write_review_workspace


@pytest.fixture
def pack(tmp_path):
    case = {"schema_version": "foresight.trace-blind-case.v1", "decision_id": "fixture:1",
            "match_id": 1, "subject": "account:7", "observation_time": 10.0,
            "boundary_status": "activation_observed_choice_unresolved",
            "observed_action": {"stage": "combat_log_observation", "item": "item_black_king_bar"},
            "own_state_time": 9.0, "own_state": [{"fact_id": "mana", "predicate": "self.mana",
                "value": 100, "correctness": "unverified", "availability_to_subject": "unverified",
                "source_prefix_record_index": 11}], "missing_context": ["subject_goal"],
            "media_status": "player_prefix_recording_required", "review_readiness": "context_incomplete",
            "own_resource_facts": [{"fact_id": "cost", "predicate": "self.activation_mana_cost",
                "raw_observation": {"value": 50, "status": "raw_observed", "source_record_index": 10,
                    "net_tick": 2, "wire_type": "int32"}, "semantic_validation": "unverified"}]}
    digest = content_hash(case)
    case["input_hash"] = digest
    (tmp_path / "blinded").mkdir()
    (tmp_path / "blinded/blind-cases.jsonl").write_text(json.dumps(case) + "\n", encoding="utf-8")
    dataset = {"decision_id": "fixture:1", "input_hash": digest, "match_id": 1,
               "replay_hash": "a" * 64, "target_player": "account:7", "patch": "fixture",
               "split": "development", "dataset_kind": "synthetic", "participants": ["account:7"]}
    (tmp_path / "dataset.jsonl").write_text(json.dumps(dataset) + "\n", encoding="utf-8")
    (tmp_path / "annotations.jsonl").write_bytes(b"")
    return tmp_path


def payload(pack, **changes):
    case = json.loads((pack / "blinded/blind-cases.jsonl").read_text(encoding="utf-8"))
    return {"schema_version": "foresight.annotation.v1", "decision_id": case["decision_id"],
        "input_hash": case["input_hash"], "replay_hash": "a" * 64, "patch": "fixture",
        "annotator_id": "fixture-only-reviewer", "acceptable_verdicts": ["insufficient_evidence"],
        "eligibility": "unknown", "rationale": "Synthetic test only, missing choice boundary",
        "facts_checked": [], "available_actions": [], "decisive_evidence_ids": [],
        "unknowns": ["choice boundary unavailable"], "dataset_kind": "synthetic",
        "annotator_kind": "human_expert", "annotation_version": 1, "pass": "decision_blinded",
        "outcome_visible": False, "system_verdict_visible": False, "adjudication_status": "unreviewed",
        "previous_annotation_hash": None, "revision_reason": None} | changes


def assessed(pack):
    return payload(pack, eligibility="eligible", acceptable_verdicts=["good"], unknowns=[],
        facts_checked=[{"fact_id": "mana", "correctness": "correct", "availability": "available",
                        "reason": "Synthetic fixture check"}],
        available_actions=[{"action_id": "action:fixture:1", "feasibility": "feasible",
                            "evidence_ids": ["mana"], "reason": "Synthetic fixture check"}],
        decisive_evidence_ids=["mana"])


def test_blank_form_does_not_generate_labels_or_load_system_files(pack):
    (pack / "system").mkdir()
    (pack / "system/predictions.jsonl").write_text("HIDDEN_SYSTEM_TOKEN", encoding="utf-8")
    (pack / "quality.json").write_text("HIDDEN_OUTCOME_TOKEN", encoding="utf-8")
    html = write_review_workspace(pack).read_text(encoding="utf-8")
    assert "HIDDEN_SYSTEM_TOKEN" not in html and "HIDDEN_OUTCOME_TOKEN" not in html
    assert 'id="identity" required maxlength="200" autocomplete="off" value=""' in html
    assert '<option value="">Выберите явно</option>' in html
    markup = html.split('<script type="application/json"')[0]
    assert " selected" not in markup and " checked" not in markup
    assert 'id="version" type="number"' in html and 'value="1"' not in html
    assert 'disabled value="outcome"' in html and 'disabled value="text"' in html
    assert (pack / "annotations.jsonl").read_bytes() == b""


def test_unknown_submission_is_recorded_without_promotion(pack):
    result = append_review(pack, payload(pack))
    annotation, = load_annotations(pack / "annotations.jsonl")
    assert annotation.dataset_kind == "synthetic"
    assert result["annotation_hash"] == annotation.annotation_hash
    assert annotation.adjudication_status == "unreviewed"
    assert result["validation_status"] == "data_validation_pending"


@pytest.mark.parametrize("field,value", [("input_hash", "b" * 64), ("replay_hash", "b" * 64),
    ("patch", "other"), ("dataset_kind", "replay"), ("decision_id", "other")])
def test_wrong_manifest_binding_rejected_without_append(pack, field, value):
    with pytest.raises(ValueError):
        append_review(pack, payload(pack, **{field: value}))
    assert (pack / "annotations.jsonl").read_bytes() == b""


@pytest.mark.parametrize("changes", [{"annotator_id": None}, {"acceptable_verdicts": []},
    {"eligibility": None}, {"pass": ""}, {"pass": "outcome"}, {"outcome_visible": True},
    {"system_verdict_visible": True}, {"annotator_kind": "system"}, {"adjudication_status": "agreed"}])
def test_blank_or_self_promoting_submissions_rejected(pack, changes):
    with pytest.raises(ValueError):
        append_review(pack, payload(pack, **changes))


def test_revision_chain_preserves_prior_bytes_and_requires_latest(pack):
    first = append_review(pack, payload(pack))
    before = (pack / "annotations.jsonl").read_bytes()
    second = payload(pack, annotation_version=2, previous_annotation_hash=first["annotation_hash"],
                     revision_reason="Fixture correction", rationale="Fixture updated reason")
    second_result = append_review(pack, second)
    assert (pack / "annotations.jsonl").read_bytes().startswith(before)
    with pytest.raises(ValueError, match="current latest"):
        append_review(pack, second)
    third = second | {"annotation_version": 3}
    with pytest.raises(ValueError, match="current latest"):
        append_review(pack, third)
    third["previous_annotation_hash"] = second_result["annotation_hash"]
    append_review(pack, third)
    assert len(load_annotations(pack / "annotations.jsonl")) == 3


def test_independent_reviewers_and_passes_have_separate_chains(pack):
    append_review(pack, payload(pack))
    append_review(pack, payload(pack, annotator_id="other-fixture-reviewer"))
    append_review(pack, payload(pack, **{"pass": "extraction"}))
    assert len(load_annotations(pack / "annotations.jsonl")) == 3


def test_unknown_action_feasibility_valid_for_abstention(pack):
    append_review(pack, payload(pack, available_actions=[{"action_id": "hold:fixture:1",
        "feasibility": "unknown", "evidence_ids": [], "reason": "Missing verified choice prefix"}]))
    assert load_annotations(pack / "annotations.jsonl")[0].available_actions[0].feasibility == "unknown"


@pytest.mark.parametrize("correctness,availability", [("incorrect", "available"),
    ("unverifiable", "available"), ("correct", "not_available"), ("correct", "unknown")])
def test_assessed_decision_cannot_rely_on_incorrect_or_unavailable_fact(pack, correctness, availability):
    row = assessed(pack)
    row["facts_checked"][0].update(correctness=correctness, availability=availability)
    with pytest.raises(ValueError, match="correct available"):
        append_review(pack, row)


def test_unknown_feasibility_does_not_establish_assessed_decision(pack):
    row = assessed(pack)
    row["available_actions"][0]["feasibility"] = "unknown"
    with pytest.raises(ValueError, match="unknown feasibility"):
        append_review(pack, row)


def test_incorrect_extraction_fact_can_be_recorded_as_disagreement(pack):
    append_review(pack, payload(pack, **{"pass": "extraction"}, facts_checked=[{
        "fact_id": "mana", "correctness": "incorrect", "availability": "unknown",
        "reason": "Fixture client value differs from extraction"}]))
    assert load_annotations(pack / "annotations.jsonl")[0].facts_checked[0].correctness == "incorrect"


def test_record_evidence_resolves_checked_own_fact(pack):
    row = assessed(pack)
    row["decisive_evidence_ids"] = ["record:11"]
    row["available_actions"][0]["evidence_ids"] = ["record:11"]
    append_review(pack, row)


@pytest.mark.parametrize("changes", [
    {"facts_checked": [{"fact_id": "world:enemy", "correctness": "correct", "availability": "available", "reason": "x"}]},
    {"decisive_evidence_ids": ["record:99999"]},
    {"available_actions": [{"action_id": "other", "feasibility": "unknown", "evidence_ids": [], "reason": "x"}]},
    {"facts_checked": [{"fact_id": "goal:fixture:1", "correctness": "correct", "availability": "available", "reason": "x"}]},
])
def test_unknown_context_and_missing_goals_cannot_be_certified(pack, changes):
    with pytest.raises(ValueError):
        append_review(pack, payload(pack, **changes))


def test_blind_case_hash_and_forbidden_fields_checked_before_render(pack):
    path = pack / "blinded/blind-cases.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["own_state"][0]["value"] = 99
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="input_hash"):
        write_review_workspace(pack)
    row["outcome"] = "leak"
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="unblinded"):
        write_review_workspace(pack)


def test_embedded_strings_cannot_close_script_element(pack):
    path = pack / "blinded/blind-cases.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["observed_action"]["item"] = "</script><script>attack()</script>"
    row["input_hash"] = content_hash({k: v for k, v in row.items() if k != "input_hash"})
    path.write_text(json.dumps(row), encoding="utf-8")
    dataset = json.loads((pack / "dataset.jsonl").read_text(encoding="utf-8"))
    dataset["input_hash"] = row["input_hash"]
    (pack / "dataset.jsonl").write_text(json.dumps(dataset), encoding="utf-8")
    html = write_review_workspace(pack).read_text(encoding="utf-8")
    assert "<script>attack()" not in html and "\\u003c/script>" in html


def test_concurrent_append_lock_and_invalid_payload_preserve_existing_file(pack):
    append_review(pack, payload(pack))
    before = (pack / "annotations.jsonl").read_bytes()
    (pack / ".annotations.lock").touch()
    with pytest.raises(ValueError, match="in progress"):
        append_review(pack, payload(pack, annotator_id="other-fixture-reviewer"))
    assert (pack / "annotations.jsonl").read_bytes() == before
    assert (pack / ".annotations.lock").exists()


def test_complete_payload_required_and_local_endpoint_only(pack):
    row = payload(pack)
    del row["system_verdict_visible"]
    with pytest.raises(ValueError, match="complete annotation"):
        append_review(pack, row)
    with pytest.raises(ValueError, match="local"):
        write_review_workspace(pack, submit_url="https://example.com/upload")
    path = write_review_workspace(pack, submit_url="/api/review", submit_token="fixture-only-token")
    assert '"submit_url": "/api/review"' in path.read_text(encoding="utf-8")
