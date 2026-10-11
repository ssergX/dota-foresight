import importlib.util
import json
from pathlib import Path
import re
from dota_coach.cli import main
from dota_coach.evidence.contracts import content_hash


def test_full_offline_flow_links_feedback_and_real_quality_exclusions(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/build_synthetic_demo.py"
    spec = importlib.util.spec_from_file_location("synthetic_demo", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.build(tmp_path) == tmp_path / "index.html"
    for page in tmp_path.rglob("*.html"):
        text = page.read_text(encoding="utf-8")
        for link in re.findall(r"href=['\"]([^'\"]+)['\"]", text):
            if not link.startswith(("#", "https:", "data:")):
                assert (page.parent / link).exists(), link
    result = json.loads((tmp_path / "criterion/evaluations.json").read_text(encoding="utf-8"))
    assert result["supplied_opportunities"] == 6
    assert result["experimental_assessed"] == 3 and result["validated_assessed"] == 0
    quality = json.loads((tmp_path / "quality.json").read_text(encoding="utf-8"))
    assert quality["cohort"]["decision_count"] == 0
    assert quality["metrics"]["false_positive_rate"]["rate"] is None
    blind = (tmp_path / "blind-review/blind-cases.jsonl").read_text(encoding="utf-8")
    assert "criterion.activate_lower" not in blind
    assert all("utility_bounds" not in json.loads(row) for row in blind.splitlines())
    report_path = tmp_path / "match/analysis.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    card = report["cards"][0]
    row = {"schema_version":"foresight.feedback.v1", "match_id":8001,
           "decision_id":card["episode_id"], "assessment_hash":content_hash(card["dossier"]["assessment"]),
           "context_hash":content_hash(card["dossier"]), "kind":"different_goal", "comment":"synthetic",
           "created_at":"2026-10-05T12:00:00Z", "status":"unreviewed"}
    feedback = tmp_path / "feedback-input.json"
    feedback.write_text(json.dumps([row]), encoding="utf-8")
    store = tmp_path / "feedback-store.json"
    assert main(["feedback", "--report-json", str(report_path), "--feedback-json",str(feedback), "--store",str(store)]) == 0
    assert json.loads(store.read_text(encoding="utf-8"))[0]["status"] == "unreviewed"
