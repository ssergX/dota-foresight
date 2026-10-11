"""Current release -> exact case review -> limited operational assessment.

The original impact evaluator stays research-only. This orchestration admits
only a reviewed goal-constraint rubric, not overall game quality. Case witnesses
are process-local and must be rechecked against current release and case reviews.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from weakref import ref

from dota_coach.evidence.contracts import EntityRef, SourceRef, TimeRef, content_hash
from dota_coach.validation.criterion_gate import (
    CallerRegistry, CriterionIdentity, ReleaseReceipt, _sources, check_inference,
)
from dota_coach.validation.contracts import sha256
from .choice_window import PrefixFact
from .defensive_impact import (
    VERSION, HistoricalImpactModel, ImpactAdmission, ImpactGoal, ImpactScope,
    _clock, _fraction, _visible, chosen_action_binding_hash, evaluate_defensive_impact,
    load_defensive_impact_input,
)

RUBRIC_VERSION = 'single-impact-goal-constraints.v1'
CASE_PASSES = frozenset({
    'complete_case_and_single_impact_scope', 'alternative_reasonableness_within_declared_goal',
    'own_command_stage_and_choice_authentication', 'rubric_covers_exact_policy_and_case',
    'case_evidence_and_explanation_entailment',
})
_CASE_WITNESSES = {}


def _hash_dataclass(value):
    result = asdict(value)
    for key, item in result.items():
        if isinstance(item, frozenset):
            result[key] = sorted(item)
    return content_hash(result)


def _case_clock(value):
    return bool(_clock(value) and value.clock_mapping_version == value.clock_mapping_version.strip()
                and value.clock_mapping_version.lower() != 'legacy')


@dataclass(frozen=True)
class ImpactCaseInput:
    scope: ImpactScope
    model: HistoricalImpactModel | None
    goal: ImpactGoal
    facts: tuple[PrefixFact, ...]
    replay_hash: str | None = None

    def __post_init__(self):
        if (not isinstance(self.scope, ImpactScope) or not isinstance(self.goal, ImpactGoal)
                or self.model is not None and not isinstance(self.model, HistoricalImpactModel)
                or not isinstance(self.facts, tuple) or len(self.facts) > 128
                or any(not isinstance(f, PrefixFact) for f in self.facts)):
            raise TypeError('bounded typed immutable impact case required')
        if self.replay_hash is not None:
            sha256(self.replay_hash, 'exact case replay hash')


@dataclass(frozen=True)
class ObservedChoice:
    input_hash: str
    subject_ref: str
    observer_ref: str
    item_entity: EntityRef
    action: str
    command_stage: str
    decision_at: TimeRef
    command_at: TimeRef
    observed_at: TimeRef
    source_refs: tuple[SourceRef, ...]

    def __post_init__(self):
        sha256(self.input_hash, 'choice input hash')
        if (not isinstance(self.item_entity, EntityRef) or not isinstance(self.decision_at, TimeRef)
                or not isinstance(self.command_at, TimeRef) or not isinstance(self.observed_at, TimeRef)
                or not self.subject_ref or not self.observer_ref):
            raise TypeError('exact own actor/item and typed command clock required')
        if ((self.action == 'activate' and self.command_stage not in ('command_accepted', 'activation_completed'))
                or (self.action == 'hold' and self.command_stage != 'explicit_hold_selected')
                or self.action not in ('activate', 'hold')):
            raise ValueError('explicit own command stage required; absence is not hold')
        _sources(self.source_refs)


@dataclass(frozen=True)
class CaseAdmission:
    case_packet_hash: str
    release_receipt_hash: str
    impact_admission_hash: str
    choice_hash: str
    rubric_version: str
    review_sources: tuple[SourceRef, ...]
    authenticated_passes: frozenset[str]

    def __post_init__(self):
        for field in ('case_packet_hash', 'release_receipt_hash', 'impact_admission_hash', 'choice_hash'):
            sha256(getattr(self, field), field)
        if self.rubric_version != RUBRIC_VERSION:
            raise ValueError('only the declared single-impact goal rubric is executable')
        _sources(self.review_sources)
        if not isinstance(self.authenticated_passes, frozenset) or not self.authenticated_passes <= CASE_PASSES:
            raise ValueError('typed exact external case review passes required')


def case_admission_hash(admission):
    if not isinstance(admission, CaseAdmission):
        raise TypeError('typed case admission required')
    return _hash_dataclass(admission)


@dataclass(frozen=True)
class NumericBounds:
    minimum: float
    maximum: float

    def __post_init__(self):
        if (type(self.minimum) not in (int, float) or type(self.maximum) not in (int, float)
                or not math.isfinite(self.minimum) or not math.isfinite(self.maximum) or self.minimum > self.maximum):
            raise ValueError('ordered finite numeric bounds required')


@dataclass(frozen=True)
class CaseAlternative:
    action: str
    feasibility: bool | None
    hp_after_impact: NumericBounds | None
    mana_after_action: NumericBounds | None
    goal_status: str

    def __post_init__(self):
        if (self.action not in ('activate', 'hold') or self.feasibility is not None and type(self.feasibility) is not bool
                or self.goal_status not in ('robustly_meets', 'robustly_fails', 'uncertain', 'infeasible')
                or any(v is not None and not isinstance(v, NumericBounds) for v in (self.hp_after_impact, self.mana_after_action))):
            raise ValueError('typed computed alternative required')


@dataclass(frozen=True)
class CaseAssessment:
    verdict: str
    match_id: int
    subject_ref: str
    dataset_kind: str
    decision_at: TimeRef
    replay_hash: str | None
    criterion_identity: CriterionIdentity | None
    input_hash: str
    case_packet_hash: str
    release_receipt_hash: str | None
    case_admission_hash: str | None
    alternatives: tuple[CaseAlternative, ...]
    choice_action: str | None
    timing_coverage: str | None
    minimum_hp_goal: float
    minimum_mana_goal: float
    evidence_refs: tuple[str, ...]
    explanation_claims: tuple[str, ...]
    reason_codes: tuple[str, ...]
    review_context: str
    interpretation: str = 'operational_single_impact_goal_constraints'
    rubric_version: str = RUBRIC_VERSION
    strategic_quality: str = 'not_established'
    training_eligible: bool = False
    global_coaching_certified: bool = False

    def __post_init__(self):
        if (self.verdict not in ('confirmed_error_within_criterion', 'good', 'reasonable_options', 'insufficient_evidence')
                or self.interpretation != 'operational_single_impact_goal_constraints' or self.rubric_version != RUBRIC_VERSION
                or self.strategic_quality != 'not_established' or self.training_eligible is not False
                or self.global_coaching_certified is not False or self.review_context not in ('testing', 'external_review', 'unadmitted')
                or not isinstance(self.decision_at, TimeRef) or not isinstance(self.alternatives, tuple)
                or any(not isinstance(a, CaseAlternative) for a in self.alternatives)):
            raise ValueError('immutable limited operational assessment required')
        for values in (self.evidence_refs, self.explanation_claims, self.reason_codes):
            if not isinstance(values, tuple) or any(not isinstance(v, str) for v in values):
                raise TypeError('immutable exact assessment claims required')


def build_impact_case(source):
    """Portable proposal only; no release/admission/outcome can be loaded here."""
    return ImpactCaseInput(**load_defensive_impact_input(source))


def _choice_known(case, choice, input_hash):
    if not (choice and choice.input_hash == input_hash and choice.subject_ref == case.scope.subject_ref
        and choice.observer_ref == case.scope.observer_ref == case.scope.subject_ref
        and choice.item_entity == case.scope.item_entity and choice.decision_at == case.scope.at
        and _case_clock(choice.observed_at) and _case_clock(choice.decision_at) and _case_clock(choice.command_at)
        and choice.observed_at.clock_mapping_version == choice.command_at.clock_mapping_version == choice.decision_at.clock_mapping_version
        and (choice.observed_at.replay_tick, choice.observed_at.sequence_in_tick)
            >= (choice.decision_at.replay_tick, choice.decision_at.sequence_in_tick)
        and _fraction(choice.observed_at.game_time_ms) - _fraction(choice.observed_at.uncertainty_ms)
            >= _fraction(choice.command_at.game_time_ms) + _fraction(choice.command_at.uncertainty_ms)
        and (choice.observed_at.replay_tick, choice.observed_at.sequence_in_tick)
            >= (choice.command_at.replay_tick, choice.command_at.sequence_in_tick)):
        return False
    if choice.command_stage in ('command_accepted', 'explicit_hold_selected'):
        return choice.command_at == choice.decision_at
    if case.model is None:
        return False
    earliest = (_fraction(case.scope.at.game_time_ms) - _fraction(case.scope.at.uncertainty_ms)
                + _fraction(case.model.activation_latency_min_ms))
    latest = (_fraction(case.scope.at.game_time_ms) + _fraction(case.scope.at.uncertainty_ms)
              + _fraction(case.model.activation_latency_max_ms))
    return bool(_fraction(choice.command_at.game_time_ms) - _fraction(choice.command_at.uncertainty_ms) >= earliest
        and _fraction(choice.command_at.game_time_ms) + _fraction(choice.command_at.uncertainty_ms) <= latest
        and (choice.command_at.replay_tick, choice.command_at.sequence_in_tick)
            >= (choice.decision_at.replay_tick, choice.decision_at.sequence_in_tick))


def impact_case_packet(case, *, release=None, impact_admission=None, choice=None):
    """Exact review binding. Action evidence is outside analytical prefix features."""
    if not isinstance(case, ImpactCaseInput):
        raise TypeError('typed case required')
    if release is not None and not isinstance(release, ReleaseReceipt):
        raise TypeError('portable release forbidden')
    if impact_admission is not None and not isinstance(impact_admission, ImpactAdmission):
        raise TypeError('portable impact admission forbidden')
    if choice is not None and not isinstance(choice, ObservedChoice):
        raise TypeError('typed own observed choice required')
    # The frozen evaluator enforces admissible prefix ordering/clock/perspective.
    prefix = tuple(f for f in case.facts if _visible(case.scope, f))
    return {'schema_version': 'foresight.impact-case-packet.v1', 'rubric_version': RUBRIC_VERSION,
        'scope': asdict(case.scope), 'model': asdict(case.model) if case.model else None,
        'replay_hash': case.replay_hash,
        'goal': asdict(case.goal), 'facts': [asdict(f) for f in sorted(prefix, key=lambda f: f.fact.predicate)],
        'release_receipt_hash': content_hash(release) if release else None,
        'impact_admission_hash': _hash_dataclass(impact_admission) if impact_admission else None,
        'choice': asdict(choice) if choice else None}


def _mint(assessment, release, admission, dependencies, synthetic_provenance):
    key = id(assessment)
    def expired(reference):
        current = _CASE_WITNESSES.get(key)
        if current is not None and current[0] is reference:
            _CASE_WITNESSES.pop(key, None)
    _CASE_WITNESSES[key] = (ref(assessment, expired), release, case_admission_hash(admission),
        frozenset(content_hash(s) for s in dependencies), synthetic_provenance)


def assess_impact_case(case, *, release=None, registry=None, impact_admission=None,
                       choice=None, case_admission=None):
    if registry is not None and not isinstance(registry, CallerRegistry):
        raise TypeError('portable current registry forbidden')
    if case_admission is not None and not isinstance(case_admission, CaseAdmission):
        raise TypeError('portable case admission forbidden')
    packet = impact_case_packet(case, release=release, impact_admission=impact_admission, choice=choice)
    result = evaluate_defensive_impact(case.scope, model=case.model, goal=case.goal, facts=case.facts,
        admission=impact_admission, chosen_action=choice.action if choice else None)
    reasons = list(result['reason_codes'])
    identity = release.identity if release else None
    identity_known = bool(identity and case.model and
        (identity.criterion_id, identity.patch, identity.item_id, identity.threat_id,
         identity.evaluator_version, identity.model_hash) == ('single_known_impact', case.scope.patch,
            case.scope.item_id, case.scope.threat_id, VERSION, content_hash(case.model)))
    if not identity_known:
        reasons.append('release_identity_model_scope_mismatch_or_missing')
    release_state = check_inference(identity, release, registry) if release and registry else None
    release_active = bool(release_state and release_state['active_exact_receipt'])
    if not release_active:
        reasons.append('current_exact_release_missing_stale_or_revoked')
    own_choice = _choice_known(case, choice, result['input_hash'])
    if (not own_choice or result['chosen_action_status'] != 'separately_reviewed_receipts'
            or not impact_admission or not choice or impact_admission.chosen_action_sources != choice.source_refs
            or impact_admission.chosen_action_binding_hash != chosen_action_binding_hash(
                result['input_hash'], choice.action, choice.source_refs)):
        reasons.append('own_command_choice_and_exact_impact_review_missing')
    packet_hash = content_hash(packet)
    case_bound = bool(case_admission and release and impact_admission and choice
        and case_admission.case_packet_hash == packet_hash
        and case_admission.release_receipt_hash == content_hash(release)
        and case_admission.impact_admission_hash == _hash_dataclass(impact_admission)
        and case_admission.choice_hash == content_hash(choice)
        and case_admission.authenticated_passes == CASE_PASSES)
    if not case_bound:
        reasons.append('independent_complete_case_alternative_and_rubric_review_missing')
    prefix = tuple(f for f in case.facts if _visible(case.scope, f))
    dependencies = (case.model.source_refs if case.model else ()) + case.goal.source_refs + tuple(
        s for f in prefix for s in f.fact.source_refs)
    if impact_admission:
        dependencies += impact_admission.review_sources + impact_admission.chosen_action_sources
    if choice:
        dependencies += choice.source_refs
    if case_admission:
        dependencies += case_admission.review_sources
    if registry is None or any(content_hash(s) not in registry.allowed_source_receipt_hashes for s in dependencies):
        reasons.append('current_exact_case_source_receipt_allowlist_missing')
    if case.scope.dataset_kind != 'replay':
        reasons.append('non_replay_case_not_real_history')
    if case.replay_hash is None:
        reasons.append('exact_case_replay_hash_missing')
    causal_clocks = (case.scope.at, case.goal.available_at) + ((case.model.available_at,) if case.model else ()) + tuple(
        t for f in prefix for t in (f.fact.valid_at, f.fact.available_at))
    if any(not _case_clock(t) for t in causal_clocks):
        reasons.append('case_dependency_clock_unverified_or_reserved')
    projected_min = next((f.fact.value for f in prefix
        if f.fact.predicate == 'threat.projected_impact_time_min_ms'), None)
    if (projected_min is not None and _clock(case.scope.at)
            and _fraction(projected_min) <= _fraction(case.scope.at.game_time_ms) + _fraction(case.scope.at.uncertainty_ms)):
        reasons.append('impact_order_not_strictly_after_choice')
    release_review_sources = tuple(s for a in registry.admissions if release and a.package_hash == release.package_hash
        for s in a.review_sources) if registry else ()
    synthetic_provenance = any(isinstance(s.provider, str) and s.provider.strip().lower() in ('synthetic', 'fixture', 'testing')
        for s in dependencies + release_review_sources)
    candidate = result['candidate_arithmetic']
    alternatives = tuple(CaseAlternative(action, data['feasibility'],
        NumericBounds(**data['hp_after_impact']) if data['hp_after_impact'] else None,
        NumericBounds(**data['mana_after_action']) if data['mana_after_action'] else None, data['goal_status'])
        for action, data in candidate['alternatives'].items()) if candidate else ()
    verdict = 'insufficient_evidence'
    admitted = not reasons and candidate is not None
    if admitted:
        selected = candidate['alternatives'][choice.action]
        other = candidate['alternatives']['hold' if choice.action == 'activate' else 'activate']
        if selected['feasibility'] is not True:
            reasons.append('observed_choice_conflicts_with_reviewed_feasibility')
        elif selected['goal_status'] == 'robustly_meets':
            verdict = 'reasonable_options' if other['goal_status'] == 'robustly_meets' else 'good'
        elif (selected['goal_status'] == 'robustly_fails' and other['feasibility'] is True
              and other['goal_status'] == 'robustly_meets'):
            verdict = 'confirmed_error_within_criterion'
        else:
            reasons.append('chosen_and_alternative_constraints_do_not_establish_verdict')
    claims = tuple('conditional:' + alt.action + ':' + alt.goal_status for alt in alternatives)
    if verdict != 'insufficient_evidence':
        claims += ('reviewed_observed_choice:' + choice.action,
                   'limited_goal_constraint_verdict:' + verdict)
    assessment = CaseAssessment(verdict, case.scope.match_id, case.scope.subject_ref,
        case.scope.dataset_kind, case.scope.at, case.replay_hash, identity, result['input_hash'], packet_hash,
        content_hash(release) if release else None, case_admission_hash(case_admission) if case_admission else None,
        alternatives, choice.action if choice else None, candidate['timing_coverage'] if candidate else None,
        case.goal.minimum_hp_after_impact, case.goal.minimum_mana_after_action,
        tuple(result['evidence_refs']), claims, tuple(sorted(set(reasons))),
        ('testing' if synthetic_provenance else registry.review_context) if verdict != 'insufficient_evidence' else 'unadmitted')
    if verdict != 'insufficient_evidence':
        _mint(assessment, release, case_admission, dependencies, synthetic_provenance)
    return assessment


def recheck_case_assessment(assessment, *, registry, current_case_admissions=()):
    if not isinstance(assessment, CaseAssessment) or not isinstance(registry, CallerRegistry):
        raise TypeError('typed case witness and current registry required')
    if (not isinstance(current_case_admissions, tuple) or len(current_case_admissions) > 1024
            or any(not isinstance(a, CaseAdmission) for a in current_case_admissions)):
        raise TypeError('bounded current typed case admissions required')
    witness = _CASE_WITNESSES.get(id(assessment))
    active = bool(witness and witness[0]() is assessment
        and witness[3] <= registry.allowed_source_receipt_hashes
        and any(case_admission_hash(a) == witness[2] for a in current_case_admissions)
        and check_inference(assessment.criterion_identity, witness[1], registry)['active_exact_receipt'])
    real = active and not witness[4] and registry.review_context == assessment.review_context == 'external_review'
    return {'active_case_witness': active, 'admitted_for_real_history': real,
        'testing_only': active and not real, 'per_history_coaching_scope_required': True,
        'training_eligible': False, 'strategic_quality': 'not_established',
        'decision_at': assessment.decision_at, 'replay_hash': assessment.replay_hash,
        'source_receipt_hashes': tuple(sorted(witness[3])) if active else (),
        'known_synthetic_provenance': witness[4] if active else None,
        'reason': 'current_exact_case_review' if real else 'testing_case_only' if active else 'missing_stale_copied_or_revoked_case'}
