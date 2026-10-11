"""Prefix analysis of supplied, attributed observations; no radius/lifetime score.

The caller must resolve validation references against its extraction registry.
This module cannot turn raw world coordinates into player knowledge or attest a
visibility extractor. Information attribution is descriptive, not ward quality.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


def _refs(value, name):
    if not isinstance(value, tuple) or any(not isinstance(v, str) or not v for v in value) or len(set(value)) != len(value):
        raise ValueError(f"immutable unique {name} required")


@dataclass(frozen=True)
class AttributedObservation:
    observation_id: str
    game_time_ms: int
    team: int
    entity_ref: str
    predicate: str
    value: str | int | float | bool
    attribution_ids: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    validation_refs: tuple[str, ...] = ()
    validation_status: str = "unverified"
    perspective: str = "team"

    def __post_init__(self):
        if any(not isinstance(v, str) or not v for v in (self.observation_id, self.entity_ref, self.predicate)) or type(self.game_time_ms) is not int or self.team not in (2, 3) or type(self.team) is not int:
            raise ValueError("observation identity/time/team required")
        if self.perspective != "team" or self.validation_status not in ("verified", "unverified"):
            raise ValueError("only team observations with explicit quality are accepted")
        if type(self.value) not in (str, int, float, bool) or (type(self.value) is float and not math.isfinite(self.value)):
            raise ValueError("finite scalar observation required")
        for field in ("attribution_ids", "evidence_refs", "validation_refs"):
            _refs(getattr(self, field), field)
        if self.validation_status == "verified" and (not self.evidence_refs or not self.validation_refs):
            raise ValueError("verified observation requires source and validation receipts")


@dataclass(frozen=True)
class WardTask:
    task_id: str
    available_at_ms: int
    predicate: str
    entity_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    validation_status: str = "unverified"

    def __post_init__(self):
        if not isinstance(self.task_id, str) or not self.task_id or type(self.available_at_ms) is not int or not isinstance(self.predicate, str) or not self.predicate:
            raise ValueError("versioned task evidence required")
        _refs(self.entity_refs, "task entity refs")
        _refs(self.evidence_refs, "task evidence refs")
        if self.validation_status not in ("verified", "unverified") or (self.validation_status == "verified" and not self.evidence_refs):
            raise ValueError("verified task requires evidence")


@dataclass(frozen=True)
class PlacementEvidence:
    action_id: str
    available_at_ms: int
    feasible: bool | None
    safe: bool | None
    evidence_refs: tuple[str, ...]
    validation_status: str = "unverified"

    def __post_init__(self):
        if not isinstance(self.action_id, str) or not self.action_id or type(self.available_at_ms) is not int:
            raise ValueError("placement action identity/time required")
        if any(v is not None and type(v) is not bool for v in (self.feasible, self.safe)):
            raise ValueError("placement feasibility/safety must be boolean or unknown")
        _refs(self.evidence_refs, "placement evidence refs")
        if self.validation_status not in ("verified", "unverified") or (self.validation_status == "verified" and not self.evidence_refs):
            raise ValueError("verified placement requires evidence")


@dataclass(frozen=True)
class WardInformationReview:
    ward_id: str
    cutoff_ms: int
    status: str
    first_observed_entity_ids: tuple[str, ...]
    novel_observation_ids: tuple[str, ...]
    duplicate_observation_ids: tuple[str, ...]
    jointly_attributed_observation_ids: tuple[str, ...]
    task_aligned_observation_ids: tuple[str, ...]
    task_alignment: str
    placement_feasible: bool | None
    placement_safe: bool | None
    feasible_alternative_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    utility: str = "not_established"


def review_ward_information(ward_id: str, *, team: int, cutoff_ms: int,
                            observations: tuple[AttributedObservation, ...],
                            stream_completeness: str = "unknown", task: WardTask | None = None,
                            placement: PlacementEvidence | None = None,
                            alternatives: tuple[PlacementEvidence, ...] = (),
                            coverage_evidence_refs: tuple[str, ...] = ()) -> WardInformationReview:
    """Count information changes in a verified supplied prefix, not global utility.

    No complete prior stream means no claim of first-seen/novel information.
    Simultaneous observations are compared as a group: callback ordering cannot
    credit the first source and unfairly call the second one redundant.
    """
    if not isinstance(ward_id, str) or not ward_id or type(team) is not int or team not in (2, 3) or type(cutoff_ms) is not int:
        raise ValueError("ward identity, team and cutoff required")
    if not isinstance(observations, tuple) or any(not isinstance(v, AttributedObservation) for v in observations):
        raise ValueError("immutable typed observation stream required")
    if not isinstance(alternatives, tuple) or any(not isinstance(v, PlacementEvidence) for v in alternatives):
        raise ValueError("immutable placement alternatives required")
    if stream_completeness not in ("complete", "partial", "unknown"):
        raise ValueError("explicit observation completeness required")
    _refs(coverage_evidence_refs, "coverage evidence refs")
    prefix = tuple(o for o in observations if o.game_time_ms <= cutoff_ms and o.team == team)
    if len({o.observation_id for o in prefix}) != len(prefix):
        raise ValueError("duplicate observation id in supplied prefix")
    if placement is not None and not isinstance(placement, PlacementEvidence) or task is not None and not isinstance(task, WardTask):
        raise ValueError("typed placement/task evidence required")
    reasons = []
    if stream_completeness != "complete":
        reasons.append("prior_observation_coverage_unknown")
    elif not coverage_evidence_refs:
        reasons.append("stream_completeness_not_verified")
    if any(o.validation_status != "verified" or not o.attribution_ids for o in prefix):
        reasons.append("observation_or_attribution_not_verified")
    known, entities, first, novel, duplicates, joint, aligned, evidence = {}, set(), [], [], [], [], [], []
    can_analyze = not reasons
    task_known = bool(task and task.validation_status == "verified" and task.available_at_ms <= cutoff_ms)
    if can_analyze:
        times = sorted({o.game_time_ms for o in prefix})
        for stamp in times:
            group = sorted((o for o in prefix if o.game_time_ms == stamp), key=lambda o: o.observation_id)
            updates = {}
            for o in group:
                key = (o.entity_ref, o.predicate)
                token = (type(o.value).__name__, o.value)
                updates.setdefault(key, set()).add(token)
            if any(len(values) != 1 for values in updates.values()):
                reasons.append("simultaneous_observation_conflict")
                can_analyze = False
                break
            for o in group:
                if ward_id not in o.attribution_ids:
                    continue
                key = (o.entity_ref, o.predicate)
                token = (type(o.value).__name__, o.value)
                evidence.extend(o.evidence_refs + o.validation_refs)
                if len(o.attribution_ids) > 1 or any(p.observation_id != o.observation_id and (p.entity_ref, p.predicate, type(p.value), p.value) == (o.entity_ref, o.predicate, type(o.value), o.value) and ward_id not in p.attribution_ids for p in group):
                    joint.append(o.observation_id)
                if known.get(key) == token:
                    duplicates.append(o.observation_id)
                else:
                    novel.append(o.observation_id)
                if o.entity_ref not in entities:
                    first.append(o.entity_ref)
                if task_known and task.available_at_ms <= stamp and o.predicate == task.predicate and (not task.entity_refs or o.entity_ref in task.entity_refs):
                    aligned.append(o.observation_id)
            for key, values in updates.items():
                known[key] = next(iter(values))
            entities.update(o.entity_ref for o in group)
    if not can_analyze:
        first, novel, duplicates, joint, aligned, evidence = [], [], [], [], [], []
    else:
        evidence.extend(coverage_evidence_refs)
    if not task_known:
        reasons.append("task_alignment_unknown")
    place_known = bool(placement and placement.validation_status == "verified" and placement.available_at_ms <= cutoff_ms)
    if not place_known:
        reasons.append("placement_feasibility_and_safety_unknown")
    alternative_ids = tuple(a.action_id for a in alternatives if a.validation_status == "verified" and a.available_at_ms <= cutoff_ms and a.feasible is True)
    if not alternative_ids:
        reasons.append("feasible_alternatives_unknown")
    return WardInformationReview(ward_id, cutoff_ms, "descriptive_information" if can_analyze else "insufficient_evidence",
                                 tuple(dict.fromkeys(first)), tuple(novel), tuple(duplicates), tuple(joint), tuple(aligned),
                                 "observed_predicate_matches_task" if task_known and can_analyze and aligned else
                                 "no_matching_observation_in_supplied_prefix" if task_known and can_analyze else "unknown",
                                 placement.feasible if place_known else None, placement.safe if place_known else None,
                                 alternative_ids, tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(evidence)))
