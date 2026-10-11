from copy import deepcopy

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.objective_state import build_objective_state, project_objective_state
from tests.test_semantic_lifecycle import marker, report


def objective(rid, kind="building_destroyed_observed", *, target="npc_dota_badguys_tower1_mid",
              actor="hero_a", domain="trace"):
    row = marker(rid, kind, target=target, actor=actor, domain=domain)
    row["ability_or_item"] = None
    if domain == "provider":
        row.update(source_ref=f"provider:7:objectives:{rid}", event_id=f"provider:7:objectives:{rid}",
            source_record_index=None, game_time=10+rid, timestamp_source="provider.time/unverified_retrospective")
        row["raw_details"] = {"key": target, "team": 3}
    return row


def test_building_key_or_killer_team_cannot_establish_ownership_or_map_control():
    source = report(lanes={"provider": [objective(1, domain="provider")]})
    result = build_objective_state(source)
    state, = result["lanes"]["provider"]["objects"]
    assert state["source_subject"] == "npc_dota_badguys_tower1_mid"
    assert state["observed_state"] == "destruction_marker_observed"
    assert state["observations"][0]["raw_details"]["team"] == 3
    assert state["ownership"] == state["player_availability"] == state["persistent_state"] == "unknown"
    assert result["map_control"] == "not_established"
    assert state["training_eligible"] is False


def test_buyback_marker_retains_actor_and_count_but_not_life_gold_or_readiness():
    source = report(lanes={"trace": [objective(2, "buyback_observed", actor="hero_a", target=None),
        objective(4, "buyback_observed", actor="hero_a", target=None)]})
    state, = build_objective_state(source)["lanes"]["trace"]["objects"]
    assert state["source_subject"] == "hero_a"
    assert len(state["evidence_refs"]) == 2
    assert state["observed_state"] == "buyback_marker_observed"
    assert state["alive"] == state["buyback_ready"] == "unknown"
    assert state["respawn_at"] is None


def test_roshan_without_exact_subject_is_event_scoped_not_invented_respawn_entity():
    source = report(lanes={"provider": [objective(1, "roshan_killed_observed", target=None, domain="provider"),
        objective(2, "roshan_killed_observed", target=None, domain="provider")]})
    states = build_objective_state(source)["lanes"]["provider"]["objects"]
    assert len(states) == 2 and states[0]["object_ref"] != states[1]["object_ref"]
    assert all(s["identity_status"] == "event_scoped_subject_unresolved" for s in states)
    assert all(s["respawn_at"] is None and s["ownership"] == "unknown" for s in states)


def test_repeat_destruction_same_source_name_is_ambiguous_without_generation():
    source = report(lanes={"trace": [objective(2), objective(4)]})
    state, = build_objective_state(source)["lanes"]["trace"]["objects"]
    assert state["ambiguity"] == ["repeated_destruction_marker_duplicate_or_generation_change_unresolved"]
    assert state["left_censored"] and state["right_censored"]
    assert state["persistent_state"] == "unknown"


def test_source_domain_and_replay_bytes_bind_stable_object_identity():
    source = report(lanes={"trace": [objective(2)], "combat_names": [objective(2, domain="combat_names")]})
    full = build_objective_state(source)
    first = full["lanes"]["trace"]["objects"][0]
    assert first["object_ref"] != full["lanes"]["combat_names"]["objects"][0]["object_ref"]
    prefix = project_objective_state(source, "trace", 4)
    assert first["object_ref"] == prefix["lanes"]["trace"]["objects"][0]["object_ref"]
    source["replay_sha256"] = "e" * 64
    changed = build_objective_state(source)
    assert first["object_ref"] != changed["lanes"]["trace"]["objects"][0]["object_ref"]


def test_future_equal_cutoff_hidden_metadata_and_other_sources_do_not_change_prefix():
    source = report(lanes={"trace": [objective(2), objective(4)]})
    first = project_objective_state(source, "trace", 4)
    source["lanes"]["trace"][1] = {"source_record_index": 4, "ownership": "invented", "source_domain": "provider"}
    source["lanes"]["trace"][0]["source_trace_hash"] = "d" * 64
    source["lanes"]["trace"][0]["raw_details"]["postmatch_winner"] = True
    source["lanes"]["provider"] = [{"winner": True}]
    source["payload_sha256"] = "f" * 64
    assert project_objective_state(source, "trace", 4) == first
    assert first["prefix_sha256"] == content_hash({k:v for k,v in first.items() if k!="prefix_sha256"})


def test_provider_has_no_replay_prefix_order_even_when_time_is_numeric():
    source = report(lanes={"provider": [objective(2, domain="provider")]})
    with pytest.raises(ValueError, match="provider"):
        project_objective_state(source, "provider", 4)


def test_absent_objective_markers_are_not_empty_map_or_no_buyback_proof():
    source = report(marker(2))
    lane = build_objective_state(source)["lanes"]["combat_names"]
    assert lane["objects"] == [] and lane["coverage"]["observed_markers"] == 0
    assert lane["absence_semantics"] == "no_matching_marker_is_not_proof_of_no_objective_or_buyback"


def test_hash_verifies_and_input_not_aliased():
    source = report(lanes={"provider": [objective(1, domain="provider")]})
    copy = deepcopy(source)
    output = build_objective_state(source)
    assert output["payload_sha256"] == content_hash({k:v for k,v in output.items() if k!="payload_sha256"})
    output["lanes"]["provider"]["objects"][0]["observations"][0]["raw_details"]["team"] = 2
    assert source == copy
