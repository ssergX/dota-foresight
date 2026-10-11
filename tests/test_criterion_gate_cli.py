"""Portable proposals cannot import caller authority or replace their inputs."""
from dataclasses import asdict
import json

import pytest

from dota_coach.cli import main
from dota_coach.validation.pipeline import write_annotations, write_dataset
from tests.test_criterion_gate import fixture


def paths(tmp_path):
    args, _ = fixture()
    proposal = {"schema_version": "foresight.criterion-gate-input.v1"}
    for key in ("identity", "policy", "cohort"):
        proposal[key] = asdict(args[key])
    for key in ("fact_requirements", "explanation_bindings"):
        proposal[key] = [asdict(row) for row in args[key]]
    inputs = [tmp_path / name for name in ("input.json", "dataset.jsonl", "predictions.jsonl", "annotations.jsonl")]
    inputs[0].write_text(json.dumps(proposal), encoding="utf-8")
    write_dataset(inputs[1], args["records"])
    inputs[2].write_text("".join(json.dumps(asdict(p)) + "\n" for p in args["predictions"]), encoding="utf-8")
    write_annotations(inputs[3], args["annotations"])
    command = ["criterion-gate-review"]
    for option, path in zip(("--input-json", "--dataset-jsonl", "--predictions-jsonl", "--annotations-jsonl"), inputs):
        command.extend((option, str(path)))
    return command, inputs, proposal


def test_cli_recomputes_quality_without_importing_release_authority(tmp_path):
    command, _, _ = paths(tmp_path)
    out = tmp_path / "result.json"
    assert main(command + ["--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["software_metrics_pass"] and result["status"] == "closed"
    assert result["release_receipt"] is None and not result["training_eligible"]
    assert result["computed_report"]["metrics"]["agreement_with_acceptable_sets"]["denominator"] == 2


@pytest.mark.parametrize("input_index", range(4))
def test_cli_rejects_overwriting_any_input_before_writes(tmp_path, input_index):
    command, inputs, _ = paths(tmp_path)
    before = [path.read_bytes() for path in inputs]
    assert main(command + ["--out", str(inputs[input_index])]) == 1
    assert [path.read_bytes() for path in inputs] == before


@pytest.mark.parametrize("field", ["registry", "admission", "release_receipt", "computed_report"])
def test_cli_rejects_portable_authority_and_supplied_quality_without_replacing_result(tmp_path, field):
    command, inputs, proposal = paths(tmp_path)
    proposal[field] = {"approved": True}
    inputs[0].write_text(json.dumps(proposal), encoding="utf-8")
    out = tmp_path / "result.json"
    out.write_text("previous result", encoding="utf-8")
    assert main(command + ["--out", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "previous result"
