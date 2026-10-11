from collections import Counter
import hashlib
import json
import os
from dataclasses import replace

import pytest

from dota_coach.ingest.action_state import build_action_states
from dota_coach.ingest.constraint_source import (
    _apply_changes, inspect_constraint_source, load_constraint_source, write_constraint_source,
)
from dota_coach.ingest.trace import parse_trace
from dota_coach.evidence.contracts import content_hash
from tests.test_action_state import source as legacy_source


def source(tmp_path, **kwargs):
    path, _ = legacy_source(tmp_path, **kwargs)
    raw = rows(path)
    handle = 1+(3 << 14)
    raw[3]["fields"]["m_vecPlayerTeamData.0000.m_hSelectedHero"] = str(handle)
    raw[6].update(selected_hero_handle=str(handle),
                  mapping_property="m_vecPlayerTeamData.0000.m_hSelectedHero")
    return path, rewrite(path, raw)


def rewrite(path, rows):
    for rid, row in enumerate(rows, 1):
        row["record_index"] = rid
    rows[-1]["counts"] = dict(Counter(r["t"] for r in rows))
    path.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":"))+"\n" for r in rows), encoding="utf-8")
    return parse_trace(path, 7)


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write(path, extraction, out, account=11):
    return write_constraint_source(path, extraction, out, resource_slot=0,
                                   actor="npc_dota_hero_axe", expected_account_id=account)


def observations(path):
    result, state = [], None
    for row in rows(path):
        if row["t"] != "raw_constraint_observation":
            continue
        if "projection" in row:
            state = row["projection"]
        else:
            _apply_changes(state, row["projection_changes"])
        result.append({k: v for k, v in row.items() if k not in ("projection", "projection_changes")}
                      | json.loads(json.dumps(state)))
    return result


def test_callback_preserves_existing_default_dossier_and_captures_same_tick_changes(tmp_path):
    path, extraction = source(tmp_path)
    before = build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe")
    captured = []
    after = build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe",
                                transition_sink=captured.append)
    assert before == after
    mana_change = next(r for r in captured if r["source_record_index"] == 9)
    cooldown_change = next(r for r in captured if r["source_record_index"] == 10)
    assert mana_change["net_tick"] == cooldown_change["net_tick"] == 120
    assert mana_change["hero"]["fields"]["m_flMana"]["value"] == 250
    assert mana_change["inventory"][0]["fields"]["m_fCooldown"]["value"] == 0
    assert cooldown_change["inventory"][0]["fields"]["m_fCooldown"]["value"] == 500
    assert "checks" not in cooldown_change["inventory"][0]


def test_source_is_streamed_complete_and_stays_unverified(tmp_path):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    summary = write(path, extraction, out)
    assert summary == load_constraint_source(out, extraction=extraction, account_id=11)
    assert summary["counts"]["observations"] == 6
    assert summary["counts"]["delta_projections"] == 3
    assert summary["observed_item_ids"] == ["item_black_king_bar"]
    assert summary["coverage"] == "changed_projected_raw_operands_not_constraint_truth"
    assert summary["training_eligible"] is False
    assert all(r["feasibility"] == "unknown" for r in observations(out))


def test_later_steam_identity_cannot_bind_earlier_hero_projection(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    identity = raw.pop(3)
    raw.insert(6, identity)
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    observed = observations(out)
    mapping = next(r for r in observed if r["transition_reason"] == "primary_mapping_changed")
    assert mapping["prefix_account_id"] is None
    assert mapping["hero"] is None and mapping["inventory"] == []
    steam = next(r for r in observed if r["transition_reason"] == "resource_identity_changed")
    assert steam["prefix_account_id"] == 11
    assert steam["subject_binding"] == "prefix_resource_account_match"
    assert steam["hero"] is None  # Earlier mapping had no active resource receipt.
    earlier = [r for r in observed if r["source_record_index"] < steam["source_record_index"]]
    identity["fields"]["m_vecPlayerData.0000.m_iPlayerSteamID"] = "76561197960265740"
    other = rewrite(path, raw)
    write(path, other, out)
    assert [r for r in observations(out) if r["source_record_index"] < steam["source_record_index"]] == earlier
    assert all(r["hero"] is None for r in observations(out))


def test_deletion_and_serial_reuse_require_exact_new_link(tmp_path):
    path, extraction = source(tmp_path, new_serial=True)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    deleted = next(r for r in observations(out) if r["transition_reason"] == "linked_entity_deleted")
    assert deleted["inventory"][0]["generation"] == 3
    assert deleted["inventory"][0]["relation_status"] == "unresolved_handle"
    assert not any(r["inventory"] and r["inventory"][0]["generation"] == 4 for r in observations(out))
    raw = rows(path)
    change = dict(raw[9])
    change.update(net_tick=111, entity_index=1, generation=3)
    change["class"] = "CDOTA_Unit_Hero_Axe"
    change["fields"] = {"m_hItems.0000": 2+(4<<14)}
    raw.insert(10, change)
    extraction = rewrite(path, raw)
    write(path, extraction, out)
    linked = next(r for r in observations(out) if r["inventory"] and r["inventory"][0]["generation"] == 4)
    assert linked["inventory"][0]["relation_status"] == "resolved_exact_handle"


def test_activation_flags_and_removed_fields_are_not_lost_to_compact_timeline(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    raw[5]["fields"].update(m_bItemEnabled=True, m_bActivated=True, m_bHidden=False)
    raw[9]["fields"] = {"m_bItemEnabled": False}
    raw[9]["removed_fields"] = ["m_bActivated"]
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    fields = observations(out)[-1]["inventory"][0]["fields"]
    assert fields["m_bItemEnabled"]["value"] is False
    assert fields["m_bActivated"]["status"] == "unknown"
    assert fields["m_bActivated"]["source_record_index"] == 10
    assert fields["m_bHidden"]["value"] is False


def test_failed_source_verification_never_publishes_or_replaces_artifact(tmp_path):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    original = out.read_bytes()
    path.write_text(path.read_text()+"\n")
    with pytest.raises(ValueError, match="source differs"):
        write(path, extraction, out)
    assert out.read_bytes() == original
    assert not list(tmp_path.glob("*.partial"))
    missing = tmp_path/"new.jsonl"
    with pytest.raises(ValueError):
        write(path, extraction, missing)
    assert not missing.exists()


@pytest.mark.parametrize("mutation", ["truncate", "hash", "count", "after_footer"])
def test_reader_requires_exact_complete_footer(tmp_path, mutation):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    raw = rows(out)
    if mutation == "truncate":
        raw.pop()
    elif mutation == "hash":
        raw[1]["projection"]["clock"]["paused"] = True
    elif mutation == "count":
        raw[-1]["counts"]["observations"] += 1
    else:
        raw.append(raw[-1])
    out.write_text("".join(json.dumps(r)+"\n" for r in raw), encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_constraint_source(out, extraction=extraction)


def test_callback_rejects_missing_source_record_even_when_extraction_digest_updated(tmp_path):
    path, extraction = source(tmp_path)
    raw = rows(path)
    raw[7]["record_index"] += 10
    path.write_text("".join(json.dumps(r)+"\n" for r in raw), encoding="utf-8")
    extraction.audit["trace_sha256"] = "a"*64
    with pytest.raises(ValueError, match="consecutive source records"):
        write(path, extraction, tmp_path/"constraints.jsonl")


def test_account_and_source_scope_checks(tmp_path):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    with pytest.raises(ValueError, match="account scope"):
        load_constraint_source(out, extraction=extraction, account_id=12)
    with pytest.raises(ValueError, match="overwrite"):
        write(path, extraction, path)
    with pytest.raises(ValueError, match="account ID"):
        write(path, extraction, out, account=True)


def reseal(path, raw):
    for row in raw:
        if row["t"] == "raw_constraint_observation":
            row["payload_sha256"] = content_hash({k: v for k, v in row.items() if k != "payload_sha256"})
    lines = [(json.dumps(r, separators=(",", ":"))+"\n").encode() for r in raw[:-1]]
    raw[-1]["prefix_sha256"] = hashlib.sha256(b"".join(lines)).hexdigest()
    path.write_bytes(b"".join(lines)+(json.dumps(raw[-1])+"\n").encode())


@pytest.mark.parametrize("mutation, error", [
    ("mapping", "exact prefix primary mapping"),
    ("clock", "future clock receipt"),
    ("world", "unexpected hero projection attributes"),
    ("delta", "outside projected state"),
])
def test_resealed_invalid_projection_cannot_bypass_semantic_reader_checks(tmp_path, mutation, error):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    raw = rows(out)
    full = next(r for r in raw if r.get("projection", {}).get("hero"))
    if mutation == "mapping":
        full["projection"]["hero"]["generation"] += 1
    elif mutation == "clock":
        full["projection"]["clock"]["evidence_records"].append(full["source_record_index"]+1)
    elif mutation == "world":
        full["projection"]["hero"]["enemy_positions"] = []
    else:
        delta = next(r for r in raw if "projection_changes" in r)
        delta["projection_changes"].append({"op": "set", "path": ["world"], "value": []})
    reseal(out, raw)
    with pytest.raises(ValueError, match=error):
        load_constraint_source(out, extraction=extraction, account_id=11)


def test_missing_clock_operand_becomes_unknown_without_changing_legacy_dossier(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    clock = dict(raw[2])
    clock["net_tick"] = 110
    clock["fields"] = {key: value for key, value in clock["fields"].items() if not key.endswith("m_bGamePaused")}
    raw.insert(8, clock)
    extraction = rewrite(path, raw)
    before = build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe")
    callback = []
    after = build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe", transition_sink=callback.append)
    assert before == after
    missing = next(r for r in callback if r["source_record_index"] == 9)
    assert missing["clock"]["paused"] is None
    assert 9 in missing["clock"]["evidence_records"]


def test_removed_steam_identity_revokes_binding_without_changing_legacy_dossier(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    removed = dict(raw[3])
    removed.update(net_tick=110, fields={}, full_snapshot=False, op_bits=2,
                   removed_fields=["m_vecPlayerData.0000.m_iPlayerSteamID"])
    raw.insert(8, removed)
    extraction = rewrite(path, raw)
    before = build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe")
    callback = []
    assert build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe", transition_sink=callback.append) == before
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    removed = next(r for r in observations(out) if r["transition_reason"] == "resource_identity_removed")
    assert removed["prefix_account_id"] is None and removed["hero"] is None


def test_future_final_roster_class_does_not_hide_earlier_declared_actor_prefix(tmp_path):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    earlier = observations(out)
    extraction.replay.heroes[0] = "CDOTA_Unit_Hero_Lina"
    write(path, extraction, out)
    assert observations(out) == earlier
    assert any(r["hero"] is not None for r in earlier)


def test_reader_line_limit_and_hardlink_alias(tmp_path):
    path, extraction = source(tmp_path)
    alias = tmp_path/"alias.jsonl"
    os.link(path, alias)
    with pytest.raises(ValueError, match="overwrite"):
        write(path, extraction, alias)
    alias.unlink()
    alias.write_bytes(b"x"*(4*1024*1024+1))
    with pytest.raises(ValueError, match="bounded reader"):
        inspect_constraint_source(alias)


@pytest.mark.parametrize("field, value", [
    ("coverage", "complete_constraint_truth_transitions_with_cue_and_pause"),
    ("projection_encoding", "arbitrary"),
    ("projection_fields", {"hero": ["enemy_position"]}),
    ("limitations", []),
    ("match_id", True),
    ("resource_slot", 10),
    ("replay_sha256", "invalid"),
])
def test_metadata_cannot_promote_or_change_finite_raw_source_contract(tmp_path, field, value):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    raw = rows(out)
    raw[0][field] = value
    reseal(out, raw)
    with pytest.raises(ValueError):
        inspect_constraint_source(out, extraction=extraction)


def test_resealed_future_source_clock_is_rejected(tmp_path):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    raw = rows(out)
    raw[1]["demo_tick"] = 2**32
    reseal(out, raw)
    with pytest.raises(ValueError, match="uint32"):
        inspect_constraint_source(out, extraction=extraction)


@pytest.mark.parametrize("mutation", ["manifest_match", "manifest_replay", "audit_match", "trace_sha"])
def test_writer_rejects_contradictory_source_identity_before_publication(tmp_path, mutation):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    original = out.read_bytes()
    if mutation == "manifest_match":
        extraction = replace(extraction, replay=replace(extraction.replay,
            manifest=replace(extraction.replay.manifest, match_id=8)))
    elif mutation == "manifest_replay":
        extraction = replace(extraction, replay=replace(extraction.replay,
            manifest=replace(extraction.replay.manifest, replay_hash="b"*64)))
    elif mutation == "audit_match":
        extraction.audit["match_id"] = 8
    else:
        extraction.audit["trace_sha256"] = "not-a-hash"
    with pytest.raises(ValueError):
        write(path, extraction, out)
    assert out.read_bytes() == original
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("field", ["counts", "transition_reasons", "subject_bindings", "projection_audit_counts"])
def test_footer_boolean_cannot_impersonate_exact_integer_count(tmp_path, field):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    raw = rows(out)
    counter = raw[-1][field]
    key = next(key for key in counter)
    counter[key] = True
    reseal(out, raw)
    with pytest.raises(ValueError, match="nonnegative exact integers"):
        inspect_constraint_source(out, extraction=extraction)


@pytest.mark.parametrize("field", ["cutoff_net_tick", "sampled_net_tick", "cutoff_policy"])
def test_each_raw_observation_has_an_exact_inclusive_network_cutoff(tmp_path, field):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    raw = rows(out)
    raw[1].pop(field)
    reseal(out, raw)
    with pytest.raises(ValueError, match="network cutoff"):
        inspect_constraint_source(out, extraction=extraction)


def test_boolean_hero_generation_cannot_impersonate_integer_mapping(tmp_path):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    raw = rows(out)
    full = next(r for r in raw if r.get("projection", {}).get("hero"))
    full["projection"]["hero"]["generation"] = True
    full["projection"]["primary_mapping"]["value"][1] = True
    reseal(out, raw)
    with pytest.raises(ValueError, match="exact uint types"):
        inspect_constraint_source(out, extraction=extraction)


@pytest.mark.parametrize("field", ["source_record_index", "net_tick"])
def test_future_receipt_leaf_in_resealed_delta_remains_rejected(tmp_path, field):
    path, extraction = source(tmp_path)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    raw = rows(out)
    delta = next(r for r in raw if "projection_changes" in r and r["source_record_index"] == 9)
    delta["projection_changes"].append({"op": "set", "path": ["hero", "fields", "m_flMana", field],
                                        "value": delta[field]+1})
    reseal(out, raw)
    with pytest.raises(ValueError, match="future"):
        inspect_constraint_source(out, extraction=extraction)


def test_removed_delta_parent_falls_back_to_surviving_ancestor():
    from dota_coach.ingest.constraint_source import _changed_receipt_subtrees
    state = {"hero": {"fields": {}}}
    parents = _changed_receipt_subtrees(state, [
        {"op": "remove", "path": ["hero", "fields", "m_flMana", "source_record_index"]},
        {"op": "remove", "path": ["hero", "fields", "m_flMana"]},
    ])
    assert parents == [state["hero"]["fields"]]


def resource_event(template, *, tick=110, generation=1, fields=None, full=False, op=2):
    event = json.loads(json.dumps(template))
    event.update(net_tick=tick, generation=generation, fields=fields or {}, full_snapshot=full,
                 op_bits=op, removed_fields=[])
    return event


def test_deleted_resource_revokes_account_and_own_projection_at_exact_prefix(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    raw.insert(8, resource_event(raw[3], op=20))
    extraction = rewrite(path, raw)
    before = build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe")
    callback = []
    assert build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe", transition_sink=callback.append) == before
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    cleared = next(r for r in observations(out) if r["transition_reason"] == "resource_entity_deleted")
    assert cleared["source_record_index"] == 9
    assert cleared["resource_steam_id"]["source_record_index"] == 9
    assert cleared["prefix_account_id"] is None and cleared["hero"] is None
    assert all(r["subject_binding"] == "prefix_account_unavailable_or_different" and r["hero"] is None
               for r in observations(out) if r["source_record_index"] >= 9)


def test_resource_generation_replacement_without_steam_revokes_old_binding(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    raw.insert(8, resource_event(raw[3], generation=2, full=True, op=1))
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    cleared = next(r for r in observations(out) if r["transition_reason"] == "resource_entity_replaced")
    assert cleared["source_record_index"] == 9
    assert cleared["resource_steam_id"]["value"] is None and cleared["hero"] is None
    assert all(r["prefix_account_id"] is None for r in observations(out) if r["source_record_index"] >= 9)


def test_new_generation_steam_rebinds_and_old_generation_updates_cannot_override(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    template = raw[3]
    raw[8:8] = [resource_event(template, generation=2, full=True, op=1),
                resource_event(template, generation=2, tick=115,
                               fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265739"}),
                resource_event(template, generation=1, tick=116,
                               fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265740"})]
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    observed = observations(out)
    assert next(r for r in observed if r["source_record_index"] == 9)["prefix_account_id"] is None
    rebound = next(r for r in observed if r["source_record_index"] == 10)
    assert rebound["prefix_account_id"] == 11 and rebound["hero"] is None
    assert rebound["resource_steam_id"]["source_record_index"] == 10
    assert not any(r["source_record_index"] == 11 for r in observed)
    assert all(r["prefix_account_id"] == 11 and r["resource_steam_id"]["source_record_index"] == 10
               for r in observed if r["source_record_index"] > 10)


def test_deleted_resource_late_delta_does_not_resurrect_binding(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    template = raw[3]
    raw[8:8] = [resource_event(template, op=20),
                resource_event(template, tick=115,
                               fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265739"})]
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    assert all(r["prefix_account_id"] is None and r["hero"] is None
               for r in observations(out) if r["source_record_index"] >= 9)


def test_replacement_baseline_with_steam_emits_once_and_binds_new_receipt(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    raw.insert(8, resource_event(raw[3], generation=2, full=True, op=1,
                               fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265739"}))
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    replacement, = [r for r in observations(out) if r["source_record_index"] == 9]
    assert replacement["transition_reason"] == "resource_entity_replaced"
    assert replacement["prefix_account_id"] == 11
    assert replacement["resource_steam_id"]["source_record_index"] == 9
    assert load_constraint_source(out, extraction=extraction, account_id=11)["source_verified"] is True


@pytest.mark.parametrize("account", [11, 12])
def test_replacement_steam_cannot_reuse_prior_resource_mapping(tmp_path, account):
    path, _ = source(tmp_path)
    raw = rows(path)
    raw.insert(8, resource_event(raw[3], generation=2, full=True, op=1,
                               fields={"m_vecPlayerData.0000.m_iPlayerSteamID": str(76561197960265728+account)}))
    extraction = rewrite(path, raw)
    before = build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe")
    callback = []
    assert build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe",
                               transition_sink=callback.append) == before
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out, account=account)
    replacement = next(r for r in observations(out) if r["source_record_index"] == 9)
    assert replacement["prefix_account_id"] == account
    assert replacement["primary_mapping"]["value"] is None
    assert replacement["primary_mapping"]["source_record_index"] == 9
    assert replacement["hero"] is None and replacement["inventory"] == []
    assert all(r["hero"] is None for r in observations(out) if r["source_record_index"] >= 9)


def test_explicit_new_mapping_after_replacement_rebinds_same_handle(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    renewal = dict(raw[6], net_tick=115)
    raw[8:8] = [resource_event(raw[3], generation=2, full=True, op=1,
                             fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265740",
                                     "m_vecPlayerTeamData.0000.m_hSelectedHero": str(1+(3 << 14))}), renewal]
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out, account=12)
    observed = observations(out)
    replacement = next(r for r in observed if r["source_record_index"] == 9)
    rebound = next(r for r in observed if r["source_record_index"] == 10)
    assert replacement["hero"] is None
    assert rebound["transition_reason"] == "primary_mapping_changed"
    assert rebound["hero"]["entity_index"] == 1
    assert rebound["hero"]["mapping_source_record_index"] == 10
    assert rebound["prefix_account_id"] == 12


def test_changed_or_removed_steam_revokes_mapping_until_new_receipt(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    changed = resource_event(raw[3], fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265740",
                                            "m_vecPlayerTeamData.0000.m_hSelectedHero": str(1+(3 << 14))})
    renewal = dict(raw[6], net_tick=115)
    removed = resource_event(raw[3], tick=116)
    removed["removed_fields"] = ["m_vecPlayerData.0000.m_iPlayerSteamID"]
    restored = resource_event(raw[3], tick=117,
                              fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265740"})
    raw[8:8] = [changed, renewal, removed, restored]
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out, account=12)
    observed = {r["source_record_index"]: r for r in observations(out)}
    assert observed[9]["prefix_account_id"] == 12 and observed[9]["hero"] is None
    assert observed[10]["hero"]["mapping_source_record_index"] == 10
    assert observed[11]["hero"] is None and observed[11]["primary_mapping"]["value"] is None
    assert observed[12]["prefix_account_id"] == 12 and observed[12]["hero"] is None


@pytest.mark.parametrize("delete", [False, True])
def test_retired_resource_full_baseline_cannot_reactivate_or_override(tmp_path, delete):
    path, _ = source(tmp_path)
    raw = rows(path)
    old = raw[3]
    inserted = [resource_event(old, generation=2, full=True, op=1,
                              fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265740"})]
    if delete:
        inserted.append(resource_event(old, generation=2, tick=111, op=20))
    inserted.append(resource_event(old, tick=115, full=True, op=1,
                                   fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265739"}))
    raw[8:8] = inserted
    extraction = rewrite(path, raw)
    before = build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe")
    callback = []
    assert build_action_states(path, extraction, resource_slot=0, actor="npc_dota_hero_axe",
                               transition_sink=callback.append) == before
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out, account=11)
    observed = observations(out)
    assert all(r["prefix_account_id"] != 11 and r["hero"] is None
               for r in observed if r["source_record_index"] >= 9)
    assert not any(r["source_record_index"] == 10+(1 if delete else 0) for r in observed)


@pytest.mark.parametrize("kind", ["replacement", "account_change"])
def test_fresh_cached_mapping_cannot_rebind_without_current_selected_hero_operand(tmp_path, kind):
    path, _ = source(tmp_path)
    raw = rows(path)
    change = resource_event(raw[3], generation=2 if kind == "replacement" else 1,
                            full=kind == "replacement", op=1 if kind == "replacement" else 2,
                            fields={"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265740"})
    raw[8:8] = [change, dict(raw[6], net_tick=115)]
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out, account=12)
    assert all(r["hero"] is None and r["primary_mapping"]["value"] is None
               for r in observations(out) if r["source_record_index"] >= 9)


@pytest.mark.parametrize("operand", ["missing", "different_handle", "different_property", "old_resource"])
def test_mapping_receipt_requires_exact_current_resource_operand(tmp_path, operand):
    path, _ = source(tmp_path)
    raw = rows(path)
    if operand == "missing":
        raw[3]["fields"].pop("m_vecPlayerTeamData.0000.m_hSelectedHero")
    elif operand == "different_handle":
        raw[6]["selected_hero_handle"] = str(2+(3 << 14))
    elif operand == "different_property":
        raw[6]["mapping_property"] = "m_vecPlayerTeamData.0001.m_hSelectedHero"
    else:
        raw[6].update(source_entity_index=9, source_generation=2)
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    assert all(r["hero"] is None for r in observations(out))


@pytest.mark.parametrize("remove", [False, True])
def test_current_selected_hero_operand_change_or_removal_revokes_mapping(tmp_path, remove):
    path, _ = source(tmp_path)
    raw = rows(path)
    change = resource_event(raw[3], fields={} if remove else
                            {"m_vecPlayerTeamData.0000.m_hSelectedHero": str(2+(3 << 14))})
    if remove:
        change["removed_fields"] = ["m_vecPlayerTeamData.0000.m_hSelectedHero"]
    raw.insert(8, change)
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    revoked = next(r for r in observations(out) if r["source_record_index"] == 9)
    assert revoked["hero"] is None and revoked["primary_mapping"]["value"] is None
    assert all(r["hero"] is None for r in observations(out) if r["source_record_index"] >= 9)


def test_full_current_resource_baseline_omitted_steam_revokes_account(tmp_path):
    path, _ = source(tmp_path)
    raw = rows(path)
    raw[8:8] = [resource_event(raw[3], full=True, op=1,
                             fields={"m_vecPlayerTeamData.0000.m_hSelectedHero": str(1+(3 << 14))}),
                dict(raw[6], net_tick=115)]
    extraction = rewrite(path, raw)
    out = tmp_path/"constraints.jsonl"
    write(path, extraction, out)
    revoked = next(r for r in observations(out) if r["source_record_index"] == 9)
    assert revoked["prefix_account_id"] is None
    assert revoked["resource_steam_id"]["source_record_index"] == 9
    assert all(r["prefix_account_id"] is None and r["hero"] is None
               for r in observations(out) if r["source_record_index"] >= 9)
