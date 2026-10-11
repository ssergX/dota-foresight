"""Streaming v3 trace reconstruction. Raw world observations remain retrospective.

No player visibility or cast feasibility is inferred from mere entity presence.
Field discovery and source checks are exported for independent extraction review.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from dota_coach.decisions.batch import strict_json
from dota_coach.evidence.contracts import CapabilityStatus, ReplayManifest, content_hash
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState, WardEvent


@dataclass
class TraceEntity:
    index: int
    generation: int
    class_name: str
    fields: dict
    record_index: int


@dataclass(frozen=True)
class LoggedAction:
    action_id: str
    event_record_index: int
    kind: str
    actor: str | None
    target: str | None
    ability_or_item: str | None
    game_time: float | None
    timestamp_source: str
    stage: str = "combat_log_observation"
    quality_flags: tuple[str, ...] = ("extraction_unverified", "command_attempt_coverage_unknown")
    raw_timestamp: float | None = None
    raw_name_ids: dict | None = None
    timing_evidence_records: tuple[int, ...] = ()
    display_game_time: float | None = None
    display_time_method: str = "unavailable"


@dataclass(frozen=True)
class TraceResult:
    replay: ParsedReplay
    actions: tuple[LoggedAction, ...]
    audit: dict
    inventory_observations: tuple[dict, ...]


def _number(v):
    if type(v) in (int, float) and math.isfinite(v):
        return v
    # v3 int64/uint64 wire values deliberately preserve decimal precision as strings.
    if isinstance(v, str):
        try:
            n = int(v)
            return n
        except ValueError:
            pass
    return None


def _integer(v):
    v = _number(v)
    return int(v) if v is not None and v == int(v) else None


def _field(fields, *names):
    for name in names:
        if name in fields:
            return fields[name]
    return None


def _coordinate(fields, axis):
    cell = _number(_field(fields, f"CBodyComponent.m_cell{axis}", f"m_cell{axis}"))
    vec = _number(_field(fields, f"CBodyComponent.m_vec{axis}", f"m_vec{axis}"))
    return cell*128+vec-16384 if cell is not None and vec is not None else None


def _unit(slot, entity):
    f = entity.fields
    life = _integer(f.get("m_lifeState"))
    return UnitState(slot, _coordinate(f,"X"), _coordinate(f,"Y"),
                     _integer(f.get("m_iHealth")), _integer(f.get("m_iMaxHealth")),
                     _number(f.get("m_flMana")), _integer(f.get("m_iCurrentLevel")),
                     _integer(f.get("m_iCurrentXP")), life == 0 if life is not None else None,
                     entity.index, entity.generation)


def _timestamp(data):
    # Only an explicit combat-log timestamp; never infer a choice from a death offset.
    for key in ("timestamp", "timestamp_raw"):
        n = _number(data.get(key))
        if n is not None:
            return float(n), f"combat_log.{key}/unverified"
    return None, "unavailable"


@dataclass
class _Clock:
    interval: float | None = None
    interval_record: int | None = None
    start: float | None = None
    start_record: int | None = None
    end: float | None = None
    paused_ticks: int | None = None
    pause_start: int | None = None
    paused: bool | None = None
    clock_record: int | None = None

    def observe(self, fields, rid):
        prefix = "m_pGameRules."
        start = _number(fields.get(prefix+"m_flGameStartTime"))
        if start is not None and start > 0 and start != self.start:
            self.start, self.start_record = float(start), rid
        end = _number(fields.get(prefix+"m_flGameEndTime"))
        if end is not None and end > 0:
            self.end = float(end)
        self.paused_ticks = _integer(fields.get(prefix+"m_nTotalPausedTicks"))
        self.pause_start = _integer(fields.get(prefix+"m_nPauseStartTick"))
        paused = fields.get(prefix+"m_bGamePaused")
        self.paused = paused if type(paused) is bool else None
        self.clock_record = rid

    @property
    def refs(self):
        return tuple(sorted({r for r in (self.interval_record, self.start_record, self.clock_record) if r is not None}))

    def at_tick(self, tick):
        if self.interval is None or self.start is None or type(tick) is not int or self.paused_ticks is None or self.paused is None:
            return None
        if self.paused_ticks < 0:
            return None
        effective_tick = tick
        if self.paused:
            if self.pause_start is None or self.pause_start <= 0 or self.pause_start > tick:
                return None
            effective_tick = self.pause_start
        return (effective_tick-self.paused_ticks)*self.interval-self.start

    def event_time(self, timestamp):
        # Combat timestamps are engine-clock observations, already distinct from
        # wall/net ticks. Do NOT subtract paused ticks a second time. The clock
        # mapping remains unverified until pause cases are checked in the client.
        return timestamp-self.start if timestamp is not None and self.start is not None else None


def _sha(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} requires a lowercase SHA256")


def _ward_kind(class_name):
    if class_name == "CDOTA_NPC_Observer_Ward":
        return "obs"
    if class_name == "CDOTA_NPC_Observer_Ward_TrueSight":
        return "sentry"
    return None


def enrich_trace_names(trace_path: str | Path, names_path: str | Path, output_path: str | Path) -> dict:
    """Join two parses only after replay hash, callback order and payload checks.

    This avoids reconstructing millions of entity maps to add name resolutions.
    The original record indices and entity observations are unchanged. Name
    observations come from the same replay's callback prefix in the second pass.
    """
    trace_path, names_path, output_path = map(Path, (trace_path, names_path, output_path))
    if output_path.resolve() in (trace_path.resolve(), names_path.resolve()):
        raise ValueError("name enrichment needs a separate output artifact")
    def digest(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    receipt = {"source_trace_sha256": digest(trace_path), "names_trace_sha256": digest(names_path),
               "method": "same_replay_callback_payload_join/v1", "validation": "unverified"}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="trace-enriched-", suffix=".tmp", dir=output_path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output, trace_path.open("rb") as source, names_path.open("rb") as names:
            name_meta = strict_json(names.readline().decode("utf-8-sig"))
            if name_meta.get("schema_version") != "replay-combat-names.v1" or name_meta.get("record_index") != 1:
                raise ValueError("combat names sidecar metadata required")
            matched, saw_end = 0, False
            for raw in source:
                row = None
                if b'"t":"meta"' in raw or b'"t":"combat_log"' in raw or b'"t":"trace_end"' in raw:
                    row = strict_json(raw.decode("utf-8-sig"))
                # Source may have whitespace-expanded JSON; the fallback only
                # parses lines lacking the compact discriminator from Go.
                elif b'"t":"' not in raw:
                    row = strict_json(raw.decode("utf-8-sig"))
                kind = row.get("t") if row else None
                if kind == "meta":
                    if row.get("schema_version") != "replay-trace.v3" or row.get("replay_sha256") != name_meta.get("replay_sha256"):
                        raise ValueError("name sidecar replay identity mismatch")
                    row["name_enrichment"] = receipt
                elif kind == "combat_log":
                    named = strict_json(names.readline().decode("utf-8-sig"))
                    matched += 1
                    if named.get("t") != "combat_log" or named.get("record_index") != matched+1 or any(
                            named.get(k) != row.get(k) for k in ("data", "demo_tick", "net_tick")):
                        raise ValueError("name sidecar event payload or callback order mismatch")
                    if named.get("name_resolution") != "CombatLogNames_at_callback/v1" or not isinstance(named.get("resolved_names"), dict):
                        raise ValueError("prefix name resolution required")
                    row.update(resolved_names=named["resolved_names"], name_resolution=named["name_resolution"])
                elif kind == "trace_end":
                    saw_end = row.get("parser_completed") is True
                    if row.get("counts", {}).get("combat_log") != matched:
                        raise ValueError("source combat count mismatch")
                output.write((json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":"))+"\n").encode("utf-8") if row else raw)
            end = strict_json(names.readline().decode("utf-8-sig"))
            if not saw_end or end.get("t") != "trace_end" or end.get("parser_completed") is not True or end.get("record_index") != matched+2 or end.get("counts") != {"meta": 1, "combat_log": matched, "trace_end": 1} or names.read().strip():
                raise ValueError("name sidecar completion/counts mismatch")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return receipt | {"matched_combat_records": matched}


def parse_trace(path: str | Path, match_id: int, *, expected_replay_sha256: str | None = None) -> TraceResult:
    """Read the entire stream, retaining bounded audit samples and 1Hz world frames.

    Every normalized knowledge timestamp uses clock observations already present
    in the prefix. A separate display timestamp can use retrospective calibration.
    Neither timing path grants client validation or simulation-order certainty.
    """
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("positive match id required")
    if expected_replay_sha256 is not None:
        _sha(expected_replay_sha256, "expected replay hash")
    digest = hashlib.sha256()
    metadata = footer = None
    entities: dict[int, TraceEntity] = {}
    mappings: dict[int, tuple[int, int]] = {}
    heroes, teams, frames, wards = {}, {}, [], []
    actions, inventory, clock_samples, frame_timing = [], [], [], []
    names, identities = {}, {}
    classes, kinds, counts = Counter(), Counter(), Counter()
    samples, types, mapping_conflicts = {}, {}, []
    clock = _Clock()
    last_record = 0
    previous = None
    last_frame = None
    clock_signature = None
    file_match_id = None
    raw_wards = []
    warnings = {"raw_entity_values_not_client_validated", "clock_mapping_not_client_validated",
                "actual_team_visibility_unverified", "reaction_cue_unavailable",
                "callback_order_not_verified_simulation_order"}
    clock_method = "server_tick_interval_minus_pauses_minus_start/unverified"

    def snapshot(rec):
        nonlocal last_frame
        time = clock.at_tick(rec.get("net_tick"))
        if time is None or time < -0.01 or (last_frame is not None and time-last_frame < 1):
            return
        if clock.end is not None and clock.start is not None and time > clock.end-clock.start+0.05:
            counts["postgame_snapshot_skipped"] += 1
            return
        if last_frame is not None and time < last_frame:
            warnings.add("clock_regressed")
            return
        units = {}
        for slot, (index, generation) in mappings.items():
            e = entities.get(index)
            if e is None or e.generation != generation or not e.class_name.startswith("CDOTA_Unit_Hero_"):
                continue
            u = _unit(slot, e)
            if any(v is not None and v < 0 for v in (u.hp, u.max_hp, u.mana, u.level, u.xp)):
                counts["invalid_resource_snapshot"] += 1
                continue
            units[slot] = u
            heroes[slot] = e.class_name
            team = _integer(e.fields.get("m_iTeamNum"))
            if team in (2, 3):
                teams[slot] = team
        if units:
            frames.append(ReplayFrame(time, units, rec.get("net_tick"), rec.get("sequence_in_tick")))
            frame_timing.append({"frame_time": time, "prefix_record_index": rec["record_index"],
                                 "clock_evidence_records": clock.refs})
            last_frame = time

    def ward_observation(rec, e, op):
        wk = _ward_kind(e.class_name)
        if wk is None:
            return
        raw_wards.append({"id": e.index, "generation": e.generation, "kind": wk,
            "team": _integer(e.fields.get("m_iTeamNum")), "x": _coordinate(e.fields, "X"),
            "y": _coordinate(e.fields, "Y"), "op": op, "record_index": rec["record_index"],
            "tick": rec.get("net_tick"), "sequence": rec.get("sequence_in_tick"),
            "prefix_game_time": clock.at_tick(rec.get("net_tick")),
            "interval": clock.interval, "paused_ticks": clock.paused_ticks,
            "paused": clock.paused, "pause_start": clock.pause_start,
            "clock_evidence_records": clock.refs})

    def combat(rec, data, suffix=""):
        if not isinstance(data, dict):
            raise ValueError("combat log object required")
        label = {4: "death", 5: "ability", 6: "item", 12: "buyback",
                 "DOTA_COMBATLOG_DEATH": "death", "DOTA_COMBATLOG_ABILITY": "ability",
                 "DOTA_COMBATLOG_ITEM": "item", "DOTA_COMBATLOG_BUYBACK": "buyback"}.get(data.get("type"))
        if not label:
            return
        raw_time, method = _timestamp(data)
        resolved = rec.get("resolved_names", {})
        if not isinstance(resolved, dict):
            raise ValueError("resolved combat names must be an object")
        def name(key):
            value = resolved.get(key) if rec.get("name_resolution") == "CombatLogNames_at_callback/v1" else None
            if value is None:
                value = names.get(str(data.get(key)))
            return value if isinstance(value, str) else None
        actor, target, item = name("attacker_name"), name("target_name"), name("inflictor_name")
        flags = ["extraction_unverified", "command_attempt_coverage_unknown"]
        if actor is None or (label in ("ability", "item") and item is None):
            flags.append("combat_name_unresolved")
        time = clock.event_time(raw_time)
        if time is None:
            flags.append("prefix_clock_unavailable")
        actions.append(LoggedAction(f"trace:{match_id}:record:{rec['record_index']}{suffix}",
            rec["record_index"], label, actor, target, item, time,
            method+"-prefix_game_start" if time is not None else "unavailable",
            quality_flags=tuple(flags), raw_timestamp=raw_time,
            raw_name_ids={key: data.get(key) for key in ("attacker_name", "target_name", "inflictor_name")},
            timing_evidence_records=clock.refs))

    with Path(path).open("rb") as stream:
        for raw in stream:
            digest.update(raw)
            if not raw.strip():
                continue
            if len(raw) > 16*1024*1024:
                raise ValueError("trace record exceeds size limit")
            rec = strict_json(raw.decode("utf-8-sig"))
            if not isinstance(rec, dict):
                raise ValueError("trace records must be objects")
            kind, rid = rec.get("t"), rec.get("record_index")
            if not isinstance(kind, str) or type(rid) is not int or rid != last_record+1:
                raise ValueError("trace records require consecutive indices and record type")
            if footer is not None:
                raise ValueError("records after completion footer")
            if previous is not None and rec.get("net_tick") != previous.get("net_tick"):
                snapshot(previous)  # all preceding tick's entity deltas have arrived
            last_record = rid
            kinds[kind] += 1
            previous = rec
            if metadata is None:
                if kind != "meta" or rec.get("schema_version") != "replay-trace.v3":
                    raise ValueError("initial replay-trace.v3 meta required")
                _sha(rec.get("replay_sha256"), "source replay hash")
                if expected_replay_sha256 is not None and rec["replay_sha256"] != expected_replay_sha256:
                    raise ValueError("source replay hash mismatch")
                metadata = rec
                previous = rec
                continue
            if kind == "meta":
                raise ValueError("duplicate trace metadata")
            if kind == "trace_end":
                if rec.get("parser_completed") is not True:
                    raise ValueError("trace parser did not complete")
                declared = rec.get("counts")
                if not isinstance(declared, dict) or any(type(v) is not int or v < 0 for v in declared.values()) or declared != dict(kinds):
                    raise ValueError("footer record counts do not match trace")
                footer = rec
            elif kind == "server_info":
                interval = _number(rec.get("data", {}).get("tick_interval"))
                if interval is not None and 0 < interval <= 1:
                    if clock.interval is not None and clock.interval != interval:
                        warnings.add("tick_interval_changed")
                    clock.interval, clock.interval_record = float(interval), rid
                else:
                    warnings.add("server_tick_interval_unavailable")
            elif kind == "clock":
                cf = rec.get("fields")
                if not isinstance(cf, dict):
                    raise ValueError("clock fields must be object")
                clock.observe(cf, rid)
                signature = (clock.start, clock.end, clock.paused_ticks, clock.pause_start, clock.paused)
                if signature != clock_signature:
                    if len(clock_samples) < 512:
                        clock_samples.append({"record_index": rid, "net_tick": rec.get("net_tick"), "fields": cf})
                    else:
                        counts["clock_samples_omitted"] += 1
                    clock_signature = signature
                counts["clock_records"] += 1
                if clock.paused:
                    counts["paused_clock_records"] += 1
            elif kind == "entity":
                idx, gen = rec.get("entity_index"), rec.get("generation")
                if type(idx) is not int or type(gen) is not int or idx < 0 or gen < 0:
                    raise ValueError("entity index/generation required")
                cn, fields = rec.get("class"), rec.get("fields")
                removed, op_bits = rec.get("removed_fields", []), rec.get("op_bits")
                if not isinstance(cn, str) or not isinstance(fields, dict) or not isinstance(removed, list) or any(not isinstance(k, str) for k in removed):
                    raise ValueError("entity class/fields/removal list required")
                if type(op_bits) is not int:
                    raise ValueError("v3 entity operation bitmask required")
                classes[cn] += 1
                for key, value in fields.items():
                    sample_key = f"{cn}:{key}"
                    if len(samples) < 12000 or sample_key in samples:
                        samples.setdefault(sample_key, value)
                        types.setdefault(sample_key, rec.get("field_types", {}).get(key))
                    else:
                        counts["property_samples_omitted"] += 1
                prior = entities.get(idx)
                if op_bits & 4:
                    if prior is not None and prior.generation == gen:
                        ward_observation(rec, prior, "gone")
                        del entities[idx]
                    else:
                        counts["unobserved_entity_removal"] += 1
                    continue
                created = prior is None or prior.generation != gen
                if created and not rec.get("full_snapshot"):
                    warnings.add("entity_delta_without_baseline")
                    continue
                if created or rec.get("full_snapshot") is True:
                    entity = TraceEntity(idx, gen, cn, dict(fields), rid)
                    entities[idx] = entity
                    if created:
                        ward_observation(rec, entity, "placed")
                else:
                    if prior.class_name != cn:
                        raise ValueError("entity class changed without new generation")
                    prior.fields.update(fields)
                    prior.record_index = rid
                    for key in removed:
                        prior.fields.pop(key, None)
                if cn == "CDOTA_PlayerResource":
                    for key, value in fields.items():
                        pieces = key.split(".")
                        if len(pieces) == 3 and pieces[0] in ("m_vecPlayerData", "m_vecPlayerTeamData") and pieces[1].isdigit():
                            slot = int(pieces[1])
                            if 0 <= slot <= 9 and pieces[2] in ("m_iPlayerSteamID", "m_iPlayerTeam", "m_nSelectedHeroID"):
                                identities.setdefault(str(slot), {})[pieces[2]] = value
                if cn.startswith("CDOTA_Unit_Hero_") and any("m_hItems" in k or "m_vecAbilities" in k for k in fields):
                    counts["inventory_delta_records"] += 1
                    inventory.append({"record_index": rid, "game_time": clock.at_tick(rec.get("net_tick")),
                        "entity_index": idx, "generation": gen,
                        "item_handles": {k: v for k, v in fields.items() if "m_hItems" in k},
                        "ability_handles": {k: v for k, v in fields.items() if "m_vecAbilities" in k},
                        "clock_evidence_records": clock.refs, "quality": "raw_handles/unverified"})
            elif kind == "player_mapping":
                slot, idx, gen = rec.get("resource_slot"), rec.get("entity_index"), rec.get("generation")
                if type(slot) is not int or not 0 <= slot <= 9:
                    counts["non_roster_resource_mapping"] += 1
                    continue
                if rec.get("status") != "resolved_handle" or type(idx) is not int or type(gen) is not int:
                    mappings.pop(slot, None)
                    continue
                if (idx, gen) in {identity for other, identity in mappings.items() if other != slot}:
                    mapping_conflicts.append({"record_index": rid, "slot": slot, "entity_index": idx})
                    mappings.pop(slot, None)
                else:
                    mappings[slot] = (idx, gen)
            elif kind == "string_table":
                table = rec.get("data", {})
                if not isinstance(table, dict):
                    raise ValueError("string table data must be object")
                if table.get("table_name") == "CombatLogNames":
                    entries = table.get("items", [])
                    if not isinstance(entries, list):
                        raise ValueError("string table items must be list")
                    names = {str(i): e["str"] for i, e in enumerate(entries) if isinstance(e, dict) and isinstance(e.get("str"), str)}
            elif kind == "combat_log":
                combat(rec, rec.get("data", {}))
            elif kind == "combat_bulk":
                # Bulk delivery can duplicate individual callbacks; retain the raw
                # trace and report it, rather than silently double count actions.
                counts["combat_bulk_records_unmerged"] += 1
                warnings.add("combat_bulk_not_deduplicated_into_actions")
            elif kind == "file_info":
                candidate = _integer(rec.get("data", {}).get("game_info", {}).get("dota", {}).get("match_id"))
                if candidate is not None:
                    if candidate != match_id or file_match_id is not None and file_match_id != candidate:
                        raise ValueError("embedded replay match ID differs from requested match")
                    file_match_id = candidate
            elif kind not in ("modifier", "game_event", "game_event_schema", "file_header", "net_tick", "protocol"):
                warnings.add("unsupported_trace_record:"+kind)
            previous = rec
    if metadata is None or footer is None:
        raise ValueError("trace incomplete: missing metadata or completion footer")
    snapshot(footer)
    if file_match_id is None:
        warnings.add("embedded_match_identity_unavailable")
    if clock.interval is None or clock.start is None:
        warnings.add("game_time_mapping_unavailable")
    if mapping_conflicts:
        warnings.add("player_mapping_conflict")
    # These are explicitly retrospective display times, never knowledge inputs.
    for raw in raw_wards:
        time, method = raw["prefix_game_time"], "prefix_clock/unverified"
        if time is None and clock.start is not None and raw["interval"] is not None and raw["paused_ticks"] is not None and raw["paused"] is not None:
            effective = raw["pause_start"] if raw["paused"] else raw["tick"]
            if type(effective) is int:
                time = (effective-raw["paused_ticks"])*raw["interval"]-clock.start
                method = "retrospective_start_backfill/display_only"
                counts["ward_display_backfills"] += 1
        raw["display_game_time"], raw["display_time_method"] = time, method
        if time is not None:
            wards.append(WardEvent(raw["id"], time, raw["kind"], raw["team"], raw["x"], raw["y"],
                                   raw["op"], raw["generation"], raw["tick"], raw["sequence"]))
    actions = [replace(a, display_game_time=a.game_time if a.game_time is not None else clock.event_time(a.raw_timestamp),
                       display_time_method="prefix_clock/unverified" if a.game_time is not None else
                       "retrospective_start_backfill/display_only" if clock.start is not None and a.raw_timestamp is not None else "unavailable")
               for a in actions]
    trace_hash = digest.hexdigest()
    observed_caps = {"primary_hero_identity": bool(mappings), "positions_resources": bool(frames),
                     "game_clock": bool(frames), "ward_lifecycle": bool(wards),
                     "inventory_abilities": bool(inventory), "cast_control_events": bool(actions)}
    manifest = ReplayManifest(metadata["replay_sha256"], match_id, "replay-trace.v3", "manta",
        metadata.get("extractor_version", "unknown"), clock_method if frames else "unavailable",
        str(footer.get("game_build")) if footer.get("game_build") else None,
        completeness="partial", parse_warnings=tuple(sorted(warnings)),
        capabilities=tuple(CapabilityStatus(c, "implemented" if present else "absent", "unverified",
            limitations=("raw_handles_not_resolved_feasibility",) if c=="inventory_abilities" else
                ("combat_log_only_command_attempt_and_control_semantics_unknown",) if c=="cast_control_events" else
                ("requires_client_semantic_validation",))
                           for c, present in observed_caps.items()) +
                     (CapabilityStatus("exact_team_visibility"), CapabilityStatus("reaction_cue_available_to_subject")),
        dataset_kind="replay")
    replay = ParsedReplay(match_id, clock.start or 0, heroes, frames, teams, sorted(wards, key=lambda w: w.time), manifest)
    audit = {"schema_version": "foresight.trace-audit.v1", "match_id": match_id, "trace_sha256": trace_hash,
        "replay_sha256": metadata["replay_sha256"], "embedded_match_id": file_match_id,
        "name_enrichment": metadata.get("name_enrichment"),
        "record_counts": dict(kinds), "class_counts": dict(classes), "property_samples": samples,
        "property_go_types": types, "clock_samples": clock_samples, "clock_samples_limit": 512,
        "clock_method": clock_method, "tick_interval": clock.interval, "start_time": clock.start,
        "end_time": clock.end, "timing_provenance": frame_timing, "ward_timing_provenance": raw_wards,
        "resource_mappings": {str(k): list(v) for k, v in mappings.items()},
        "resource_identities": identities, "mapping_conflicts": mapping_conflicts,
        "source_checks": "parser_complete_footer_counts_checked_not_client_validated",
        "source_hash_check": "matches_expected" if expected_replay_sha256 else "declared_not_independently_checked",
        "combat_action_counts": dict(Counter(a.kind for a in actions)),
        "unresolved_actor_count": sum(a.actor is None for a in actions),
        "unresolved_item_ability_count": sum(a.kind in ("item", "ability") and a.ability_or_item is None for a in actions),
        "extraction_counts": dict(counts), "warnings": tuple(sorted(warnings))}
    return TraceResult(replay, tuple(actions), audit, tuple(inventory))


def save_trace_result(result: TraceResult, path: str | Path) -> None:
    payload = {"schema_version": "foresight.trace-extraction.v1", "replay": asdict(result.replay),
               "actions": [asdict(a) for a in result.actions], "audit": result.audit,
               "inventory_observations": list(result.inventory_observations)}
    payload["payload_sha256"] = content_hash(payload)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")


def load_trace_result(path: str | Path) -> TraceResult:
    payload = strict_json(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema_version") != "foresight.trace-extraction.v1":
        raise ValueError("unsupported trace extraction artifact")
    expected = payload.pop("payload_sha256", None)
    _sha(expected, "extraction payload hash")
    if content_hash(payload) != expected:
        raise ValueError("extraction payload hash mismatch")
    raw, audit = payload["replay"], payload["audit"]
    if raw["match_id"] != audit["match_id"]:
        raise ValueError("extraction match identity mismatch")
    manifest = dict(raw["manifest"])
    if manifest["replay_hash"] != audit["replay_sha256"] or manifest["match_id"] != raw["match_id"]:
        raise ValueError("extraction source identity mismatch")
    if manifest.get("dataset_kind") != "replay":
        raise ValueError("trace extraction must identify replay source")
    caps = []
    for c in manifest["capabilities"]:
        c = dict(c)
        if c["validation"] != "unverified":
            raise ValueError("cached extraction cannot grant validation")
        c["limitations"], c["validation_refs"] = tuple(c["limitations"]), tuple(c["validation_refs"])
        caps.append(CapabilityStatus(**c))
    manifest["capabilities"], manifest["parse_warnings"] = tuple(caps), tuple(manifest["parse_warnings"])
    replay = ParsedReplay(raw["match_id"], raw["game_start_time"],
        {int(k): v for k, v in raw["heroes"].items()},
        [ReplayFrame(f["time"], {int(k): UnitState(**u) for k, u in f["units"].items()}, f.get("tick"), f.get("sequence")) for f in raw["frames"]],
        {int(k): v for k, v in raw["teams"].items()}, [WardEvent(**w) for w in raw["wards"]], ReplayManifest(**manifest))
    actions = tuple(LoggedAction(**(a | {"quality_flags": tuple(a["quality_flags"]),
                              "timing_evidence_records": tuple(a.get("timing_evidence_records", []))})) for a in payload["actions"])
    return TraceResult(replay, actions, audit, tuple(payload["inventory_observations"]))
