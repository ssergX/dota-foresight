from collections import Counter
from dataclasses import replace
import json

import pytest

from dota_coach.ingest.semantic_events import (
    build_semantic_events, load_combat_semantic_events, project_semantic_timeline,
)
from dota_coach.evidence.contracts import ReplayManifest
from dota_coach.ingest.trace import LoggedAction, TraceResult
from dota_coach.models import ParsedReplay


def trace(actions=()):
    return TraceResult(ParsedReplay(7, 10, {}, []), tuple(actions), {"replay_sha256": "a" * 64}, ())


def action(rid=10, *, item="item_tpscroll", actor="hero_a", target=None, time=1.0):
    return LoggedAction(f"trace:7:record:{rid}", rid, "item", actor, target, item, time,
        "combat_log.timestamp/unverified-prefix_game_start" if time is not None else "unavailable",
        raw_timestamp=11, timing_evidence_records=(2, 3))


def sidecar(path, events, *, mutate=None):
    rows = [{"t": "meta", "schema_version": "replay-combat-names.v1", "replay_sha256": "a" * 64}]
    rows += events
    rows += [{"t": "trace_end", "parser_completed": True}]
    for i, row in enumerate(rows, 1):
        row["record_index"] = i
    rows[-1]["counts"] = dict(Counter(r["t"] for r in rows[:-1]))
    if mutate:
        mutate(rows)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def combat(kind="DOTA_COMBATLOG_MODIFIER_ADD", *, modifier="modifier_smoke_of_deceit",
           target="hero_b", actor="hero_a", timestamp=12):
    return {"t": "combat_log", "name_resolution": "CombatLogNames_at_callback/v1",
            "resolved_names": {"attacker_name": actor, "target_name": target, "inflictor_name": modifier},
            "data": {"type": kind, "timestamp": timestamp}}


def load(path):
    return load_combat_semantic_events(path, match_id=7, expected_replay_sha256="a" * 64)


def test_item_use_does_not_manufacture_tp_channel_arrival_or_target():
    e = build_semantic_events(trace([action()]))["lanes"]["trace"][0]
    assert e["kind"] == "tp_use_observed"
    assert e["target"] is None
    assert {"channel_start", "channel_end", "interruption", "arrival", "destination"} <= set(e["unknown_fields"])
    assert e["validation"] == "unverified"


def test_display_only_backfill_is_not_prefix_time():
    a = replace(action(time=None), display_game_time=3, display_time_method="retrospective_backfill")
    e = build_semantic_events(trace([a]))["lanes"]["trace"][0]
    assert e["game_time"] is None
    assert "game_time" in e["unknown_fields"]


def test_future_clock_reference_is_rejected():
    with pytest.raises(ValueError, match="future"):
        build_semantic_events(trace([replace(action(), timing_evidence_records=(15,))]))


def test_game_time_without_clock_provenance_is_downgraded():
    e = build_semantic_events(trace([replace(action(), timing_evidence_records=())]))["lanes"]["trace"][0]
    assert e["game_time"] is None
    assert "prefix_clock_provenance_unavailable" in e["quality_flags"]


def test_oversized_numeric_time_is_unknown_not_an_overflow():
    e = build_semantic_events(trace([replace(action(), game_time=10 ** 1000, raw_timestamp=10 ** 1000)]))["lanes"]["trace"][0]
    assert e["game_time"] is None and e["raw_timestamp"] is None


def test_manifest_source_authority_with_missing_or_conflicting_audit():
    t = trace([action()])
    replay = replace(t.replay, manifest=ReplayManifest("a" * 64, 7))
    report = build_semantic_events(replace(t, replay=replay, audit={}))
    assert report["replay_sha256"] == "a" * 64
    with pytest.raises(ValueError, match="identity mismatch"):
        build_semantic_events(replace(t, replay=replay, audit={"replay_sha256": "b" * 64}))


def test_source_identity_mixture_cannot_pollute_actor_state():
    row = build_semantic_events(trace([action()]))["lanes"]["trace"][0]
    foreign = row | {"source_ref": "trace:8:record:10", "event_id": "trace:8:record:10"}
    with pytest.raises(ValueError, match="replay identities"):
        project_semantic_timeline([row, foreign], source_domain="trace", cutoff_record_index=20)


def test_unresolved_buyback_actor_is_not_guessed_from_timestamp():
    a = replace(action(actor=None, item=None), kind="buyback")
    e = build_semantic_events(trace([a]))["lanes"]["trace"][0]
    assert e["kind"] == "buyback_observed" and e["actor"] is None


def test_provider_source_slots_are_not_interchanged():
    raw = {"match_id": 7, "players": [{"player_slot": 128, "account_id": 99, "hero_id": 1,
        "buyback_log": [{"time": 10, "slot": 5}]}], "objectives": [
        {"type": "building_kill", "time": 11, "slot": 5, "key": "tower"},
        {"type": "CHAT_MESSAGE_ROSHAN_KILL", "time": 12, "player_slot": 128},
        {"type": "CHAT_MESSAGE_AEGIS", "time": 13}]}
    report = build_semantic_events(trace(), raw)
    events = report["lanes"]["provider"]
    assert len(events) == 3
    assert events[0]["actor"] is None
    assert events[1]["actor"] == events[2]["actor"] == "provider_player_slot:128"
    assert events[2]["raw_details"]["account_id"] == 99
    with pytest.raises(ValueError, match="prefix"):
        project_semantic_timeline(events, source_domain="provider", cutoff_record_index=10)


def test_provider_buyback_actor_contradiction_rejected():
    raw = {"match_id": 7, "players": [{"player_slot": 0, "buyback_log": [{"player_slot": 1}]}]}
    with pytest.raises(ValueError, match="contradicts"):
        build_semantic_events(trace(), raw)


def test_provider_boolean_slot_cannot_attribute_building_kill_to_slot_zero():
    raw = {"match_id": 7, "players": [{"player_slot": 0}], "objectives": [
        {"type": "building_kill", "player_slot": False, "time": 1}]}
    e = build_semantic_events(trace(), raw)["lanes"]["provider"][0]
    assert e["actor"] is None


def test_missing_provider_fields_do_not_claim_zero_coverage():
    report = build_semantic_events(trace(), {"match_id": 7, "players": [{"player_slot": 0}]})
    assert report["source_availability"]["provider_objectives"] == "unknown"
    assert report["source_availability"]["provider_buybacks"] == "partial_or_unknown"


def test_prefix_excludes_future_even_malformed_future_payload():
    rows = build_semantic_events(trace([action(10), action(20)]))["lanes"]["trace"]
    first = project_semantic_timeline(rows, source_domain="trace", cutoff_record_index=20)
    rows[1]["validation"] = "invented_validation"
    rows[1]["timing_evidence_records"] = [100000]
    second = project_semantic_timeline(rows, source_domain="trace", cutoff_record_index=20)
    assert first == second
    assert first["states"][0]["use_count"] == 1
    assert first["states"][0]["lifecycle_outcome"] == "unknown"


def test_smoke_modifier_subject_is_target_not_caster_and_remove_is_not_break(tmp_path):
    path = sidecar(tmp_path / "names", [combat(), combat("DOTA_COMBATLOG_MODIFIER_REMOVE")])
    result = load(path)
    rows = result["lanes"]["combat_names"]
    assert all(e["game_time"] is None for e in rows)
    assert [e["kind"] for e in rows] == ["smoke_modifier_applied", "smoke_modifier_removed"]
    before = project_semantic_timeline(rows, source_domain="combat_names", cutoff_record_index=3)
    after = project_semantic_timeline(rows, source_domain="combat_names", cutoff_record_index=4)
    assert before["states"][0]["subject"] == "hero_b"
    assert before["states"][0]["modifier_status"] == "apply_marker_observed"
    assert after["states"][0]["modifier_status"] == "remove_marker_observed"
    assert after["states"][0]["lifecycle_outcome"] == "unknown"
    assert "break_reason" in rows[1]["unknown_fields"]


def test_teleport_modifier_removal_without_apply_is_unknown_not_interrupt(tmp_path):
    path = sidecar(tmp_path / "names", [combat("DOTA_COMBATLOG_MODIFIER_REMOVE", modifier="modifier_teleporting")])
    rows = load(path)["lanes"]["combat_names"]
    state = project_semantic_timeline(rows, source_domain="combat_names", cutoff_record_index=3)["states"][0]
    assert state["lifecycle_outcome"] == "unknown"
    assert state["quality_flags"] == ["remove_without_prior_apply_in_observed_prefix"]


def test_raw_nonfinite_timestamp_does_not_become_exact_time(tmp_path):
    row = combat(timestamp=None)
    rows = load(sidecar(tmp_path / "names", [row]))["lanes"]["combat_names"]
    assert rows[0]["raw_timestamp"] is None and rows[0]["game_time"] is None


def test_sidecar_domain_cannot_be_mixed_with_trace_ordinal(tmp_path):
    rows = load(sidecar(tmp_path / "names", [combat()]))["lanes"]["combat_names"]
    with pytest.raises(ValueError, match="domains"):
        project_semantic_timeline(rows, source_domain="trace", cutoff_record_index=3)


@pytest.mark.parametrize("mutation", [
    lambda r: r[0].update(replay_sha256="b" * 64),
    lambda r: r[1].update(record_index=99),
    lambda r: r[1].update(name_resolution="final_string_table"),
    lambda r: r[-1].update(parser_completed=False),
    lambda r: r[-1].update(counts={}),
])
def test_sidecar_rejects_source_or_completeness_failure(tmp_path, mutation):
    with pytest.raises(ValueError):
        load(sidecar(tmp_path / "names", [combat()], mutate=mutation))


def test_duplicate_event_identity_cannot_inflate_observation_count():
    rows = build_semantic_events(trace([action()]))["lanes"]["trace"]
    with pytest.raises(ValueError, match="duplicate"):
        project_semantic_timeline(rows * 2, source_domain="trace", cutoff_record_index=20)


def test_unrelated_modifiers_are_not_tp_or_smoke_events(tmp_path):
    result = load(sidecar(tmp_path / "names", [combat(modifier="modifier_fountain_aura_buff")]))
    assert result["lanes"]["combat_names"] == []


@pytest.mark.parametrize("dataset_kind", ["replay", "synthetic", "unknown"])
def test_semantic_standalone_exports_preserve_manifest_kind(dataset_kind):
    t = trace([action()])
    t = replace(t, replay=replace(t.replay, manifest=ReplayManifest("a" * 64, 7, dataset_kind=dataset_kind)))
    raw = {"match_id": 7, "players": [{"player_slot": 0, "buyback_log": [{"time": 2}]}]}
    report = build_semantic_events(t, raw)
    assert report["dataset_kind"] == dataset_kind
    assert all(e["dataset_kind"] == dataset_kind for events in report["lanes"].values() for e in events)
    prefix = project_semantic_timeline(report["lanes"]["trace"], source_domain="trace", cutoff_record_index=20)
    assert prefix["dataset_kind"] == dataset_kind


@pytest.mark.parametrize("dataset_kind", ["replay", "synthetic", "unknown"])
def test_sidecar_kind_requires_explicit_header_and_propagates_to_prefix(tmp_path, dataset_kind):
    path = sidecar(tmp_path / "names", [combat()])
    assert load(path)["dataset_kind"] == "unknown"
    report = load_combat_semantic_events(path, match_id=7, expected_replay_sha256="a" * 64,
        dataset_kind=dataset_kind)
    assert report["dataset_kind"] == dataset_kind
    rows = report["lanes"]["combat_names"]
    assert rows[0]["dataset_kind"] == dataset_kind
    assert project_semantic_timeline(rows, source_domain="combat_names", cutoff_record_index=3)["dataset_kind"] == dataset_kind
    empty = project_semantic_timeline(rows, source_domain="combat_names", cutoff_record_index=2,
        dataset_kind=dataset_kind)
    assert empty["dataset_kind"] == dataset_kind and empty["events"] == []


def test_future_dataset_kind_cannot_change_prefix_or_hash():
    rows = build_semantic_events(trace([action(10), action(20)]))["lanes"]["trace"]
    before = project_semantic_timeline(rows, source_domain="trace", cutoff_record_index=20)
    rows[1]["dataset_kind"] = "replay"
    assert project_semantic_timeline(rows, source_domain="trace", cutoff_record_index=20) == before
    rows[1]["dataset_kind"] = "invalid_future_payload"
    assert project_semantic_timeline(rows, source_domain="trace", cutoff_record_index=20) == before


def test_unknown_event_cannot_be_promoted_by_prefix_header():
    rows = build_semantic_events(trace([action()]))["lanes"]["trace"]
    with pytest.raises(ValueError, match="promote"):
        project_semantic_timeline(rows, source_domain="trace", cutoff_record_index=20, dataset_kind="replay")
    rows.append(rows[0] | {"event_id": "trace:7:record:11", "source_ref": "trace:7:record:11",
        "source_record_index": 11, "dataset_kind": "synthetic"})
    with pytest.raises(ValueError, match="dataset kinds"):
        project_semantic_timeline(rows, source_domain="trace", cutoff_record_index=20)


@pytest.mark.parametrize("dataset_kind", [None, True, "real", [], {}])
def test_sidecar_dataset_kind_strict_enum(tmp_path, dataset_kind):
    path = sidecar(tmp_path / "names", [combat()])
    with pytest.raises(ValueError, match="dataset_kind"):
        load_combat_semantic_events(path, match_id=7, expected_replay_sha256="a" * 64,
            dataset_kind=dataset_kind)


def test_empty_prefix_without_header_stays_unknown():
    empty = project_semantic_timeline([], source_domain="trace", cutoff_record_index=1)
    assert empty["dataset_kind"] == "unknown"
