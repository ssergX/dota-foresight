"""Current, receipt-bound personal history of a limited admitted criterion.

Portable records are proposals. Every rebuild rechecks the exact process-local
case witness and the caller's current source, census and goal registries. Rates
describe this criterion; they establish neither strategic quality nor a causal
effect of coaching. An absence in a partial ledger is never a denominator.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import MISSING, asdict, dataclass, fields
from datetime import datetime
from fractions import Fraction
import math
from pathlib import Path
from typing import TYPE_CHECKING
from weakref import ref

from dota_coach.evidence.contracts import SourceRef, TimeRef, content_hash
from dota_coach.learning.study import StudyMatch, select_study_matches
from dota_coach.validation.criterion_gate import CriterionIdentity

if TYPE_CHECKING:
    from dota_coach.decisions.impact_pipeline import CaseAssessment

SCHEMA = 'foresight.verified-history.v1'
MAX_MATCHES = 256
MAX_OPPORTUNITIES = 32768
CUES = ('noticed', 'observable_attention_unknown', 'not_observed', 'unreal', 'unknown')
_HISTORY_WITNESSES = {}


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError('bounded explicit identity/text required')


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('exact SHA256 binding required')


def _refs(value):
    if not isinstance(value, tuple) or not 1 <= len(value) <= 32 or any(not isinstance(s, SourceRef) for s in value):
        raise ValueError('bounded immutable source receipts required')
    for s in value:
        _sha(s.content_hash)
        for name in ('artifact_id', 'provider', 'schema_version', 'locator', 'extractor_version'):
            _text(getattr(s, name))
    if len({content_hash(s) for s in value}) != len(value):
        raise ValueError('duplicate source receipt')


def _stamp(value):
    _text(value)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('explicit timezone required')
    return parsed


def _verified_context(context):
    # Matching two unknown labels does not establish transfer comparability.
    return (context.role_quality == 'verified' and all(
        value == value.strip() and value.lower() not in ('unknown','unavailable','unverified','legacy')
        for value in (context.role,context.opponent_level_proxy)))


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _tuple(value, cls, limit):
    if not isinstance(value, tuple) or len(value) > limit or any(not isinstance(v, cls) for v in value):
        raise ValueError('bounded immutable typed input required')


@dataclass(frozen=True)
class HistoryContext:
    account_id: int
    subject_ref: str
    hero_id: int
    role: str
    role_quality: str
    opponent_level_proxy: str
    criterion: CriterionIdentity
    minimum_hp_goal: float | None = None
    minimum_mana_goal: float | None = None

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in (self.account_id, self.hero_id)):
            raise ValueError('positive account/hero required')
        for v in (self.subject_ref, self.role, self.opponent_level_proxy):
            _text(v)
        if self.subject_ref != f'account:{self.account_id}':
            raise ValueError('subject identity must bind the exact requested account')
        if self.role_quality not in ('verified', 'estimated', 'user_declared', 'unknown') or not isinstance(self.criterion, CriterionIdentity):
            raise ValueError('typed criterion and explicit role quality required')
        for v in (self.minimum_hp_goal, self.minimum_mana_goal):
            if v is not None and (not _finite(v) or v < 0):
                raise ValueError('finite nonnegative decision goal or unknown required')


@dataclass(frozen=True)
class HistoryMatch:
    match_id: int
    context: HistoryContext
    started_at: str
    ended_at: str
    replay_sha256: str
    observation_start_ms: float
    observation_end_ms: float
    source_refs: tuple[SourceRef, ...]
    dataset_kind: str = 'unknown'

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id <= 0 or not isinstance(self.context, HistoryContext):
            raise ValueError('typed match context required')
        if _stamp(self.started_at) >= _stamp(self.ended_at):
            raise ValueError('increasing match chronology required')
        _sha(self.replay_sha256); _refs(self.source_refs)
        if self.replay_sha256 not in {s.content_hash for s in self.source_refs}:
            raise ValueError('exact replay source receipt required')
        if (not _finite(self.observation_start_ms) or not _finite(self.observation_end_ms)
                or self.observation_start_ms >= self.observation_end_ms):
            raise ValueError('ordered finite full observation interval required')
        if self.dataset_kind not in ('replay', 'synthetic', 'unknown'):
            raise ValueError('explicit dataset provenance required')


@dataclass(frozen=True)
class HistoryFeature:
    name: str
    value: float | None
    unit: str
    scale_min: float
    scale_max: float
    measurement_version: str
    subject_ref: str
    available_at: TimeRef | None
    source_refs: tuple[SourceRef, ...]

    def __post_init__(self):
        for v in (self.name, self.unit, self.measurement_version, self.subject_ref):
            _text(v)
        _refs(self.source_refs)
        if not _finite(self.scale_min) or not _finite(self.scale_max) or self.scale_min >= self.scale_max:
            raise ValueError('finite increasing feature scale required')
        if self.value is not None and (not _finite(self.value) or not self.scale_min <= self.value <= self.scale_max):
            raise ValueError('finite measurement within explicit scale required')
        if self.available_at is not None and not isinstance(self.available_at, TimeRef):
            raise ValueError('typed measurement availability required')


@dataclass(frozen=True)
class HistoryOpportunity:
    opportunity_id: str
    match_id: int
    context: HistoryContext
    at: TimeRef
    eligibility: str
    cue_status: str
    source_refs: tuple[SourceRef, ...]
    assessment: CaseAssessment | None = None
    features: tuple[HistoryFeature, ...] = ()
    observed_action: str | None = None

    def __post_init__(self):
        _text(self.opportunity_id); _refs(self.source_refs)
        if type(self.match_id) is not int or self.match_id <= 0 or not isinstance(self.context, HistoryContext) or not isinstance(self.at, TimeRef):
            raise ValueError('typed opportunity scope and time required')
        if self.eligibility not in ('eligible', 'ineligible', 'unknown') or self.cue_status not in CUES:
            raise ValueError('explicit eligibility and distinct cue/attention status required')
        _tuple(self.features, HistoryFeature, 32)
        if len({f.name for f in self.features}) != len(self.features):
            raise ValueError('duplicate feature')
        if self.observed_action is not None and self.observed_action not in ('activate','hold'):
            raise ValueError('limited criterion observed action required')
        if self.assessment is not None:
            from dota_coach.decisions.impact_pipeline import CaseAssessment
            if not isinstance(self.assessment, CaseAssessment):
                raise ValueError('actual typed case assessment required; portable validation flags forbidden')
            if self.observed_action is not None and self.assessment.choice_action != self.observed_action:
                raise ValueError('style action contradicts actual case choice')


@dataclass(frozen=True)
class HistoryCoverage:
    match_hash: str
    context_hash: str
    opportunity_hashes: tuple[str, ...]
    start_ms: float
    end_ms: float
    census_version: str
    review_sources: tuple[SourceRef, ...]

    def __post_init__(self):
        _sha(self.match_hash); _sha(self.context_hash); _text(self.census_version); _refs(self.review_sources)
        if (not isinstance(self.opportunity_hashes, tuple) or len(self.opportunity_hashes) > MAX_OPPORTUNITIES
                or len(set(self.opportunity_hashes)) != len(self.opportunity_hashes)):
            raise ValueError('bounded exact full opportunity manifest required')
        for v in self.opportunity_hashes:
            _sha(v)
        if not _finite(self.start_ms) or not _finite(self.end_ms) or self.start_ms >= self.end_ms:
            raise ValueError('ordered census interval required')


@dataclass(frozen=True)
class HistoryGoal:
    goal_id: str
    context_hash: str
    statement: str
    exercise: str
    trigger: str
    measured_behavior: str
    source_refs: tuple[SourceRef, ...]

    def __post_init__(self):
        for v in (self.goal_id, self.statement, self.exercise, self.trigger, self.measured_behavior):
            _text(v)
        _sha(self.context_hash); _refs(self.source_refs)


@dataclass(frozen=True)
class HistoryAdmission:
    """Caller-owned current registry, never accepted by a portable JSON loader.

    Exact coverage admission attests census boundaries, identity/context, cue
    labels and the complete manifest, including explicit exclusions and unknowns.
    This class does not authenticate a reviewer or invent complete discovery.
    """
    match_hashes: frozenset[str]
    coverage_hashes: frozenset[str]
    source_hashes: frozenset[str]
    goal_hashes: frozenset[str] = frozenset()
    study_hashes: frozenset[str] = frozenset()
    coaching_hashes: frozenset[str] = frozenset()
    study_target_hashes: frozenset[str] = frozenset()

    def __post_init__(self):
        for values in (self.match_hashes, self.coverage_hashes, self.source_hashes, self.goal_hashes,
                       self.study_hashes, self.coaching_hashes, self.study_target_hashes):
            if not isinstance(values, frozenset) or len(values) > MAX_OPPORTUNITIES:
                raise ValueError('bounded immutable current registry required')
            for v in values:
                _sha(v)


@dataclass(frozen=True)
class HistoryPolicy:
    minimum_assessed: int = 5
    minimum_error_cases: int = 3
    minimum_error_matches: int = 2
    version: str = 'history-product-thresholds.v1'

    def __post_init__(self):
        _text(self.version)
        for v in (self.minimum_assessed, self.minimum_error_cases, self.minimum_error_matches):
            if type(v) is not int or not 2 <= v <= MAX_OPPORTUNITIES:
                raise ValueError('bounded repeated evidence policy required')


@dataclass(frozen=True)
class HistoryCoachingScope:
    context_hash: str
    coverage_hashes: tuple[str, ...]
    case_packet_hashes: tuple[str, ...]
    goal_hash: str
    policy_hash: str
    review_sources: tuple[SourceRef, ...]

    def __post_init__(self):
        for v in (self.context_hash, self.goal_hash, self.policy_hash):
            _sha(v)
        _refs(self.review_sources)
        for values in (self.coverage_hashes, self.case_packet_hashes):
            if not isinstance(values, tuple) or len(values) > MAX_OPPORTUNITIES or len(set(values)) != len(values):
                raise ValueError('bounded exact coaching scope manifest required')
            for v in values:
                _sha(v)


@dataclass(frozen=True)
class HistoryGroup:
    context: HistoryContext
    match_ids: tuple[int, ...]
    complete_match_ids: tuple[int, ...]
    census_versions: tuple[str, ...]
    opportunity_ids: tuple[str, ...]
    eligible_count: int
    ineligible_count: int
    unknown_count: int
    assessed_count: int
    error_count: int
    cue_counts: tuple[tuple[str, int], ...]
    example_ids: tuple[str, ...]
    counterexample_ids: tuple[str, ...]
    assessment_coverage: float | None
    error_rate_among_assessed: float | None
    complete_denominator_error_rate: float | None
    status: str
    exercise: HistoryGoal | None
    action_rates: tuple[tuple[str, int, int, float], ...]
    feature_means: tuple[tuple[str, str, str, float, int], ...]
    reason_codes: tuple[str, ...]
    style_observed_action_count: int = 0
    style_considered_opportunity_count: int = 0
    style_interpretation: str = 'own_observed_action_rates_and_resources_no_rarity_error_or_stable_style_label'


@dataclass(frozen=True)
class VerifiedHistory:
    account_id: int
    groups: tuple[HistoryGroup, ...]
    matches: tuple[HistoryMatch, ...]
    input_hash: str
    admission_hash: str | None
    policy: HistoryPolicy
    status: str
    reason_codes: tuple[str, ...]
    interpretation: str = 'operational_single_impact_criterion_only_no_strategic_quality_or_causal_coaching_claim'


def _source_active(sources, admission):
    return bool(admission and {content_hash(s) for s in sources} <= admission.source_hashes
                and all(getattr(s, 'provider', '').strip().lower() not in ('synthetic', 'fixture', 'testing')
                        for s in sources))


def _known_clock(at):
    return (at.order_status == 'verified' and at.game_time_ms is not None and at.uncertainty_ms is not None
            and at.replay_tick is not None and at.sequence_in_tick is not None
            and isinstance(at.clock_mapping_version,str)
            and at.clock_mapping_version.strip()==at.clock_mapping_version
            and at.clock_mapping_version.lower() not in ('', 'unknown', 'legacy/unverified', 'legacy/unknown', 'unavailable', 'unverified'))


def _feature_active(feature, opportunity, admission):
    return bool(feature.value is not None and feature.subject_ref == opportunity.context.subject_ref
                and feature.available_at is not None and _known_clock(feature.available_at)
                and _known_clock(opportunity.at) and feature.available_at.definitely_available_before(opportunity.at)
                and (feature.available_at.replay_tick, feature.available_at.sequence_in_tick)
                < (opportunity.at.replay_tick, opportunity.at.sequence_in_tick)
                and _source_active(feature.source_refs, admission))


def _case_active(opportunity, registry, admissions, *, replay_hash=None):
    case = opportunity.assessment
    if case is None or registry is None:
        return False
    from dota_coach.decisions.impact_pipeline import recheck_case_assessment
    check = recheck_case_assessment(case, registry=registry, current_case_admissions=admissions)
    return bool(check.get('active_case_witness') and check.get('admitted_for_real_history')
                and case.subject_ref == opportunity.context.subject_ref and case.match_id == opportunity.match_id
                and case.dataset_kind == 'replay' and case.criterion_identity == opportunity.context.criterion
                and case.decision_at == opportunity.at and _known_clock(case.decision_at)
                and case.replay_hash is not None and (replay_hash is None or case.replay_hash == replay_hash)
                and opportunity.context.minimum_hp_goal == case.minimum_hp_goal
                and opportunity.context.minimum_mana_goal == case.minimum_mana_goal
                and opportunity.eligibility == 'eligible' and opportunity.cue_status in ('noticed', 'observable_attention_unknown')
                and case.verdict != 'insufficient_evidence')


def build_verified_history(matches: tuple[HistoryMatch, ...], opportunities: tuple[HistoryOpportunity, ...],
                           coverages: tuple[HistoryCoverage, ...] = (), *, account_id: int,
                           admission: HistoryAdmission | None = None, case_registry=None,
                           current_case_admissions: tuple = (), goals: tuple[HistoryGoal, ...] = (),
                           coaching_scopes: tuple[HistoryCoachingScope, ...] = (),
                           policy: HistoryPolicy | None = None) -> VerifiedHistory:
    """Recompute whole supplied censuses; default inputs carry no authority."""
    _tuple(matches, HistoryMatch, MAX_MATCHES); _tuple(opportunities, HistoryOpportunity, MAX_OPPORTUNITIES)
    _tuple(coverages, HistoryCoverage, MAX_MATCHES); _tuple(goals, HistoryGoal, MAX_MATCHES)
    _tuple(coaching_scopes, HistoryCoachingScope, MAX_MATCHES)
    if type(account_id) is not int or account_id <= 0 or not isinstance(current_case_admissions, tuple):
        raise ValueError('positive account and immutable current case registry required')
    if admission is not None and not isinstance(admission, HistoryAdmission):
        raise ValueError('portable admission flags forbidden')
    policy = policy or HistoryPolicy()
    if not isinstance(policy, HistoryPolicy):
        raise ValueError('typed repetition policy required')
    by_match = {m.match_id: m for m in matches}
    if len(by_match) != len(matches) or len({m.replay_sha256 for m in matches}) != len(matches):
        raise ValueError('duplicate match or replay source copy')
    if len({o.opportunity_id for o in opportunities}) != len(opportunities):
        raise ValueError('duplicate opportunity id')
    cases = tuple(o.assessment for o in opportunities if o.assessment is not None)
    if (len({c.case_packet_hash for c in cases}) != len(cases)
            or len({c.input_hash for c in cases}) != len(cases)):
        raise ValueError('case witness or prefix input reused under another opportunity id')
    if len({c.match_hash for c in coverages}) != len(coverages):
        raise ValueError('duplicate census coverage')
    if len({g.context_hash for g in goals}) != len(goals):
        raise ValueError('ambiguous goals for context')
    if len({s.context_hash for s in coaching_scopes}) != len(coaching_scopes):
        raise ValueError('ambiguous coaching scopes')
    for m in matches:
        if m.context.account_id != account_id:
            raise ValueError('foreign account in personal history')
    for o in opportunities:
        m = by_match.get(o.match_id)
        if m is None or m.context != o.context or o.context.account_id != account_id:
            raise ValueError('opportunity outside exact user/match/context')
        if o.at.game_time_ms is None or not m.observation_start_ms <= o.at.game_time_ms <= m.observation_end_ms:
            raise ValueError('opportunity outside full observation interval')
    grouped = defaultdict(list)
    for m in matches:
        grouped[content_hash(m.context)].append(m)
    coverage_by_match = {c.match_hash: c for c in coverages}
    goals_by_context = {g.context_hash: g for g in goals}
    coaching_by_context = {s.context_hash: s for s in coaching_scopes}
    results = []
    for context_hash, group_matches in sorted(grouped.items()):
        context = group_matches[0].context
        ids = {m.match_id for m in group_matches}
        ledger = tuple(sorted((o for o in opportunities if o.match_id in ids), key=lambda o: (o.match_id, o.opportunity_id)))
        complete, versions = [], set()
        for m in group_matches:
            c = coverage_by_match.get(content_hash(m))
            supplied = tuple(o for o in ledger if o.match_id == m.match_id)
            if (admission and m.dataset_kind == 'replay' and content_hash(m) in admission.match_hashes
                    and _source_active(m.source_refs, admission) and c is not None
                    and content_hash(c) in admission.coverage_hashes and _source_active(c.review_sources, admission)
                    and c.context_hash == context_hash and c.start_ms == m.observation_start_ms
                    and c.end_ms == m.observation_end_ms
                    and set(c.opportunity_hashes) == {content_hash(o) for o in supplied}
                    and all(_source_active(o.source_refs, admission) and _known_clock(o.at) for o in supplied)):
                complete.append(m.match_id); versions.add(c.census_version)
        active = tuple(o for o in ledger if o.match_id in complete and _case_active(o, case_registry,
            current_case_admissions, replay_hash=by_match[o.match_id].replay_sha256))
        examples = tuple(o.opportunity_id for o in active if o.assessment.verdict == 'confirmed_error_within_criterion')
        counters = tuple(o.opportunity_id for o in active if o.assessment.verdict in ('good', 'reasonable_options'))
        eligible = sum(o.eligibility == 'eligible' for o in ledger)
        excluded = sum(o.eligibility == 'ineligible' for o in ledger)
        unknown = sum(o.eligibility == 'unknown' for o in ledger)+eligible-len(active)
        reasons = []
        if set(complete) != ids:
            reasons.append('whole_match_census_not_currently_admitted')
        if unknown:
            reasons.append('unknown_opportunities_or_inactive_case_witnesses')
        if not _verified_context(context):
            reasons.append('context_not_verified')
        if len(active) < policy.minimum_assessed:
            reasons.append('too_few_admitted_cases')
        if len(examples) < policy.minimum_error_cases:
            reasons.append('criterion_pattern_not_repeated')
        if len({o.match_id for o in active if o.opportunity_id in examples}) < policy.minimum_error_matches:
            reasons.append('pattern_not_repeated_across_matches')
        if not counters:
            reasons.append('counterexamples_unavailable')
        if len(versions) != 1:
            reasons.append('census_policy_unknown_or_mixed')
        goal = goals_by_context.get(context_hash)
        goal_active = bool(goal and admission and content_hash(goal) in admission.goal_hashes and _source_active(goal.source_refs, admission))
        if not goal_active:
            reasons.append('specific_goal_and_exercise_not_currently_admitted')
        coaching = coaching_by_context.get(context_hash)
        if (not coaching or not admission or content_hash(coaching) not in admission.coaching_hashes
                or not _source_active(coaching.review_sources, admission)
                or coaching.goal_hash != (content_hash(goal) if goal else None)
                or coaching.policy_hash != content_hash(policy)
                or set(coaching.coverage_hashes) != {content_hash(coverage_by_match[content_hash(m)])
                    for m in group_matches if m.match_id in complete}
                or set(coaching.case_packet_hashes) != {o.assessment.case_packet_hash for o in active}):
            reasons.append('separate_exact_history_coaching_scope_not_admitted')
        observed = tuple(o for o in ledger if o.match_id in complete and o.observed_action is not None)
        actions = Counter(o.observed_action for o in observed)
        features = defaultdict(list)
        for o in ledger:
            if o.match_id in complete:
                for f in o.features:
                    if _feature_active(f, o, admission):
                        features[(f.name, f.unit, f.measurement_version, f.scale_min, f.scale_max)].append(f.value)
        means = tuple((key[0], key[1], key[2], float(sum(Fraction(str(v)) for v in values)/len(values)), len(values))
                      for key, values in sorted(features.items()))
        results.append(HistoryGroup(context, tuple(sorted(ids)), tuple(sorted(complete)), tuple(sorted(versions)),
            tuple(o.opportunity_id for o in ledger), eligible, excluded, unknown, len(active), len(examples),
            tuple((v, sum(o.cue_status == v for o in ledger)) for v in CUES), examples, counters,
            len(active)/eligible if eligible else None, len(examples)/len(active) if active else None,
            len(examples)/eligible if eligible and not unknown and set(complete) == ids else None,
            'criterion_exercise_available' if not reasons else 'insufficient_evidence', goal if not reasons else None,
            tuple((action, count, len(observed), count/len(observed)) for action, count in sorted(actions.items())),
            means, tuple(reasons), style_observed_action_count=len(observed),
            style_considered_opportunity_count=len(tuple(o for o in ledger if o.match_id in complete))))
    ordered_matches = tuple(sorted(matches, key=lambda m: m.match_id))
    payload = {'matches': ordered_matches, 'opportunities': tuple(sorted(opportunities, key=lambda o: o.opportunity_id)),
               'coverages': tuple(sorted(coverages, key=lambda c: c.match_hash)), 'goals': tuple(sorted(goals, key=lambda g: g.goal_id)),
               'coaching_scopes': tuple(sorted(coaching_scopes, key=lambda s: s.context_hash)),
               'policy': policy}
    # content_hash handles single dataclasses, not arbitrary nested dataclasses.
    input_hash = content_hash({k: [asdict(v) for v in value] if isinstance(value, tuple) else asdict(value)
                               for k, value in payload.items()})
    admission_hash = None if admission is None else content_hash({name: sorted(getattr(admission, name))
        for name in ('match_hashes', 'coverage_hashes', 'source_hashes', 'goal_hashes', 'study_hashes',
                     'coaching_hashes', 'study_target_hashes')})
    status = 'criterion_exercise_available' if any(g.exercise for g in results) else 'insufficient_evidence'
    history = VerifiedHistory(account_id, tuple(results), ordered_matches, input_hash, admission_hash, policy, status,
                              () if results else ('no_personal_history_supplied',))
    key = id(history)
    def expired(reference):
        current = _HISTORY_WITNESSES.get(key)
        if current and current[0] is reference:
            _HISTORY_WITNESSES.pop(key, None)
    _HISTORY_WITNESSES[key] = (ref(history, expired), (matches, opportunities, coverages, goals, coaching_scopes, policy))
    return history


def recheck_history(history: VerifiedHistory, *, admission: HistoryAdmission | None = None,
                    case_registry=None, current_case_admissions: tuple = ()) -> dict:
    """Copies and imported DTOs have no witness; changed registries revoke rates."""
    if not isinstance(history, VerifiedHistory):
        raise ValueError('typed history required')
    witness = _HISTORY_WITNESSES.get(id(history))
    if not witness or witness[0]() is not history:
        return {'active_history_witness': False, 'reason': 'copied_imported_or_unissued_history'}
    matches, opportunities, coverages, goals, coaching_scopes, policy = witness[1]
    current = build_verified_history(matches, opportunities, coverages, account_id=history.account_id,
        admission=admission, case_registry=case_registry, current_case_admissions=current_case_admissions,
        goals=goals, coaching_scopes=coaching_scopes, policy=policy)
    return {'active_history_witness': current == history,
            'reason': 'current_exact_history' if current == history else 'current_registry_or_case_dependency_changed'}


def history_document(history: VerifiedHistory, *, admission: HistoryAdmission | None = None,
                     case_registry=None, current_case_admissions: tuple = ()) -> dict:
    if not isinstance(history, VerifiedHistory):
        raise ValueError('typed computed history required')
    check = recheck_history(history, admission=admission, case_registry=case_registry,
                            current_case_admissions=current_case_admissions)
    if not check['active_history_witness']:
        payload = {'schema_version': SCHEMA, 'account_id': history.account_id, 'status': 'insufficient_evidence',
                   'groups': [], 'input_hash': history.input_hash, 'reason_codes': [check['reason']],
                   'portable_authority': False, 'current_history_witness': False}
        return {**payload, 'payload_sha256': content_hash(payload)}
    payload = {'schema_version': SCHEMA, **asdict(history), 'portable_authority': False,
               'current_history_witness': True,
               'strategic_quality': 'not_established', 'causal_coaching_effect': 'not_established',
               'global_coaching_certified': False}
    return {**payload, 'payload_sha256': content_hash(payload)}


def compare_verified_progress(baseline: VerifiedHistory, followup: VerifiedHistory, *,
                              admission: HistoryAdmission | None = None, case_registry=None,
                              current_case_admissions: tuple = ()) -> dict:
    """Chronological, disjoint, comparable measurement; never coach causality."""
    reasons = []
    for history in (baseline, followup):
        if not recheck_history(history, admission=admission, case_registry=case_registry,
                               current_case_admissions=current_case_admissions)['active_history_witness']:
            reasons.append('history_witness_not_current_or_copied')
    if baseline.account_id != followup.account_id:
        reasons.append('account_changed')
    if {m.match_id for m in baseline.matches} & {m.match_id for m in followup.matches}:
        reasons.append('overlapping_matches')
    if {m.replay_sha256 for m in baseline.matches} & {m.replay_sha256 for m in followup.matches}:
        reasons.append('replay_copy_crosses_periods')
    if not baseline.matches or not followup.matches:
        reasons.append('empty_period')
    elif max(_stamp(m.ended_at) for m in baseline.matches) >= min(_stamp(m.started_at) for m in followup.matches):
        reasons.append('followup_not_strictly_after_baseline')
    if baseline.policy != followup.policy:
        reasons.append('measurement_policy_changed')
    a = {content_hash(g.context): g for g in baseline.groups}
    b = {content_hash(g.context): g for g in followup.groups}
    if set(a) != set(b):
        reasons.append('context_or_criterion_changed')
    measurements = []
    for key in sorted(set(a) & set(b)):
        left, right = a[key], b[key]
        if not _verified_context(left.context) or not _verified_context(right.context):
            reasons.append('comparable_context_not_verified')
        if (left.census_versions != right.census_versions or len(left.census_versions) != 1
                or left.complete_match_ids != left.match_ids or right.complete_match_ids != right.match_ids
                or left.unknown_count or right.unknown_count or left.assessed_count < baseline.policy.minimum_assessed
                or right.assessed_count < followup.policy.minimum_assessed):
            reasons.append('comparable_complete_measurement_unavailable')
        if left.complete_denominator_error_rate is not None and right.complete_denominator_error_rate is not None:
            measurements.append({'context_hash': key, 'baseline_rate': left.complete_denominator_error_rate,
                                 'followup_rate': right.complete_denominator_error_rate,
                                 'rate_delta': right.complete_denominator_error_rate-left.complete_denominator_error_rate})
    return {'status': 'comparable_descriptive_measurement' if not reasons else 'insufficient_evidence',
            'reason_codes': sorted(set(reasons)), 'measurements': measurements if not reasons else [],
            'baseline_input_hash': baseline.input_hash, 'followup_input_hash': followup.input_hash,
            'interpretation': 'rate_change_only_no_causal_coaching_effect_or_habit_correction_established'}


@dataclass(frozen=True)
class StudyEpisode:
    episode_id: str
    study: StudyMatch
    opportunity: HistoryOpportunity
    source_refs: tuple[SourceRef, ...]

    def __post_init__(self):
        _text(self.episode_id); _refs(self.source_refs)
        if not isinstance(self.study, StudyMatch) or not isinstance(self.opportunity, HistoryOpportunity):
            raise ValueError('typed source-backed study and case episode required')
        if self.study.match_id != self.opportunity.match_id or self.episode_id not in self.study.episode_refs:
            raise ValueError('exact study episode linkage required')
        if (self.opportunity.assessment is None or self.opportunity.assessment.replay_hash is None
                or self.opportunity.assessment.replay_hash not in {s.content_hash for s in self.source_refs}):
            raise ValueError('exact study case replay source receipt required')


def select_verified_study_episodes(target: HistoryOpportunity, episodes: tuple[StudyEpisode, ...], *,
                                  admission: HistoryAdmission | None = None, case_registry=None,
                                  current_case_admissions: tuple = (), limit: int = 3) -> dict:
    """Rank reviewed episodes by explicit scaled prefix measurements, not wins."""
    _tuple(episodes, StudyEpisode, 1024)
    if not isinstance(target, HistoryOpportunity) or type(limit) is not int or not 1 <= limit <= 32:
        raise ValueError('typed target and bounded result count required')
    if len({e.episode_id for e in episodes}) != len(episodes):
        raise ValueError('duplicate episode')
    target_features = {f.name: f for f in target.features if _feature_active(f, target, admission)}
    exclusions, selected = [], []
    target_current = bool(admission and content_hash(target) in admission.study_target_hashes
                          and _source_active(target.source_refs, admission)
                          and _case_active(target, case_registry, current_case_admissions))
    for e in episodes:
        o, study = e.opportunity, e.study
        reasons = []
        if not target_current:
            reasons.append('target_case_not_currently_admitted')
        if (not admission or content_hash(e) not in admission.study_hashes or not _source_active(e.source_refs, admission)
                or not _source_active(o.source_refs, admission) or not _source_active(study.sources, admission)):
            reasons.append('current_study_existence_expertise_replay_review_missing')
        selection = select_study_matches((study,), hero_id=target.context.hero_id,
                                          role=target.context.role, patch=target.context.criterion.patch, limit=1)
        if not selection.matches:
            reasons.extend(selection.exclusions[0][1])
        if (o.context.hero_id != target.context.hero_id or o.context.role != target.context.role
                or not _verified_context(o.context) or not _verified_context(target.context)
                or o.context.opponent_level_proxy != target.context.opponent_level_proxy
                or target.context.opponent_level_proxy == 'unknown'
                or (o.context.minimum_hp_goal, o.context.minimum_mana_goal)
                    != (target.context.minimum_hp_goal, target.context.minimum_mana_goal)
                or o.context.criterion != target.context.criterion):
            reasons.append('criterion_or_transfer_context_mismatch')
        if o.match_id == target.match_id or o.context.subject_ref == target.context.subject_ref:
            reasons.append('target_copy_or_own_episode')
        if o.assessment and target.assessment and o.assessment.replay_hash == target.assessment.replay_hash:
            reasons.append('target_replay_copy')
        if not _case_active(o, case_registry, current_case_admissions):
            reasons.append('study_case_not_currently_admitted')
        measured = {f.name: f for f in o.features if _feature_active(f, o, admission)}
        if (not target_features or len(target_features) != len(target.features)
                or len(measured) != len(o.features) or set(measured) != set(target_features)):
            reasons.append('same_complete_feature_inventory_unavailable')
        distances = []
        for name in sorted(set(measured) & set(target_features)):
            left, right = target_features[name], measured[name]
            if (left.unit, left.measurement_version, left.scale_min, left.scale_max) != (right.unit, right.measurement_version, right.scale_min, right.scale_max):
                reasons.append('feature_scale_or_measurement_mismatch')
            else:
                distances.append(abs(Fraction(str(left.value))-Fraction(str(right.value)))/
                                 (Fraction(str(left.scale_max))-Fraction(str(left.scale_min))))
        if reasons:
            exclusions.append({'episode_id': e.episode_id, 'reason_codes': sorted(set(reasons))})
        else:
            selected.append({'episode_id': e.episode_id, 'match_id': study.match_id,
                'url': next(s.url for s in study.sources if s.status == 'verified'),
                'scaled_mean_absolute_distance': float(sum(distances)/len(distances)),
                'feature_names': sorted(target_features), 'transfer_limitations': list(study.transfer_limitations),
                'criterion': asdict(target.context.criterion), 'case_packet_hash': o.assessment.case_packet_hash,
                'verdict': o.assessment.verdict, 'choice_action': o.assessment.choice_action,
                'alternatives': [asdict(a) for a in o.assessment.alternatives],
                'learning_task': study.learning_task})
    chosen = sorted(selected, key=lambda r: (r['scaled_mean_absolute_distance'], r['episode_id']))[:limit]
    return {'status': 'available' if chosen else 'unavailable', 'episodes': chosen, 'exclusions': exclusions,
            'reason_codes': [] if chosen else ['no_current_source_backed_comparable_decision_episodes'],
            'interpretation': 'scaled_prefix_feature_distance_only_no_style_label_or_win_utility'}


def load_verified_history_input(source) -> dict:
    """Strict bounded portable proposal loader; assessments cannot be imported."""
    from dota_coach.decisions.batch import strict_json
    if isinstance(source, Path) or (isinstance(source, str) and not source.lstrip().startswith('{')):
        path = Path(source)
        if path.stat().st_size > 16 << 20:
            raise ValueError('bounded history input required')
        data = strict_json(path.read_text(encoding='utf-8-sig'))
    elif isinstance(source, str):
        if len(source.encode('utf-8')) > 16 << 20:
            raise ValueError('bounded history input required')
        data = strict_json(source)
    else:
        data = source
    allowed = {'schema_version', 'account_id', 'matches', 'opportunities', 'coverages', 'goals', 'policy'}
    if (not isinstance(data, dict) or set(data)-allowed
            or not {'schema_version', 'account_id', 'matches', 'opportunities'} <= set(data)
            or data['schema_version'] != 'foresight.verified-history-input.v1'):
        raise ValueError('strict history proposal schema required; portable grants forbidden')

    def construct(cls, obj, **converted):
        if not isinstance(obj, dict):
            raise ValueError('typed proposal object required')
        definitions = fields(cls)
        permitted = {f.name for f in definitions}
        required = {f.name for f in definitions if f.default is MISSING and f.default_factory is MISSING}
        if set(obj)-permitted or not required <= set(obj):
            raise ValueError('unknown or missing proposal fields')
        try:
            return cls(**(obj | converted))
        except TypeError as exc:
            raise ValueError('malformed typed history proposal') from exc

    def sequence(name, limit):
        value = data.get(name, [])
        if not isinstance(value, list) or len(value) > limit or any(not isinstance(row,dict) for row in value):
            raise ValueError('bounded history proposal object arrays required')
        return value

    def sources(values):
        if not isinstance(values, list) or not 1 <= len(values) <= 32:
            raise ValueError('bounded proposal source array required')
        return tuple(construct(SourceRef, v) for v in values)

    def context(obj):
        if not isinstance(obj, dict):
            raise ValueError('context object required')
        return construct(HistoryContext, obj, criterion=construct(CriterionIdentity, obj.get('criterion')))

    def time(obj):
        result = construct(TimeRef, obj)
        _text(result.clock_mapping_version)
        return result

    matches = tuple(construct(HistoryMatch, obj, context=context(obj.get('context')),
                             source_refs=sources(obj.get('source_refs'))) for obj in sequence('matches', MAX_MATCHES))
    opportunities = []
    for obj in sequence('opportunities', MAX_OPPORTUNITIES):
        if not isinstance(obj, dict) or obj.get('assessment') is not None:
            raise ValueError('portable assessments or validation flags cannot issue a case witness')
        raw_features = obj.get('features', [])
        if not isinstance(raw_features, list) or len(raw_features) > 32 or any(not isinstance(f,dict) for f in raw_features):
            raise ValueError('bounded feature proposals required')
        features = tuple(construct(HistoryFeature, f,
            available_at=time(f['available_at']) if f.get('available_at') is not None else None,
            source_refs=sources(f.get('source_refs'))) for f in raw_features)
        opportunities.append(construct(HistoryOpportunity, obj, context=context(obj.get('context')),
            at=time(obj.get('at')), features=features, source_refs=sources(obj.get('source_refs'))))
    coverages = tuple(construct(HistoryCoverage, obj, opportunity_hashes=tuple(obj.get('opportunity_hashes', [])),
                               review_sources=sources(obj.get('review_sources')))
                      for obj in sequence('coverages', MAX_MATCHES))
    goals = tuple(construct(HistoryGoal, obj, source_refs=sources(obj.get('source_refs')))
                  for obj in sequence('goals', MAX_MATCHES))
    result = {'account_id': data['account_id'], 'matches': matches, 'opportunities': tuple(opportunities),
              'coverages': coverages, 'goals': goals,
              'policy': construct(HistoryPolicy, data['policy']) if 'policy' in data else HistoryPolicy()}
    # Structural joins are checked even though the result has no authority.
    build_verified_history(**result)
    return result
