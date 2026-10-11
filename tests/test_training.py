"""Behavior measurements and task matching, not expert decision validation."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json

import pytest

from dota_coach.ingest.study_sources import BASE, OpenDotaStudySource
from dota_coach.learning.training import (TrainingGoal, TrainingScope, BehaviorOpportunity,
    TrainingPeriod, assign_exercise, summarize_period, compare_training_periods, match_study_to_goal,
    load_training_goal, load_training_scope, load_training_period, write_training_report)


def goal(code="fight_entry", origin="user_confirmed"):
    return TrainingGoal("test-goal", code, "Хочу сравнивать варианты перед подключением.", origin,
                        ("test-user-message",), "2026-10-06T10:00:00Z")


def scope():
    return TrainingScope("account:111", 145, "position_1", "estimated", "opendota_patch_id:60", "rank_tier:80")


def period(index=1, behaviors=(True, False, None), coverage="user_journal_complete"):
    assignment = assign_exercise(goal(), scope())
    return TrainingPeriod(f"period:{index}", assignment.assignment_id, scope(),
                          f"2026-10-{5+index:02}T10:00:00Z", f"2026-10-{5+index:02}T12:00:00Z",
                          (1000 + index,), tuple(BehaviorOpportunity(f"op:{index}:{i}", 1000 + index,
                           assignment.assignment_id, "eligible", v, "user_journal", (f"test-journal:{index}:{i}",))
                           for i, v in enumerate(behaviors)), coverage, ("test-period-log",), "journal.v1")


def test_confirmed_goal_assigns_specific_process_exercise_without_diagnosis():
    assignment = assign_exercise(goal(), scope())
    assert assignment.status == "assigned_self_directed" and "две" in assignment.exercise
    assert assignment.diagnostic_status == "no_gameplay_error_inferred"
    assert assignment.measured_behavior and assignment.eligibility_rule and assignment.guardrails


def test_unconfirmed_goal_cannot_get_personal_prescription():
    assignment = assign_exercise(goal(origin="unconfirmed"), scope())
    assert assignment.status == "unavailable" and assignment.exercise is None
    with pytest.raises(ValueError):
        replace(goal(), confirmation_refs=())
    with pytest.raises(ValueError):
        TrainingGoal("issue", "fight_entry", "Test issue", "reviewed_issue", issue_id="test-issue")


def test_unknown_behavior_is_not_zero_and_denominators_include_abstentions():
    p = period()
    assignment = p.assignment_id
    p = replace(p, opportunities=p.opportunities + (
        BehaviorOpportunity("unknown", 1001, assignment, "unknown", None, "unknown", (), reason_codes=("unresolved-trigger",)),
        BehaviorOpportunity("forced", 1001, assignment, "ineligible", None, "user_journal", ("test-forced",))))
    m = summarize_period(p)
    assert (m.supplied_opportunities, m.eligible, m.ineligible, m.eligibility_unknown) == (5, 3, 1, 1)
    assert m.behavior_observed == 2 and m.behavior_completed == 1 and m.behavior_unknown == 1
    assert m.completion_rate_among_observed == .5 and m.coverage_among_eligible == 2 / 3
    assert m.example_ids == ("op:1:0",) and m.counterexample_ids == ("op:1:1",)


def test_selfreported_comparable_behavior_delta_is_not_resolved_or_causal():
    result = compare_training_periods(period(1, (True, False)), period(2, (True, True)))
    assert result.status == "comparable_self_report" and result.completion_rate_delta == .5
    assert "не устанавливает исправление" in result.conclusion and "причинный" in result.conclusion


def test_no_followup_opportunity_is_insufficient_data_not_fixed_issue():
    result = compare_training_periods(period(1, (False,)), period(2, ()))
    assert result.status == "insufficient_evidence" and result.completion_rate_delta is None
    assert "behavior_or_eligibility_missing" in result.reason_codes


@pytest.mark.parametrize("change,reason", [
    (lambda p: replace(p, match_ids=(1001,), opportunities=tuple(replace(o, match_id=1001) for o in p.opportunities)), "overlapping_matches"),
    (lambda p: replace(p, started_at="2026-10-06T11:00:00Z"), "overlapping_or_reversed_periods"),
    (lambda p: replace(p, coverage_policy="changed"), "coverage_changed"),
    (lambda p: replace(p, scope=replace(scope(), patch="other")), "context_or_measurement_changed"),
    (lambda p: replace(p, opportunities=tuple(replace(o, evidence_kind="independent_observation") for o in p.opportunities)), "evidence_source_changed"),
])
def test_noncomparable_context_has_no_progress_delta(change, reason):
    result = compare_training_periods(period(1, (False,)), change(period(2, (True,))))
    assert result.completion_rate_delta is None and reason in result.reason_codes


def test_duplicate_or_out_of_scope_behavior_records_rejected():
    p = period(1, (True,))
    with pytest.raises(ValueError):
        replace(p, opportunities=p.opportunities * 2)
    with pytest.raises(ValueError):
        replace(p, opportunities=(replace(p.opportunities[0], match_id=999),))
    with pytest.raises(ValueError):
        replace(p.opportunities[0], behavior_completed=1)
    with pytest.raises(ValueError):
        replace(p, coverage_refs=())


def raw(mid=1001, account=111):
    return {"match_id": mid, "patch": 60, "duration": 1800,
            "replay_url": f"http://replay273.valve.net/570/{mid}_123.dem.bz2",
            "players": [{"account_id": account, "player_slot": 0, "hero_id": 145,
                         "lane_role": 1, "last_hits": 300, "gold_per_min": 600,
                         "deaths": 3, "obs_placed": 2, "rank_tier": 80,
                         "teamfight_participation": .5,
                         "purchase_log": [{"time": 600, "key": "black_king_bar"}],
                         "obs_log": [{"time": 500, "x": 1, "y": 2}]},
                        {"account_id": 222, "player_slot": 1, "hero_id": 112, "lane_role": 1, "last_hits": 20}],
            "teamfights": [{"start": 413}]}


class Response:
    status_code = 200
    def __init__(self, value=None, binary=None):
        self.content = binary if binary is not None else json.dumps(value).encode()
    def close(self): pass
    def iter_content(self, chunk_size=8): yield self.content[:chunk_size]


class Session:
    def __init__(self, candidate):
        self.routes = {BASE + "/proMatches": Response([{"match_id": candidate["match_id"]}]),
                       BASE + f"/matches/{candidate['match_id']}": Response(candidate),
                       BASE + "/proPlayers": Response([{"account_id": candidate["players"][0]["account_id"]}]),
                       candidate["replay_url"]: Response(binary=b"BZh9test")}
    def get(self, url, **kwargs): return self.routes[url]


def discover(tmp_path, candidate=None):
    candidate = candidate or raw()
    return OpenDotaStudySource(tmp_path, session=Session(candidate), min_interval=0,
                               now=lambda: datetime(2026, 10, 6, tzinfo=timezone.utc)).discover(145, max_fetches=1)


def test_taskmatched_episode_refs_and_transparent_style_feature_distance(tmp_path):
    selection = match_study_to_goal(goal(), raw(2001, 333), account_id=333, discovery=discover(tmp_path))
    assert selection.status == "task_matched_descriptive_examples"
    item = selection.matches[0]
    assert item.match_id == 1001 and item.task_code == "fight_entry"
    assert item.episode_refs[0].endswith("#/teamfights/0")
    assert item.descriptive_feature_distance == 0 and item.shared_feature_count == 5
    assert item.quality_claim == "not_established" and "role_is_estimated_not_verified" in item.differences
    assert goal().statement in item.viewing_task


@pytest.mark.parametrize("task,suffix", [("defensive_item_plan", "/purchase_log/0"), ("vision_plan", "/obs_log/0")])
def test_matching_user_task_uses_actual_source_specific_events(tmp_path, task, suffix):
    selection = match_study_to_goal(goal(task), raw(2001, 333), account_id=333, discovery=discover(tmp_path))
    assert selection.matches[0].episode_refs[0].endswith(suffix)


def test_missing_task_event_does_not_reuse_irrelevant_teamfight(tmp_path):
    candidate = raw()
    candidate["players"][0]["purchase_log"] = [{"time": 600, "key": "boots"}]
    result = match_study_to_goal(goal("defensive_item_plan"), raw(2001, 333), account_id=333,
                                discovery=discover(tmp_path, candidate))
    assert result.status == "unavailable" and result.matches == ()
    assert "requested_task_source_episode_missing" in result.exclusions[0][1]


def test_missing_features_do_not_imply_zero_distance_or_matching_style(tmp_path):
    target = raw(2001, 333)
    for key in ("gold_per_min", "deaths", "teamfight_participation"):
        del target["players"][0][key]
    result = match_study_to_goal(goal(), target, account_id=333, discovery=discover(tmp_path))
    selected = result.matches[0]
    assert selected.descriptive_feature_distance is None and selected.shared_feature_count == 2
    assert len(selected.missing_features) == 3


def test_target_self_and_unconfirmed_goal_cannot_get_recommendations(tmp_path):
    discovery = discover(tmp_path)
    assert match_study_to_goal(goal(), raw(), account_id=111, discovery=discovery).matches == ()
    assert match_study_to_goal(goal(origin="unconfirmed"), raw(2001, 333), account_id=333, discovery=discovery).matches == ()


def test_patch_role_and_hero_differences_are_not_silently_accepted(tmp_path):
    target = raw(2001, 333)
    target["patch"] = 59
    result = match_study_to_goal(goal(), target, account_id=333, discovery=discover(tmp_path))
    assert result.status == "unavailable" and "provider_patch_mismatch_or_unknown" in result.exclusions[0][1]


def test_strict_goal_scope_and_period_roundtrip():
    assert load_training_goal(json.dumps(asdict(goal()))) == goal()
    assert load_training_scope(json.dumps(asdict(scope()))) == scope()
    p = period(1, (True, False))
    assert load_training_period(json.dumps(asdict(p))) == p
    with pytest.raises(ValueError):
        load_training_goal('{"goal_id":"a","goal_id":"b"}')
    with pytest.raises(ValueError):
        load_training_goal(json.dumps(asdict(goal()) | {"verified_diagnosis": True}))
    with pytest.raises(ValueError):
        load_training_period(json.dumps(asdict(p) | {"radiant_win": True}))


def test_reviewable_training_report_contains_real_supplied_denominators_and_missing_periods(tmp_path):
    assignment = assign_exercise(goal(), scope())
    result = write_training_report(assignment, tmp_path, baseline=period(1, (True, False)))
    assert result["baseline_measurement"]["eligible"] == 2 and result["followup"] is None
    assert result["automatic_error_diagnosis"] is False and result["quality_validation"] == "not_established"
    text = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Журнал не предоставлен" in text and "training.json" in text
    with pytest.raises(ValueError):
        write_training_report(assignment, tmp_path, baseline=replace(period(), assignment_id="other"))


def test_training_report_escapes_user_statement(tmp_path):
    assignment = assign_exercise(replace(goal(), statement="<script>alert(1)</script>"), scope())
    write_training_report(assignment, tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html and "&lt;script&gt;" in html
