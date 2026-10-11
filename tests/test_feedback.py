from dataclasses import asdict
import pytest
from dota_coach.feedback import Feedback, import_feedback, store_feedback
from dota_coach.evidence.contracts import content_hash


def inputs():
    assessment = {"verdict": "insufficient_evidence", "reason_codes": ["missing"]}
    report = {"schema_version": "foresight.dossier-report.v1", "match_id": 1,
              "cards": [{"episode_id": "episode:1", "dossier": {"assessment": assessment}}]}
    feedback = Feedback(1, "episode:1", content_hash(assessment), "different_goal", "escape", "2026-10-05T12:00:00Z",
                        content_hash(report["cards"][0]["dossier"]))
    return report, feedback


def test_feedback_bound_to_revision_idempotent_and_unreviewed(tmp_path):
    report, value = inputs()
    imported = import_feedback(report, [asdict(value)])
    assert imported == (value,)
    assert store_feedback(imported, str(tmp_path / "feedback.json")) == 1
    assert store_feedback(imported, str(tmp_path / "feedback.json")) == 1
    report["cards"][0]["dossier"]["assessment"]["verdict"] = "good"
    with pytest.raises(ValueError):
        import_feedback(report, [asdict(value)])


def test_feedback_cannot_self_approve():
    report, value = inputs()
    with pytest.raises(ValueError):
        import_feedback(report, [asdict(value) | {"status": "validated"}])


def test_feedback_not_reused_after_evidence_changes():
    report, value = inputs()
    report["cards"][0]["dossier"]["new_evidence"] = 10
    with pytest.raises(ValueError):
        import_feedback(report, [asdict(value)])
