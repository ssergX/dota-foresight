from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dota_coach.evidence.contracts import TimeRef, content_hash
from dota_coach.evidence.knowledge import KnowledgeSnapshot


@dataclass(frozen=True)
class DecisionBoundary:
    boundary_id: str
    anchor: TimeRef | None
    status: Literal["resolved", "unresolved"] = "unresolved"
    method: str = "unresolved"
    resolution_evidence_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if self.status not in ("resolved", "unresolved"):
            raise ValueError("invalid boundary status")
        if self.status == "resolved" and (self.anchor is None or
                not self.resolution_evidence_ids or self.method == "unresolved"):
            raise ValueError("resolved boundary requires timestamp and evidence")
        if self.status == "unresolved" and self.anchor is not None:
            raise ValueError("unresolved boundary must not invent an anchor")


@dataclass(frozen=True)
class ActionObservation:
    kind: Literal["command_attempt", "accepted_command", "activation_commit",
                  "observed_no_activation"]
    action_id: str
    log_completeness: Literal["complete", "partial", "unknown"]
    event_refs: tuple[str, ...]
    # No free-form interpretation of intent or outcome is accepted here.

    def __post_init__(self):
        if self.kind not in ("command_attempt", "accepted_command", "activation_commit",
                             "observed_no_activation"):
            raise ValueError("invalid action observation")
        if self.log_completeness not in ("complete", "partial", "unknown"):
            raise ValueError("invalid action log quality")
        if not self.action_id or not isinstance(self.event_refs, tuple):
            raise ValueError("action requires immutable source references")
        if self.kind == "observed_no_activation" and self.log_completeness != "complete":
            raise ValueError("incomplete log cannot prove absence of activation")


@dataclass(frozen=True)
class DecisionInput:
    decision_id: str
    knowledge: KnowledgeSnapshot
    boundary: DecisionBoundary
    action: ActionObservation
    criterion_id: str
    criterion_version: str

    def __post_init__(self):
        if not isinstance(self.knowledge, KnowledgeSnapshot):
            raise TypeError("decision input requires an allowlisted KnowledgeSnapshot")
        if self.boundary.status != "resolved" or self.boundary.anchor is None:
            raise ValueError("unresolved incident is not a decision input")
        if self.boundary.anchor != self.knowledge.cutoff:
            raise ValueError("boundary and knowledge cutoff disagree")
        if not self.criterion_id or not self.criterion_version:
            raise ValueError("versioned criterion required")

    @property
    def input_hash(self) -> str:
        return content_hash(self)


@dataclass(frozen=True)
class ActionCandidate:
    action_id: str
    description: str
    feasibility: Literal["feasible", "infeasible", "unknown"] = "unknown"
    prerequisite_fact_ids: tuple[str, ...] = ()
    unknown_requirements: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assessment:
    assessment_id: str
    verdict: str = "insufficient_evidence"
    reason_codes: tuple[str, ...] = ()
    criterion_id: str = "defensive_activation.v1"
    evaluator_version: str = "disabled/no-validated-criterion"
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self):
        # S0-S2 may report evidence gaps; they cannot emit a mechanical verdict.
        if self.verdict != "insufficient_evidence" or not self.reason_codes:
            raise ValueError("no validated criterion: only explained abstention is supported")

    @property
    def assessment_hash(self) -> str:
        return content_hash(self)


@dataclass(frozen=True)
class Opportunity:
    opportunity_id: str
    decision_class: str
    eligibility: Literal["eligible", "ineligible", "unknown"]
    boundary: DecisionBoundary
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityLedger:
    opportunities: tuple[Opportunity, ...] = ()
    scope_status: str = "discovery_unavailable"
    reason_codes: tuple[str, ...] = ("cast_control_events_unavailable",
                                      "reaction_cue_unavailable")

    @property
    def assessed_count(self) -> int:
        return 0
