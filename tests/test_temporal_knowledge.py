from dataclasses import replace

import pytest

from dota_coach.evidence.contracts import EntityRef, Fact, SourceRef, TimeRef
from dota_coach.evidence.temporal import TemporalKnowledgePolicy, project_temporal_knowledge


def time(ms, *, uncertainty=0, tick=None, sequence=None, version="explicit-observation-clock.v1"):
    return TimeRef(ms, tick, sequence, uncertainty, version, "verified")


def fact(fid="f1", value=100, *, valid=1000, available=1001, perspective="screen", observer="me",
         subject="enemy:1", predicate="enemy.hp", status="observed", uncertainty=0):
    source = SourceRef("source", "a"*64, "test_observation", "v1", "record:"+fid)
    return Fact(fid, subject, predicate, value, status, time(valid, uncertainty=uncertainty),
        time(available), perspective, (source,), observer_ref=observer,
        quality_flags=("extraction_unverified",), unknown_reason="explicit_unknown" if value is None else None)


def project(*facts, cutoff=None, ttl=2000, **kwargs):
    return project_temporal_knowledge(tuple(facts), subject_player="me", cutoff=cutoff or time(2000),
        policy=TemporalKnowledgePolicy("test-policy.v1", (("enemy.hp", ttl),)), dataset_kind="synthetic", **kwargs)


def test_last_known_retains_original_validity_and_observation_quality():
    snapshot = project(fact())
    state, = snapshot.states
    observed, = snapshot.facts
    assert state.status == "last_known" and state.value == 100
    assert state.min_age_ms == state.max_age_ms == 1000
    assert observed.valid_at == time(1000) and observed.available_at == time(1001)
    assert "extraction_unverified" in observed.quality_flags
    assert "last_known_not_current_visibility" in observed.quality_flags
    assert snapshot.dataset_kind == "synthetic"


def test_explicit_ttl_demotes_old_value_to_stale_without_claiming_current_location():
    snapshot = project(fact(), ttl=500)
    state, = snapshot.states
    assert state.status == "stale" and state.value is None
    assert state.reason == "explicit_predicate_age_policy_exceeded"
    assert snapshot.facts[0].status == "unknown" and snapshot.facts[0].value is None


def test_uncertainty_overlap_ttl_is_unknown_not_arbitrary_threshold_choice():
    state, = project(fact(uncertainty=100), ttl=1000).states
    assert state.status == "unknown" and state.reason == "staleness_boundary_overlaps_uncertainty"
    assert (state.min_age_ms, state.max_age_ms) == (900, 1100)


def test_explicit_static_predicate_ttl_retains_available_old_fact():
    state, = project(fact(), ttl=None, cutoff=time(100000)).states
    assert state.status == "last_known" and state.value == 100


def test_future_hidden_world_foreign_observer_and_whole_file_hashes_do_not_change_input():
    first = project(fact())
    altered = replace(fact(), source_refs=(replace(fact().source_refs[0], content_hash="d"*64),))
    second = project(altered, fact("future", 0, available=3000),
        fact("world", 99999, perspective="world"), fact("other-observer", 20, observer="someone_else"))
    assert first == second and first.input_hash == second.input_hash


def test_missing_query_stays_unknown_without_scanning_excluded_enemy_subjects():
    empty = project(queries=(("enemy:1", "enemy.hp"),))
    future = project(fact("future", subject="enemy:hidden", available=5000), queries=(("enemy:1", "enemy.hp"),))
    assert empty == future
    assert empty.states[0].reason == "no_definitely_available_observation"


@pytest.mark.parametrize("available", [time(1500, uncertainty=None), time(1500, version="legacy/unverified"),
    time(1500, version="other-clock"), time(1990, uncertainty=100)])
def test_missing_uncertain_or_mismatched_availability_clock_is_not_knowledge(available):
    f = replace(fact(), available_at=available)
    snapshot = project(f, queries=(("enemy:1", "enemy.hp"),))
    assert snapshot.states[0].status == "unknown" and snapshot.states[0].value is None


def test_exact_boundary_requires_strict_callback_order_and_never_accepts_current_callback():
    f = replace(fact(), available_at=time(2000))
    assert project(f).states == ()
    f = replace(f, available_at=time(2000, tick=8, sequence=1))
    snapshot = project(f, cutoff=time(2000, tick=8, sequence=2))
    assert snapshot.states[0].value == 100
    assert project(f, cutoff=time(2000, tick=8, sequence=1)).states == ()


def test_delayed_older_observation_does_not_overwrite_newer_validity():
    older = fact("older", 100, valid=1000, available=1800)
    newer = fact("newer", 50, valid=1500, available=1501)
    snapshot = project(older, newer)
    assert snapshot.states[0].value == 50
    assert snapshot.states[0].evidence_fact_ids == ("newer",)


def test_overlapping_contradictory_intervals_are_conflict_until_definitely_newer_observation():
    a = fact("a", 100, valid=1000, uncertainty=100)
    b = fact("b", 50, valid=1100, available=1200, uncertainty=100)
    state, = project(a, b).states
    assert state.status == "conflict" and state.value is None
    assert state.reason == "contradictory_overlapping_last_known_values"
    c = fact("c", 25, valid=1500, available=1501)
    assert project(a, b, c).states[0].value == 25


def test_entity_generation_conflict_does_not_merge_same_subject_values():
    a, b = fact("a"), fact("b")
    snapshot = project(a, b, entity_bindings=(("a", EntityRef("replay", 7, 1)),
        ("b", EntityRef("replay", 7, 2))))
    state, = snapshot.states
    assert state.status == "conflict" and state.reason == "entity_generation_or_identity_conflict"
    assert len(state.entity_refs) == 2


def test_generation_replacement_is_safe_when_new_fact_is_definitely_later():
    a, b = fact("a"), fact("b", valid=1500, available=1501)
    state, = project(a, b, entity_bindings=(("a", EntityRef("replay", 7, 1)),
        ("b", EntityRef("replay", 7, 2)))).states
    assert state.status == "last_known" and state.entity_refs == (EntityRef("replay", 7, 2),)


def test_public_observation_can_be_available_without_private_observer():
    state, = project(fact(perspective="public", observer=None)).states
    assert state.status == "last_known"


def test_unknown_or_conflict_observation_does_not_restore_previous_known_value():
    unknown = fact("u", None, status="unknown", valid=1500, available=1501)
    assert project(fact(), unknown).states[0].status == "unknown"
    conflict = replace(unknown, status="conflict")
    assert project(fact(), conflict).states[0].status == "conflict"


@pytest.mark.parametrize("ttl", [True, -1, float("nan"), float("inf"), 10**1000])
def test_invalid_age_policy_fails_closed(ttl):
    with pytest.raises(ValueError, match="TTL"):
        TemporalKnowledgePolicy("policy.v1", (("enemy.hp", ttl),))


def test_duplicate_available_fact_identity_and_unlisted_query_are_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        project(fact(), fact())
    with pytest.raises(ValueError, match="predicate"):
        project(queries=(("enemy:1", "enemy.hidden_inventory"),))


def test_self_fact_for_other_subject_is_not_observer_knowledge():
    snapshot = project_temporal_knowledge((fact(subject="other", predicate="self.hp"),),
        subject_player="me", cutoff=time(2000), policy=TemporalKnowledgePolicy("self.v1", (("self.hp", 2000),)))
    assert snapshot.states == ()
