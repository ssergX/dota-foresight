"""Pure experimental criterion engine; no extraction or outcome dependencies.

Utility bounds must be produced by a separately validated patch-scoped rubric.
This engine intentionally has no live validation grant for a Dota item/ability.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from dota_coach.decisions.contracts import ActionObservation, DecisionBoundary
from dota_coach.evidence.contracts import Fact, TimeRef, content_hash

CONDITIONS = ("self.activation_feasible", "self.hold_feasible",
              "screen.reaction_cue", "context.window_stable")
BOUND_PREDICATES = ("criterion.activate_lower", "criterion.activate_upper",
                    "criterion.hold_lower", "criterion.hold_upper")
REQUIRED_CAPABILITIES = ("primary_hero_identity", "game_clock", "inventory_abilities",
                         "cast_control_events", "reaction_cue_available_to_subject",
                         "patch_mechanics", "utility_rubric")


@dataclass(frozen=True)
class ActivationInput:
    decision_id: str
    match_id: int
    subject_ref: str
    patch: str
    criterion_version: str
    boundary: DecisionBoundary
    action: ActionObservation
    conditions: tuple[Fact, ...]
    utility_bounds: tuple[Fact, ...]
    dataset_kind: str = "unknown"

    def __post_init__(self):
        if not self.decision_id or type(self.match_id) is not int or self.match_id <= 0:
            raise ValueError("decision and match identity required")
        if not self.subject_ref or not self.patch or not self.criterion_version:
            raise ValueError("explicit subject, patch and criterion required")
        if self.dataset_kind not in ("replay", "synthetic", "unknown"):
            raise ValueError("invalid dataset kind")
        if self.boundary.status != "resolved" or self.boundary.anchor is None:
            raise ValueError("incident without a resolved choice cannot be evaluated")
        anchor = self.boundary.anchor
        if anchor.order_status != "verified" or anchor.uncertainty_ms != 0 or (
                anchor.replay_tick is None or anchor.sequence_in_tick is None or
                anchor.clock_mapping_version in ("legacy/unverified", "unknown")):
            raise ValueError("criterion requires a verified ordered boundary with exact clock")
        if not isinstance(self.conditions, tuple) or not isinstance(self.utility_bounds, tuple):
            raise ValueError("immutable evidence required")
        if tuple(f.predicate for f in self.conditions) != CONDITIONS:
            raise ValueError("condition allowlist and order required")
        if tuple(f.predicate for f in self.utility_bounds) != BOUND_PREDICATES:
            raise ValueError("utility bound allowlist and order required")
        facts = self.conditions + self.utility_bounds
        if len({f.fact_id for f in facts}) != len(facts):
            raise ValueError("duplicate fact identity")
        for f in facts:
            if f.perspective == "world" or f.subject_ref != self.subject_ref:
                raise ValueError("world or foreign subject evidence forbidden")
            if f.predicate == "screen.reaction_cue" and (
                    f.perspective != "screen" or f.observer_ref != self.subject_ref):
                raise ValueError("team knowledge does not prove a screen cue")
            if f.predicate.startswith("self.") and f.perspective != "screen":
                raise ValueError("own control evidence must be subject scoped")
            if f.status not in ("unknown", "conflict"):
                if f.available_at is None or f.available_at.game_time_ms is None:
                    raise ValueError("known facts require availability time")
                cutoff = self.boundary.anchor.game_time_ms
                if cutoff is None or f.valid_at.game_time_ms is None:
                    raise ValueError("known facts require a clock mapping")
                if f.available_at.uncertainty_ms is None:
                    raise ValueError("known availability requires explicit uncertainty")
                if not f.available_at.definitely_available_before(anchor):
                    raise ValueError("future or uncertain future evidence forbidden")
                if f.valid_at != anchor:
                    raise ValueError("this criterion requires one stable decision step")
                if f.available_at.replay_tick is None or f.available_at.sequence_in_tick is None:
                    raise ValueError("mechanical facts require event ordering")
                if f.predicate in CONDITIONS and type(f.value) is not bool:
                    raise ValueError("conditions are boolean or unknown")
                if f.predicate in BOUND_PREDICATES and (
                        type(f.value) not in (int, float) or not math.isfinite(f.value)):
                    raise ValueError("utility bounds are finite numbers or unknown")
        for low, high in ((4, 5), (6, 7)):
            if facts[low].value is not None and facts[high].value is not None:
                if facts[low].value > facts[high].value:
                    raise ValueError("reversed utility interval")

    @property
    def input_hash(self) -> str:
        return content_hash(self)


@dataclass(frozen=True)
class CriterionScope:
    patch: str
    criterion_version: str
    capabilities: tuple[str, ...] = ()
    rubric_source_ids: tuple[str, ...] = ()
    mode: str = "disabled"
    acceptable_floor: float | None = None

    def __post_init__(self):
        # There is deliberately no 'validated' switch supplied by replay metadata.
        if not all(isinstance(v, str) and v for v in (self.patch, self.criterion_version)):
            raise ValueError("scope requires explicit versioned identities")
        for refs in (self.capabilities, self.rubric_source_ids):
            if not isinstance(refs, tuple) or not all(isinstance(v, str) and v for v in refs):
                raise ValueError("immutable nonempty scope references required")
            if len(set(refs)) != len(refs):
                raise ValueError("duplicate scope references")
        if self.mode not in ("disabled", "experimental"):
            raise ValueError("real validation grant is not implemented; cannot self-promote")
        if self.acceptable_floor is not None and (type(self.acceptable_floor) not in (int, float)
                                                  or not math.isfinite(self.acceptable_floor)):
            raise ValueError("finite explicit acceptability threshold required")


@dataclass(frozen=True)
class Claim:
    claim_id: str
    code: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class Evaluation:
    decision_id: str
    input_hash: str
    verdict: str
    reason_codes: tuple[str, ...]
    claims: tuple[Claim, ...] = ()
    criterion_id: str = "defensive_activation.v1"
    evaluator_version: str = "bounded-dominance.v1"
    validation_status: str = "unverified"
    training_eligible: bool = False
    scope_hash: str | None = None

    @property
    def assessment_hash(self) -> str:
        return content_hash(self)


def evaluate_activation(value: ActivationInput, scope: CriterionScope) -> Evaluation:
    def result(verdict, reasons, evidence=()):
        claims = tuple(Claim(content_hash((value.input_hash, content_hash(scope), code, evidence)), code,
                             tuple(evidence)) for code in reasons)
        return Evaluation(value.decision_id, value.input_hash, verdict, tuple(reasons), claims,
                          scope_hash=content_hash(scope))

    gaps = []
    if scope.mode == "disabled":
        gaps.append("criterion_disabled")
    if value.patch != scope.patch or value.criterion_version != scope.criterion_version:
        gaps.append("scope_mismatch")
    if not scope.rubric_source_ids:
        gaps.append("rubric_sources_missing")
    gaps.extend("capability_missing:" + c for c in REQUIRED_CAPABILITIES if c not in scope.capabilities)
    facts = value.conditions + value.utility_bounds
    gaps.extend("fact_not_supported:" + f.predicate for f in facts
                if f.status not in ("observed", "derived") or f.quality_flags
                or f.method_version != value.criterion_version
                or f.valid_at.order_status != "verified"
                or f.available_at is None or f.available_at.order_status != "verified")
    if value.action.kind not in ("activation_commit", "observed_no_activation"):
        gaps.append("command_not_activation")
    if not value.action.event_refs:
        gaps.append("action_source_missing")
    if gaps:
        return result("insufficient_evidence", gaps)
    activate, hold, cue, stable = (f.value for f in value.conditions)
    if not cue or not stable:
        return result("insufficient_evidence", ("cue_unavailable" if not cue else "window_changed",))
    chosen_activate = value.action.kind == "activation_commit"
    if not activate:
        # Inability to activate is never an error; a conflicting commit needs review.
        return result("insufficient_evidence" if chosen_activate else "not_actionable",
                      ("action_evidence_conflict" if chosen_activate else "activation_infeasible",),
                      (value.conditions[0].fact_id,))
    if not hold:
        return result("insufficient_evidence", ("hold_feasibility_unresolved",))
    alo, ahi, hlo, hhi = (f.value for f in value.utility_bounds)
    evidence = tuple(f.fact_id for f in facts)
    if alo > hhi:
        return result("good_decision" if chosen_activate else "mistake",
                      ("activate_robustly_dominates",), evidence)
    if hlo > ahi:
        return result("mistake" if chosen_activate else "good_decision",
                      ("hold_robustly_dominates",), evidence)
    if scope.acceptable_floor is not None and min(alo, hlo) >= scope.acceptable_floor:
        return result("reasonable_alternative", ("both_actions_meet_rubric_floor",), evidence)
    return result("insufficient_evidence", ("bounds_do_not_establish_acceptability",), evidence)


CLAIM_TEXT = {
    "activate_robustly_dominates": "По заданной экспериментальной рубрике диапазон активации выше диапазона ожидания.",
    "hold_robustly_dominates": "По заданной экспериментальной рубрике диапазон ожидания выше диапазона активации.",
    "both_actions_meet_rubric_floor": "Обе альтернативы проходят явно заданный порог приемлемости экспериментальной рубрики.",
    "bounds_do_not_establish_acceptability": "Пересечение диапазонов не доказывает разумность альтернатив; оценка отложена.",
    "activation_infeasible": "В переданных данных активация недоступна; этот случай исключён из упражнения.",
}


def explain_evaluation(evaluation: Evaluation) -> tuple[str, ...]:
    """Only deterministic, bounded claims; arbitrary LLM prose is not accepted."""
    return tuple(CLAIM_TEXT.get(c.code, "Оценка недоступна: " + c.code)
                 for c in evaluation.claims)
