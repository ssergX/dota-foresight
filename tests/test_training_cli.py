from dataclasses import asdict, replace
import json

import pytest

from dota_coach.cli import main
from dota_coach.learning.training import (TrainingGoal, TrainingScope, assign_exercise,
    BehaviorOpportunity, TrainingPeriod)


def inputs(tmp_path, *, origin="user_confirmed"):
    goal = TrainingGoal("user-goal", "fight_entry", "Я хочу сравнивать варианты перед подключением.", origin,
                        ("test-human-confirmation",), "2026-10-06T10:00:00Z")
    scope = TrainingScope("account:111", 145, "position_1", "estimated", "opendota_patch_id:60", "rank_tier:80")
    assignment = assign_exercise(goal, scope)
    g, s = tmp_path / "goal.json", tmp_path / "scope.json"
    g.write_text(json.dumps(asdict(goal)), encoding="utf-8")
    s.write_text(json.dumps(asdict(scope)), encoding="utf-8")
    return goal, scope, assignment, g, s


def journal(tmp_path, assignment, scope, *, index=1, behaviors=(True, False)):
    p = TrainingPeriod(f"period:{index}", assignment.assignment_id, scope,
                       f"2026-10-{5+index:02}T10:00:00Z", f"2026-10-{5+index:02}T12:00:00Z", (1000 + index,),
                       tuple(BehaviorOpportunity(f"op:{index}:{i}", 1000 + index, assignment.assignment_id,
                             "eligible", value, "user_journal", (f"test-user-note:{index}:{i}",))
                             for i, value in enumerate(behaviors)),
                       "user_journal_complete", ("test-census-note",), "user-choice-trigger.v1")
    path = tmp_path / f"period{index}.json"
    path.write_text(json.dumps(asdict(p)), encoding="utf-8")
    return path, p


def run(g, s, out, *extra):
    return main(["training", "--goal-json", str(g), "--scope-json", str(s), "--out", str(out), *extra])


def test_cli_confirmed_exercise_with_no_journal_does_not_forge_history(tmp_path):
    _, _, _, g, s = inputs(tmp_path)
    out = tmp_path / "result"
    assert run(g, s, out) == 0
    payload = json.loads((out / "training.json").read_text(encoding="utf-8"))
    assert payload["assignment"]["status"] == "assigned_self_directed"
    assert payload["baseline"] is None and payload["followup"] is None and payload["progress"] is None
    assert payload["automatic_error_diagnosis"] is False
    assert payload["quality_validation"] == "not_established"


def test_cli_unconfirmed_goal_and_missing_journal_are_explicitly_unavailable(tmp_path):
    _, _, _, g, s = inputs(tmp_path, origin="unconfirmed")
    out = tmp_path / "result"
    assert run(g, s, out) == 0
    payload = json.loads((out / "training.json").read_text(encoding="utf-8"))
    assert payload["assignment"]["exercise"] is None
    assert payload["baseline_measurement"] is None


def test_imported_reviewed_issue_cannot_self_promote_with_arbitrary_refs(tmp_path):
    _,_,_,g,s=inputs(tmp_path)
    data=json.loads(g.read_text(encoding='utf-8'))
    data.update(origin='reviewed_issue',issue_id='self-declared',independent_review_refs=['unresolved-ref'])
    g.write_text(json.dumps(data),encoding='utf-8')
    out=tmp_path/'result'
    assert run(g,s,out)==0
    payload=json.loads((out/'training.json').read_text(encoding='utf-8'))
    assert payload['assignment']['goal']['origin']=='unconfirmed'
    assert payload['assignment']['exercise'] is None


def test_imported_independent_observation_and_verified_census_are_demoted(tmp_path):
    from dota_coach.learning.training import load_training_period
    _,scope,assignment,_,_=inputs(tmp_path)
    _,p=journal(tmp_path,assignment,scope)
    raw=asdict(p);raw['coverage_status']='verified_complete'
    raw['opportunities'][0]['evidence_kind']='independent_observation'
    loaded=load_training_period(json.dumps(raw))
    assert loaded.coverage_status=='partial'
    assert loaded.opportunities[0].behavior_completed is None
    assert loaded.opportunities[0].evidence_kind=='unknown'


def test_cli_knownzero_unknown_denominators_and_empty_followup_do_not_resolve(tmp_path):
    _, scope, assignment, g, s = inputs(tmp_path)
    baseline, _ = journal(tmp_path, assignment, scope, behaviors=(False, None))
    followup, _ = journal(tmp_path, assignment, scope, index=2, behaviors=())
    out = tmp_path / "result"
    assert run(g, s, out, "--baseline-json", str(baseline), "--followup-json", str(followup)) == 0
    payload = json.loads((out / "training.json").read_text(encoding="utf-8"))
    measurement = payload["baseline_measurement"]
    assert measurement["eligible"] == 2 and measurement["behavior_observed"] == 1
    assert measurement["behavior_completed"] == 0 and measurement["behavior_unknown"] == 1
    assert measurement["completion_rate_among_observed"] == 0
    assert payload["progress"]["status"] == "insufficient_evidence"
    assert payload["progress"]["completion_rate_delta"] is None


def test_cli_full_comparable_periods_are_labeled_selfreport(tmp_path):
    _, scope, assignment, g, s = inputs(tmp_path)
    baseline, _ = journal(tmp_path, assignment, scope)
    followup, _ = journal(tmp_path, assignment, scope, index=2, behaviors=(True, True))
    out = tmp_path / "result"
    assert run(g, s, out, "--baseline-json", str(baseline), "--followup-json", str(followup)) == 0
    payload = json.loads((out / "training.json").read_text(encoding="utf-8"))
    assert payload["progress"]["status"] == "comparable_self_report"
    assert payload["progress"]["completion_rate_delta"] == .5
    assert "не устанавливает исправление" in payload["progress"]["conclusion"]


def test_cli_scope_assignment_mismatch_cannot_import_foreign_history(tmp_path):
    _, scope, assignment, g, s = inputs(tmp_path)
    baseline, p = journal(tmp_path, assignment, scope)
    baseline.write_text(json.dumps(asdict(replace(p, scope=replace(scope, hero_id=112)))), encoding="utf-8")
    out = tmp_path / "result"
    assert run(g, s, out, "--baseline-json", str(baseline)) == 1
    assert not out.exists()


def test_cli_followup_without_baseline_is_not_created(tmp_path):
    _, scope, assignment, g, s = inputs(tmp_path)
    followup, _ = journal(tmp_path, assignment, scope, index=2)
    out = tmp_path / "result"
    assert run(g, s, out, "--followup-json", str(followup)) == 1
    assert not out.exists()


@pytest.mark.parametrize("name", ["training.json", "index.html"])
def test_cli_output_guard_preserves_input_even_when_input_is_generated_filename(tmp_path, name):
    _, _, _, g, s = inputs(tmp_path)
    target = tmp_path / name
    target.write_bytes(g.read_bytes())
    before = target.read_bytes()
    assert run(target, s, tmp_path) == 1
    assert target.read_bytes() == before


def test_cli_partial_study_arguments_do_not_forge_a_candidate(tmp_path):
    _, _, _, g, s = inputs(tmp_path)
    out = tmp_path / "result"
    assert run(g, s, out, "--account-id", "111") == 1
    assert not out.exists()


def test_cli_source_account_hero_patch_binding_precedes_study_load(tmp_path):
    _, _, _, g, s = inputs(tmp_path)
    match = tmp_path / "match.json"
    study = tmp_path / "study.json"
    match.write_text(json.dumps({"match_id": 1, "patch": 59, "players": [{"account_id": 111, "hero_id": 145}]}), encoding="utf-8")
    study.write_text("{}", encoding="utf-8")
    out = tmp_path / "result"
    assert run(g, s, out, "--account-id", "111", "--match-json", str(match), "--study-json", str(study)) == 1
    assert not out.exists()
