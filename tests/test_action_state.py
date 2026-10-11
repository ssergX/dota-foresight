from collections import Counter
import json

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.trace import parse_trace
from dota_coach.ingest.action_state import (
    build_action_states, load_action_states, save_action_states, validate_action_states,
    unverified_cooldown_check,
)


def source(tmp_path, *, new_serial=False, future_cooldown=500, actor="npc_dota_hero_axe"):
    def entity(idx, gen, cn, fields, *, tick=100, full=True, op=1):
        return {"t": "entity", "net_tick": tick, "entity_index": idx, "generation": gen,
                "class": cn, "fields": fields, "field_types": {}, "removed_fields": [],
                "full_snapshot": full, "op_bits": op, "op": "Created+Entered" if op == 1 else "Updated"}
    rows = [
        {"t": "meta", "schema_version": "replay-trace.v3", "replay_sha256": "a"*64},
        {"t": "server_info", "data": {"tick_interval": 0.1}},
        {"t": "clock", "fields": {"m_pGameRules.m_flGameStartTime": 10,
         "m_pGameRules.m_flGameEndTime": 0, "m_pGameRules.m_nTotalPausedTicks": 0,
         "m_pGameRules.m_nPauseStartTick": 0, "m_pGameRules.m_bGamePaused": False}},
        entity(9, 1, "CDOTA_PlayerResource", {"m_vecPlayerData.0000.m_iPlayerSteamID": "76561197960265739"}),
        entity(1, 3, "CDOTA_Unit_Hero_Axe", {"m_iTeamNum": 2, "m_iHealth": 100, "m_flMana": 300,
          "m_iMaxHealth": 100, "m_lifeState": 0, "m_hItems.0000": 2+(3<<14), "m_nUnitState64": "0"}),
        entity(2, 3, "CDOTA_Item_Black_King_Bar", {"m_fCooldown": 0, "m_iManaCost": 50,
          "m_bFrozenCooldown": False, "m_bInIndefiniteCooldown": False}),
        {"t": "player_mapping", "resource_slot": 0, "entity_index": 1, "generation": 3, "status": "resolved_handle"},
        {"t": "net_tick", "net_tick": 110},
    ]
    if new_serial:
        rows += [entity(2, 3, "CDOTA_Item_Black_King_Bar", {}, tick=110, op=20, full=False),
                 entity(2, 4, "CDOTA_Item_Black_King_Bar", {"m_fCooldown": 0}, tick=111)]
    rows += [entity(1, 3, "CDOTA_Unit_Hero_Axe", {"m_flMana": 250}, tick=120, full=False, op=2),
             entity(2, 3 if not new_serial else 4, "CDOTA_Item_Black_King_Bar", {"m_fCooldown": future_cooldown}, tick=120, full=False, op=2),
             {"t": "combat_log", "net_tick": 120, "data": {"type": "DOTA_COMBATLOG_ITEM", "timestamp": 12,
               "attacker_name": 1, "inflictor_name": 2}, "resolved_names": {"attacker_name": actor, "inflictor_name": "item_black_king_bar"},
              "name_resolution": "CombatLogNames_at_callback/v1"},
             {"t": "net_tick", "net_tick": 130},
             {"t": "file_info", "net_tick": 130, "data": {"game_info": {"dota": {"match_id": "7"}}}},
             {"t": "trace_end", "net_tick": 130, "parser_completed": True, "game_build": 1}]
    for i, r in enumerate(rows):
        r.update(record_index=i+1, demo_tick=i, sequence_in_tick=i)
        r.setdefault("net_tick", 100)
    rows[-1]["counts"] = dict(Counter(r["t"] for r in rows))
    path = tmp_path/"trace.jsonl"
    path.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":"))+"\n" for r in rows), encoding="utf-8")
    return path, parse_trace(path, 7)


def build(path, result):
    return build_action_states(path, result, resource_slot=0, actor="npc_dota_hero_axe")


def test_previous_tick_excludes_postcast_mana_and_cooldown_from_same_tick(tmp_path):
    path, result = source(tmp_path)
    payload = build(path, result)
    snap, = payload["snapshots"]
    assert snap["hero"]["fields"]["m_flMana"]["value"] == 300
    item, = snap["inventory"]
    assert item["fields"]["m_fCooldown"]["value"] == 0
    assert item["item_id"] == "item_black_king_bar"
    assert item["relation_status"] == "resolved_exact_handle"
    assert snap["feasibility"] == "unknown"
    assert next(c for c in item["checks"] if c["code"] == "control_allows_activation")["value"] is None
    assert payload["account_id_verified_by_resource"] == 11
    validate_action_states(payload, result)


def test_serial_reuse_cannot_attach_new_item_to_old_inventory_handle(tmp_path):
    path, result = source(tmp_path, new_serial=True)
    item, = build(path, result)["snapshots"][0]["inventory"]
    assert item["relation_status"] == "unresolved_handle"
    assert item["fields"] == {} and item["class"] is None


def test_future_same_tick_changes_do_not_change_prefix_projection(tmp_path):
    a_path, a_result = source(tmp_path, future_cooldown=500)
    a = build(a_path, a_result)["snapshots"]
    b_path, b_result = source(tmp_path, future_cooldown=999)
    assert build(b_path, b_result)["snapshots"] == a


def test_actor_resource_and_trace_binding_required(tmp_path):
    path, result = source(tmp_path)
    with pytest.raises(ValueError, match="actor and resource"):
        build_action_states(path, result, resource_slot=0, actor="npc_dota_hero_lina")
    path.write_text(path.read_text()+"\n")
    with pytest.raises(ValueError, match="source differs"):
        build(path, result)


def test_saved_artifact_rejects_tampering_and_source_prefix_injection(tmp_path):
    path, result = source(tmp_path)
    payload = build(path, result)
    save_action_states(payload, tmp_path/"states.json")
    assert load_action_states(tmp_path/"states.json", extraction=result) == payload
    snap = payload["snapshots"][0]
    snap["hero"]["fields"]["m_flMana"]["source_record_index"] = snap["cutoff_record_index"]
    payload["payload_sha256"] = content_hash({k: v for k, v in payload.items() if k != "payload_sha256"})
    with pytest.raises(ValueError, match="future source"):
        validate_action_states(payload)


def test_unknown_field_is_not_a_negative_control_flag(tmp_path):
    path, result = source(tmp_path)
    payload = build(path, result)
    fields = payload["snapshots"][0]["hero"]["fields"]
    assert fields["m_nUnitState"]["status"] == "unknown" and fields["m_nUnitState"]["value"] is None
    assert payload["timeline"] and all(s["discovery_status"] == "inventory_samples_not_opportunities" for s in payload["timeline"])


def test_fresh_decode_zero_cooldown_stays_unknown_until_semantics_review(tmp_path):
    path,result=source(tmp_path)
    payload=build(path,result)
    check=next(c for c in payload['snapshots'][0]['inventory'][0]['checks']
               if c['code']=='raw_cooldown_end_not_after_clock')
    assert check['value'] is None and check['status']=='unknown'
    assert check['raw_cooldown_fact']['value']==0
    assert [h['arithmetic_comparison_value'] for h in check['interpretations']]==[True,True]
    assert check['chosen_interpretation'] is None
    validate_action_states(payload,result)


@pytest.mark.parametrize('raw_cooldown',[0,94.9,93.90002])
def test_competing_cooldown_hypotheses_never_become_usability(raw_cooldown):
    fact=lambda v:{'value':v,'status':'raw_observed','source_record_index':2,'net_tick':3}
    c=unverified_cooldown_check({'m_fCooldown':fact(raw_cooldown),
        'm_bFrozenCooldown':fact(False),'m_bInIndefiniteCooldown':fact(False)},
        {'tick_interval':0.1,'paused_ticks':0,'paused':False,'semantic_validation':'unverified',
         'evidence_records':[1]},30000,10)
    assert c['status']=='unknown' and c['value'] is None and c['feasibility']=='unknown'
    assert [h['arithmetic_comparison_value'] for h in c['interpretations']]==[raw_cooldown<=0,True]
    assert all(h['status']=='unverified_hypothesis' for h in c['interpretations'])
