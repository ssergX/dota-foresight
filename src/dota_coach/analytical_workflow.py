"""Executable prefix -> alternatives -> separately admitted case orchestration.

Only a backend caller can supply typed review context. Neither a portable input
nor an HTTP form can deserialize releases, registries or case admissions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from dota_coach.decisions.defensive_impact import ImpactAdmission, evaluate_defensive_impact, load_defensive_impact_input
from dota_coach.decisions.impact_pipeline import (CaseAdmission, ObservedChoice, ImpactCaseInput,
    assess_impact_case, build_impact_case, recheck_case_assessment)
from dota_coach.ingest.impact_prefix import ImpactPrefixRegistry, compile_impact_prefix
from dota_coach.validation.criterion_gate import CallerRegistry, ReleaseReceipt
from dota_coach.decisions.impact_pipeline import CaseAssessment
from dota_coach.decisions.terrain import TerrainRegistry
from dota_coach.learning.verified_history import (HistoryAdmission, HistoryCoachingScope,
    build_verified_history, history_document)


@dataclass(frozen=True)
class CaseReviewContext:
    release: ReleaseReceipt
    registry: CallerRegistry
    impact_admission: ImpactAdmission
    choice: ObservedChoice
    case_admission: CaseAdmission

    def __post_init__(self):
        for value, cls in ((self.release, ReleaseReceipt), (self.registry, CallerRegistry),
            (self.impact_admission, ImpactAdmission), (self.choice, ObservedChoice), (self.case_admission, CaseAdmission)):
            if not isinstance(value, cls):
                raise TypeError('typed backend-owned current case review required')


@dataclass(frozen=True)
class HistoryReviewContext:
    admission: HistoryAdmission
    case_registry: CallerRegistry
    current_case_admissions: tuple[CaseAdmission, ...]
    assessments: tuple[tuple[str, CaseAssessment], ...]
    coaching_scopes: tuple[HistoryCoachingScope, ...] = ()

    def __post_init__(self):
        if not isinstance(self.admission, HistoryAdmission) or not isinstance(self.case_registry, CallerRegistry):
            raise TypeError('typed backend-owned history review required')
        for values, cls in ((self.current_case_admissions, CaseAdmission), (self.coaching_scopes, HistoryCoachingScope)):
            if not isinstance(values, tuple) or len(values)>1024 or any(not isinstance(v,cls) for v in values):
                raise TypeError('bounded immutable current history reviews required')
        if (not isinstance(self.assessments, tuple) or len(self.assessments)>1024 or
            any(not isinstance(pair, tuple) or len(pair)!=2 or not isinstance(pair[0],str) or not pair[0]
                or not isinstance(pair[1],CaseAssessment) for pair in self.assessments) or
            len({pair[0] for pair in self.assessments})!=len(self.assessments)):
            raise TypeError('bounded exact opportunity/case witness associations required')


@dataclass(frozen=True)
class AnalyticsReviewContext:
    prefix_registry: ImpactPrefixRegistry | None = None
    case_review: CaseReviewContext | None = None
    history_review: HistoryReviewContext | None = None
    terrain_registry: TerrainRegistry | None = None

    def __post_init__(self):
        for value, cls in ((self.prefix_registry, ImpactPrefixRegistry), (self.case_review, CaseReviewContext),
            (self.history_review, HistoryReviewContext), (self.terrain_registry, TerrainRegistry)):
            if value is not None and not isinstance(value, cls):
                raise TypeError('portable analytical review context forbidden')


def evaluate_history_workflow(inputs, *, review=None):
    if review is not None and not isinstance(review, HistoryReviewContext):
        raise TypeError('portable history review forbidden')
    options = dict(inputs)
    if review is not None:
        bindings = dict(review.assessments)
        if set(bindings)-{o.opportunity_id for o in options['opportunities']}:
            raise ValueError('reviewed case outside supplied whole history census')
        options['opportunities'] = tuple(replace(o,assessment=bindings.get(o.opportunity_id,o.assessment)) for o in options['opportunities'])
        options.update(admission=review.admission,case_registry=review.case_registry,
            current_case_admissions=review.current_case_admissions,coaching_scopes=review.coaching_scopes)
    history = build_verified_history(**options)
    document_options = {} if review is None else {name:getattr(review,name) for name in
        ('admission','case_registry','current_case_admissions')}
    return history, history_document(history, **document_options)


@dataclass(frozen=True)
class WorkflowResult:
    prefix: dict | None
    impact: dict | None
    assessment: object | None

    def document(self, *, current_review=None):
        active = None
        if self.assessment is not None and current_review is not None:
            if not isinstance(current_review, CaseReviewContext):
                raise TypeError('typed current review required')
            active = recheck_case_assessment(self.assessment, registry=current_review.registry,
                current_case_admissions=(current_review.case_admission,))
        assessment = asdict(self.assessment) if self.assessment is not None else None
        # Exporting a snapshot never exports a reusable validation witness.
        if assessment is not None:
            assessment['snapshot_only'] = True
            assessment['current_review'] = active
            if active is None or not active['admitted_for_real_history']:
                assessment['verdict'] = 'insufficient_evidence'
                assessment['explanation_claims'] = tuple(c for c in assessment['explanation_claims'] if c.startswith('conditional:'))
                assessment['reason_codes'] = tuple(sorted(set(assessment['reason_codes']) | {'current_real_case_review_not_established'}))
        return {'schema_version':'foresight.analytical-workflow.v1', 'prefix':self.prefix,
            'defensive_impact':self.impact, 'case_assessment':assessment,
            'portable_document_grants_validation':False, 'training_eligible':False}


def evaluate_case_proposal(proposal, *, review=None):
    if review is not None and not isinstance(review, CaseReviewContext):
        raise TypeError('portable review context forbidden')
    case = proposal if isinstance(proposal, ImpactCaseInput) else build_impact_case(proposal)
    impact = evaluate_defensive_impact(case.scope, facts=case.facts, model=case.model, goal=case.goal)
    options = as_context_options(review)
    assessment = assess_impact_case(case, **options)
    return WorkflowResult(None, impact, assessment)


def as_context_options(review):
    # asdict would copy the minted release object and revoke its identity.
    return {} if review is None else {name:getattr(review, name) for name in
        ('release', 'registry', 'impact_admission', 'choice', 'case_admission')}


def evaluate_prefix_workflow(inputs, *, prefix_registry=None, review=None):
    if prefix_registry is not None and not isinstance(prefix_registry, ImpactPrefixRegistry):
        raise TypeError('portable prefix registry forbidden')
    if review is not None and not isinstance(review, CaseReviewContext):
        raise TypeError('portable case review forbidden')
    prefix = compile_impact_prefix(**inputs, registry=prefix_registry)
    candidate = prefix['candidate_defensive_impact_input']
    if candidate is None:
        return WorkflowResult(prefix, None, None)
    case = replace(build_impact_case(candidate), replay_hash=inputs['query'].replay_sha256)
    result = evaluate_case_proposal(case, review=review)
    return WorkflowResult(prefix, result.impact, result.assessment)
