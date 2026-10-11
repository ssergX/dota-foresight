from copy import deepcopy
import json

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.semantic_lifecycle import (
    build_semantic_lifecycles, project_semantic_lifecycles,
)


def marker(rid, kind="tp_modifier_applied", *, target="hero_b", actor="hero_a",
           domain="combat_names", illusion=None, raw_time=None):
    prefix = "combat-names" if domain == "combat_names" else "trace"
    ref = f"{prefix}:7:record:{rid}"
    item = "item_tpscroll" if kind == "tp_use_observed" else (
        "item_smoke_of_deceit" if kind == "smoke_use_observed" else (
        "modifier_teleporting" if kind.startswith("tp_") else "modifier_smoke_of_deceit"))
    return {"event_id": ref, "source_ref": ref, "source_domain": domain,
        "source_record_index": rid, "kind": kind, "actor": actor, "target": target,
        "ability_or_item": item, "game_time": None, "raw_timestamp": raw_time,
        "timestamp_source": "combat_log.timestamp/unverified_engine_clock",
        "timing_evidence_records": [], "dataset_kind": "synthetic", "validation": "unverified",
        "perspective": "retrospective_world_observation", "quality_flags": [], "unknown_fields": [],
        "raw_details": {} if illusion is None else {"is_target_illusion": illusion}}


def report(*events, lanes=None):
    return {"schema_version": "foresight.semantic-events.v1", "match_id": 7,
        "replay_sha256": "a" * 64, "dataset_kind": "synthetic", "validation": "unverified",
        "lanes": lanes or {"combat_names": list(events)}, "payload_sha256": "b" * 64,
        "source_sha256": "c" * 64}


def fold(*events):
    return build_semantic_lifecycles(report(*events))["lanes"]["combat_names"]


def test_tp_closed_bracket_preserves_evidence_but_has_no_arrival_or_interruption():
    start = marker(2, raw_time=10)
    end = marker(4, "tp_modifier_removed", raw_time=13)
    end["raw_details"] = {"modifier_purged": True, "modifier_duration": 3}
    lane = fold(start, end)
    bracket, = lane["intervals"]
    assert bracket["subject"] == "hero_b"
    assert bracket["apply_refs"] == [start["source_ref"]]
    assert bracket["remove_ref"] == end["source_ref"]
    assert bracket["status"] == "apply_remove_markers_bracketed"
    assert bracket["observed_timestamp_delta"] == 3
    assert bracket["timestamp_delta_status"] == "raw_clock_difference_not_verified_modifier_duration"
    assert bracket["arrival"] == bracket["interruption"] == bracket["removal_reason"] == "unknown"
    assert lane["events"][1]["raw_details"]["modifier_purged"] is True
    assert bracket["training_eligible"] is False


def test_smoke_removal_is_not_expiration_proximity_or_break_even_with_duration():
    start = marker(2, "smoke_modifier_applied")
    end = marker(3, "smoke_modifier_removed")
    end["raw_details"] = {"modifier_elapsed_duration": 35, "modifier_duration": 35}
    bracket, = fold(start, end)["intervals"]
    assert bracket["smoke_break"] == bracket["lifecycle_outcome"] == bracket["removal_reason"] == "unknown"
    assert bracket["arrival"] == "not_applicable"


def test_use_markers_never_join_nearby_modifier_subject_or_claim_channel_start():
    use = marker(1, "tp_use_observed", target=None, actor="hero_b")
    lane = fold(use, marker(2), marker(3, "tp_modifier_removed"))
    assert len(lane["uses"]) == 1
    assert lane["uses"][0]["actor"] == "hero_b"
    assert lane["uses"][0]["interval_association"] == "not_established"
    assert lane["causal_joins"] == "not_performed"


def test_repeated_apply_retains_all_refs_and_rejects_single_duration_interpretation():
    lane = fold(marker(2, raw_time=10), marker(3, raw_time=11),
                marker(4, "tp_modifier_removed", raw_time=13), marker(5, "tp_modifier_removed"))
    bracket, orphan = lane["intervals"]
    assert bracket["apply_refs"] == ["combat-names:7:record:2", "combat-names:7:record:3"]
    assert bracket["ambiguity"]
    assert bracket["observed_timestamp_delta"] is None
    assert orphan["left_censored"] is True
    assert orphan["apply_refs"] == []
    assert orphan["lifecycle_outcome"] == "unknown"


def test_orphan_remove_and_open_apply_are_opposite_observation_censoring():
    orphan, open_bracket = fold(marker(1, "tp_modifier_removed"), marker(2))["intervals"]
    assert orphan["status"] == "left_censored_removal_observed"
    assert orphan["left_censored"] and not orphan["right_censored"]
    assert open_bracket["status"] == "right_censored_at_observed_marker_end"
    assert not open_bracket["left_censored"] and open_bracket["right_censored"]


def test_interval_id_is_stable_between_open_prefix_and_retrospective_closure():
    data = report(marker(2), marker(4, "tp_modifier_removed"))
    before = project_semantic_lifecycles(data, "combat_names", 4)
    after = build_semantic_lifecycles(data)
    first = before["lanes"]["combat_names"]["intervals"][0]
    second = after["lanes"]["combat_names"]["intervals"][0]
    assert first["interval_id"] == second["interval_id"]
    assert first["right_censored"] and not second["right_censored"]


def test_distinct_replay_bytes_and_repeat_cycles_have_distinct_immutable_ids():
    data = report(marker(2), marker(4, "tp_modifier_removed"), marker(5), marker(6, "tp_modifier_removed"))
    original = build_semantic_lifecycles(data)["lanes"]["combat_names"]["intervals"]
    assert original[0]["interval_id"] != original[1]["interval_id"]
    data["replay_sha256"] = "d" * 64
    changed = build_semantic_lifecycles(data)["lanes"]["combat_names"]["intervals"]
    assert changed[0]["interval_id"] != original[0]["interval_id"]


def test_missing_modifier_target_never_falls_back_to_caster():
    lane = fold(marker(2, target=None), marker(3, "tp_modifier_removed", target=None))
    assert lane["intervals"] == []
    assert len(lane["unresolved_markers"]) == 2
    assert all(m["reason"] == "modifier_subject_unknown_no_caster_fallback" for m in lane["unresolved_markers"])


def test_subject_category_and_illusion_coordinates_do_not_cross_close():
    lane = fold(marker(1, target="hero_b", illusion=True),
        marker(2, target="hero_b", illusion=False),
        marker(3, target="hero_c", illusion=False),
        marker(4, "smoke_modifier_applied", target="hero_b", illusion=False),
        marker(5, "tp_modifier_removed", target="hero_b", illusion=False))
    assert len(lane["intervals"]) == 4
    closed = [b for b in lane["intervals"] if not b["right_censored"]]
    assert len(closed) == 1 and closed[0]["subject_is_illusion"] is False
    assert closed[0]["apply_refs"] == ["combat-names:7:record:2"]


def test_illusion_unknown_not_silently_converted_to_real_hero():
    lane = fold(marker(1, illusion=None), marker(2, "tp_modifier_removed", illusion=False))
    assert len(lane["intervals"]) == 2
    assert lane["intervals"][0]["right_censored"]
    assert lane["intervals"][1]["left_censored"]


def test_clock_regression_and_incompatible_sources_do_not_yield_duration():
    bracket, = fold(marker(1, raw_time=20), marker(2, "tp_modifier_removed", raw_time=10))["intervals"]
    assert bracket["observed_timestamp_delta"] is None
    assert "raw_clock_regression" in bracket["quality_flags"]
    end = marker(2, "tp_modifier_removed", raw_time=10)
    end["timestamp_source"] = "unavailable"
    bracket, = fold(marker(1, raw_time=2), end)["intervals"]
    assert bracket["observed_timestamp_delta"] is None


def test_finite_extreme_clock_difference_cannot_produce_infinite_duration():
    bracket, = fold(marker(1, raw_time=-1e308), marker(2, "tp_modifier_removed", raw_time=1e308))["intervals"]
    assert bracket["observed_timestamp_delta"] is None
    assert "raw_clock_difference_overflow" in bracket["quality_flags"]


def test_unavailable_clock_does_not_become_known_elapsed_duration():
    start, end = marker(1, raw_time=10), marker(2, "tp_modifier_removed", raw_time=13)
    start["timestamp_source"] = end["timestamp_source"] = "unavailable"
    bracket, = fold(start, end)["intervals"]
    assert bracket["observed_timestamp_delta"] is None
    assert bracket["timestamp_delta_status"] == "unknown"


def test_source_lanes_never_cross_join_even_for_same_names_and_timestamps():
    a = marker(1, domain="trace", raw_time=10)
    b = marker(2, "tp_modifier_removed", raw_time=13)
    output = build_semantic_lifecycles(report(lanes={"trace": [a], "combat_names": [b]}))
    assert output["lanes"]["trace"]["intervals"][0]["right_censored"]
    assert output["lanes"]["combat_names"]["intervals"][0]["left_censored"]
    assert output["cross_source_deduplication"].startswith("not_performed")


def test_prefix_is_invariant_under_future_hidden_provider_and_receipt_mutations():
    data = report(marker(2), marker(4, "tp_modifier_removed"))
    baseline = project_semantic_lifecycles(data, "combat_names", 4)
    data["lanes"]["combat_names"][1] = {"source_record_index": 4, "source_domain": "provider", "validation": "invented"}
    data["lanes"]["trace"] = [{"hidden_world_state": "win_probability_and_enemy_positions"}]
    data["lanes"]["provider"] = [{"winner": True}]
    data["coverage"] = "mutated_after_game"
    data["payload_sha256"] = "d" * 64
    data["source_sha256"] = "e" * 64
    data["source_match_binding"] = "mutated"
    assert project_semantic_lifecycles(data, "combat_names", 4) == baseline
    assert "source_receipts" not in baseline
    assert "provider" not in json.dumps(baseline)


def test_hidden_or_full_file_metadata_in_observed_event_is_not_prefix_operand():
    data = report(marker(2))
    baseline = project_semantic_lifecycles(data, "combat_names", 4)
    data["lanes"]["combat_names"][0]["postmatch_winner"] = True
    data["lanes"]["combat_names"][0]["source_trace_hash"] = "d" * 64
    data["lanes"]["combat_names"][0]["raw_details"]["enemy_hidden_inventory"] = ["item_rapier"]
    assert project_semantic_lifecycles(data, "combat_names", 4) == baseline


def test_cutoff_is_strict_and_empty_prefix_preserves_source_kind_and_identity():
    data = report(marker(2))
    result = project_semantic_lifecycles(data, "combat_names", 2)
    assert result["lanes"]["combat_names"]["events"] == []
    assert result["dataset_kind"] == "synthetic"
    assert result["match_id"] == 7 and result["replay_sha256"] == "a" * 64
    assert result["training_eligible"] is False


def test_prefix_clock_evidence_and_exact_record_refs_survive_without_mapping_upgrade():
    event = marker(5, domain="trace", raw_time=10)
    event.update(game_time=2, timestamp_source="combat_log.timestamp/unverified-prefix_game_start", timing_evidence_records=[2, 3])
    result = project_semantic_lifecycles(report(lanes={"trace": [event]}), "trace", 6)
    bracket = result["lanes"]["trace"]["intervals"][0]
    assert bracket["start_clock"]["timing_evidence_records"] == [2, 3]
    assert bracket["start_clock"]["game_time"] == 2
    assert result["validation"] == "unverified"


@pytest.mark.parametrize("field,value,message", [
    ("validation", "verified", "validation"),
    ("perspective", "player", "perspective"),
    ("dataset_kind", "replay", "dataset"),
    ("source_domain", "trace", "domains"),
    ("source_ref", "combat-names:8:record:2", "identity"),
    ("ability_or_item", "modifier_fake", "modifier"),
    ("timing_evidence_records", [3], "future"),
    ("raw_timestamp", float("nan"), "finite"),
    ("source_record_index", True, "integer"),
    ("game_time", 2, "clock"),
])
def test_invalid_observed_prefix_fails_closed(field, value, message):
    event = marker(2)
    event[field] = value
    with pytest.raises(ValueError, match=message):
        project_semantic_lifecycles(report(event), "combat_names", 4)


def test_duplicate_event_or_source_ref_rejected_instead_of_counting_twice():
    with pytest.raises(ValueError, match="duplicate"):
        fold(marker(2), marker(2))


@pytest.mark.parametrize("domain,cutoff", [("provider", 4), ("combat_names", True), ("combat_names", -1)])
def test_provider_ordinal_and_invalid_boundaries_rejected(domain, cutoff):
    with pytest.raises(ValueError):
        project_semantic_lifecycles(report(marker(2)), domain, cutoff)


def test_result_does_not_alias_or_mutate_input_and_hash_verifies():
    data = report(marker(2), marker(3, "tp_modifier_removed"))
    original = deepcopy(data)
    result = build_semantic_lifecycles(data)
    assert data == original
    digest = result.pop("payload_sha256")
    assert digest == content_hash(result)
    result["lanes"]["combat_names"]["events"][0]["raw_details"]["made_up"] = 1
    assert data == original


def test_retrospective_receipts_retained_without_converting_to_prefix_hashes():
    result = build_semantic_lifecycles(report(marker(2)))
    assert result["source_receipts"] == {"payload_sha256": "b" * 64, "source_sha256": "c" * 64}
    assert result["scope"] == "retrospective_source_local"
