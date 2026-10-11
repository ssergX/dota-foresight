from dataclasses import asdict,replace
import json

import pytest

from dota_coach.decisions.contracts import ActionObservation,DecisionBoundary
from dota_coach.decisions.mana_reserve import (ManaReserveInput,ReserveGoal,PREDICATES,
    evaluate_mana_reserve,read_mana_reserve,resolve_reviewed_facts)
from dota_coach.evidence.contracts import Fact,SourceRef,TimeRef
from dota_coach.validation.contracts import Annotation,DatasetRecord,FactCheck


def input_value(mana=300,cost=100,reserve_cost=110,kind="activation_commit"):
    t=TimeRef(1000,30,1,0,"fixture.clock.v1","verified")
    s=SourceRef("fixture","a"*64,"synthetic","v1","own-before-choice")
    predicates=(PREDICATES[0],PREDICATES[1]+':selected',PREDICATES[2]+':named own action',*PREDICATES[3:])
    fs=tuple(Fact(str(i),"account:7",p,v,"observed",t,t,"screen",(s,),observer_ref="account:7",method_version="fixture.v1")
        for i,(p,v) in enumerate(zip(predicates,(mana,cost,reserve_cost,True,True))))
    goal=ReserveGoal("goal","account:7","named own action",2,0,"user_confirmed",t,s)
    return ManaReserveInput("d",1,"account:7","fixture-patch",DecisionBoundary("b",t,"resolved","fixture",("b",)),
        ActionObservation(kind,"selected", "complete",("cast",)),goal,fs,"synthetic")


def evaluate(v):
    return evaluate_mana_reserve(v,admitted_patch=v.patch,verified_fact_ids=frozenset(f.fact_id for f in v.facts),
        reviewed_boundary=True,reviewed_goal=True,reviewed_action_bindings=True)


def test_derived_budget_not_caller_utility_bounds():
    v=input_value()
    r=evaluate(v)
    assert r.required_mana==220 and r.mana_after_activate==200 and r.mana_after_hold==300
    assert r.verdict=="probable_error" and r.reason_codes==("violates_declared_mana_constraint_only",)
    assert not r.training_eligible and r.strategic_quality=="not_established"
    assert evaluate(replace(v,action=replace(v.action,kind="observed_no_activation"))).verdict=="good"


def test_equal_budget_and_zero_cost_preserve_both_options():
    for cost in (0,80):
        r=evaluate(input_value(cost=cost))
        assert r.verdict=="reasonable_options" and r.activate_meets_goal


def test_already_insufficient_reserve_is_not_choice_error():
    r=evaluate(input_value(mana=200,cost=10))
    assert r.verdict=="insufficient_evidence" and r.reason_codes==("declared_reserve_already_unattainable",)


def test_no_self_admission_no_goal_reading_and_no_fake_clock():
    v=input_value()
    assert evaluate_mana_reserve(v).verdict=="insufficient_evidence"
    assert evaluate(replace(v,goal=replace(v.goal,origin="research_hypothesis"))).verdict=="insufficient_evidence"
    assert evaluate(replace(v,boundary=DecisionBoundary("b",None))).verdict=="insufficient_evidence"
    assert evaluate(replace(v,goal=replace(v.goal,declared_at=replace(v.goal.declared_at,game_time_ms=2000)))).verdict=="insufficient_evidence"


@pytest.mark.parametrize("index",range(5))
def test_each_missing_requirement_abstains(index):
    v=input_value();fs=list(v.facts)
    fs[index]=replace(fs[index],value=None,status="unknown",unknown_reason="missing",source_refs=())
    assert evaluate(replace(v,facts=tuple(fs))).verdict=="insufficient_evidence"


def test_unverified_stale_and_world_never_promoted():
    v=input_value()
    fs=(replace(v.facts[0],quality_flags=("extraction_unverified",)),)+v.facts[1:]
    assert evaluate(replace(v,facts=fs)).verdict=="insufficient_evidence"
    fs=(replace(v.facts[0],valid_at=replace(v.facts[0].valid_at,game_time_ms=100)),)+v.facts[1:]
    assert evaluate(replace(v,facts=fs)).verdict=="insufficient_evidence"
    for perspective in ("world","team"):
        with pytest.raises(ValueError):
            replace(v,facts=(replace(v.facts[0],perspective=perspective),)+v.facts[1:])
    with pytest.raises(ValueError):
        replace(v,facts=(replace(v.facts[0],available_at=replace(v.facts[0].available_at,sequence_in_tick=2)),)+v.facts[1:])


def test_infeasible_activation_excluded_and_conflicting_cast_abstains():
    v=input_value(mana=40,cost=50)
    assert evaluate(v).verdict=="insufficient_evidence"
    assert evaluate(replace(v,action=replace(v.action,kind="observed_no_activation"))).verdict=="not_actionable"


def test_strict_import_rejects_outcome_and_unknown_fields():
    v=input_value();raw=asdict(v)|{"schema_version":"foresight.mana-reserve-input.v1"}
    assert read_mana_reserve(json.dumps(raw))==v
    for key in ("radiant_win","future_hp","enemy_positions","verified_fact_ids"):
        with pytest.raises(ValueError):
            read_mana_reserve(json.dumps(raw|{key:True}))


def annotation_fixture():
    v=replace(input_value(),dataset_kind="replay")
    record=DatasetRecord(v.decision_id,v.input_hash,1,"a"*64,v.subject_ref,v.patch,"development")
    def label(who,kind="human_expert",correct="correct"):
        return Annotation(v.decision_id,v.input_hash,"a"*64,v.patch,who,("insufficient_evidence",),"unknown","extraction only",
            facts_checked=tuple(FactCheck(f.fact_id,correct,"available","checked against client") for f in v.facts),
            unknowns=("decision not labelled",),review_pass="extraction",annotator_kind=kind)
    return v,record,label


def test_real_review_references_resolved_not_status_flag():
    v,record,label=annotation_fixture()
    assert not resolve_reviewed_facts(v,[record],[label("one")])["verified_fact_ids"]
    assert not resolve_reviewed_facts(v,[record],[label("one"),label("model","system")])["verified_fact_ids"]
    admission=resolve_reviewed_facts(v,[record],[label("one"),label("two")])
    assert len(admission["verified_fact_ids"])==5 and admission["admitted_patch"]==v.patch
    assert not resolve_reviewed_facts(v,[record],[label("one"),label("two",correct="incorrect")])["verified_fact_ids"]
    with pytest.raises(ValueError):
        resolve_reviewed_facts(replace(v,subject_ref="other",goal=replace(v.goal,subject_ref="other"),
            facts=tuple(replace(f,subject_ref="other",observer_ref="other") for f in v.facts)),[record],[])


def test_latest_negative_review_retracts_admission():
    v,record,label=annotation_fixture();one=label("one")
    revised=replace(one,annotation_version=2,previous_annotation_hash=one.annotation_hash,revision_reason="field mismatch",
        facts_checked=(FactCheck("0","incorrect","available","rechecked"),))
    admission=resolve_reviewed_facts(v,[record],[one,revised,label("two")])
    assert "0" not in admission["verified_fact_ids"]


def test_fact_review_alone_cannot_admit_choice_or_goal():
    v,record,label=annotation_fixture()
    admission=resolve_reviewed_facts(v,[record],[label('one'),label('two')])
    assert not admission['reviewed_boundary'] and not admission['reviewed_goal'] and not admission['reviewed_action_bindings']
    result=evaluate_mana_reserve(v,admitted_patch=admission['admitted_patch'],verified_fact_ids=admission['verified_fact_ids'])
    assert result.verdict=='insufficient_evidence'


def test_action_cost_binding_legacy_clock_and_overflow_are_closed():
    v=input_value()
    with pytest.raises(ValueError,match='allowlist'):
        replace(v,action=replace(v.action,action_id='unrelated'))
    with pytest.raises(ValueError,match='allowlist'):
        replace(v,goal=replace(v.goal,reserve_action='unrelated'))
    clock=replace(v.boundary.anchor,clock_mapping_version='legacy/unverified')
    legacy=replace(v,boundary=replace(v.boundary,anchor=clock),goal=replace(v.goal,declared_at=clock),
        facts=tuple(replace(f,valid_at=clock,available_at=clock) for f in v.facts))
    assert evaluate(legacy).verdict=='insufficient_evidence'
    huge=input_value(mana=1e308,cost=0,reserve_cost=1e308)
    result=evaluate(huge)
    assert result.verdict=='insufficient_evidence' and result.required_mana is None
    json.dumps(asdict(result),allow_nan=False)
