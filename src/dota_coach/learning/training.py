"""Self-directed exercises and source-backed study matching.

User confirmation selects a learning goal; it does not establish an error.
Behavior journals measure the stated behavior, not the quality of the action.
Externally reviewed issues retain receipt references; no JSON flag grants a
criterion admission or independent validation to a gameplay evaluator.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import html
import json
import math
from pathlib import Path
from typing import Literal

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.study_sources import SourcedStudyExample, StudyDiscovery, estimate_role

TASKS = {
    "fight_entry": (
        "Перед добровольным присоединением к драке запиши свою задачу, наблюдаемый сигнал и две доступные альтернативы.",
        "Добровольный выбор присоединиться к драке; вынужденный бой исключай и указывай причину.",
        "Отметка записи задачи, наблюдаемого сигнала и двух альтернатив до выбора",
        ("Не задерживай необходимое действие ради заполнения журнала: заполняй после эпизода с честной отметкой времени.",
         "Присоединение и отказ от драки не оцениваются только по результату.")),
    "defensive_item_plan": (
        "Перед следующей защитной покупкой сформулируй наблюдаемую угрозу, две альтернативы и цену выбора. После изменения контекста пересмотри план.",
        "Выбор защитного предмета при наличии подтверждённой собственной цели; неизвестные предметы противника отметь отдельно.",
        "Запись угрозы, двух альтернатив и tradeoff перед покупкой",
        ("Это упражнение сравнения вариантов, а не указание покупать конкретный предмет.",
         "Не используй скрытые предметы врага и будущий исход для объяснения раннего выбора.")),
    "vision_plan": (
        "Перед установкой варда назови ближайшее действие команды и информацию, нужную для него; после эпизода отметь реально полученное наблюдение или unknown.",
        "Собственная установка варда; вынужденные и недоступные установки учитывай отдельно.",
        "Запись задачи обзора до установки и наблюдения после неё",
        ("Срок жизни и количество вардов не равны полезности.",
         "Запись цели не доказывает безопасность точки или качество установки.")),
    "choice_alternatives": (
        "Выбери один повторяемый тип решения и записывай цель, доступные сведения, две альтернативы и неизвестные условия.",
        "Повторяемый выбор, явно указанный пользователем; случаи без реального выбора исключай.",
        "Запись цели, доступной информации и двух альтернатив",
        ("Это самопроверка процесса, а не диагностика ошибки.",
         "Отделяй доступную информацию от увиденного после решения результата.")),
}
TASK_LABELS={'fight_entry':'подключение к драке','defensive_item_plan':'план защитных предметов',
    'vision_plan':'задача варда','choice_alternatives':'цель и альтернативы'}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: nonempty string required")


def _refs(value, name):
    if not isinstance(value, tuple) or any(not isinstance(v, str) or not v for v in value) or len(set(value)) != len(value):
        raise ValueError(f"{name}: immutable unique references required")


def _stamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed


@dataclass(frozen=True)
class TrainingGoal:
    goal_id: str
    task_code: str
    statement: str
    origin: Literal["user_confirmed", "reviewed_issue", "unconfirmed"]
    confirmation_refs: tuple[str, ...] = ()
    confirmed_at: str | None = None
    issue_id: str | None = None
    independent_review_refs: tuple[str, ...] = ()

    def __post_init__(self):
        _text(self.goal_id, "goal_id")
        _text(self.statement, "goal statement")
        if self.task_code not in TASKS or self.origin not in ("user_confirmed", "reviewed_issue", "unconfirmed"):
            raise ValueError("unsupported task/origin")
        _refs(self.confirmation_refs, "confirmation refs")
        _refs(self.independent_review_refs, "review refs")
        if self.origin == "user_confirmed" and (not self.confirmation_refs or self.confirmed_at is None):
            raise ValueError("user-directed goal requires explicit confirmation receipt and time")
        if self.origin == "reviewed_issue" and (not self.issue_id or not self.independent_review_refs):
            raise ValueError("reviewed issue requires independent review references")
        if self.issue_id is not None:
            _text(self.issue_id, "issue_id")
        if self.confirmed_at is not None:
            _stamp(self.confirmed_at)


@dataclass(frozen=True)
class TrainingScope:
    subject_ref: str
    hero_id: int
    role: str
    role_quality: str
    patch: str
    opponent_level_proxy: str
    measurement_version: str = "behavior-journal.v1"

    def __post_init__(self):
        for name in ("subject_ref", "role", "patch", "opponent_level_proxy", "measurement_version"):
            _text(getattr(self, name), name)
        if type(self.hero_id) is not int or self.hero_id <= 0 or self.role_quality not in ("verified", "estimated", "user_declared", "unknown"):
            raise ValueError("explicit hero/role quality required")


@dataclass(frozen=True)
class TrainingAssignment:
    assignment_id: str
    goal: TrainingGoal
    scope: TrainingScope
    status: str
    exercise: str | None
    eligibility_rule: str | None
    measured_behavior: str | None
    review_match_count: int
    guardrails: tuple[str, ...]
    reason_codes: tuple[str, ...]
    diagnostic_status: str = "no_gameplay_error_inferred"


def assign_exercise(goal: TrainingGoal, scope: TrainingScope, *, review_match_count: int = 3) -> TrainingAssignment:
    if not isinstance(goal, TrainingGoal) or not isinstance(scope, TrainingScope) or type(review_match_count) is not int or review_match_count < 1:
        raise ValueError("typed goal/scope and positive review period required")
    reasons = ("goal_not_confirmed",) if goal.origin == "unconfirmed" else ()
    instruction, eligibility, behavior, guardrails = TASKS[goal.task_code]
    return TrainingAssignment(content_hash((asdict(goal), asdict(scope), review_match_count)), goal, scope,
                              "assigned_self_directed" if not reasons else "unavailable",
                              instruction if not reasons else None, eligibility if not reasons else None,
                              behavior if not reasons else None, review_match_count, guardrails, reasons)


@dataclass(frozen=True)
class BehaviorOpportunity:
    opportunity_id: str
    match_id: int
    assignment_id: str
    eligibility: str
    behavior_completed: bool | None
    evidence_kind: str
    evidence_refs: tuple[str, ...]
    game_time_ms: int | None = None
    reason_codes: tuple[str, ...] = ()
    note: str | None = None

    def __post_init__(self):
        _text(self.opportunity_id, "opportunity_id")
        _text(self.assignment_id, "assignment_id")
        if type(self.match_id) is not int or self.match_id <= 0 or self.eligibility not in ("eligible", "ineligible", "unknown"):
            raise ValueError("valid match and eligibility required")
        if self.behavior_completed is not None and type(self.behavior_completed) is not bool:
            raise ValueError("behavior is explicit boolean or unknown")
        if self.evidence_kind not in ("user_journal", "independent_observation", "unknown"):
            raise ValueError("behavior evidence source required")
        _refs(self.evidence_refs, "behavior evidence")
        _refs(self.reason_codes, "behavior reasons")
        if self.note is not None and (not isinstance(self.note,str) or len(self.note)>2000):
            raise ValueError('journal note must be text up to 2000 characters')
        if self.behavior_completed is not None and (self.eligibility != "eligible" or not self.evidence_refs or self.evidence_kind == "unknown"):
            raise ValueError("known behavior needs eligible opportunity and evidence")
        if self.game_time_ms is not None and type(self.game_time_ms) is not int:
            raise ValueError("exact journal time or unknown required")


@dataclass(frozen=True)
class TrainingPeriod:
    period_id: str
    assignment_id: str
    scope: TrainingScope
    started_at: str
    ended_at: str
    match_ids: tuple[int, ...]
    opportunities: tuple[BehaviorOpportunity, ...]
    coverage_status: str
    coverage_refs: tuple[str, ...]
    coverage_policy: str

    def __post_init__(self):
        _text(self.period_id, "period_id")
        _text(self.assignment_id, "assignment_id")
        _text(self.coverage_policy, "coverage_policy")
        if not isinstance(self.scope, TrainingScope) or _stamp(self.started_at) >= _stamp(self.ended_at):
            raise ValueError("typed scope and increasing period required")
        if not isinstance(self.match_ids, tuple) or len(set(self.match_ids)) != len(self.match_ids) or any(type(m) is not int or m <= 0 for m in self.match_ids):
            raise ValueError("immutable distinct positive match set required")
        if not isinstance(self.opportunities, tuple) or any(not isinstance(o, BehaviorOpportunity) for o in self.opportunities):
            raise ValueError("typed full opportunity ledger required")
        if len({o.opportunity_id for o in self.opportunities}) != len(self.opportunities):
            raise ValueError("duplicate behavior opportunity")
        if any(o.match_id not in self.match_ids or o.assignment_id != self.assignment_id for o in self.opportunities):
            raise ValueError("behavior opportunity outside period/assignment")
        if self.coverage_status not in ("user_journal_complete", "verified_complete", "partial", "unknown"):
            raise ValueError("explicit journal coverage required")
        _refs(self.coverage_refs, "coverage refs")
        if self.coverage_status.endswith("complete") and not self.coverage_refs:
            raise ValueError("complete coverage requires evidence receipt")


@dataclass(frozen=True)
class PeriodMeasurement:
    period_id: str
    considered_matches: int
    supplied_opportunities: int
    eligible: int
    ineligible: int
    eligibility_unknown: int
    behavior_observed: int
    behavior_completed: int
    behavior_unknown: int
    completion_rate_among_observed: float | None
    coverage_among_eligible: float | None
    evidence_kinds: tuple[str, ...]
    population_status: str
    example_ids: tuple[str, ...]
    counterexample_ids: tuple[str, ...]
    limitations: tuple[str, ...]


def summarize_period(period: TrainingPeriod) -> PeriodMeasurement:
    eligible = tuple(o for o in period.opportunities if o.eligibility == "eligible")
    observed = tuple(o for o in eligible if o.behavior_completed is not None)
    completed = tuple(o for o in observed if o.behavior_completed)
    return PeriodMeasurement(period.period_id, len(period.match_ids), len(period.opportunities), len(eligible),
                             sum(o.eligibility == "ineligible" for o in period.opportunities),
                             sum(o.eligibility == "unknown" for o in period.opportunities), len(observed), len(completed),
                             len(eligible) - len(observed), len(completed) / len(observed) if observed else None,
                             len(observed) / len(eligible) if eligible else None,
                             tuple(sorted({o.evidence_kind for o in observed})), period.coverage_status,
                             tuple(o.opportunity_id for o in completed),
                             tuple(o.opportunity_id for o in observed if not o.behavior_completed),
                             ("Измеряется выполнение выбранного упражнения, а не правильность игрового решения.",
                              "User journal — самоотчёт; полное заполнение не является независимой аттестацией поведения."))


@dataclass(frozen=True)
class TrainingProgress:
    status: str
    baseline: PeriodMeasurement
    followup: PeriodMeasurement
    completion_rate_delta: float | None
    reason_codes: tuple[str, ...]
    conclusion: str = "Изменение измеренного поведения не устанавливает исправление ошибки или причинный эффект тренера."


def compare_training_periods(baseline: TrainingPeriod, followup: TrainingPeriod) -> TrainingProgress:
    a, b = summarize_period(baseline), summarize_period(followup)
    reasons = []
    if baseline.assignment_id != followup.assignment_id:
        reasons.append("assignment_changed")
    if set(baseline.match_ids) & set(followup.match_ids):
        reasons.append("overlapping_matches")
    if _stamp(baseline.ended_at) > _stamp(followup.started_at):
        reasons.append("overlapping_or_reversed_periods")
    if baseline.scope != followup.scope:
        reasons.append("context_or_measurement_changed")
    if baseline.scope.role_quality == "unknown" or followup.scope.role_quality == "unknown":
        reasons.append("comparison_role_quality_unknown")
    if any(v in ("unknown", "estimated:unknown") for v in (baseline.scope.role, baseline.scope.patch, baseline.scope.opponent_level_proxy)):
        reasons.append("comparison_context_unknown")
    if baseline.coverage_status != followup.coverage_status or baseline.coverage_policy != followup.coverage_policy:
        reasons.append("coverage_changed")
    if a.evidence_kinds and b.evidence_kinds and a.evidence_kinds != b.evidence_kinds:
        reasons.append("evidence_source_changed")
    if any(p.coverage_status not in ("verified_complete", "user_journal_complete") for p in (baseline, followup)):
        reasons.append("opportunity_population_unknown")
    if any(m.eligibility_unknown or m.behavior_unknown or not m.behavior_observed for m in (a, b)):
        reasons.append("behavior_or_eligibility_missing")
    status = "comparable_self_report" if not reasons and a.evidence_kinds == ("user_journal",) else "comparable_observations" if not reasons else "rebaseline_required" if any(r.endswith("_changed") for r in reasons) else "insufficient_evidence"
    return TrainingProgress(status, a, b,
                            b.completion_rate_among_observed - a.completion_rate_among_observed if not reasons else None,
                            tuple(reasons))


# Fixed, transparent display scales. They normalize feature units and are not
# empirically learned style weights, a quality benchmark, or win probabilities.
FEATURE_SCALES = {"gold_per_min": 500., "last_hits_per_min": 10., "deaths_per_10min": 5.,
                  "wards_per_10min": 5., "teamfight_participation": 1.}


@dataclass(frozen=True)
class StyleFeature:
    name: str
    value: float | None
    evidence_refs: tuple[str, ...]
    method: str = "descriptive-match-aggregate.v1"


@dataclass(frozen=True)
class StudyTaskMatch:
    match_id: int
    task_code: str
    episode_refs: tuple[str, ...]
    viewing_task: str
    differences: tuple[str, ...]
    descriptive_feature_distance: float | None
    shared_feature_count: int
    requested_feature_count: int
    missing_features: tuple[str, ...]
    source_receipt_ids: tuple[str, ...]
    candidate_features: tuple[StyleFeature, ...]
    quality_claim: str = "not_established"


@dataclass(frozen=True)
class PersonalizedStudySelection:
    status: str
    goal_id: str
    matches: tuple[StudyTaskMatch, ...]
    exclusions: tuple[tuple[int, tuple[str, ...]], ...]
    target_features: tuple[StyleFeature, ...]
    limitations: tuple[str, ...]


def _features(raw: dict, player: dict, pointer: str) -> tuple[StyleFeature, ...]:
    duration = raw.get("duration")
    minutes = duration / 60 if type(duration) in (int, float) and math.isfinite(duration) and duration > 0 else None
    features = []
    for name, source_key, factor in (("gold_per_min", "gold_per_min", None), ("last_hits_per_min", "last_hits", 1),
                                     ("deaths_per_10min", "deaths", 10), ("wards_per_10min", "obs_placed", 10),
                                     ("teamfight_participation", "teamfight_participation", None)):
        raw_value = player.get(source_key)
        known = type(raw_value) in (int, float) and math.isfinite(raw_value) and raw_value >= 0
        value = float(raw_value) if known and factor is None else raw_value / minutes * factor if known and minutes else None
        if name == "teamfight_participation" and value is not None and value > 1:
            value = None
        refs = (pointer + "/" + source_key,) + ((pointer.split("#/players/")[0] + "#/duration",) if factor is not None else ())
        features.append(StyleFeature(name, value, refs if value is not None else ()))
    return tuple(features)


def match_study_to_goal(goal: TrainingGoal, target_raw: dict, *, account_id: int,
                        discovery: StudyDiscovery, limit: int = 3,
                        requested_features: tuple[str, ...] = tuple(FEATURE_SCALES),
                        min_shared_features: int = 3) -> PersonalizedStudySelection:
    """Match a confirmed task first, then rank transparent descriptive features.

    Candidate tasks use actual sourced event pointers. Similarity only compares
    the stated measurements: neither stable style nor tactical equivalence is
    inferred. Missing features are reported and do not receive zero distance.
    """
    if not isinstance(goal, TrainingGoal) or not isinstance(discovery, StudyDiscovery) or not isinstance(target_raw, dict):
        raise ValueError("typed goal, captured discovery and target match required")
    if type(account_id) is not int or account_id <= 0 or type(limit) is not int or limit < 1:
        raise ValueError("positive account and selection limit required")
    if not isinstance(requested_features, tuple) or not requested_features or len(set(requested_features)) != len(requested_features) or any(v not in FEATURE_SCALES for v in requested_features) or type(min_shared_features) is not int or not 1 <= min_shared_features <= len(requested_features):
        raise ValueError("explicit unique feature set/shared threshold required")
    target_id = target_raw.get("match_id")
    if type(target_id) is not int or target_id <= 0 or not isinstance(target_raw.get("players"), list):
        raise ValueError("target match identity/roster required")
    own = [(i, p) for i, p in enumerate(target_raw["players"]) if isinstance(p, dict) and type(p.get("account_id")) is int and p.get("account_id") == account_id]
    if len(own) != 1:
        raise ValueError("target association absent or ambiguous")
    ordinal, player = own[0]
    role = estimate_role(target_raw, player, "target-source").role
    target_pointer = "local-match:" + content_hash(target_raw) + f"#/players/{ordinal}"
    features = _features(target_raw, player, target_pointer)
    target_values = {f.name: f.value for f in features}
    exclusions, candidates = [], []
    for example in discovery.examples:
        study = example.study
        reasons = []
        if goal.origin == "unconfirmed":
            reasons.append("goal_not_confirmed")
        if study.match_id == target_id:
            reasons.append("target_match_is_not_external_example")
        if study.hero_id != player.get("hero_id"):
            reasons.append("hero_mismatch")
        if target_raw.get("patch") is None or example.patch_id != target_raw.get("patch"):
            reasons.append("provider_patch_mismatch_or_unknown")
        if role == "unknown" or example.role_estimate.role != role:
            reasons.append("role_mismatch_or_unknown")
        if example.expertise_class not in ("registered_pro", "high_rank") or study.dataset_kind != "real" or not any(s.status == "verified" for s in study.sources):
            reasons.append("strong_player_source_not_confirmed")
        if example.replay_probe.status != "available":
            reasons.append("captured_replay_availability_unknown")
        receipts = [r for r in example.receipts if r.source_url.endswith(f"/matches/{study.match_id}")]
        if len(receipts) != 1:
            reasons.append("candidate_match_receipt_missing")
            exclusions.append((study.match_id, tuple(reasons)))
            continue
        receipt = receipts[0]
        raw = receipt.data
        actors = [(i, p) for i, p in enumerate(raw["players"]) if p["player_slot"] == example.player_slot and p["hero_id"] == study.hero_id and p.get("account_id") == example.account_id]
        if len(actors) != 1:
            reasons.append("candidate_association_not_supported")
            exclusions.append((study.match_id, tuple(reasons)))
            continue
        actor_ordinal, actor = actors[0]
        pointer = receipt.receipt_id + f"#/players/{actor_ordinal}"
        episode_refs = []
        if goal.task_code in ("fight_entry", "choice_alternatives"):
            episode_refs = [receipt.receipt_id + f"#/teamfights/{i}" for i, tf in enumerate(raw.get("teamfights") or []) if isinstance(tf, dict) and type(tf.get("start")) in (int, float) and math.isfinite(tf["start"]) and tf["start"] >= 0][:3]
        elif goal.task_code == "defensive_item_plan":
            defensive = {"black_king_bar", "manta", "force_staff", "hurricane_pike", "glimmer_cape", "sphere", "aeon_disk", "lotus_orb"}
            episode_refs = [pointer + f"/purchase_log/{i}" for i, p in enumerate(actor.get("purchase_log") or []) if isinstance(p, dict) and p.get("key") in defensive][:3]
        elif goal.task_code == "vision_plan":
            episode_refs = [pointer + f"/obs_log/{i}" for i, w in enumerate(actor.get("obs_log") or []) if isinstance(w, dict) and type(w.get("time")) in (int, float) and math.isfinite(w["time"])][:3]
        if not episode_refs:
            reasons.append("requested_task_source_episode_missing")
        if reasons:
            exclusions.append((study.match_id, tuple(dict.fromkeys(reasons))))
            continue
        candidate_features = _features(raw, actor, pointer)
        candidate_values = {f.name: f.value for f in candidate_features}
        shared = tuple(f for f in requested_features if target_values[f] is not None and candidate_values[f] is not None)
        missing = tuple(f for f in requested_features if f not in shared)
        distance = sum(abs(candidate_values[f] - target_values[f]) / FEATURE_SCALES[f] for f in shared) / len(shared) if len(shared) >= min_shared_features else None
        differences = ["role_is_estimated_not_verified", "team_goals_opponents_and_known_information_differ",
                       "aggregate_feature_distance_is_not_decision_quality_or_stable_style", "captured_replay_probe_may_expire"]
        if missing:
            differences.append("feature_missingness:" + ",".join(missing))
        if example.account_id == account_id:
            differences.append("same_account_other_match_not_independent_player_example")
        viewing = (f"Твоя цель: {goal.statement.rstrip('.')}. В матче {study.match_id} изучи {len(episode_refs)} отмеченных мест для задачи «{TASK_LABELS[goal.task_code]}». "
                   "Сначала запиши цель, доступные сведения и варианты игрока; затем сравни процесс выбора со своим. Итог эпизода отдели от качества решения.")
        candidates.append(StudyTaskMatch(study.match_id, goal.task_code, tuple(episode_refs), viewing, tuple(differences), distance,
                                          len(shared), len(requested_features), missing,
                                          tuple(r.receipt_id for r in example.receipts), candidate_features))
    candidates.sort(key=lambda c: (c.descriptive_feature_distance is None, -c.shared_feature_count,
                                    c.descriptive_feature_distance if c.descriptive_feature_distance is not None else math.inf, c.match_id))
    return PersonalizedStudySelection("task_matched_descriptive_examples" if candidates else "unavailable", goal.goal_id,
                                      tuple(candidates[:limit]), tuple(exclusions), features,
                                      ("User-confirmed цель не является подтверждением ошибки.",
                                       "Feature scales заданы для сравнения единиц; статистически не обучены и не валидируют сходство стиля.",
                                       "Task anchors из журналов обозначают места изучения, не доказанные границы решения."))


def _strict_object(text: str) -> dict:
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValueError("duplicate training JSON key")
            data[key] = value
        return data
    def invalid(value):
        raise ValueError("nonfinite training JSON number")
    data = json.loads(text, object_pairs_hook=unique, parse_constant=invalid)
    if not isinstance(data, dict):
        raise ValueError("training JSON object required")
    return data


def _tuple_field(row: dict, name: str, *, default=False):
    value = row.get(name, []) if default else row[name]
    if not isinstance(value, list):
        raise ValueError(f"{name} must be an array")
    row[name] = tuple(value)


def load_training_goal(text: str) -> TrainingGoal:
    """Load a declared goal; references require human/provenance review.

    Confirmation is an explicit user's choice, not a finding of the engine.
    Loading cannot promote any evaluator, issue label or independently judged
    decision into a validated gameplay assessment.
    """
    row = _strict_object(text)
    if set(row) - {"goal_id", "task_code", "statement", "origin", "confirmation_refs", "confirmed_at", "issue_id", "independent_review_refs"}:
        raise ValueError("unknown training goal fields")
    for name in ("confirmation_refs", "independent_review_refs"):
        _tuple_field(row, name, default=True)
    if row.get('origin')=='reviewed_issue':
        # References in a user-supplied file are not resolved review receipts.
        row['origin']='unconfirmed'
    return TrainingGoal(**row)


def load_training_scope(text: str) -> TrainingScope:
    row = _strict_object(text)
    if set(row) - {"subject_ref", "hero_id", "role", "role_quality", "patch", "opponent_level_proxy", "measurement_version"}:
        raise ValueError("unknown training scope fields")
    if row.get('role_quality')=='verified':
        row['role_quality']='user_declared'
    return TrainingScope(**row)


def load_training_period(text: str) -> TrainingPeriod:
    row = _strict_object(text)
    if set(row) != {"period_id", "assignment_id", "scope", "started_at", "ended_at", "match_ids", "opportunities", "coverage_status", "coverage_refs", "coverage_policy"}:
        raise ValueError("invalid training period fields")
    if not isinstance(row["scope"], dict) or not isinstance(row["opportunities"], list):
        raise ValueError("typed scope/opportunity arrays required")
    row["scope"] = load_training_scope(json.dumps(row["scope"], allow_nan=False))
    for name in ("match_ids", "coverage_refs"):
        _tuple_field(row, name)
    if row.get('coverage_status')=='verified_complete':
        row['coverage_status']='partial'
    opportunities = []
    for raw in row["opportunities"]:
        if not isinstance(raw, dict) or set(raw) - {"opportunity_id", "match_id", "assignment_id", "eligibility", "behavior_completed", "evidence_kind", "evidence_refs", "game_time_ms", "reason_codes", "note"}:
            raise ValueError("unknown behavior opportunity fields")
        opportunity = dict(raw)
        _tuple_field(opportunity, "evidence_refs")
        _tuple_field(opportunity, "reason_codes", default=True)
        if opportunity.get('evidence_kind')=='independent_observation':
            opportunity['evidence_kind']='unknown'
            opportunity['behavior_completed']=None
            opportunity['reason_codes']+=('independent_observation_receipt_not_resolved',)
        opportunities.append(BehaviorOpportunity(**opportunity))
    row["opportunities"] = tuple(opportunities)
    return TrainingPeriod(**row)


def write_training_report(assignment: TrainingAssignment, out_dir: str | Path, *,
                          baseline: TrainingPeriod | None = None, followup: TrainingPeriod | None = None,
                          selection: PersonalizedStudySelection | None = None) -> dict:
    """Produce a reviewable offline cycle; users supply real journals separately."""
    if not isinstance(assignment, TrainingAssignment):
        raise ValueError("typed assignment required")
    if followup is not None and baseline is None:
        raise ValueError("followup requires baseline")
    for period in (baseline, followup):
        if period is not None and (period.assignment_id != assignment.assignment_id or period.scope != assignment.scope):
            raise ValueError("journal belongs to a different assignment/scope")
    if selection is not None and selection.goal_id != assignment.goal.goal_id:
        raise ValueError("study selection belongs to another goal")
    progress = compare_training_periods(baseline, followup) if baseline is not None and followup is not None else None
    payload = {"schema_version": "foresight.training-cycle.v1", "assignment": asdict(assignment),
               "baseline": asdict(baseline) if baseline else None, "followup": asdict(followup) if followup else None,
               "baseline_measurement": asdict(summarize_period(baseline)) if baseline else None,
               "followup_measurement": asdict(summarize_period(followup)) if followup else None,
               "progress": asdict(progress) if progress else None, "study_selection": asdict(selection) if selection else None,
               "quality_validation": "not_established", "automatic_error_diagnosis": False}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "training.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    status_label='Упражнение выбрано по вашей цели' if assignment.status=='assigned_self_directed' else 'Цель ещё не подтверждена'
    sections = [f"<h1>Персональная проверка выбранного поведения</h1><p>Цель: {html.escape(assignment.goal.statement)}</p>",
                f"<p>{status_label}. Это проверка процесса; ошибка игрока не установлена.</p>"]
    if assignment.exercise:
        sections.append(f"<h2>Упражнение</h2><p>{html.escape(assignment.exercise)}</p><p>Подходящая ситуация: {html.escape(assignment.eligibility_rule)}</p><p>Измерение: {html.escape(assignment.measured_behavior)}</p>")
    sections.append("<ul>" + "".join(f"<li>{html.escape(g)}</li>" for g in assignment.guardrails) + "</ul>")
    for label, period in (("Базовый период", baseline), ("Следующая проверка", followup)):
        if period is None:
            sections.append(f"<h2>{label}</h2><p>Журнал не предоставлен; выполнение упражнения не измерено.</p>")
            continue
        m = summarize_period(period)
        rate = f"{m.completion_rate_among_observed:.1%}" if m.completion_rate_among_observed is not None else "неизвестно"
        coverage={'user_journal_complete':'Полнота журнала подтверждена вами','verified_complete':'Полный учёт по отдельно проверенному источнику','partial':'Частичный учёт','unknown':'Полнота неизвестна'}.get(m.population_status,'Полнота неизвестна')
        source='собственные отметки' if m.evidence_kinds==('user_journal',) else 'неполный или отдельно проверяемый источник'
        sections.append(f"<h2>{label}</h2><p>Матчей: {m.considered_matches}; подходящих ситуаций: {m.eligible}, исключённых: {m.ineligible}, условия не установлены: {m.eligibility_unknown}. Известно выполнение: {m.behavior_observed}, неизвестно: {m.behavior_unknown}. Выполнено: {m.behavior_completed}/{m.behavior_observed}; доля среди наблюдённых: {rate}.</p><p>{coverage}; источник: {source}.</p>")
        observations=[]
        for opportunity in period.opportunities:
            eligibility={'eligible':'подходит для упражнения','ineligible':'исключено из упражнения','unknown':'условия неизвестны'}[opportunity.eligibility]
            behavior='выполнено по записи' if opportunity.behavior_completed is True else 'не выполнено по записи' if opportunity.behavior_completed is False else 'выполнение неизвестно'
            time=f'{opportunity.game_time_ms/1000:g} секунд' if opportunity.game_time_ms is not None else 'время не указано'
            note=html.escape(opportunity.note or 'без заметки')
            observations.append(f'<li>Матч {opportunity.match_id}, {time}: {eligibility}; {behavior}. {note}</li>')
        sections.append('<details><summary>Примеры, невыполненные и неизвестные случаи</summary><ul>'+''.join(observations)+'</ul></details>')
    if progress:
        delta = f"{progress.completion_rate_delta:+.1%}" if progress.completion_rate_delta is not None else "сравнение недоступно"
        label={'comparable_self_report':'Сопоставимое сравнение собственных отметок','comparable_independent_observation':'Сопоставимое сравнение отдельного наблюдения','rebaseline_required':'Нужен новый базовый период','insufficient_evidence':'Недостаточно данных для сравнения'}.get(progress.status,'Сравнение ограничено')
        sections.append(f"<h2>Сравнение</h2><p>{label}: {delta}.</p><p>{html.escape(progress.conclusion)}</p><details><summary>Основания проверки сопоставимости</summary><ul>" + "".join(f"<li>{html.escape(r)}</li>" for r in progress.reason_codes) + "</ul></details>")
    if selection:
        sections.append("<h2>Примеры для выбранной задачи</h2>")
        for example in selection.matches:
            distance = f"{example.descriptive_feature_distance:.3f}" if example.descriptive_feature_distance is not None else "не вычислена"
            sections.append(f"<article><h3><a href='https://www.opendota.com/matches/{example.match_id}'>Матч {example.match_id}</a></h3><p>{html.escape(example.viewing_task)}</p><p>Описательная дистанция: {distance}; общих измерений: {example.shared_feature_count}/{example.requested_feature_count}. Это не доказательство сходства стиля или правильности решений.</p><details><summary>Различия и отсутствующие измерения</summary><ul>" + "".join(f"<li>{html.escape(d)}</li>" for d in example.differences) + "</ul></details></article>")
    sections.append("<p><a href='training.json'>Полные данные, знаменатели и источники</a></p>")
    (out / "index.html").write_text("<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><link rel='icon' href='data:,'><title>Foresight — проверка поведения</title><style>body{font:16px/1.55 system-ui;max-width:900px;margin:30px auto;padding:0 20px;color:#e4edf4;background:#12202a}a{color:#7dccff}article,details{padding:12px;border:1px solid #426070;border-radius:8px;margin:12px 0}</style></head><body><main>" + "".join(sections) + "</main></body></html>", encoding="utf-8")
    return payload
