"""User feedback is review material, never a gold label or training target."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile

from dota_coach.evidence.contracts import content_hash

KINDS = ("disagree", "different_goal", "useful")


@dataclass(frozen=True)
class Feedback:
    match_id: int
    decision_id: str
    assessment_hash: str
    kind: str
    comment: str
    created_at: str
    context_hash: str
    schema_version: str = "foresight.feedback.v1"
    status: str = "unreviewed"

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id <= 0 or not self.decision_id:
            raise ValueError("feedback identity required")
        if len(self.assessment_hash) != 64 or any(c not in "0123456789abcdef" for c in self.assessment_hash):
            raise ValueError("assessment content hash required")
        if len(self.context_hash) != 64 or any(c not in "0123456789abcdef" for c in self.context_hash):
            raise ValueError("review context content hash required")
        if self.kind not in KINDS or not isinstance(self.comment, str) or len(self.comment) > 2000:
            raise ValueError("invalid feedback kind or comment")
        if self.schema_version != "foresight.feedback.v1" or self.status != "unreviewed":
            raise ValueError("feedback cannot promote itself to expert truth")
        stamp = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("feedback timestamp requires timezone")


def import_feedback(report: dict, rows: list[dict]) -> tuple[Feedback, ...]:
    if report.get("schema_version") not in ("foresight.dossier-report.v1", "foresight.trace-review.v1"):
        raise ValueError("unsupported report")
    lookup = {c["episode_id"]: (content_hash(c["dossier"]["assessment"]), content_hash(c["dossier"]))
              for c in report.get("cards", ()) if c.get("dossier") and c.get("episode_id")}
    if not isinstance(rows, list):
        raise ValueError("feedback export must be a list")
    result = tuple(Feedback(**row) for row in rows)
    for value in result:
        if value.match_id != report["match_id"] or lookup.get(value.decision_id) != (
                value.assessment_hash, value.context_hash):
            raise ValueError("feedback belongs to a different decision/report revision")
    return result


def store_feedback(values: tuple[Feedback, ...], path: str) -> int:
    target = Path(path)
    old = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    if not isinstance(old, list):
        raise ValueError("feedback store must contain a JSON list")
    # Validate pre-existing entries; idempotent import preserves all distinct responses.
    for row in old:
        Feedback(**row)
    indexed = {content_hash(row): row for row in old}
    for value in values:
        row = asdict(value)
        indexed[content_hash(row)] = row
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix="feedback-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(list(indexed.values()), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return len(indexed)
