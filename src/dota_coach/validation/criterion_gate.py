"""Versioned admission of one limited criterion, never global coaching validation.

Portable metrics are proposals. Only an independent caller-owned current registry
can approve the exact packet. Review passes are external attestations, not a
cryptographic authentication implementation. Per-case evidence remains separate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
import math
from weakref import ref

from dota_coach.evidence.contracts import SourceRef, content_hash
from .contracts import (ERROR_VERDICTS, Annotation, DatasetRecord, Prediction,
                        canonical_verdict, identifier, identifiers, sha256)
from .pipeline import _latest, audit_splits, evaluate_predictions

REQUIRED_PASSES = frozenset({
    'prespecified_policy', 'criterion_model_binding', 'human_identity_independence',
    'heldout_provenance_and_access', 'client_fact_correctness_and_availability',
    'explanation_entailment_and_authentication',
    'mixed_outcome_and_alternative_case_coverage',
})
MAX_RECORDS = 1024
# A typed DTO alone does not prove that evaluate_gate ran its software checks.
# Keep a process-local weak witness for the exact issued object. There is no
# portable receipt import; another process must recompute the reviewed packet.
_ISSUED_RECEIPTS = {}


def _mint(receipt, dependencies):
    key = id(receipt)
    def expired(reference):
        current = _ISSUED_RECEIPTS.get(key)
        if current is not None and current[0] is reference:
            _ISSUED_RECEIPTS.pop(key, None)
    _ISSUED_RECEIPTS[key] = (ref(receipt, expired), frozenset(content_hash(s) for s in dependencies))


def _identity_text(value, name):
    identifier(value, name)
    if len(value) > 512 or value.strip().lower() in ('unknown', 'unverified', 'unavailable'):
        raise ValueError('bounded known identity required: ' + name)


def _sources(sources):
    if not isinstance(sources, tuple) or not 1 <= len(sources) <= 32:
        raise ValueError('immutable bounded independent review sources required')
    for source in sources:
        if not isinstance(source, SourceRef):
            raise TypeError('typed source receipts required')
        sha256(source.content_hash, 'source digest')
        for field in ('artifact_id', 'provider', 'schema_version', 'locator', 'extractor_version'):
            _identity_text(getattr(source, field), field)
    if len({content_hash(s) for s in sources}) != len(sources):
        raise ValueError('duplicate review source receipt')


def _utc(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('explicit bounded UTC protocol timestamp required')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('UTC protocol timestamp required') from exc
    if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
        raise ValueError('UTC protocol timestamp required')
    return stamp


@dataclass(frozen=True)
class CriterionIdentity:
    criterion_id: str
    patch: str
    item_id: str
    threat_id: str
    evaluator_version: str
    model_hash: str

    def __post_init__(self):
        for field in ('criterion_id', 'patch', 'item_id', 'threat_id', 'evaluator_version'):
            _identity_text(getattr(self, field), field)
        sha256(self.model_hash, 'model_hash')


@dataclass(frozen=True)
class ReleasePolicy:
    version: str
    minimum_real_decisions: int
    minimum_matches: int
    minimum_players: int
    coverage_floor: float
    missed_assessable_ceiling: float
    false_positive_ceiling: float
    minimum_fact_reviews: int
    fact_error_ceiling: float
    agreement_floor: float
    minimum_reference_error_cases: int
    minimum_reference_nonerror_cases: int
    source_refs: tuple[SourceRef, ...]
    declared_at: str
    minimum_raters: int = 2

    def __post_init__(self):
        _identity_text(self.version, 'policy version')
        _sources(self.source_refs)
        _utc(self.declared_at)
        for field in ('minimum_real_decisions', 'minimum_matches', 'minimum_players', 'minimum_fact_reviews',
                      'minimum_reference_error_cases', 'minimum_reference_nonerror_cases'):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= MAX_RECORDS * 128:
                raise ValueError('positive bounded minimum required')
        if type(self.minimum_raters) is not int or not 2 <= self.minimum_raters <= 32:
            raise ValueError('at least two bounded independent raters required')
        for field in ('coverage_floor', 'missed_assessable_ceiling', 'false_positive_ceiling', 'fact_error_ceiling',
                      'agreement_floor'):
            value = getattr(self, field)
            try:
                valid = type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError('finite probability policy threshold required')


@dataclass(frozen=True)
class GateCohort:
    training_match_ids: tuple[int, ...] = ()
    retrieval_match_ids: tuple[int, ...] = ()
    training_player_ids: tuple[str, ...] = ()
    retrieval_player_ids: tuple[str, ...] = ()
    seal_source_refs: tuple[SourceRef, ...] = ()
    sealed_at: str | None = None

    def __post_init__(self):
        if self.seal_source_refs:
            _sources(self.seal_source_refs)
        elif not isinstance(self.seal_source_refs, tuple):
            raise TypeError('immutable seal receipts required')
        if self.sealed_at is not None:
            _utc(self.sealed_at)
        for field in ('training_match_ids', 'retrieval_match_ids'):
            values = getattr(self, field)
            if (not isinstance(values, tuple) or len(values) > MAX_RECORDS
                    or any(type(v) is not int or v <= 0 for v in values) or len(set(values)) != len(values)):
                raise ValueError('bounded unique external match inventory required')
        for field in ('training_player_ids', 'retrieval_player_ids'):
            values = getattr(self, field)
            identifiers(values, field)
            if len(values) > MAX_RECORDS * 10:
                raise ValueError('bounded external player inventory required')


@dataclass(frozen=True)
class FactRequirement:
    """Exact complete case fact inventory; its provenance requires external review."""
    decision_id: str
    input_hash: str
    fact_ids: tuple[str, ...]

    def __post_init__(self):
        _identity_text(self.decision_id, 'decision_id')
        sha256(self.input_hash, 'input_hash')
        identifiers(self.fact_ids, 'required fact ids')
        if not 1 <= len(self.fact_ids) <= 128:
            raise ValueError('nonempty bounded case fact inventory required')


@dataclass(frozen=True)
class ExplanationBinding:
    decision_id: str
    input_hash: str
    explanation_hash: str
    source_refs: tuple[SourceRef, ...]

    def __post_init__(self):
        _identity_text(self.decision_id, 'decision_id')
        sha256(self.input_hash, 'input_hash')
        sha256(self.explanation_hash, 'explanation_hash')
        _sources(self.source_refs)


@dataclass(frozen=True)
class GateAdmission:
    """External exact-packet approval, never decoded from portable JSON."""
    package_hash: str
    identity: CriterionIdentity
    policy_hash: str
    report_hash: str
    review_sources: tuple[SourceRef, ...]
    authenticated_passes: frozenset[str]

    def __post_init__(self):
        for field in ('package_hash', 'policy_hash', 'report_hash'):
            sha256(getattr(self, field), field)
        if not isinstance(self.identity, CriterionIdentity):
            raise TypeError('typed criterion identity required')
        _sources(self.review_sources)
        if (not isinstance(self.authenticated_passes, frozenset)
                or not self.authenticated_passes <= REQUIRED_PASSES):
            raise ValueError('typed exact external review passes required')


@dataclass(frozen=True)
class CallerRegistry:
    admissions: tuple[GateAdmission, ...]
    allowed_source_receipt_hashes: frozenset[str]
    review_context: str = 'external_review'

    def __post_init__(self):
        if (not isinstance(self.admissions, tuple) or len(self.admissions) > 128
                or any(not isinstance(a, GateAdmission) for a in self.admissions)):
            raise TypeError('bounded typed current admissions required')
        if len({a.package_hash for a in self.admissions}) != len(self.admissions):
            raise ValueError('ambiguous current package approval')
        if not isinstance(self.allowed_source_receipt_hashes, frozenset):
            raise TypeError('immutable receipt allowlist required')
        for digest in self.allowed_source_receipt_hashes:
            sha256(digest, 'allowed exact source receipt')
        if self.review_context not in ('external_review', 'testing'):
            raise ValueError('explicit external review or testing registry required')


@dataclass(frozen=True)
class ReleaseReceipt:
    identity: CriterionIdentity
    package_hash: str
    policy_hash: str
    report_hash: str
    admission_hash: str
    review_context: str
    schema_version: str = 'foresight.limited-criterion-release.v1'
    scope: str = 'limited_criterion_only'
    training_eligible: bool = False
    global_coaching_certified: bool = False
    game_correctness_basis: str = 'actual_external_review_not_software_or_crypto_authentication'

    def __post_init__(self):
        if not isinstance(self.identity, CriterionIdentity):
            raise TypeError('typed criterion identity required')
        for field in ('package_hash', 'policy_hash', 'report_hash', 'admission_hash'):
            sha256(getattr(self, field), field)
        if (self.review_context not in ('external_review', 'testing')
                or self.schema_version != 'foresight.limited-criterion-release.v1'
                or self.scope != 'limited_criterion_only' or self.training_eligible is not False
                or self.global_coaching_certified is not False
                or self.game_correctness_basis != 'actual_external_review_not_software_or_crypto_authentication'):
            raise ValueError('release cannot certify global coaching or training')


def _receipt(admission, registry):
    bound = asdict(admission)
    bound['authenticated_passes'] = sorted(admission.authenticated_passes)
    return ReleaseReceipt(admission.identity, admission.package_hash, admission.policy_hash,
                          admission.report_hash, content_hash(bound), registry.review_context)


def _active(admission, registry):
    return (admission.authenticated_passes == REQUIRED_PASSES
            and all(content_hash(s) in registry.allowed_source_receipt_hashes for s in admission.review_sources))


def _typed(values, cls, limit, name):
    if not isinstance(values, tuple) or len(values) > limit or any(not isinstance(v, cls) for v in values):
        raise TypeError('bounded immutable typed ' + name + ' required')


def evaluate_gate(identity, policy, records, predictions, annotations, *, cohort=GateCohort(),
                  fact_requirements=(), explanation_bindings=(), registry=None):
    """Recompute metrics and bind all revisions; default closed without registry.

The fact inventory is mandatory for admission: a few reviewed facts cannot
stand in for an unknown denominator of required case evidence.
"""
    if not isinstance(identity, CriterionIdentity) or not isinstance(policy, ReleasePolicy) or not isinstance(cohort, GateCohort):
        raise TypeError('typed criterion, prespecified policy and cohort required')
    if registry is not None and not isinstance(registry, CallerRegistry):
        raise TypeError('portable registry/admission grants forbidden')
    _typed(records, DatasetRecord, MAX_RECORDS, 'records')
    _typed(predictions, Prediction, MAX_RECORDS, 'predictions')
    _typed(annotations, Annotation, MAX_RECORDS * 8, 'annotations')
    _typed(fact_requirements, FactRequirement, MAX_RECORDS, 'fact inventories')
    _typed(explanation_bindings, ExplanationBinding, MAX_RECORDS, 'explanation bindings')
    report = evaluate_predictions(predictions, annotations, records, split='holdout', min_raters=policy.minimum_raters)
    strict_audit = audit_splits(records, training_match_ids=cohort.training_match_ids,
        retrieval_match_ids=cohort.retrieval_match_ids, training_player_ids=cohort.training_player_ids,
        retrieval_player_ids=cohort.retrieval_player_ids, require_all_player_disjoint=True)
    latest = tuple(sorted(_latest(annotations), key=lambda a: a.key))
    package = {'schema_version': 'foresight.criterion-gate-packet.v1', 'identity': asdict(identity),
        'policy': asdict(policy), 'cohort': asdict(cohort),
        'records': [asdict(r) for r in sorted(records, key=lambda r: r.decision_id)],
        'predictions': [asdict(p) for p in sorted(predictions, key=lambda p: p.decision_id)],
        'annotations': [asdict(a) for a in sorted(annotations, key=lambda a: a.key)],
        'latest_annotations': [a.annotation_hash for a in latest],
        'fact_requirements': [asdict(f) for f in sorted(fact_requirements, key=lambda f: f.decision_id)],
        'explanation_bindings': [asdict(e) for e in sorted(explanation_bindings, key=lambda e: e.decision_id)],
        'computed_report': report, 'strict_split_audit': strict_audit}
    package_hash = content_hash(package)
    reasons = []
    if (not cohort.seal_source_refs or cohort.sealed_at is None
            or _utc(policy.declared_at) >= _utc(cohort.sealed_at)):
        reasons.append('prespecified_policy_or_bound_cohort_seal_missing')
    heldout = tuple(r for r in records if r.split == 'holdout')
    if not strict_audit['valid']:
        reasons.append('split_leakage_or_incomplete_rosters')
    if any(r.dataset_kind != 'replay' for r in heldout):
        reasons.append('non_real_holdout')
    if any(r.patch != identity.patch for r in heldout):
        reasons.append('criterion_patch_mismatch')
    if any(p.evaluator_version != identity.evaluator_version for p in predictions):
        reasons.append('criterion_evaluator_version_mismatch')
    for name, measured, minimum in (
        ('real_decisions', report['cohort']['decision_count'], policy.minimum_real_decisions),
        ('matches', report['cohort']['match_count'], policy.minimum_matches),
        ('players', report['cohort']['target_player_count'], policy.minimum_players)):
        if measured < minimum:
            reasons.append('insufficient_' + name)
    interrater = report['interrater']
    if any(interrater[name] for name in ('incompatible_verdict_pairs', 'different_acceptable_set_pairs',
            'eligibility_disagreement_pairs', 'multi_rater_no_common_verdict_decisions')):
        reasons.append('rater_dissent')
    groups = {}
    for a in latest:
        if a.review_pass == 'decision_blinded':
            groups.setdefault(a.decision_id, []).append(a)
    reference_errors = reference_nonerrors = 0
    assessable = []
    for r in heldout:
        group = groups.get(r.decision_id, [])
        if (len(group) < policy.minimum_raters or any(a.annotator_kind != 'human_expert'
                or a.eligibility != 'eligible' or a.adjudication_status not in ('agreed', 'adjudicated') for a in group)):
            continue
        accepted = set.intersection(*({canonical_verdict(v) for v in a.acceptable_verdicts} for a in group))
        if not accepted or 'insufficient_evidence' in accepted or 'not_actionable' in accepted:
            continue
        assessable.append(r)
        reference_errors += int(accepted <= ERROR_VERDICTS)
        reference_nonerrors += int(not bool(accepted & ERROR_VERDICTS))
    if reference_errors < policy.minimum_reference_error_cases:
        reasons.append('insufficient_reference_error_cases')
    if reference_nonerrors < policy.minimum_reference_nonerror_cases:
        reasons.append('insufficient_reference_nonerror_cases')
    for name, measured, minimum in (
        ('assessable_real_decisions', len(assessable), policy.minimum_real_decisions),
        ('assessable_matches', len({r.match_id for r in assessable}), policy.minimum_matches),
        ('assessable_players', len({r.target_player for r in assessable}), policy.minimum_players)):
        if measured < minimum:
            reasons.append('insufficient_' + name)
    requirements = {f.decision_id: f for f in fact_requirements}
    explanations = {e.decision_id: e for e in explanation_bindings}
    heldout_predictions = {p.decision_id: p for p in predictions if p.decision_id in {r.decision_id for r in heldout}}
    if (len(explanations) != len(explanation_bindings) or set(explanations) != set(heldout_predictions)
            or any(e.input_hash != heldout_predictions[e.decision_id].input_hash for e in explanations.values()
                   if e.decision_id in heldout_predictions)):
        reasons.append('complete_bound_explanation_inventory_missing')
    if len(requirements) != len(fact_requirements) or set(requirements) != {r.decision_id for r in heldout}:
        reasons.append('complete_bound_fact_inventory_missing')
    for r in heldout:
        group = groups.get(r.decision_id, [])
        required = requirements.get(r.decision_id)
        if required is None or required.input_hash != r.input_hash:
            reasons.append('case_fact_inventory_not_bound')
        if len(group) < policy.minimum_raters:
            reasons.append('insufficient_independent_blinded_humans')
        for a in group:
            if (a.annotator_kind != 'human_expert' or a.dataset_kind != 'replay'
                    or a.outcome_visible or a.system_verdict_visible
                    or a.adjudication_status not in ('agreed', 'adjudicated') or a.eligibility == 'unknown'
                    or a.unknowns):
                reasons.append('human_blinded_reference_unreviewed_or_unknown')
            checks = {c.fact_id: c for c in a.facts_checked}
            if required is not None and not set(required.fact_ids) <= set(checks):
                reasons.append('required_facts_not_reviewed')
            if any(c.correctness == 'unverifiable' or c.availability != 'available' for c in checks.values()):
                reasons.append('fact_correctness_or_availability_unknown')
            cited = set(a.decisive_evidence_ids) | {e for action in a.available_actions for e in action.evidence_ids}
            if any(e not in checks or checks[e].correctness != 'correct' or checks[e].availability != 'available' for e in cited):
                reasons.append('decisive_or_action_evidence_not_correct_available')
            if any(action.feasibility == 'unknown' for action in a.available_actions):
                reasons.append('action_feasibility_unknown')
    for name, threshold, is_floor in (
        ('agreement_with_acceptable_sets', policy.agreement_floor, True),
        ('assessment_coverage', policy.coverage_floor, True),
        ('missed_assessable_cases', policy.missed_assessable_ceiling, False),
        ('false_positive_rate', policy.false_positive_ceiling, False)):
        metric = report['metrics'][name]
        if not metric['denominator'] or metric['unknown_count']:
            reasons.append('unknown_or_zero_denominator:' + name)
        else:
            exact = Fraction(metric['numerator'], metric['denominator'])
            bound = Fraction(str(threshold))
            if (exact < bound if is_floor else exact > bound):
                reasons.append('policy_threshold_failed:' + name)
    fact_review = report['fact_review']
    if any(f['decision_id'] not in requirements or f['fact_id'] not in requirements[f['decision_id']].fact_ids
           for f in fact_review['facts']):
        reasons.append('reviewed_fact_outside_bound_case_inventory')
    if fact_review['known_consensus_facts'] < policy.minimum_fact_reviews:
        reasons.append('insufficient_fact_reviews')
    error = fact_review['factual_error_rate']
    if (not error['denominator'] or error['unknown_or_disputed']
            or any(f['availability'] != 'available' for f in fact_review['facts'])):
        reasons.append('unknown_or_zero_fact_denominator')
    elif Fraction(error['numerator'], error['denominator']) > Fraction(str(policy.fact_error_ceiling)):
        reasons.append('policy_threshold_failed:fact_error_rate')
    software_pass = not reasons
    admission = next((a for a in registry.admissions if a.package_hash == package_hash
        and a.identity == identity and a.policy_hash == content_hash(policy)
        and a.report_hash == content_hash(report) and _active(a, registry)), None) if registry else None
    packet_sources = policy.source_refs + cohort.seal_source_refs + tuple(
        s for e in explanation_bindings for s in e.source_refs)
    if admission and any(content_hash(s) not in registry.allowed_source_receipt_hashes for s in packet_sources):
        admission = None
    if admission is None:
        reasons.append('independent_exact_packet_and_authenticated_passes_missing')
    receipt = _receipt(admission, registry) if software_pass and admission is not None else None
    if receipt is not None:
        _mint(receipt, packet_sources + admission.review_sources)
    return {'schema_version': 'foresight.criterion-gate-evaluation.v1', 'package_hash': package_hash,
        'policy_hash': content_hash(policy), 'identity_hash': content_hash(identity), 'report_hash': content_hash(report),
        'computed_report': report, 'strict_split_audit': strict_audit, 'software_metrics_pass': software_pass,
        'status': 'testing_receipt_only' if receipt and receipt.review_context == 'testing' else
                  'limited_criterion_available' if receipt else 'closed',
        'reason_codes': sorted(set(reasons)), 'release_receipt': receipt,
        'training_eligible': False, 'global_coaching_certified': False,
        'limitations': ['external_attestations_are_not_cryptographic_authentication',
            'receipt_does_not_admit_any_individual_case_or_promote_impact_review',
            'finite_prespecified_software_thresholds_do_not_prove_population_accuracy']}


def check_inference(identity, receipt, registry):
    """Current release check only. Every case still needs its own admissibility."""
    if not isinstance(identity, CriterionIdentity) or not isinstance(registry, CallerRegistry):
        raise TypeError('typed identity and current caller registry required')
    if receipt is not None and not isinstance(receipt, ReleaseReceipt):
        raise TypeError('portable release receipt forbidden')
    witness = _ISSUED_RECEIPTS.get(id(receipt)) if receipt is not None else None
    active = bool(receipt and witness and witness[0]() is receipt
        and witness[1] <= registry.allowed_source_receipt_hashes and receipt.identity == identity and any(
        a.identity == identity and _active(a, registry) and _receipt(a, registry) == receipt
        for a in registry.admissions))
    available = active and registry.review_context == 'external_review'
    return {'criterion_available': available, 'active_exact_receipt': active,
        'reason': 'active_limited_release' if available else 'testing_registry_not_real_release' if active else 'missing_stale_revoked_or_foreign_receipt',
        'per_case_admission_required': True, 'per_case_unknown_must_abstain': True,
        'receipt_transport': 'process_local_recompute_before_use_elsewhere',
        'impact_review_promoted': False, 'training_eligible': False, 'global_coaching_certified': False}
