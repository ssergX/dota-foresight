"""Offline review records. These declarations never enable a release gate."""
from __future__ import annotations

import re
from dataclasses import dataclass

from dota_coach.evidence.contracts import content_hash

VERDICTS = frozenset({"good", "reasonable_options", "probable_error",
                      "confirmed_error_within_criterion", "insufficient_evidence",
                      "good_decision", "reasonable_alternative", "mistake", "not_actionable"})
ERROR_VERDICTS = frozenset({"probable_error", "confirmed_error_within_criterion", "mistake"})
VERDICT_ALIASES = {"good_decision": "good", "reasonable_alternative": "reasonable_options",
                   "mistake": "probable_error"}


def canonical_verdict(value: str) -> str:
    return VERDICT_ALIASES.get(value, value)
SPLITS = frozenset({"development", "calibration", "holdout", "patch_transfer",
                    "longitudinal_baseline", "longitudinal_followup"})
ANNOTATION_SCHEMA = "foresight.annotation.v1"


def identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


def sha256(value: str, name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hash")


def identifiers(values: tuple[str, ...], name: str) -> None:
    if not isinstance(values, tuple):
        raise ValueError(f"{name} must be an immutable tuple")
    for value in values:
        identifier(value, name)
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {name}")


@dataclass(frozen=True)
class DatasetRecord:
    decision_id: str
    input_hash: str
    match_id: int
    replay_hash: str
    target_player: str
    patch: str
    split: str
    dataset_kind: str = "replay"
    participants: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.decision_id, "decision_id")
        sha256(self.input_hash, "input_hash")
        sha256(self.replay_hash, "replay_hash")
        if type(self.match_id) is not int or self.match_id <= 0:
            raise ValueError("positive match_id required")
        identifier(self.target_player, "target_player")
        identifier(self.patch, "patch")
        if self.split not in SPLITS:
            raise ValueError("invalid dataset split")
        if self.dataset_kind not in ("replay", "synthetic", "unknown"):
            raise ValueError("invalid dataset kind")
        identifiers(self.participants, "participants")
        if self.participants and self.target_player not in self.participants:
            raise ValueError("target player absent from participant roster")


@dataclass(frozen=True)
class FactCheck:
    fact_id: str
    correctness: str
    availability: str
    reason: str

    def __post_init__(self):
        identifier(self.fact_id, "fact_id")
        if self.correctness not in ("correct", "incorrect", "unverifiable"):
            raise ValueError("invalid fact correctness")
        if self.availability not in ("available", "not_available", "unknown"):
            raise ValueError("invalid fact availability")
        identifier(self.reason, "fact check reason")


@dataclass(frozen=True)
class ActionCheck:
    action_id: str
    feasibility: str
    evidence_ids: tuple[str, ...]
    reason: str

    def __post_init__(self):
        identifier(self.action_id, "action_id")
        if self.feasibility not in ("feasible", "infeasible", "unknown"):
            raise ValueError("invalid action feasibility")
        identifiers(self.evidence_ids, "action evidence ids")
        identifier(self.reason, "action check reason")
        if self.feasibility != "unknown" and not self.evidence_ids:
            raise ValueError("known action feasibility requires evidence")


@dataclass(frozen=True)
class Annotation:
    decision_id: str
    input_hash: str
    replay_hash: str
    patch: str
    annotator_id: str
    acceptable_verdicts: tuple[str, ...]
    eligibility: str
    rationale: str
    facts_checked: tuple[FactCheck, ...] = ()
    available_actions: tuple[ActionCheck, ...] = ()
    decisive_evidence_ids: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    dataset_kind: str = "replay"
    annotator_kind: str = "human_expert"
    annotation_version: int = 1
    review_pass: str = "decision_blinded"
    outcome_visible: bool = False
    system_verdict_visible: bool = False
    adjudication_status: str = "unreviewed"
    previous_annotation_hash: str | None = None
    revision_reason: str | None = None
    schema_version: str = ANNOTATION_SCHEMA

    def __post_init__(self):
        for name in ("decision_id", "patch", "annotator_id", "rationale"):
            identifier(getattr(self, name), name)
        for name in ("input_hash", "replay_hash"):
            sha256(getattr(self, name), name)
        if self.schema_version != ANNOTATION_SCHEMA:
            raise ValueError("unsupported annotation schema")
        if self.dataset_kind not in ("replay", "synthetic", "unknown"):
            raise ValueError("templates are not completed annotations")
        if self.annotator_kind not in ("human_expert", "system", "self_evaluation"):
            raise ValueError("invalid annotator kind")
        if self.review_pass not in ("decision_blinded", "extraction", "outcome", "text"):
            raise ValueError("invalid review pass")
        if type(self.outcome_visible) is not bool or type(self.system_verdict_visible) is not bool:
            raise ValueError("visibility flags must be explicit booleans")
        if self.review_pass == "decision_blinded" and (self.outcome_visible or self.system_verdict_visible):
            raise ValueError("decision label must precede outcome and system verdict disclosure")
        if self.eligibility not in ("eligible", "ineligible", "unknown"):
            raise ValueError("invalid eligibility")
        identifiers(self.acceptable_verdicts, "acceptable verdicts")
        if not self.acceptable_verdicts or not set(self.acceptable_verdicts) <= VERDICTS:
            raise ValueError("completed annotation requires acceptable verdicts")
        identifiers(self.decisive_evidence_ids, "decisive evidence ids")
        identifiers(self.unknowns, "unknown reasons")
        if self.eligibility == "unknown" and not self.unknowns:
            raise ValueError("unknown eligibility requires a reason")
        if self.adjudication_status not in ("unreviewed", "agreed", "disputed", "adjudicated"):
            raise ValueError("invalid adjudication status")
        if type(self.annotation_version) is not int or self.annotation_version < 1:
            raise ValueError("positive annotation version required")
        if self.annotation_version == 1 and (self.previous_annotation_hash or self.revision_reason):
            raise ValueError("first annotation cannot reference a previous revision")
        if self.annotation_version > 1:
            sha256(self.previous_annotation_hash, "previous_annotation_hash")
            identifier(self.revision_reason, "revision_reason")
        if not isinstance(self.facts_checked, tuple) or not all(
                isinstance(check, FactCheck) for check in self.facts_checked):
            raise ValueError("typed immutable fact checks required")
        if not isinstance(self.available_actions, tuple) or not all(
                isinstance(check, ActionCheck) for check in self.available_actions):
            raise ValueError("typed immutable action checks required")
        if len({check.fact_id for check in self.facts_checked}) != len(self.facts_checked):
            raise ValueError("duplicate fact check")
        if len({check.action_id for check in self.available_actions}) != len(self.available_actions):
            raise ValueError("duplicate action check")
        if self.review_pass == "decision_blinded":
            normalized = {canonical_verdict(v) for v in self.acceptable_verdicts}
            if "not_actionable" in normalized and self.eligibility != "ineligible":
                raise ValueError("not actionable label requires ineligible opportunity")
            if "insufficient_evidence" in normalized and not self.unknowns:
                raise ValueError("insufficient evidence label requires unknown reasons")
            if normalized - {"insufficient_evidence", "not_actionable"} and (
                    not self.facts_checked or not self.available_actions or not self.decisive_evidence_ids):
                raise ValueError("assessed label requires fact, action and decisive evidence checks")
            if "reasonable_options" in normalized and sum(
                    check.feasibility == "feasible" for check in self.available_actions) < 2:
                raise ValueError("reasonable options require two checked feasible actions")

    @property
    def annotation_hash(self) -> str:
        return content_hash(self)

    @property
    def key(self) -> tuple[str, str, str, int]:
        return self.decision_id, self.annotator_id, self.review_pass, self.annotation_version


@dataclass(frozen=True)
class Prediction:
    decision_id: str
    input_hash: str
    verdict: str
    evaluator_version: str

    def __post_init__(self):
        identifier(self.decision_id, "decision_id")
        sha256(self.input_hash, "input_hash")
        identifier(self.evaluator_version, "evaluator_version")
        if self.verdict not in VERDICTS:
            raise ValueError("invalid predicted verdict")
