from collections import Counter
from dataclasses import asdict
import json

import pytest

from dota_coach.ingest.trace import _Clock, parse_trace, save_trace_result, load_trace_result, enrich_trace_names


def clock(start=10, end=0):
    return {"m_pGameRules.m_flGameStartTime": start,
            "m_pGameRules.m_flGameEndTime": end,
            "m_pGameRules.m_nTotalPausedTicks": 0,
            "m_pGameRules.m_nPauseStartTick": 0,
            "m_pGameRules.m_bGamePaused": False}


def write_trace(path, events, *, match=7, mutate=None):
    rows = [{"t": "meta", "schema_version": "replay-trace.v3", "replay_sha256": "a"*64,
             "extractor_version": "test"}] + events + [
             {"t": "file_info", "net_tick": 150, "data": {"game_info": {"dota": {"match_id": str(match)}}}},
             {"t": "trace_end", "net_tick": 150, "parser_completed": True, "game_build": 1}]
    for i, row in enumerate(rows):
        row.update(record_index=i+1, demo_tick=i, sequence_in_tick=1)
        row.setdefault("net_tick", 100)
    rows[-1]["counts"] = dict(Counter(r["t"] for r in rows))
    if mutate:
        mutate(rows)
    path.write_text("".join(json.dumps(r)+"\n" for r in rows), encoding="utf-8")
    return path


def entity(index, tick, cn="CDOTA_Unit_Hero_Axe", fields=None, op=1):
    return {"t": "entity", "net_tick": tick, "entity_index": index, "generation": 3,
            "class": cn, "op_bits": op, "op": "Deleted+Left" if op & 4 else "Created+Entered",
            "full_snapshot": op == 1, "removed_fields": [], "fields": fields or {}, "field_types": {}}


def basic():
    return [{"t": "server_info", "data": {"tick_interval": 0.1}},
            {"t": "clock", "fields": clock()},
            entity(1, 100, fields={"m_iTeamNum": 2, "m_iHealth": 10, "m_iMaxHealth": 20,
                   "m_lifeState": 0, "m_hItems.0000": 16777215}),
            {"t": "player_mapping", "resource_slot": 0, "entity_index": 1,
             "generation": 3, "status": "resolved_handle"},
            {"t": "net_tick", "net_tick": 111}]


def test_server_interval_and_entity_deletion_do_not_leave_ghost_hero(tmp_path):
    events = basic() + [entity(1, 112, op=20), {"t": "net_tick", "net_tick": 140}]
    result = parse_trace(write_trace(tmp_path/"trace", events), 7)
    assert result.replay.frames[0].time == 0
    assert all(f.time < 1.2 for f in result.replay.frames)
    assert result.replay.manifest.replay_hash == "a"*64
    assert result.audit["embedded_match_id"] == 7
    assert not any("unsupported_trace_record" in w for w in result.audit["warnings"])


def test_real_string_table_shape_and_callback_names_are_prefix_scoped(tmp_path):
    events = basic() + [
        {"t": "string_table", "data": {"table_name": "CombatLogNames", "items": [{"str": "npc_dota_hero_axe"}, {"str": "item_blink"}]}},
        {"t": "combat_log", "data": {"type": "DOTA_COMBATLOG_ITEM", "attacker_name": 0, "inflictor_name": 1, "timestamp": 11.5}},
        {"t": "combat_log", "data": {"type": "DOTA_COMBATLOG_ABILITY", "attacker_name": 8, "inflictor_name": 9, "timestamp": 12},
         "resolved_names": {"attacker_name": "npc_dota_hero_axe", "inflictor_name": "axe_berserkers_call"},
         "name_resolution": "CombatLogNames_at_callback/v1"}]
    result = parse_trace(write_trace(tmp_path/"trace", events), 7)
    assert result.actions[0].ability_or_item == "item_blink"
    assert result.actions[0].game_time == 1.5
    assert result.actions[1].ability_or_item == "axe_berserkers_call"
    assert result.actions[1].raw_name_ids["inflictor_name"] == 9


def test_future_horn_only_updates_display_not_action_knowledge_time(tmp_path):
    events = [{"t": "server_info", "data": {"tick_interval": 0.1}},
              {"t": "clock", "fields": clock(start=0)},
              {"t": "combat_log", "data": {"type": "DOTA_COMBATLOG_ITEM", "timestamp": 9}},
              {"t": "clock", "fields": clock(start=10)}]
    result = parse_trace(write_trace(tmp_path/"trace", events), 7)
    action, = result.actions
    assert action.game_time is None and action.display_game_time == -1
    assert action.display_time_method == "retrospective_start_backfill/display_only"
    assert max(action.timing_evidence_records) < action.event_record_index


def test_pause_candidate_clock_freezes_and_does_not_double_subtract_combat_pause():
    c = _Clock(interval=.5, interval_record=1)
    fields = clock(start=5)
    fields["m_pGameRules.m_nTotalPausedTicks"] = 2
    c.observe(fields, 2)
    assert c.at_tick(20) == 4
    fields.update({"m_pGameRules.m_bGamePaused": True, "m_pGameRules.m_nPauseStartTick": 18})
    c.observe(fields, 3)
    assert c.at_tick(20) == c.at_tick(30) == 3
    assert c.event_time(9) == 4
    fields.update({"m_pGameRules.m_bGamePaused": False, "m_pGameRules.m_nTotalPausedTicks": 6})
    c.observe(fields, 4)
    assert c.at_tick(22) == 3


def test_postgame_frames_stop_at_observed_end(tmp_path):
    events = basic()+[{"t": "clock", "net_tick": 115, "fields": clock(end=11.5)},
                      {"t": "net_tick", "net_tick": 500}]
    result = parse_trace(write_trace(tmp_path/"trace", events), 7)
    assert result.replay.frames and max(f.time for f in result.replay.frames) <= 1.55


@pytest.mark.parametrize("change", [
    lambda rows: rows[-1].update(parser_completed=False),
    lambda rows: rows[-1]["counts"].update(entity=99),
    lambda rows: rows[2].update(record_index=100),
    lambda rows: rows[0].update(replay_sha256="invalid"),
])
def test_source_completion_and_counts_are_checked(tmp_path, change):
    with pytest.raises(ValueError):
        parse_trace(write_trace(tmp_path/"trace", basic(), mutate=change), 7)


def test_match_identity_and_expected_replay_hash_are_checked(tmp_path):
    trace = write_trace(tmp_path/"trace", basic(), match=8)
    with pytest.raises(ValueError, match="match ID"):
        parse_trace(trace, 7)
    with pytest.raises(ValueError, match="hash mismatch"):
        parse_trace(trace, 8, expected_replay_sha256="b"*64)


def test_cache_roundtrip_and_tampering_rejected(tmp_path):
    result = parse_trace(write_trace(tmp_path/"trace", basic()), 7)
    save_trace_result(result, tmp_path/"result.json")
    loaded = load_trace_result(tmp_path/"result.json")
    assert asdict(loaded.replay) == asdict(result.replay)
    payload = json.loads((tmp_path/"result.json").read_text())
    payload["audit"]["match_id"] = 999
    (tmp_path/"result.json").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="hash mismatch"):
        load_trace_result(tmp_path/"result.json")


def test_clock_audit_samples_are_changes_not_one_entry_per_tick(tmp_path):
    result = parse_trace(write_trace(tmp_path/"trace", basic()+[
        {"t": "clock", "net_tick": tick, "fields": clock()} for tick in range(120, 800)]), 7)
    assert len(result.audit["clock_samples"]) == 1
    assert all(not c.validation_refs and c.validation == "unverified" for c in result.replay.manifest.capabilities)


def test_name_sidecar_requires_same_replay_and_identical_combat_payload(tmp_path):
    action = {"t": "combat_log", "data": {"type": "DOTA_COMBATLOG_ITEM", "timestamp": 12,
              "attacker_name": 123, "inflictor_name": 124}}
    trace = write_trace(tmp_path/"trace", basic()+[action])
    source_rows = [json.loads(line) for line in trace.read_text().splitlines()]
    original = next(r for r in source_rows if r["t"] == "combat_log")
    rows = [{"t": "meta", "record_index": 1, "schema_version": "replay-combat-names.v1", "replay_sha256": "a"*64},
            original | {"record_index": 2, "resolved_names": {"attacker_name": "npc_dota_hero_axe", "inflictor_name": "item_blink"},
                        "name_resolution": "CombatLogNames_at_callback/v1"},
            {"t": "trace_end", "record_index": 3, "parser_completed": True,
             "counts": {"meta": 1, "combat_log": 1, "trace_end": 1}}]
    names = tmp_path/"names"
    names.write_text("".join(json.dumps(r)+"\n" for r in rows))
    assert enrich_trace_names(trace, names, tmp_path/"enriched")["matched_combat_records"] == 1
    result = parse_trace(tmp_path/"enriched", 7)
    assert result.actions[0].ability_or_item == "item_blink"
    rows[1]["data"] = rows[1]["data"] | {"timestamp": 13}
    names.write_text("".join(json.dumps(r)+"\n" for r in rows))
    with pytest.raises(ValueError, match="payload"):
        enrich_trace_names(trace, names, tmp_path/"mismatched")
    assert not (tmp_path/"mismatched").exists()
