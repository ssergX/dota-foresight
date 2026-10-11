from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


VERDICTS = frozenset(("good", "reasonable_options", "probable_error",
                      "confirmed_error_within_criterion", "insufficient_evidence"))


@dataclass(frozen=True)
class AssessmentProof:
    """A reference to an assessment and its independently maintained validation.

    This DTO does not validate a criterion by itself. Importers must resolve the
    references against the validation registry before setting status=validated.
    """
    assessment_id: str
    verdict: str
    criterion_version: str
    patch: str
    criterion_id: str
    status: Literal["validated", "unverified", "synthetic"] = "unverified"
    validation_refs: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    evaluator_version: str = "unknown"

    def __post_init__(self):
        if self.verdict not in VERDICTS or self.status not in ("validated", "unverified", "synthetic"):
            raise ValueError("invalid assessment status/verdict")
        if any(not isinstance(value, str) or not value for value in
               (self.assessment_id, self.criterion_id, self.criterion_version, self.patch, self.evaluator_version)):
            raise ValueError("assessment must identify its scope")
        if not isinstance(self.validation_refs, tuple) or not isinstance(self.evidence_ids, tuple):
            raise TypeError("immutable references required")
        if any(not isinstance(ref, str) or not ref for ref in self.validation_refs + self.evidence_ids):
            raise TypeError("nonempty string references required")
        if self.status == "validated" and (not self.validation_refs or not self.evidence_ids or
                                           not self.evaluator_version or self.evaluator_version == "unknown"):
            raise ValueError("validated assessment requires validation and decision evidence")


@dataclass(frozen=True)
class OpportunityRecord:
    opportunity_id: str
    match_id: int
    criterion_id: str
    role: str
    patch: str
    eligibility: Literal["eligible", "ineligible", "unknown"]
    assessment: AssessmentProof | None = None
    dataset_kind: Literal["replay", "synthetic", "unknown"] = "unknown"
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self):
        if isinstance(self.match_id, bool) or not isinstance(self.match_id, int) or self.match_id <= 0:
            raise ValueError("positive numeric match id required")
        if any(not isinstance(value, str) or not value for value in
               (self.opportunity_id, self.criterion_id, self.role, self.patch)):
            raise ValueError("opportunity requires identity and context")
        if self.eligibility not in ("eligible", "ineligible", "unknown"):
            raise ValueError("invalid eligibility")
        if self.dataset_kind not in ("replay", "synthetic", "unknown"):
            raise ValueError("invalid dataset kind")
        if not isinstance(self.reason_codes, tuple):
            raise TypeError("immutable reasons required")
        if any(not isinstance(reason, str) or not reason for reason in self.reason_codes):
            raise TypeError("string reason codes required")
        if self.assessment is not None:
            if not isinstance(self.assessment, AssessmentProof):
                raise TypeError("typed assessment proof required")
            if (self.assessment.patch, self.assessment.criterion_id) != (self.patch, self.criterion_id):
                raise ValueError("assessment patch/criterion mismatch")


@dataclass(frozen=True)
class HabitEvidence:
    habit_id: str
    criterion_id: str
    criterion_version: str
    role: str
    patch: str
    match_ids: tuple[int, ...]
    coverage_signature: str
    discovery_status: str
    records: tuple[OpportunityRecord, ...]
    eligible_count: int
    ineligible_count: int
    assessed_count: int
    unknown_count: int
    confirmed_error_count: int
    probable_error_count: int
    example_ids: tuple[str, ...]
    counterexample_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def assessment_coverage(self) -> float | None:
        return self.assessed_count / self.eligible_count if self.eligible_count else None

    @property
    def confirmed_error_rate_among_assessed(self) -> float | None:
        return self.confirmed_error_count / self.assessed_count if self.assessed_count else None

    @property
    def evaluator_versions(self) -> tuple[str, ...]:
        return tuple(sorted({r.assessment.evaluator_version for r in self.records
                             if _validated(r, self.criterion_version)}))


def _validated(record: OpportunityRecord, criterion_version: str) -> bool:
    proof = record.assessment
    return bool(record.eligibility == "eligible" and record.dataset_kind == "replay" and proof
                and proof.status == "validated" and proof.criterion_version == criterion_version
                and proof.verdict != "insufficient_evidence")


def build_habit_evidence(records: tuple[OpportunityRecord, ...], *, habit_id: str,
                         criterion_id: str, criterion_version: str, role: str, patch: str,
                         match_ids: tuple[int, ...], coverage_signature: str,
                         discovery_status: str = "unknown") -> HabitEvidence:
    """Consume the entire supplied scope, including abstentions and ineligible cases.

    A caller may group a ledger by context first, but may not pass only mistakes.
    Discovery completeness is a separate input and never inferred from counts.
    """
    if not isinstance(records, tuple) or not isinstance(match_ids, tuple):
        raise TypeError("immutable ledger and match set required")
    if any(not isinstance(record, OpportunityRecord) for record in records):
        raise TypeError("typed opportunity records required")
    if len(set(match_ids)) != len(match_ids) or any(type(m) is not int or m <= 0 for m in match_ids):
        raise ValueError("distinct positive numeric match ids required")
    if discovery_status not in ("validated_complete", "partial", "unknown", "unavailable"):
        raise ValueError("invalid discovery coverage")
    if discovery_status == "validated_complete" and not coverage_signature:
        raise ValueError("complete discovery requires coverage signature")
    if not all((habit_id, criterion_id, criterion_version, role, patch)):
        raise ValueError("versioned habit context required")
    if len({r.opportunity_id for r in records}) != len(records):
        raise ValueError("duplicate opportunity id")
    for r in records:
        if r.match_id not in match_ids or (r.criterion_id, r.role, r.patch) != (criterion_id, role, patch):
            raise ValueError("ledger record outside habit scope")
    assessed = tuple(r for r in records if _validated(r, criterion_version))
    examples = tuple(r.opportunity_id for r in assessed
                     if r.assessment.verdict == "confirmed_error_within_criterion")
    counters = tuple(r.opportunity_id for r in assessed
                     if r.assessment.verdict in ("good", "reasonable_options"))
    eligible = sum(r.eligibility == "eligible" for r in records)
    unknown = sum(r.eligibility == "unknown" for r in records) + eligible - len(assessed)
    reasons = []
    if discovery_status != "validated_complete":
        reasons.append("opportunity_discovery_not_validated_complete")
    if unknown:
        reasons.append("opportunity_or_assessment_unknown")
    if not assessed:
        reasons.append("no_validated_assessments")
    if len({r.assessment.evaluator_version for r in assessed}) > 1:
        reasons.append("mixed_evaluator_versions")
    if role == "unknown" or patch == "unknown":
        reasons.append("context_unknown")
    return HabitEvidence(habit_id, criterion_id, criterion_version, role, patch,
                         tuple(sorted(match_ids)), coverage_signature, discovery_status, records,
                         eligible, sum(r.eligibility == "ineligible" for r in records), len(assessed),
                         unknown, len(examples), sum(r.assessment.verdict == "probable_error"
                                                   for r in assessed), examples, counters, tuple(reasons))


@dataclass(frozen=True)
class CoachingPlan:
    habit_id: str
    status: Literal["exercise_available", "insufficient_evidence"]
    exercise: str | None
    trigger: str | None
    baseline_match_ids: tuple[int, ...]
    measured_behavior: str
    example_ids: tuple[str, ...]
    counterexample_ids: tuple[str, ...]
    guardrails: tuple[str, ...]
    reason_codes: tuple[str, ...]


def build_coaching_plan(habit: HabitEvidence, *, min_assessed: int = 5,
                        min_confirmed_errors: int = 3) -> CoachingPlan:
    """Conservative product policy thresholds; not empirically validated defaults.

    They establish neither statistical significance nor probability/confidence.
    Independent comprehension and behavior evaluation remain separate gates.
    """
    if type(min_assessed) is not int or type(min_confirmed_errors) is not int or min_assessed < 1 or min_confirmed_errors < 2:
        raise ValueError("training requires repeated evidence")
    reasons = list(habit.reason_codes)
    if habit.assessed_count < min_assessed:
        reasons.append("too_few_assessed_opportunities")
    if habit.confirmed_error_count < min_confirmed_errors:
        reasons.append("confirmed_pattern_not_repeated")
    if len({r.match_id for r in habit.records if r.opportunity_id in habit.example_ids}) < 2:
        reasons.append("pattern_not_observed_across_matches")
    if not habit.counterexample_ids:
        reasons.append("counterexamples_unavailable")
    allowed = not reasons
    return CoachingPlan(habit.habit_id, "exercise_available" if allowed else "insufficient_evidence",
                        "Перед выбором назови доступные альтернативы и условия применимости критерия; после матча сверь выбор с доказательствами."
                        if allowed else None, habit.criterion_id if allowed else None,
                        habit.match_ids, "Доля подтверждённых нарушений среди оценённых допустимых возможностей",
                        habit.example_ids, habit.counterexample_ids,
                        ("Не применяй правило за пределами проверенного патча и контекста.",
                         "Не заменяй оценку решения результатом драки.",
                         "Сравнивай контрпримеры и цену альтернатив перед изменением привычки."),
                        tuple(dict.fromkeys(reasons)))


@dataclass(frozen=True)
class ProgressObservation:
    status: Literal["comparable", "rebaseline_required", "insufficient_evidence"]
    reason_codes: tuple[str, ...]
    baseline_match_ids: tuple[int, ...]
    followup_match_ids: tuple[int, ...]
    baseline_rate: float | None
    followup_rate: float | None
    rate_delta: float | None
    interpretation: str


def compare_progress(baseline: HabitEvidence, followup: HabitEvidence) -> ProgressObservation:
    reasons = []
    if set(baseline.match_ids) & set(followup.match_ids):
        reasons.append("overlapping_match_sets")
    for name in ("criterion_id", "criterion_version", "evaluator_versions", "role", "patch", "coverage_signature"):
        if name == "evaluator_versions" and (not baseline.evaluator_versions or not followup.evaluator_versions):
            continue
        if getattr(baseline, name) != getattr(followup, name):
            reasons.append(f"{name}_changed")
    if not baseline.coverage_signature or not followup.coverage_signature:
        reasons.append("coverage_unknown")
    if baseline.role == "unknown" or followup.role == "unknown" or baseline.patch == "unknown" or followup.patch == "unknown":
        reasons.append("context_unknown")
    if any(h.discovery_status != "validated_complete" or h.unknown_count or not h.assessed_count
           for h in (baseline, followup)):
        reasons.append("comparable_assessment_coverage_unavailable")
    if any(len(h.evaluator_versions) > 1 for h in (baseline, followup)):
        reasons.append("mixed_evaluator_versions")
    status = "comparable" if not reasons else (
        "rebaseline_required" if any(r.endswith("_changed") for r in reasons) else "insufficient_evidence")
    a, b = baseline.confirmed_error_rate_among_assessed, followup.confirmed_error_rate_among_assessed
    return ProgressObservation(status, tuple(reasons), baseline.match_ids, followup.match_ids,
                               a, b, b - a if status == "comparable" else None,
                               "Изменение измеренной доли; причинный эффект тренера и исправление привычки не установлены.")
