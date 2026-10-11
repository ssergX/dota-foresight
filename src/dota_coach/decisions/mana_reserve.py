"""Compute a declared mana constraint, never a counterfactual fight outcome.

Unlike the older interval comparator this criterion derives its quantities
from own resources and costs. A confirmed goal is a user policy, not a claim
that the player had that intention in a past replay. Domain admission remains
separate from arithmetic, so unverified replay fields cannot issue a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from dota_coach.decisions.contracts import ActionObservation, DecisionBoundary
from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, content_hash

PREDICATES = ("self.mana", "self.selected_mana_cost", "self.reserve_mana_cost",
              "self.activation_feasible", "self.hold_feasible")
VERSION = "declared-mana-reserve.v1"


@dataclass(frozen=True)
class ReserveGoal:
    goal_id: str
    subject_ref: str
    reserve_action: str
    repetitions: int
    margin_mana: float
    origin: str
    declared_at: TimeRef
    source: SourceRef

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() for x in
                   (self.goal_id, self.subject_ref, self.reserve_action)):
            raise ValueError("explicit goal, subject and reserved action required")
        if type(self.repetitions) is not int or not 1 <= self.repetitions <= 20:
            raise ValueError("bounded positive action repetition count required")
        if type(self.margin_mana) not in (int, float) or not math.isfinite(self.margin_mana) or self.margin_mana < 0:
            raise ValueError("nonnegative finite user reserve margin required")
        if self.origin not in ("user_confirmed", "research_hypothesis"):
            raise ValueError("goal cannot be inferred from outcomes")
        if not isinstance(self.declared_at, TimeRef) or not isinstance(self.source, SourceRef):
            raise TypeError("goal declaration requires time and source")


@dataclass(frozen=True)
class ManaReserveInput:
    decision_id: str
    match_id: int
    subject_ref: str
    patch: str
    boundary: DecisionBoundary
    action: ActionObservation
    goal: ReserveGoal
    facts: tuple[Fact, ...]
    dataset_kind: str = "unknown"

    def __post_init__(self):
        if not self.decision_id or type(self.match_id) is not int or self.match_id <= 0:
            raise ValueError("decision and match identity required")
        if not self.subject_ref or not self.patch or self.goal.subject_ref != self.subject_ref:
            raise ValueError("goal must bind to this subject and patch")
        if self.dataset_kind not in ("replay", "synthetic", "unknown"):
            raise ValueError("invalid dataset kind")
        expected=(PREDICATES[0],PREDICATES[1]+':'+self.action.action_id,
                  PREDICATES[2]+':'+self.goal.reserve_action,*PREDICATES[3:])
        if not isinstance(self.facts, tuple) or tuple(f.predicate for f in self.facts) != expected:
            raise ValueError("own mana/feasibility allowlist required")
        if len({f.fact_id for f in self.facts}) != len(self.facts):
            raise ValueError("duplicate fact identity")
        anchor = self.boundary.anchor
        for index, fact in enumerate(self.facts):
            if fact.subject_ref != self.subject_ref or fact.observer_ref != self.subject_ref or fact.perspective != "screen":
                raise ValueError("world, foreign, or merely team knowledge forbidden")
            if fact.status in ("unknown", "conflict"):
                continue
            if index < 3 and (type(fact.value) not in (int, float) or not math.isfinite(fact.value) or fact.value < 0):
                raise ValueError("mana and costs must be finite nonnegative numbers")
            if index >= 3 and type(fact.value) is not bool:
                raise ValueError("feasibility requires a boolean or unknown")
            if anchor is not None and (fact.available_at is None or not fact.available_at.definitely_available_before(anchor)
                    or not fact.valid_at.definitely_available_before(anchor)):
                raise ValueError("future or temporally ambiguous evidence forbidden")

    @property
    def input_hash(self):
        return content_hash(self)


@dataclass(frozen=True)
class ManaReserveReview:
    decision_id: str
    input_hash: str
    verdict: str
    reason_codes: tuple[str, ...]
    required_mana: float | None
    mana_after_activate: float | None
    mana_after_hold: float | None
    activate_meets_goal: bool | None
    hold_meets_goal: bool | None
    evidence_ids: tuple[str, ...]
    explanation: str
    criterion_id: str = VERSION
    validation_status: str = "unverified"
    training_eligible: bool = False
    strategic_quality: str = "not_established"

    @property
    def assessment_hash(self):
        return content_hash(self)


def evaluate_mana_reserve(value: ManaReserveInput, *, admitted_patch: str | None = None,
                          verified_fact_ids: frozenset[str] = frozenset(),
                          reviewed_boundary: bool = False, reviewed_goal: bool = False,
                          reviewed_action_bindings: bool = False,
                          freshness_ms: int = 100) -> ManaReserveReview:
    """Admitted facts must be resolved by the independent caller's review registry.

    No DTO status, parser metadata or goal declaration grants that admission.
    This returns a conditional research assessment even when inputs are admitted;
    it never promotes a criterion or turns a violation into an overall mistake.
    No restoration, future regeneration or future fight enters this calculation.
    """
    if type(freshness_ms) is not int or freshness_ms < 0 or not isinstance(verified_fact_ids, frozenset):
        raise ValueError("explicit freshness and immutable admission set required")
    gaps=[]
    if not reviewed_boundary:
        gaps.append('choice_boundary_not_independently_reviewed')
    if not reviewed_goal:
        gaps.append('goal_declaration_not_independently_reviewed')
    if not reviewed_action_bindings:
        gaps.append('cost_action_links_not_independently_reviewed')
    anchor=value.boundary.anchor
    if value.boundary.status != "resolved" or anchor is None:
        gaps.append("choice_boundary_unresolved")
    elif anchor.order_status != "verified" or anchor.uncertainty_ms != 0 or anchor.replay_tick is None or anchor.sequence_in_tick is None or anchor.clock_mapping_version in ('legacy/unverified','unknown'):
        gaps.append("choice_clock_not_verified")
    if admitted_patch is None or value.patch != admitted_patch:
        gaps.append("historical_costs_not_admitted")
    if value.goal.origin != "user_confirmed":
        gaps.append("goal_is_hypothesis")
    if anchor is None or not value.goal.declared_at.definitely_available_before(anchor):
        gaps.append("goal_not_declared_before_choice")
    if value.goal.declared_at.order_status!='verified' or value.goal.declared_at.uncertainty_ms!=0:
        gaps.append('goal_clock_not_verified')
    if value.action.kind not in ("activation_commit", "observed_no_activation") or not value.action.event_refs:
        gaps.append("chosen_action_unresolved")
    if value.action.kind == "observed_no_activation" and value.action.log_completeness != "complete":
        gaps.append("absence_not_established")
    for fact in value.facts:
        if fact.status not in ("observed", "derived") or fact.quality_flags or fact.fact_id not in verified_fact_ids or fact.method_version in ('legacy/unverified','unknown') or fact.available_at is None or fact.available_at.order_status!='verified':
            gaps.append("fact_not_admitted:"+fact.predicate)
        if anchor is not None:
            t=fact.valid_at
            if t.game_time_ms is None or anchor.game_time_ms is None or t.uncertainty_ms is None or t.order_status != "verified" or (
                    anchor.game_time_ms-t.game_time_ms+t.uncertainty_ms > freshness_ms):
                gaps.append("fact_not_fresh:"+fact.predicate)
    def result(verdict, reasons, numbers=(None,None,None,None,None), text="Расчёт недоступен: нет проверенного состояния и заявленной до выбора цели."):
        return ManaReserveReview(value.decision_id,value.input_hash,verdict,tuple(dict.fromkeys(reasons)),
            *numbers,tuple(f.fact_id for f in value.facts),text)
    if gaps:
        return result("insufficient_evidence",gaps)
    mana,cost,reserve_cost,activate,hold=(f.value for f in value.facts)
    if not activate or cost > mana:
        return result("insufficient_evidence" if value.action.kind == "activation_commit" else "not_actionable",
                      ("activation_evidence_conflict" if value.action.kind == "activation_commit" else "activation_infeasible",))
    if not hold:
        return result("insufficient_evidence",("hold_feasibility_unresolved",))
    required=reserve_cost*value.goal.repetitions+value.goal.margin_mana
    if not math.isfinite(required):
        return result('insufficient_evidence',('resource_arithmetic_out_of_range',))
    after=mana-cost
    am,hm=after>=required,mana>=required
    numbers=(required,after,mana,am,hm)
    explanation=(f"Заявленный запас для {value.goal.reserve_action}: {reserve_cost:g} × {value.goal.repetitions} + "
                 f"{value.goal.margin_mana:g} = {required:g} маны. После активации останется {after:g}; "
                 f"при удержании — {mana:g}. Это немедленный баланс ресурса, без будущего восстановления. "
                 "Польза самой защиты и необходимость пересмотреть цель требуют отдельного разбора.")
    if not hm:
        return result("insufficient_evidence",("declared_reserve_already_unattainable",),numbers,explanation)
    if am:
        return result("reasonable_options",("both_actions_preserve_declared_mana",),numbers,explanation)
    if value.action.kind == "activation_commit":
        return result("probable_error",("violates_declared_mana_constraint_only",),numbers,explanation)
    return result("good",("holds_declared_mana_constraint_only",),numbers,explanation)


def read_mana_reserve(text: str) -> ManaReserveInput:
    from dota_coach.decisions.batch import strict_json, _keys, read_fact, read_time
    d=strict_json(text)
    _keys(d,("schema_version","decision_id","match_id","subject_ref","patch","boundary","action","goal","facts","dataset_kind"))
    if d.pop("schema_version") != "foresight.mana-reserve-input.v1":
        raise ValueError("unsupported mana reserve input")
    b,a,g=d.pop("boundary"),d.pop("action"),d.pop("goal")
    _keys(b,("boundary_id","anchor","status","method","resolution_evidence_ids"))
    _keys(a,("kind","action_id","log_completeness","event_refs"))
    _keys(g,("goal_id","subject_ref","reserve_action","repetitions","margin_mana","origin","declared_at","source"))
    for obj,key in ((b,"resolution_evidence_ids"),(a,"event_refs")):
        if not isinstance(obj[key],list) or any(not isinstance(x,str) or not x for x in obj[key]):
            raise ValueError("source reference array required")
        obj[key]=tuple(obj[key])
    b["anchor"]=read_time(b["anchor"]) if b["anchor"] is not None else None
    g["declared_at"]=read_time(g["declared_at"])
    g["source"]=SourceRef(**g["source"])
    if not isinstance(d["facts"],list):
        raise ValueError("fact array required")
    d["facts"]=tuple(read_fact(f) for f in d["facts"])
    return ManaReserveInput(**d,boundary=DecisionBoundary(**b),action=ActionObservation(**a),goal=ReserveGoal(**g))


def resolve_reviewed_facts(value: ManaReserveInput, records, annotations) -> dict:
    """Resolve references, not a self-declared `validated` flag in input JSON.

    Two distinct human extraction reviewers must confirm both correctness and
    availability of each cited fact in this exact hashed input. Their identity,
    independence and client access still require external provenance review.
    This admission is for research arithmetic only and grants no live release.
    """
    from dota_coach.validation.pipeline import validate_annotations
    validate_annotations(annotations,records)
    record=next((r for r in records if r.decision_id==value.decision_id),None)
    if record is None or record.input_hash != value.input_hash or record.patch != value.patch or (
            record.match_id != value.match_id or record.target_player != value.subject_ref or record.dataset_kind != value.dataset_kind):
        raise ValueError("review manifest must bind this input, subject, match and patch")
    latest={}
    for annotation in annotations:
        if annotation.decision_id!=value.decision_id or annotation.annotator_kind!="human_expert" or annotation.review_pass!="extraction" or annotation.dataset_kind!="replay":
            continue
        previous=latest.get(annotation.annotator_id)
        if previous is None or annotation.annotation_version>previous.annotation_version:
            latest[annotation.annotator_id]=annotation
    admitted=[]
    refs=[]
    for fact in value.facts:
        votes=[(a,next((f for f in a.facts_checked if f.fact_id==fact.fact_id),None)) for a in latest.values()]
        votes=[(a,c) for a,c in votes if c is not None]
        if len(votes)>=2 and all(a.adjudication_status!="disputed" and c.correctness=="correct" and c.availability=="available" for a,c in votes):
            admitted.append(fact.fact_id)
            refs.extend(a.annotation_hash for a,c in votes)
    decisions={}
    for a in annotations:
        if a.decision_id!=value.decision_id or a.annotator_kind!='human_expert' or a.review_pass!='decision_blinded' or a.dataset_kind!='replay':
            continue
        old=decisions.get(a.annotator_id)
        if old is None or a.annotation_version>old.annotation_version:
            decisions[a.annotator_id]=a
    def context_checked(a):
        return a.adjudication_status!='disputed' and a.eligibility=='eligible' and not set(a.acceptable_verdicts)&{'insufficient_evidence','not_actionable'}
    def checked(a,ident):
        return any(f.fact_id==ident and f.correctness=='correct' and f.availability=='available' for f in a.facts_checked)
    group=list(decisions.values())
    boundary= len(group)>=2 and all(context_checked(a) and checked(a,'boundary:'+value.boundary.boundary_id) and
        set(value.boundary.resolution_evidence_ids)<=set(a.decisive_evidence_ids) for a in group)
    goal= len(group)>=2 and all(context_checked(a) and checked(a,'goal:'+value.goal.goal_id) for a in group)
    def linked(a,action_id,cost_id):
        return any(c.action_id==action_id and c.feasibility=='feasible' and cost_id in c.evidence_ids for c in a.available_actions)
    links= len(group)>=2 and all(context_checked(a) and linked(a,value.action.action_id,value.facts[1].fact_id) and
        linked(a,value.goal.reserve_action,value.facts[2].fact_id) for a in group)
    if boundary or goal or links:
        refs.extend(a.annotation_hash for a in group)
    costs={value.facts[1].fact_id,value.facts[2].fact_id}
    return {"verified_fact_ids":frozenset(admitted),"admitted_patch":value.patch if costs<=set(admitted) else None,
            'reviewed_boundary':boundary,'reviewed_goal':goal,'reviewed_action_bindings':links,
            "annotation_hashes":tuple(sorted(set(refs))),"status":"reviewed_declarations_not_release_admission"}
