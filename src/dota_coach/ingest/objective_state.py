"""Temporal source-local objective/buyback observations, separate from knowledge.

A building-kill key identifies a source name, not its owner or entity generation.
Roshan callbacks do not identify a respawn generation; buyback callbacks do not
establish current life, funds or cooldown. Provider time is retrospective only.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.semantic_lifecycle import (
    build_semantic_lifecycles, project_semantic_lifecycles,
)

SCHEMA = "foresight.objective-state.v1"
KINDS = {"building_destroyed_observed": "building", "roshan_killed_observed": "roshan",
         "buyback_observed": "player_buyback"}


def _fold(events, domain, identity, *, prefix):
    selected = [deepcopy(event) for event in events if event["kind"] in KINDS]
    objects = {}
    for event in selected:
        category = KINDS[event["kind"]]
        subject = event["actor"] if category == "player_buyback" else event["target"]
        # A Roshan marker without a named target stays event-scoped. Never merge
        # possible respawns into one invented persistent entity.
        key = (category, subject) if subject is not None else (category, event["source_ref"])
        if key not in objects:
            binding = {**identity, "source_domain": domain, "category": category,
                       "source_subject": subject}
            if subject is None:
                binding["unresolved_origin_ref"] = event["source_ref"]
            objects[key] = {"object_ref": "observed-object:" + content_hash(binding),
                "category": category, "source_subject": subject,
                "subject_rule": "exact_source_actor_for_buyback_target_for_objectives_no_name_team_inference",
                "identity_status": "exact_source_name_generation_unknown" if subject else "event_scoped_subject_unresolved",
                "evidence_refs": [], "event_ids": [], "observations": [],
                "observed_state": "unknown", "state_status": "observed_marker_only",
                "persistent_state": "unknown", "ownership": "unknown", "ownership_status": "unknown",
                "player_availability": "unknown", "availability_status": "unknown",
                "alive": "unknown", "buyback_ready": "unknown", "respawn_at": None,
                "left_censored": True, "right_censored": True, "ambiguity": [],
                "censoring_boundary": "source_prefix_cutoff" if prefix else "observed_source_marker_window",
                "quality_flags": ["extraction_unverified", "entity_generation_unknown",
                                  "player_observation_availability_not_supplied"],
                "unknown_fields": ["ownership", "player_availability", "entity_generation",
                    "persistent_state", "cause", "buyback_ready", "respawn_at"],
                "training_eligible": False}
        state = objects[key]
        state["evidence_refs"].append(event["source_ref"])
        state["event_ids"].append(event["event_id"])
        state["observations"].append({"source_ref": event["source_ref"], "kind": event["kind"],
            "source_record_index": event["source_record_index"], "actor": event["actor"],
            "clock": {k: deepcopy(event[k]) for k in ("game_time", "raw_timestamp", "timestamp_source", "timing_evidence_records")},
            "raw_details": deepcopy(event["raw_details"])})
        state["observed_state"] = {"building": "destruction_marker_observed",
            "roshan": "kill_marker_observed", "player_buyback": "buyback_marker_observed"}[category]
        if category == "building" and len(state["evidence_refs"]) > 1:
            state["ambiguity"] = ["repeated_destruction_marker_duplicate_or_generation_change_unresolved"]
        if category == "roshan" and subject is not None and len(state["evidence_refs"]) > 1:
            state["ambiguity"] = ["multiple_roshan_kill_markers_respawn_generation_unresolved"]
        # `team` is the callback/provider event field, never building ownership.
    return {"source_domain": domain, "events": selected, "objects": list(objects.values()),
        "coverage": {"observed_markers": len(selected), "source_objects": len(objects),
                     "kinds": dict(Counter(event["kind"] for event in selected))},
        "temporal_order": "source_callback_order_not_verified_game_clock" if domain != "provider" else "provider_array_order_retrospective_not_replay_order",
        "absence_semantics": "no_matching_marker_is_not_proof_of_no_objective_or_buyback",
        "perspective": "retrospective_world_observation", "training_eligible": False}


def _result(source, *, scope, cutoff=None):
    identity = {key: source[key] for key in ("match_id", "replay_sha256", "dataset_kind")}
    lanes = {name: _fold(lane["events"], name, identity, prefix=cutoff is not None)
             for name, lane in source["lanes"].items()}
    result = {"schema_version": SCHEMA, **identity, "scope": scope, "lanes": lanes,
        "validation": "unverified", "perspective": "retrospective_world_observation",
        "training_eligible": False, "ownership": "unknown", "player_availability": "unknown",
        "cross_source_join": "not_performed", "map_control": "not_established",
        "limitations": ["source_names_not_entity_generations", "provider_is_not_player_knowledge",
            "no_causal_team_ownership_inference", "no_respawn_or_buyback_cooldown_inference",
            "observation_window_not_continuous_state_coverage"]}
    if cutoff is not None:
        result.update(source_domain=source["source_domain"], cutoff_record_index=cutoff,
                      boundary="strictly_before_source_callback_record")
        result["prefix_sha256"] = content_hash(result)
    else:
        result["source_receipts"] = source["source_receipts"]
        result["payload_sha256"] = content_hash(result)
    return result


def build_objective_state(semantic_events: dict) -> dict:
    """Expose all objective observations; no retrospective-to-player promotion."""
    return _result(build_semantic_lifecycles(semantic_events), scope="retrospective_source_local")


def project_objective_state(semantic_events: dict, source_domain: str,
                            cutoff_record_index: int) -> dict:
    """Fold only the selected replay lane strictly before the callback boundary."""
    source = project_semantic_lifecycles(semantic_events, source_domain, cutoff_record_index)
    return _result(source, scope="source_local_prefix", cutoff=cutoff_record_index)
