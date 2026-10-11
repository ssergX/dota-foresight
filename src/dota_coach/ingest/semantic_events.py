"""Observed replay markers and source-separated prefix projections.

Item use is not a channel, modifier removal is not an interruption/smoke break,
and an objective outcome is never an observation available to the player.
Combat callbacks are observation order, not verified simulation order.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import math
from pathlib import Path
from typing import Iterable

from dota_coach.decisions.batch import strict_json
from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.trace import TraceResult, _sha

SCHEMA = "foresight.semantic-events.v1"
TP_ITEMS = frozenset({"item_tpscroll", "item_travel_boots", "item_travel_boots_2"})
TP_MODIFIERS = frozenset({"modifier_teleporting"})
SMOKE_MODIFIERS = frozenset({"modifier_smoke_of_deceit"})
GAPS = ("tp_channel_start_unverified", "tp_end_reason_unknown", "tp_arrival_unknown",
        "smoke_removal_reason_unknown", "player_visibility_unknown",
        "command_attempt_and_opportunity_coverage_unknown", "historical_modifier_semantics_unverified")


def _finite(value):
    if type(value) not in (int, float):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except (OverflowError, ValueError):
        return None


def _text(value):
    return value if isinstance(value, str) and value and len(value) <= 512 else None


def _id(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} requires a nonnegative integer")
    return value


def _dataset_kind(value):
    if type(value) is not str or value not in ("replay", "synthetic", "unknown"):
        raise ValueError("dataset_kind requires replay, synthetic or unknown")
    return value


def _kind(kind, item):
    if kind == "item" and item in TP_ITEMS:
        return "tp_use_observed"
    if kind == "item" and item == "item_smoke_of_deceit":
        return "smoke_use_observed"
    if kind == "buyback":
        return "buyback_observed"
    if kind in ("modifier_add", "modifier_remove"):
        suffix = "applied" if kind == "modifier_add" else "removed"
        if item in TP_MODIFIERS:
            return f"tp_modifier_{suffix}"
        if item in SMOKE_MODIFIERS:
            return f"smoke_modifier_{suffix}"
    return None


def _event(*, event_id, kind, actor, target, item, time, raw_time, timestamp_source,
           domain, record, source_ref, flags=(), timing_refs=(), raw_details=None):
    missing = ["player_visibility", "choice_time", "feasibility"]
    if actor is None:
        missing.append("actor")
    if time is None:
        missing.append("game_time")
    if kind.startswith("tp_"):
        missing += ["channel_start", "channel_end", "interruption", "arrival", "destination"]
    if kind.startswith("smoke_"):
        missing += ["break_reason", "enemy_proximity", "recipient_coverage"]
    if "modifier_" in kind:
        flags = (*flags, "historical_modifier_semantics_unverified")
    return {"event_id": event_id, "kind": kind, "actor": actor, "target": target,
            "ability_or_item": item, "game_time": time, "raw_timestamp": raw_time,
            "timestamp_source": timestamp_source, "source_domain": domain,
            "source_record_index": record, "source_ref": source_ref,
            "perspective": "retrospective_world_observation", "validation": "unverified",
            "dataset_kind": "unknown",
            "unknown_fields": missing, "quality_flags": sorted(set(flags) | {"extraction_unverified"}),
            "timing_evidence_records": list(timing_refs), "raw_details": raw_details or {}}


def _trace_events(trace):
    match_id = trace.replay.match_id
    rows = []
    for action in trace.actions:
        kind = _kind(action.kind, action.ability_or_item)
        if kind is None:
            continue
        rid = _id(action.event_record_index, "trace record")
        refs = tuple(_id(r, "timing record") for r in action.timing_evidence_records)
        if any(r > rid for r in refs):
            raise ValueError("semantic event clock references future trace records")
        time = _finite(action.game_time)
        flags = action.quality_flags
        timestamp_source = action.timestamp_source
        if time is not None and (not refs or action.timestamp_source == "unavailable"):
            time = None
            timestamp_source = "unavailable"
            flags = (*flags, "prefix_clock_provenance_unavailable")
        rows.append(_event(event_id=action.action_id, kind=kind, actor=_text(action.actor),
            target=_text(action.target), item=action.ability_or_item, time=time,
            raw_time=_finite(action.raw_timestamp), timestamp_source=timestamp_source,
            domain="trace", record=rid, source_ref=f"trace:{match_id}:record:{rid}",
            flags=flags, timing_refs=refs))
    return rows


def _provider_events(raw, match_id):
    if raw.get("match_id") != match_id:
        raise ValueError("provider and replay match identity mismatch")
    players = raw.get("players", [])
    if not isinstance(players, list) or not isinstance(raw.get("objectives", []), list):
        raise ValueError("provider players/objectives must be arrays")
    slot_map = {}
    for player in players:
        if not isinstance(player, dict):
            raise ValueError("provider player must be an object")
        slot = player.get("player_slot")
        if type(slot) is not int or slot not in (*range(5), *range(128, 133)) or slot in slot_map:
            raise ValueError("provider player_slot missing, invalid or duplicated")
        slot_map[slot] = player
    rows = []
    def make(kind, data, ref, *, player=None):
        slot = data.get("player_slot")
        resolved = player if player is not None else slot_map.get(slot) if type(slot) is int else None
        # provider `slot` is a separate coordinate, never cast to player_slot.
        actor = f"provider_player_slot:{resolved['player_slot']}" if resolved else None
        details = {key: data[key] for key in ("type", "key", "unit", "player_slot", "team") if key in data}
        if resolved:
            details.update(account_id=resolved.get("account_id"), hero_id=resolved.get("hero_id"))
        return _event(event_id=ref, kind=kind, actor=actor, target=_text(data.get("key")),
            item=None, time=_finite(data.get("time")), raw_time=None,
            timestamp_source="provider.time/unverified_retrospective", domain="provider",
            record=None, source_ref=ref, flags=("not_player_prefix_evidence", "provider_parse_unverified"),
            raw_details=details)
    for index, objective in enumerate(raw.get("objectives", [])):
        if not isinstance(objective, dict):
            raise ValueError("provider objective must be an object")
        kind = {"building_kill": "building_destroyed_observed",
                "CHAT_MESSAGE_ROSHAN_KILL": "roshan_killed_observed"}.get(objective.get("type"))
        if kind:
            rows.append(make(kind, objective, f"provider:{match_id}:objectives:{index}"))
    for index, player in enumerate(players):
        logs = player.get("buyback_log")
        logs = [] if logs is None else logs
        if not isinstance(logs, list):
            raise ValueError("provider buyback_log must be an array")
        for j, log in enumerate(logs):
            if not isinstance(log, dict):
                raise ValueError("provider buyback log must be an object")
            supplied = log.get("player_slot")
            if supplied is not None and (type(supplied) is not int or supplied != player["player_slot"]):
                raise ValueError("provider buyback actor contradicts containing player")
            rows.append(make("buyback_observed", log,
                f"provider:{match_id}:players:{index}:buyback_log:{j}", player=player))
    return rows


def build_semantic_events(trace: TraceResult, provider_raw: dict | None = None) -> dict:
    """Build source-separated markers; no chronological cross-source causal join."""
    manifest = trace.replay.manifest
    dataset_kind = _dataset_kind(manifest.dataset_kind if manifest is not None else "unknown")
    audit_hash = trace.audit.get("replay_sha256")
    replay_hash = manifest.replay_hash if manifest is not None else audit_hash
    _sha(replay_hash, "replay SHA256")
    if audit_hash is not None and audit_hash != replay_hash:
        raise ValueError("semantic replay manifest/audit source identity mismatch")
    if manifest is not None and manifest.match_id != trace.replay.match_id:
        raise ValueError("semantic replay manifest match identity mismatch")
    lanes = {"trace": _trace_events(trace), "provider": []}
    if provider_raw is not None:
        lanes["provider"] = _provider_events(provider_raw, trace.replay.match_id)
    for rows in lanes.values():
        for event in rows:
            event["dataset_kind"] = dataset_kind
    result = {"schema_version": SCHEMA, "match_id": trace.replay.match_id,
        "dataset_kind": dataset_kind,
        "replay_sha256": replay_hash, "validation": "unverified",
        "lanes": lanes, "capability_gaps": list(GAPS),
        "coverage": {name: dict(Counter(e["kind"] for e in rows)) for name, rows in lanes.items()},
        "cross_source_deduplication": "not_performed_identity_and_clock_join_unverified"}
    result["source_availability"] = {"trace_actions": "observed_subset_attempt_coverage_unknown",
        "provider_objectives": "array_present_retrospective" if provider_raw is not None and isinstance(provider_raw.get("objectives"), list) else "unknown",
        "provider_buybacks": "arrays_present_retrospective" if provider_raw is not None and provider_raw.get("players") and all(isinstance(p.get("buyback_log"), list) for p in provider_raw["players"]) else "partial_or_unknown"}
    result["payload_sha256"] = content_hash(result)
    return result


def load_combat_semantic_events(path: str | Path, *, match_id: int,
                               expected_replay_sha256: str, dataset_kind: str = "unknown") -> dict:
    """Read a complete names sidecar. Its ordinals are NEVER full-trace ordinals.

    No retrospective game-start mapping is accepted. Game time remains unknown.
    Modifier apply/remove retain subject/target separately from caster/actor.
    """
    _id(match_id, "match ID")
    _sha(expected_replay_sha256, "replay SHA256")
    dataset_kind = _dataset_kind(dataset_kind)
    counts, digest, rows = Counter(), hashlib.sha256(), []
    footer, seen = None, 0
    with Path(path).open("rb") as stream:
        for line in stream:
            digest.update(line)
            if not line.strip():
                continue
            if len(line) > 16 * 1024 * 1024:
                raise ValueError("combat sidecar record exceeds size limit")
            rec = strict_json(line.decode("utf-8-sig"))
            if not isinstance(rec, dict) or rec.get("record_index") != seen + 1 or type(rec.get("record_index")) is not int:
                raise ValueError("combat sidecar requires consecutive record indices")
            if footer is not None:
                raise ValueError("combat sidecar has records after completion footer")
            seen += 1
            kind = rec.get("t")
            counts[kind] += 1
            if seen == 1:
                if kind != "meta" or rec.get("schema_version") != "replay-combat-names.v1" or rec.get("replay_sha256") != expected_replay_sha256:
                    raise ValueError("combat sidecar source identity/schema mismatch")
                continue
            if kind == "trace_end":
                footer = rec
                continue
            if kind != "combat_log":
                raise ValueError("unsupported combat sidecar record")
            data = rec.get("data")
            names = rec.get("resolved_names")
            if not isinstance(data, dict) or not isinstance(names, dict) or rec.get("name_resolution") != "CombatLogNames_at_callback/v1":
                raise ValueError("combat sidecar requires callback-scoped name resolution")
            source_kind = {"DOTA_COMBATLOG_ITEM": "item", 6: "item",
                "DOTA_COMBATLOG_BUYBACK": "buyback", 12: "buyback",
                "DOTA_COMBATLOG_MODIFIER_ADD": "modifier_add", 2: "modifier_add",
                "DOTA_COMBATLOG_MODIFIER_REMOVE": "modifier_remove", 3: "modifier_remove"}.get(data.get("type"))
            item = _text(names.get("inflictor_name"))
            event_kind = _kind(source_kind, item)
            if event_kind is None:
                continue
            rid = rec["record_index"]
            ref = f"combat-names:{match_id}:record:{rid}"
            details = {k: data[k] for k in ("modifier_purged", "modifier_elapsed_duration", "modifier_duration",
                "is_target_illusion", "is_attacker_illusion", "value") if k in data}
            rows.append(_event(event_id=ref, kind=event_kind, actor=_text(names.get("attacker_name")),
                target=_text(names.get("target_name")), item=item, time=None,
                raw_time=_finite(data.get("timestamp")), timestamp_source="combat_log.timestamp/unverified_engine_clock",
                domain="combat_names", record=rid, source_ref=ref,
                flags=("callback_order_not_verified_simulation_order", "game_clock_unavailable"), raw_details=details))
    if footer is None or footer.get("parser_completed") is not True:
        raise ValueError("combat sidecar requires completed parser footer")
    supplied = footer.get("counts")
    expected_counts = dict(counts)
    expected_counts.pop("trace_end")
    if supplied != expected_counts and supplied != dict(counts):
        raise ValueError("combat sidecar footer counts mismatch")
    result = {"schema_version": SCHEMA, "match_id": match_id, "replay_sha256": expected_replay_sha256,
        "dataset_kind": dataset_kind,
        "source_sha256": digest.hexdigest(), "validation": "unverified", "lanes": {"combat_names": rows},
        "capability_gaps": list(GAPS), "coverage": {"combat_names": dict(Counter(e["kind"] for e in rows))},
        "source_match_binding": "caller_match_id_and_verified_replay_hash_not_embedded_match_id",
        "cross_source_deduplication": "not_performed_identity_and_clock_join_unverified"}
    for event in rows:
        event["dataset_kind"] = dataset_kind
    result["payload_sha256"] = content_hash(result)
    return result


def project_semantic_timeline(events: Iterable[dict], *, source_domain: str,
                              cutoff_record_index: int, dataset_kind: str | None = None) -> dict:
    """Retain only records strictly before a source-local observation boundary.

    Future payloads are never inspected. States describe buff markers, not TP
    success, invisibility, smoke break, or available options at a decision.
    """
    _id(cutoff_record_index, "cutoff record")
    prefix_kind = _dataset_kind(dataset_kind) if dataset_kind is not None else None
    if source_domain not in ("trace", "combat_names"):
        raise ValueError("only source-local replay records support prefix projection")
    selected, states, seen = [], {}, set()
    source_identity = None
    for event in events:
        if not isinstance(event,dict):
            raise ValueError('semantic event object required')
        rid = _id(event.get("source_record_index"), "source record")
        if rid >= cutoff_record_index:
            continue
        if event.get("source_domain") != source_domain:
            raise ValueError("prefix projection cannot mix source ordinal domains")
        event_kind = _dataset_kind(event.get("dataset_kind", "unknown"))
        if prefix_kind is not None and event_kind != prefix_kind:
            raise ValueError("prefix projection cannot mix dataset kinds or promote unknown source")
        prefix_kind = event_kind
        ref = event.get("source_ref")
        prefix = "trace:" if source_domain == "trace" else "combat-names:"
        if not isinstance(ref, str) or not ref.startswith(prefix) or ":record:" not in ref:
            raise ValueError("semantic event source reference/domain mismatch")
        identity, ref_rid = ref.rsplit(":record:", 1)
        if ref_rid != str(rid):
            raise ValueError("semantic event source reference/record mismatch")
        if source_identity is not None and identity != source_identity:
            raise ValueError("prefix projection cannot mix replay identities")
        source_identity = identity
        if event.get("event_id") in seen:
            raise ValueError("duplicate semantic event identity")
        seen.add(event.get("event_id"))
        if event.get("validation") != "unverified":
            raise ValueError("semantic markers cannot grant gameplay validation")
        if any(_id(r, "timing record") > rid for r in event.get("timing_evidence_records", [])):
            raise ValueError("semantic event uses future clock evidence")
        # Only marker operands and clock/identity receipts belong to this
        # projection. Whole-file hashes and arbitrary postmatch payloads cannot
        # become a dependency merely by being nested inside a source event.
        fields=('event_id','kind','actor','target','ability_or_item','game_time','raw_timestamp',
                'timestamp_source','source_domain','source_record_index','source_ref','perspective',
                'validation','dataset_kind','unknown_fields','quality_flags','timing_evidence_records')
        details=event.get('raw_details',{})
        if not isinstance(details,dict):
            raise ValueError('raw semantic details object required')
        allowed_details=('modifier_purged','modifier_elapsed_duration','modifier_duration',
                         'is_target_illusion','is_attacker_illusion','value','type','key','unit',
                         'player_slot','team','account_id','hero_id')
        projected={key:deepcopy(event[key]) for key in fields if key in event}
        projected['raw_details']={key:deepcopy(details[key]) for key in allowed_details if key in details}
        selected.append(projected)
    selected.sort(key=lambda e: (e["source_record_index"], e["event_id"]))
    for event in selected:
        kind = event["kind"]
        # Modifier subject is target, not the caster. No unresolved actor/target grouping.
        subject = event.get("target") if "modifier_" in kind else event.get("actor")
        if subject is None or event.get("raw_details", {}).get("is_target_illusion") is True:
            continue
        if not kind.startswith(("tp_", "smoke_")):
            continue
        category = "tp" if kind.startswith("tp_") else "smoke"
        key = f"{category}:{subject}"
        state = states.setdefault(key, {"subject": subject, "category": category, "use_count": 0,
            "modifier_status": "unknown", "last_source_ref": None,
            "lifecycle_outcome": "unknown", "validation": "unverified", "quality_flags": []})
        if kind.endswith("use_observed"):
            state["use_count"] += 1
        elif kind.endswith("applied"):
            state["modifier_status"] = "apply_marker_observed"
        elif kind.endswith("removed"):
            if state["modifier_status"] != "apply_marker_observed":
                state["quality_flags"].append("remove_without_prior_apply_in_observed_prefix")
            state["modifier_status"] = "remove_marker_observed"
        state["last_source_ref"] = event["source_ref"]
    result = {"schema_version": "foresight.semantic-prefix.v1", "source_domain": source_domain,
        "dataset_kind": prefix_kind if prefix_kind is not None else "unknown",
        "source_identity": source_identity,
        "cutoff_record_index": cutoff_record_index, "boundary": "strictly_before_callback_record_unverified",
        "events": selected, "states": list(states.values()), "capability_gaps": list(GAPS),
        "perspective": "retrospective_world_observation", "training_eligible": False}
    result["prefix_sha256"] = content_hash(result)
    return result
