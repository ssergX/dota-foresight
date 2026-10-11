"""Synthetic attributed-stream cases; no actual visibility is validated here."""
from dataclasses import replace

import pytest

from dota_coach.learning.ward_review import (
    AttributedObservation, PlacementEvidence, WardTask, review_ward_information,
)


def observation(identity, time, *, entity="enemy:1", value=1, sources=("ward:1",)):
    return AttributedObservation(identity, time, 2, entity, "position.cell", value,
                                  sources, (f"test-source:{identity}",),
                                  ("test-attribution-validation",), "verified")


def review(observations, **kwargs):
    return review_ward_information("ward:1", team=2, cutoff_ms=1000,
                                  observations=tuple(observations), stream_completeness="complete",
                                  coverage_evidence_refs=("test-complete-prefix",), **kwargs)


def test_first_observed_novel_changes_duplicate_and_task_alignment():
    observations = [observation("first", 100), observation("duplicate", 200),
                    observation("changed", 300, value=2), observation("other", 400, entity="enemy:2")]
    task = WardTask("test-task", 0, "position.cell", ("enemy:1",), ("test-task-evidence",), "verified")
    result = review(observations, task=task)
    assert result.status == "descriptive_information"
    assert result.first_observed_entity_ids == ("enemy:1", "enemy:2")
    assert result.novel_observation_ids == ("first", "changed", "other")
    assert result.duplicate_observation_ids == ("duplicate",)
    assert result.task_aligned_observation_ids == ("first", "duplicate", "changed")
    assert result.placement_safe is None and result.feasible_alternative_ids == ()
    assert result.utility == "not_established"


def test_previous_information_from_another_source_is_not_new_ward_information():
    observations = [observation("ally-first", 100, sources=("hero:ally",)), observation("ward-later", 200)]
    result = review(observations)
    assert result.first_observed_entity_ids == () and result.novel_observation_ids == ()
    assert result.duplicate_observation_ids == ("ward-later",)


def test_simultaneous_other_source_is_joint_not_exclusive_credit():
    a = observation("ally", 100, sources=("hero:ally",))
    w = observation("ward", 100)
    one, two = review((a, w)), review((w, a))
    assert one == two and one.jointly_attributed_observation_ids == ("ward",)
    assert one.novel_observation_ids == ("ward",) and one.utility == "not_established"


def test_joint_source_attribution_does_not_claim_marginal_utility():
    result = review([observation("joint", 100, sources=("ward:1", "hero:ally"))])
    assert result.jointly_attributed_observation_ids == ("joint",)
    assert result.utility == "not_established"


def test_future_observation_dropped_without_changing_prefix_result():
    past = observation("past", 100)
    future = replace(observation("future", 2000, value=9), validation_status="unverified", attribution_ids=())
    assert review((past,)) == review((past, future))
    assert review((past, future)) == review((past, replace(future, value=999)))


def test_future_task_and_action_are_unknown_not_backdated():
    task = WardTask("future-task", 2000, "position.cell", (), ("test-task",), "verified")
    action = PlacementEvidence("future-place", 2000, True, True, ("test-action",), "verified")
    result = review((observation("past", 100),), task=task, placement=action, alternatives=(action,))
    assert result.task_alignment == "unknown" and result.placement_feasible is None
    assert result.placement_safe is None and not result.feasible_alternative_ids


@pytest.mark.parametrize("changed", [
    lambda o: replace(o, attribution_ids=()),
    lambda o: replace(o, validation_status="unverified"),
])
def test_missing_attribution_or_validation_abstains(changed):
    result = review((changed(observation("unknown", 100)),))
    assert result.status == "insufficient_evidence" and not result.novel_observation_ids
    assert "observation_or_attribution_not_verified" in result.reason_codes


def test_unknown_prior_stream_prevents_firstseen_and_novel_claims():
    result = review_ward_information("ward:1", team=2, cutoff_ms=1000,
                                    observations=(observation("seen", 100),), stream_completeness="partial")
    assert result.status == "insufficient_evidence" and result.first_observed_entity_ids == ()
    assert result.novel_observation_ids == ()


def test_complete_declaration_without_coverage_receipt_is_not_verified():
    result = review_ward_information("ward:1", team=2, cutoff_ms=1000,
                                    observations=(observation("seen", 100),), stream_completeness="complete")
    assert result.status == "insufficient_evidence"
    assert "stream_completeness_not_verified" in result.reason_codes


def test_confirmed_supplied_actions_are_only_placement_safety_basis():
    placement = PlacementEvidence("place", 0, True, False, ("test-action",), "verified")
    alternative = PlacementEvidence("alternative", 0, True, None, ("test-alternative",), "verified")
    unverified = replace(alternative, action_id="guess", validation_status="unverified")
    result = review((observation("seen", 100),), placement=placement, alternatives=(alternative, unverified))
    assert result.placement_feasible is True and result.placement_safe is False
    assert result.feasible_alternative_ids == ("alternative",) and result.utility == "not_established"


def test_conflicting_same_time_values_abstain_without_cherry_picking():
    result = review((observation("first", 100, value=1), observation("other", 100, value=2)))
    assert result.status == "insufficient_evidence" and not result.novel_observation_ids
    assert "simultaneous_observation_conflict" in result.reason_codes


def test_foreign_team_and_world_observations_do_not_become_subject_knowledge():
    own = observation("own", 100)
    assert review((own, replace(observation("other-team", 200), team=3))) == review((own,))
    with pytest.raises(ValueError):
        replace(own, perspective="world")


def test_lifetime_not_an_input_and_short_information_event_still_described():
    result = review((observation("one-short-observation", 10),))
    assert result.novel_observation_ids == ("one-short-observation",)
    assert result.utility == "not_established"
    with pytest.raises(TypeError):
        review_ward_information("ward:1", team=2, cutoff_ms=1000, observations=(), observed_lifetime=500)
