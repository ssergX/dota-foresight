"""Own-state projections from raw replay prefixes, never a validated cast oracle.

Two observations per field preserve the previous network tick even when combat
delivery follows post-cast entity changes within the current tick. That ordering
is a conservative observation boundary, not a proven player decision timestamp.
Control bit interpretation and historical patch mechanics remain explicit gaps.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Callable

from dota_coach.decisions.batch import strict_json
from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.trace import TraceResult, _Clock, _integer, _number, _sha

SCHEMA = "foresight.action-states.v1"
STEAM_ACCOUNT_BASE = 76561197960265728
INVALID_HANDLE = 16777215
INDEX_MASK = (1 << 14)-1  # Manta v1.5.0 FindEntityByHandle, serial is remaining bits.
ITEM_ALIASES = {
    "CDOTA_Item_Black_King_Bar": "item_black_king_bar",
    "CDOTA_Item_BlinkDagger": "item_blink",
    "CDOTA_Item_ForceStaff": "item_force_staff",
    "CDOTA_Item_Manta": "item_manta",
    "CDOTA_Item_MantaStyle": "item_manta",
    "CDOTA_Item_Cyclone": "item_cyclone",
    "CDOTA_Item_WindWaker": "item_wind_waker",
    "CDOTA_Item_Ghost": "item_ghost",
    "CDOTA_Item_GlimmerCape": "item_glimmer_cape",
    "CDOTA_Item_Hurricane_Pike": "item_hurricane_pike",
    "CDOTA_Item_Sphere": "item_sphere",
    "CDOTA_Item_Lotus_Orb": "item_lotus_orb",
    "CDOTA_Item_AeonDisk": "item_aeon_disk",
}
DEFENSIVE_ITEMS = frozenset(ITEM_ALIASES.values())
HERO_FIELDS = ("m_iHealth", "m_iMaxHealth", "m_flMana", "m_flMaxMana", "m_lifeState",
               "m_iCurrentLevel", "m_nUnitState64", "m_nUnitState", "m_iPlayerID",
               "m_iIsControllableByPlayer64", "m_nPlayerOwnerID", "m_hOwnerEntity",
               "m_hOwnerNPC", "m_bCanUseAllItems", "m_iTeamNum")
ACTION_FIELDS = ("m_fCooldown", "m_flCooldownLength", "m_iManaCost", "m_iLevel",
                 "m_nAbilityCurrentCharges", "m_iCurrentCharges", "m_bRequiresCharges",
                 "m_bInAbilityPhase", "m_bActivated", "m_bItemEnabled", "m_bHidden",
                 "m_bFrozenCooldown", "m_bInIndefiniteCooldown", "m_flCastStartTime",
                 "m_flChannelStartTime", "m_flAbilityMuteDuration", "m_flEnableTime",
                 "m_iPlayerOwnerID", "m_hOwnerEntity", "m_bCanBeUsedOutOfInventory")


@dataclass(frozen=True)
class _Observation:
    value: object
    source_record_index: int
    net_tick: int
    wire_type: str | None = None


class _Versions:
    def __init__(self):
        self.latest: _Observation | None = None
        self.previous: _Observation | None = None

    def put(self, value, rid, tick, wire_type=None):
        if self.latest is not None and tick < self.latest.net_tick:
            raise ValueError("network ticks regressed within field history")
        if self.latest is not None and tick != self.latest.net_tick:
            self.previous = self.latest
        self.latest = _Observation(value, rid, tick, wire_type)

    def before(self, tick: int, strict: bool):
        if self.latest is None:
            return None
        if not strict or self.latest.net_tick < tick:
            return self.latest
        return self.previous if self.previous and self.previous.net_tick < tick else None


@dataclass
class _Entity:
    index: int
    generation: int
    class_name: str
    active: _Versions
    fields: dict[str, _Versions]


def _fact(field: _Versions | None, tick: int, strict: bool) -> dict:
    value = field.before(tick, strict) if field else None
    if value is None or value.value is None:
        return {"value": None, "status": "unknown", "source_record_index": value.source_record_index if value else None,
                "net_tick": value.net_tick if value else None, "wire_type": value.wire_type if value else None}
    return asdict(value) | {"status": "raw_observed"}


def _active(entity, tick, strict):
    state = entity.active.before(tick, strict) if entity else None
    return bool(state and state.value is True)


def _relation(handle):
    value = _integer(handle)
    if value is None or value < 0:
        return None
    return value & INDEX_MASK, value >> 14


def _condition(code, value, evidence, limitation=None):
    return {"code": code, "value": value, "status": "unverified_candidate" if value is not None else "unknown",
            "evidence_record_indices": sorted({e for e in evidence if e is not None}), "limitation": limitation}


def unverified_cooldown_check(fields: dict, clock: dict, sampled_tick: int | None,
                              cutoff_record_index: int | None = None) -> dict:
    """Preserve competing arithmetic interpretations; neither establishes ready.

    In particular, a remaining duration is almost always below absolute engine
    time. That comparison cannot select the field's historical semantics. Legacy
    cached positive flags must be recomputed through this demotion as well.
    """
    def fact(key):
        raw = fields.get(key, {})
        value = {k: raw.get(k) for k in ('value', 'status', 'source_record_index', 'net_tick', 'wire_type')}
        rid = value['source_record_index']
        if rid is not None and (type(rid) is not int or rid < 0 or (
                cutoff_record_index is not None and rid >= cutoff_record_index)):
            raise ValueError('cooldown source must precede cutoff')
        return value
    cooldown, frozen, indefinite = (fact(k) for k in ('m_fCooldown', 'm_bFrozenCooldown', 'm_bInIndefiniteCooldown'))
    def known(value):
        return (value['status'] == 'raw_observed' and type(value['source_record_index']) is int
                and type(value['net_tick']) is int and value['net_tick'] >= 0)
    cd = _number(cooldown['value']) if known(cooldown) else None
    interval, pauses = _number(clock.get('tick_interval')), clock.get('paused_ticks')
    tick = clock.get('pause_start_tick') if clock.get('paused') is True else sampled_tick
    refs = clock.get('evidence_records', [])
    if not isinstance(refs, list) or any(type(r) is not int or r < 0 or (
            cutoff_record_index is not None and r >= cutoff_record_index) for r in refs):
        raise ValueError('cooldown clock evidence must precede cutoff')
    engine_time = None
    if (interval is not None and interval > 0 and type(pauses) is int and pauses >= 0
            and type(tick) is int and tick >= pauses and type(clock.get('paused')) is bool
            and clock.get('semantic_validation') == 'unverified' and refs):
        candidate_time = (tick - pauses) * interval
        if math.isfinite(candidate_time):
            engine_time = candidate_time
    result = _condition('raw_cooldown_end_not_after_clock', None,
        [f['source_record_index'] for f in (cooldown, frozen, indefinite)] + refs,
        'Cooldown field may be a remaining duration or an absolute end time; historical semantics are unverified. Neither arithmetic hypothesis grants readiness.')
    result.update(reason_codes=['cooldown_field_semantics_ambiguous_unverified',
                                'freeze_charges_and_activation_constraints_unverified'],
        chosen_interpretation=None, raw_cooldown_fact=cooldown,
        raw_constraint_facts={'frozen': frozen, 'indefinite': indefinite},
        interpretations=[{'interpretation': 'remaining_duration_seconds', 'status': 'unverified_hypothesis',
            'arithmetic_predicate': 'raw_value_not_above_zero',
            'arithmetic_comparison_value': cd <= 0 if cd is not None else None},
            {'interpretation': 'absolute_engine_end_time_seconds', 'status': 'unverified_hypothesis',
             'arithmetic_predicate': 'raw_value_not_after_engine_clock', 'engine_clock_seconds': engine_time,
             'arithmetic_comparison_value': cd <= engine_time if cd is not None and engine_time is not None else None}],
        feasibility='unknown')
    return result


def _checks(hero, item, clock, tick, cutoff_record_index=None):
    hf, fields = hero.get("fields", {}), item.get("fields", {})
    def value(mapping, key):
        return mapping.get(key, {}).get("value")
    def refs(mapping, *keys):
        return [mapping.get(k, {}).get("source_record_index") for k in keys]
    mana, cost = _number(value(hf, "m_flMana")), _number(value(fields, "m_iManaCost"))
    return [
        _condition("exact_inventory_handle_resolves", True if item.get("relation_status") == "resolved_exact_handle" else None,
                   [item.get("handle_fact", {}).get("source_record_index")], "Handle linkage is not an item usability verdict."),
        _condition("raw_mana_at_least_reported_cost", mana >= cost if mana is not None and cost is not None and min(mana, cost) >= 0 else None,
                   refs(hf, "m_flMana")+refs(fields, "m_iManaCost"), "Dynamic cost and decoder semantics are not independently validated."),
        unverified_cooldown_check(fields, clock, tick, cutoff_record_index),
        _condition("control_allows_activation", None, refs(hf, "m_nUnitState64", "m_nUnitState"),
                   "Raw control bits are preserved; bit semantics, exception rules and player agency are unverified."),
        _condition("inventory_slot_allows_activation", None, [item.get("handle_fact", {}).get("source_record_index")],
                   "Raw slot index is retained; backpack/stash/neutral and swap delays require historical mechanics."),
        _condition("target_and_command_constraints_satisfied", None, [], "Command log and target/selection constraints are unavailable."),
    ]


def build_action_states(trace_path: str | Path, extraction: TraceResult, *, resource_slot: int,
                        actor: str, action_ids: tuple[str, ...] | None = None,
                        include_timeline: bool = True,
                        transition_sink: Callable[[dict], None] | None = None) -> dict:
    """Build a source-bound own-only dossier, with no feasibility promotion.

    Default captures this actor's logged defensive-item activations. It is not an
    opportunity census; timeline samples are inventory observations, not choices.
    """
    if type(resource_slot) is not int or not 0 <= resource_slot <= 9 or not isinstance(actor, str) or not actor:
        raise ValueError("explicit resource slot and canonical actor required")
    class_name = extraction.replay.heroes.get(resource_slot, "")
    class_key = class_name.removeprefix("CDOTA_Unit_Hero_").replace("_", "").lower()
    actor_key = actor.removeprefix("npc_dota_hero_").replace("_", "").lower()
    transition_only = transition_sink is not None and action_ids == () and include_timeline is False
    if not actor.startswith("npc_dota_hero_") or not actor_key or (not transition_only and (
            not class_name.startswith("CDOTA_Unit_Hero_") or class_key != actor_key)):
        raise ValueError("actor and resource primary-hero identity do not match")
    available = {a.action_id: a for a in extraction.actions}
    if action_ids is None:
        selected = [a for a in extraction.actions if a.actor == actor and a.kind == "item" and a.ability_or_item in DEFENSIVE_ITEMS]
    else:
        if not isinstance(action_ids, tuple) or len(set(action_ids)) != len(action_ids) or any(i not in available for i in action_ids):
            raise ValueError("distinct action IDs in the bound extraction required")
        selected = [available[i] for i in action_ids]
        if any(a.actor != actor for a in selected):
            raise ValueError("action actor differs from requested own perspective")
    selected_by_record = {a.event_record_index: a for a in selected}
    timeline_tasks = {p["prefix_record_index"]+1: p for p in extraction.audit.get("timing_provenance", [])} if include_timeline else {}
    all_tasks = sorted(set(selected_by_record) | set(timeline_tasks))
    if len(selected_by_record) != len(selected):
        raise ValueError("duplicate action delivery record")
    entities: dict[tuple[int, int], _Entity] = {}
    mapping = _Versions()
    resource_identity: dict[str, _Versions] = {}
    clock_fields: dict[str, _Versions] = {}
    transition_resource_identity: dict[str, _Versions] = {}
    transition_resource_entity_identity: tuple[int, int] | None = None
    transition_retired_resource_identities: set[tuple[int, int]] = set()
    transition_mapping = _Versions()
    transition_selected_hero = _Versions()
    selected_hero_property = f"m_vecPlayerTeamData.{resource_slot:04d}.m_hSelectedHero"
    transition_clock_fields: dict[str, _Versions] = {}
    interval = _Versions()
    snapshots, timeline, audit_counts = [], [], Counter()
    raw_digest = hashlib.sha256()
    last_tick = None
    previous_tick = None
    task_index = 0
    metadata = footer = None
    transition_last_record = 0
    entity_prefixes = (b'"class":"CDOTA_Unit_Hero_', b'"class":"CDOTA_Item', b'"class":"CDOTA_Ability', b'"class":"CDOTA_PlayerResource"')

    def clock_at(tick, strict, *, fields=None):
        itv = _fact(interval, tick, strict)
        raw = {k: _fact(v, tick, strict) for k, v in (clock_fields if fields is None else fields).items()}
        def val(k):
            return raw.get("m_pGameRules."+k, {}).get("value")
        return {"tick_interval": _number(itv["value"]), "start_time": _number(val("m_flGameStartTime")),
                "paused_ticks": _integer(val("m_nTotalPausedTicks")), "paused": val("m_bGamePaused"),
                "pause_start_tick": _integer(val("m_nPauseStartTick")),
                "evidence_records": sorted({v["source_record_index"] for v in [itv]+list(raw.values()) if v["source_record_index"] is not None}),
                "semantic_validation": "unverified"}

    def capture(cutoff_rid, tick, strict, compact=False, raw_only=False):
        mapped = (transition_mapping if raw_only else mapping).before(tick, strict)
        own = entities.get(mapped.value) if mapped else None
        if not _active(own, tick, strict):
            return {"cutoff_record_index": cutoff_rid, "hero": None, "inventory": [], "abilities": [],
                    "reason_codes": ["primary_hero_identity_unavailable_at_cutoff"], "feasibility": "unknown"}
        hero = {"entity_index": own.index, "generation": own.generation, "class": own.class_name,
                "mapping_source_record_index": mapped.source_record_index,
                "fields": {k: _fact(own.fields.get(k), tick, strict) for k in
                           ("m_iHealth", "m_flMana", "m_lifeState", "m_nUnitState64") if compact}}
        if not compact:
            hero["fields"] = {k: _fact(own.fields.get(k), tick, strict) for k in HERO_FIELDS}
        inv, abilities = [], []
        for key, version in sorted(own.fields.items()):
            is_item, is_ability = key.startswith("m_hItems."), key.startswith("m_vecAbilities.")
            if not is_item and not is_ability:
                continue
            fact = _fact(version, tick, strict)
            handle = _integer(fact["value"])
            if handle == INVALID_HANDLE:
                continue  # Explicit empty slot; no item entity to project.
            relation = _relation(handle)
            linked = entities.get(relation) if relation is not None else None
            resolved = linked is not None and _active(linked, tick, strict)
            if compact and (not is_item or not resolved or linked.class_name not in ITEM_ALIASES):
                continue
            record = {"slot": int(key.rsplit(".", 1)[1]), "handle": str(handle) if handle is not None else None,
                "handle_fact": fact, "relation_status": "resolved_exact_handle" if resolved else "unresolved_handle",
                "entity_index": relation[0] if relation else None, "generation": relation[1] if relation else None,
                "class": linked.class_name if resolved else None,
                "item_id": ITEM_ALIASES.get(linked.class_name) if resolved and is_item else None,
                "identity_method": "exact_class_alias/unverified" if resolved and is_item and linked.class_name in ITEM_ALIASES else "raw_entity_class",
                "fields": {k: _fact(linked.fields.get(k), tick, strict) for k in
                           (("m_fCooldown", "m_iManaCost", "m_bFrozenCooldown", "m_bInIndefiniteCooldown",
                             "m_bRequiresCharges", "m_iCurrentCharges") if compact else ACTION_FIELDS)} if resolved else {}}
            (inv if is_item else abilities).append(record)
        clk = clock_at(tick, strict)
        sampled_tick = previous_tick if strict else tick
        if not compact and not raw_only:
            for item in inv:
                item["checks"] = _checks(hero, item, clk, sampled_tick if sampled_tick is not None else tick, cutoff_rid)
        return {"cutoff_record_index": cutoff_rid, "cutoff_net_tick": tick,
                "sampled_net_tick": sampled_tick, "cutoff_policy": "strict_previous_network_tick" if strict else "prefix_record_inclusive",
                "hero": hero, "inventory": inv, "abilities": abilities, "clock": clk,
                "feasibility": "unknown", "reason_codes": ["historical_patch_mechanics_unverified",
                "control_bit_semantics_unverified", "callback_order_not_simulation_order",
                "command_constraints_and_subject_attention_unavailable"]}

    def linked_to_primary(identity, tick):
        mapped = transition_mapping.before(tick, False)
        own = entities.get(mapped.value) if mapped else None
        if mapped and identity == mapped.value:
            return True
        return bool(own and any(_relation(v.latest.value) == identity for k, v in own.fields.items()
                               if k.startswith(("m_hItems.", "m_vecAbilities.")) and v.latest))

    def emit_transition(rec, rid, tick, reason):
        if transition_sink is None:
            return
        # This identity receipt is evaluated now, never from the final resource
        # identity used in the separate action-state dossier.
        steam_fact = _fact(transition_resource_identity.get("steam_id"), tick, False)
        steam_number = _integer(steam_fact["value"])
        account = steam_number-STEAM_ACCOUNT_BASE if steam_number is not None and STEAM_ACCOUNT_BASE < steam_number <= STEAM_ACCOUNT_BASE+0xffffffff else None
        projected = capture(rid+1, tick, False, raw_only=True)
        if projected.get("hero") and (not projected["hero"]["class"].startswith("CDOTA_Unit_Hero_") or
                projected["hero"]["class"].removeprefix("CDOTA_Unit_Hero_").replace("_", "").lower() != actor_key):
            projected.update(hero=None, inventory=[], abilities=[],
                             reason_codes=["mapped_hero_class_differs_from_declared_actor"])
        # Unknown hero identity does not erase the clock and mapping receipts.
        projected["clock"] = clock_at(tick, False, fields=transition_clock_fields)
        projected.update(source_record_index=rid, net_tick=tick,
                         demo_tick=rec.get("demo_tick"), sequence_in_tick=rec.get("sequence_in_tick"),
                         source_kind=rec["t"], transition_reason=reason,
                         primary_mapping=_fact(transition_mapping, tick, False),
                         resource_steam_id=steam_fact, prefix_account_id=account)
        transition_sink(projected)

    with Path(trace_path).open("rb") as stream:
        for raw in stream:
            raw_digest.update(raw)
            if not raw.strip():
                continue
            # Go's compact records have predictable scalar keys. All retained
            # records are JSON-decoded; whole-source hash is checked at the end.
            rid_match = re.search(rb'"record_index"\s*:\s*(\d+)', raw)
            tick_match = re.search(rb'"net_tick"\s*:\s*(\d+)', raw)
            if rid_match is None or tick_match is None:
                raise ValueError("trace record identity/tick unavailable")
            rid, tick = int(rid_match.group(1)), int(tick_match.group(1))
            # Footer counts contain a nested `net_tick` count before the top-level
            # tick in Go's sorted JSON. Read this record structurally.
            if b'"trace_end"' in raw:
                footer_record = strict_json(raw.decode("utf-8-sig"))
                if footer_record.get("t") == "trace_end":
                    rid, tick = footer_record["record_index"], footer_record["net_tick"]
            if transition_sink is not None:
                if footer is not None or rid != transition_last_record+1:
                    raise ValueError("complete consecutive source records required for transition projection")
                transition_last_record = rid
            prior_record_tick = last_tick
            if last_tick is not None and tick < last_tick:
                raise ValueError("network tick regression prevents prefix projection")
            if tick != last_tick:
                previous_tick, last_tick = last_tick, tick
            while task_index < len(all_tasks) and all_tasks[task_index] <= rid:
                task = all_tasks[task_index]
                if task in selected_by_record:
                    if task != rid:
                        raise ValueError("selected event record absent from source trace")
                    action = selected_by_record[task]
                    snap = capture(task, tick, True)
                    snap.update(action_id=action.action_id, event_record_index=task,
                                event_game_time=action.game_time, event_net_tick=tick,
                                logged_action=action.ability_or_item, actor=actor,
                                temporal_relation="previous_tick_before_combat_delivery_not_resolved_choice")
                    snapshots.append(snap)
                if task in timeline_tasks:
                    proof = timeline_tasks[task]
                    snap = capture(task, prior_record_tick if prior_record_tick is not None else tick, False, True)
                    # Every retained observation came from a processed prefix;
                    # exact game time uses the original extraction provenance.
                    snap.update(game_time=proof["frame_time"], prefix_record_index=task-1,
                                discovery_status="inventory_samples_not_opportunities")
                    snap.pop("abilities", None)
                    timeline.append(snap)
                task_index += 1
            compact_raw = b'"t":"' in raw
            decoded = None if compact_raw else strict_json(raw.decode("utf-8-sig"))
            is_entity = b'"t":"entity"' in raw if compact_raw else decoded.get("t") == "entity"
            projected_entity = any(prefix in raw for prefix in entity_prefixes) if compact_raw else decoded.get("class", "").startswith(("CDOTA_Unit_Hero_", "CDOTA_Item", "CDOTA_Ability", "CDOTA_PlayerResource"))
            if is_entity and not projected_entity:
                continue
            allowed_kind = any(b'"t":"'+k+b'"' in raw for k in (b"meta", b"trace_end", b"clock", b"server_info", b"player_mapping")) if compact_raw else decoded.get("t") in ("meta", "trace_end", "clock", "server_info", "player_mapping")
            if not is_entity and not allowed_kind:
                continue
            rec = decoded if decoded is not None else strict_json(raw.decode("utf-8-sig"))
            kind = rec["t"]
            audit_counts[kind] += 1
            if kind == "meta":
                if metadata is not None or rec.get("schema_version") != "replay-trace.v3":
                    raise ValueError("source trace metadata mismatch")
                metadata = rec
            elif kind == "trace_end":
                footer = rec
            elif kind == "server_info":
                value = rec.get("data", {}).get("tick_interval")
                changed = interval.latest is None or interval.latest.value != value
                interval.put(value, rid, tick)
                if changed:
                    emit_transition(rec, rid, tick, "clock_interval_observation_changed")
            elif kind == "clock":
                changed = False
                for key, value in rec.get("fields", {}).items():
                    if key.endswith(("m_flGameStartTime", "m_nTotalPausedTicks", "m_bGamePaused", "m_nPauseStartTick")):
                        version = clock_fields.setdefault(key, _Versions())
                        changed |= version.latest is None or version.latest.value != value
                        version.put(value, rid, tick)
                        if transition_sink is not None:
                            transition_clock_fields.setdefault(key, _Versions()).put(value, rid, tick)
                if transition_sink is not None:
                    # Trace clock records are complete projections, not entity
                    # deltas. Missing previously observed operands mean unknown.
                    removed = set(rec.get("removed_fields", [])) | (set(transition_clock_fields)-set(rec.get("fields", {})))
                    for key in removed:
                        if key in transition_clock_fields and transition_clock_fields[key].latest.value is not None:
                            transition_clock_fields[key].put(None, rid, tick)
                            changed = True
                if changed:
                    emit_transition(rec, rid, tick, "clock_operand_observation_changed")
            elif kind == "player_mapping" and rec.get("resource_slot") == resource_slot:
                identity = (rec.get("entity_index"), rec.get("generation")) if rec.get("status") == "resolved_handle" else None
                mapping.put(identity, rid, tick)
                if transition_sink is not None:
                    # A receipt from a revoked resource lifetime cannot be
                    # carried into its replacement, even for the same handle.
                    current_resource = entities.get(transition_resource_entity_identity)
                    resource_active = _active(current_resource, tick, False)
                    source_identity = (rec.get("source_entity_index"), rec.get("source_generation"))
                    if source_identity != (None, None) and source_identity != transition_resource_entity_identity:
                        resource_active = False
                    selected = transition_selected_hero.before(tick, False)
                    selected_handle = _integer(selected.value) if selected else None
                    # The Go mapping emitter has a global handle cache. Even a
                    # fresh mapping callback must match the selected-hero
                    # operand observed in the current resource lifetime.
                    handle_matches = (selected_handle is not None and selected_handle != INVALID_HANDLE
                                      and rec.get("mapping_property") == selected_hero_property
                                      and _integer(rec.get("selected_hero_handle")) == selected_handle
                                      and _relation(selected_handle) == identity)
                    callback_identity = identity if resource_active and handle_matches else None
                    changed = transition_mapping.latest is None or transition_mapping.latest.value != callback_identity
                    transition_mapping.put(callback_identity, rid, tick)
                    if changed:
                        emit_transition(rec, rid, tick, "primary_mapping_changed")
            elif kind == "entity":
                identity = (rec["entity_index"], rec["generation"])
                entity = entities.get(identity)
                relevant = transition_sink is not None and linked_to_primary(identity, tick)
                if rec["op_bits"] & 4:
                    changed = entity is None or entity.active.latest is None or entity.active.latest.value is not False
                    if entity:
                        entity.active.put(False, rid, tick)
                    resource_deleted = transition_sink is not None and identity == transition_resource_entity_identity
                    if resource_deleted:
                        transition_resource_identity.setdefault("steam_id", _Versions()).put(None, rid, tick)
                        transition_mapping.put(None, rid, tick)
                        transition_selected_hero.put(None, rid, tick)
                        transition_retired_resource_identities.add(identity)
                        transition_resource_entity_identity = None
                        emit_transition(rec, rid, tick, "resource_entity_deleted")
                    elif relevant and changed:
                        emit_transition(rec, rid, tick, "linked_entity_deleted")
                    continue
                changed = entity is None
                if entity is None:
                    if not rec.get("full_snapshot"):
                        audit_counts["delta_without_baseline"] += 1
                        if relevant:
                            emit_transition(rec, rid, tick, "linked_delta_without_baseline")
                        continue
                    entity = _Entity(*identity, rec["class"], _Versions(), {})
                    entity.active.put(True, rid, tick)
                    entities[identity] = entity
                if entity.class_name == "CDOTA_PlayerResource":
                    resource_reason = None
                    if (transition_sink is not None and rec.get("full_snapshot")
                            and identity != transition_resource_entity_identity
                            and identity not in transition_retired_resource_identities):
                        replaced = transition_resource_entity_identity is not None
                        if replaced:
                            transition_retired_resource_identities.add(transition_resource_entity_identity)
                        transition_resource_entity_identity = identity
                        transition_resource_identity.setdefault("steam_id", _Versions()).put(None, rid, tick)
                        transition_mapping.put(None, rid, tick)
                        transition_selected_hero.put(None, rid, tick)
                        if replaced:
                            resource_reason = "resource_entity_replaced"
                    resource_current = (transition_sink is not None and identity == transition_resource_entity_identity
                                        and _active(entity, tick, False))
                    steam_property = f"m_vecPlayerData.{resource_slot:04d}.m_iPlayerSteamID"
                    if resource_current and rec.get("full_snapshot") and steam_property not in rec["fields"]:
                        steam_version = transition_resource_identity.get("steam_id")
                        if steam_version and steam_version.latest and steam_version.latest.value is not None:
                            transition_resource_identity["steam_id"].put(None, rid, tick)
                            transition_mapping.put(None, rid, tick)
                            transition_selected_hero.put(None, rid, tick)
                            resource_reason = resource_reason or "resource_identity_removed"
                    if resource_current and (steam_property in rec["fields"] or steam_property in rec.get("removed_fields", [])):
                        steam_version = transition_resource_identity.get("steam_id")
                        prior_steam = steam_version.latest.value if steam_version and steam_version.latest else None
                        next_steam = rec["fields"].get(steam_property)
                        if steam_property in rec.get("removed_fields", []) or prior_steam != next_steam:
                            # Do this before processing fields, independent of
                            # their JSON order. A selected handle from the prior
                            # account cannot certify a new account's mapping.
                            transition_selected_hero.put(None, rid, tick)
                    for key, value in rec["fields"].items():
                        if key == f"m_vecPlayerData.{resource_slot:04d}.m_iPlayerSteamID":
                            version = resource_identity.setdefault("steam_id", _Versions())
                            version.put(value, rid, tick)
                            if resource_current:
                                transition_version = transition_resource_identity.setdefault("steam_id", _Versions())
                                identity_changed = transition_version.latest is None or transition_version.latest.value != value
                                transition_version.put(value, rid, tick)
                                if identity_changed:
                                    transition_mapping.put(None, rid, tick)
                                    resource_reason = resource_reason or "resource_identity_changed"
                        if resource_current and key == selected_hero_property:
                            selected_changed = (transition_selected_hero.latest is None
                                                or transition_selected_hero.latest.value != value)
                            transition_selected_hero.put(value, rid, tick)
                            if selected_changed:
                                transition_mapping.put(None, rid, tick)
                                resource_reason = resource_reason or "resource_selected_hero_changed"
                    if resource_current and f"m_vecPlayerData.{resource_slot:04d}.m_iPlayerSteamID" in rec.get("removed_fields", []):
                        transition_resource_identity.setdefault("steam_id", _Versions()).put(None, rid, tick)
                        transition_mapping.put(None, rid, tick)
                        resource_reason = "resource_identity_removed"
                    if resource_current and (selected_hero_property in rec.get("removed_fields", [])
                                             or (rec.get("full_snapshot") and selected_hero_property not in rec["fields"])):
                        if transition_selected_hero.latest and transition_selected_hero.latest.value is not None:
                            transition_selected_hero.put(None, rid, tick)
                            transition_mapping.put(None, rid, tick)
                            resource_reason = resource_reason or "resource_selected_hero_removed"
                    if resource_reason:
                        emit_transition(rec, rid, tick, resource_reason)
                for key, value in rec["fields"].items():
                    if key in HERO_FIELDS or key in ACTION_FIELDS or key.startswith(("m_hItems.", "m_vecAbilities.")):
                        version = entity.fields.setdefault(key, _Versions())
                        wire_type = rec.get("field_types", {}).get(key)
                        changed |= version.latest is None or version.latest.value != value or version.latest.wire_type != wire_type
                        version.put(value, rid, tick, wire_type)
                for key in rec.get("removed_fields", []):
                    if key in entity.fields:
                        changed |= entity.fields[key].latest.value is not None
                        entity.fields[key].put(None, rid, tick)
                if relevant and changed:
                    emit_transition(rec, rid, tick, "own_or_linked_operand_observation_changed")
    if metadata is None or footer is None or footer.get("parser_completed") is not True:
        raise ValueError("complete source trace required")
    if raw_digest.hexdigest() != extraction.audit["trace_sha256"] or metadata.get("replay_sha256") != extraction.audit["replay_sha256"]:
        raise ValueError("own-state projection source differs from extraction")
    if task_index < len(all_tasks) and all_tasks[task_index] == footer["record_index"]+1 and all_tasks[task_index] in timeline_tasks:
        task = all_tasks[task_index]
        proof = timeline_tasks[task]
        snap = capture(task, last_tick, False, True)
        snap.update(game_time=proof["frame_time"], prefix_record_index=task-1,
                    discovery_status="inventory_samples_not_opportunities")
        snap.pop("abilities", None)
        timeline.append(snap)
        task_index += 1
    if task_index != len(all_tasks):
        raise ValueError("requested cutoff is beyond source trace")
    steam = resource_identity.get("steam_id")
    steam_fact = _fact(steam, last_tick, False)
    steam_number = _integer(steam_fact["value"])
    account = steam_number-STEAM_ACCOUNT_BASE if steam_number is not None and STEAM_ACCOUNT_BASE < steam_number <= STEAM_ACCOUNT_BASE+0xffffffff else None
    payload = {"schema_version": SCHEMA, "match_id": extraction.replay.match_id,
               "resource_slot": resource_slot, "actor": actor, "account_id_verified_by_resource": account,
               "account_link_validation": "arithmetic_resource_link_not_client_validated", "resource_steam_id": steam_fact,
               "replay_sha256": extraction.audit["replay_sha256"], "trace_sha256": extraction.audit["trace_sha256"],
               "source_extraction_hash": content_hash(asdict(extraction)), "validation": "unverified",
               "snapshots": snapshots, "timeline": timeline, "action_selection": "explicit_ids" if action_ids is not None else "logged_defensive_item_activations",
               "opportunity_coverage": None, "audit_counts": dict(audit_counts),
               "limitations": ["own_state_only_no_hidden_enemy_fields", "field_values_and_class_aliases_unverified",
                "combat_delivery_not_decision_boundary", "timeline_is_not_available_action_opportunity_census",
                "unitstate_bits_not_decoded_without_patch_review", "no_current_catalog_used_as_historical_mechanics"]}
    payload["payload_sha256"] = content_hash(payload)
    return payload


def save_action_states(payload: dict, path: str | Path) -> None:
    validate_action_states(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")


def validate_action_states(payload: dict, extraction: TraceResult | None = None) -> None:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA or payload.get("validation") != "unverified":
        raise ValueError("unsupported or self-promoted own-state artifact")
    _sha(payload.get("payload_sha256"), "own-state payload hash")
    if content_hash({k: v for k, v in payload.items() if k != "payload_sha256"}) != payload["payload_sha256"]:
        raise ValueError("own-state payload hash mismatch")
    if extraction is not None:
        if payload["match_id"] != extraction.replay.match_id or any(payload[k] != extraction.audit[k] for k in ("trace_sha256", "replay_sha256")) or payload["source_extraction_hash"] != content_hash(asdict(extraction)):
            raise ValueError("own-state artifact bound to different extraction")
        lookup = {a.action_id: a for a in extraction.actions}
        for snap in payload["snapshots"]:
            action = lookup.get(snap.get("action_id"))
            if action is None or action.event_record_index != snap.get("event_record_index") or action.actor != payload["actor"]:
                raise ValueError("own-state action linkage mismatch")
    for snap in payload["snapshots"]+payload["timeline"]:
        if snap.get("feasibility") != "unknown":
            raise ValueError("unverified raw projection cannot grant cast feasibility")
        cutoff = snap.get("cutoff_record_index")
        if type(cutoff) is not int:
            raise ValueError("explicit prefix cutoff required")
        allowed = {"cutoff_record_index", "cutoff_net_tick", "sampled_net_tick", "cutoff_policy", "hero", "inventory",
                   "abilities", "clock", "feasibility", "reason_codes", "action_id", "event_record_index",
                   "event_game_time", "event_net_tick", "logged_action", "actor", "temporal_relation", "game_time",
                   "prefix_record_index", "discovery_status"}
        if set(snap) - allowed:
            raise ValueError("unexpected own-state field; world payload forbidden")
        hero = snap.get("hero")
        if hero is not None and set(hero.get("fields", {})) - set(HERO_FIELDS):
            raise ValueError("hero projection contains non-allowlisted fields")
        for item in snap.get("inventory", [])+snap.get("abilities", []):
            if set(item.get("fields", {}))-set(ACTION_FIELDS):
                raise ValueError("linked entity contains non-allowlisted fields")
            if item.get("relation_status") == "resolved_exact_handle" and _relation(item.get("handle")) != (item.get("entity_index"), item.get("generation")):
                raise ValueError("linked entity does not match complete inventory handle")
            for condition in item.get("checks", []):
                if condition.get("status") not in ("unknown", "unverified_candidate") or type(condition.get("value")) not in (bool, type(None)):
                    raise ValueError("raw conditions cannot promote themselves to validation")
        def check(value):
            if isinstance(value, dict):
                rid = value.get("source_record_index")
                if rid is not None and (type(rid) is not int or rid >= cutoff):
                    raise ValueError("future source observation in own-state projection")
                for child in value.values():
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
        check(snap)


def load_action_states(path: str | Path, *, extraction: TraceResult | None = None) -> dict:
    payload = strict_json(Path(path).read_text(encoding="utf-8-sig"))
    validate_action_states(payload, extraction)
    return payload
