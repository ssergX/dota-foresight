"""Bounded-memory raw constraint observations from complete trace prefixes.

Changed projected fields are source observations, not a certified truth stream.
The replay clock, patch semantics and subject's screen availability remain open.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from dota_coach.decisions.batch import strict_json
from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.action_state import ACTION_FIELDS, HERO_FIELDS, STEAM_ACCOUNT_BASE, _relation, build_action_states
from dota_coach.ingest.trace import TraceResult, _sha

SCHEMA = "foresight.raw-constraint-source.v1"
DOMAIN = "replay-trace.v3.record_index"
MAX_RECORD_BYTES = 4*1024*1024
COVERAGE = "changed_projected_raw_operands_not_constraint_truth"
ENCODING = "full_identity_boundaries_and_exact_field_set_remove_deltas"
FIELD_MANIFEST = {"hero": list(HERO_FIELDS), "linked_action": list(ACTION_FIELDS),
                  "links": ["m_hItems.*", "m_vecAbilities.*"],
                  "clock": ["tick_interval", "m_flGameStartTime", "m_nTotalPausedTicks",
                            "m_bGamePaused", "m_nPauseStartTick"]}
LIMITATIONS = ["callback_order_not_simulation_order", "clock_mapping_unverified",
               "field_and_patch_semantics_unverified", "no_screen_attention_evidence",
               "no_command_channel_evidence", "no_truth_transition_completeness_certificate"]
_STATE_KEYS = frozenset({"hero", "inventory", "abilities", "clock", "primary_mapping",
                         "resource_steam_id", "prefix_account_id", "feasibility", "reason_codes"})


def _differences(previous, current, path=()):
    if previous == current:
        return []
    if isinstance(previous, dict) and isinstance(current, dict):
        result = [{"op": "remove", "path": list(path+(key,))} for key in sorted(set(previous)-set(current))]
        for key in sorted(current):
            if key not in previous:
                result.append({"op": "set", "path": list(path+(key,)), "value": current[key]})
            else:
                result.extend(_differences(previous[key], current[key], path+(key,)))
        return result
    if isinstance(previous, list) and isinstance(current, list) and len(previous) == len(current):
        return [change for index, value in enumerate(current)
                for change in _differences(previous[index], value, path+(index,))]
    return [{"op": "set", "path": list(path), "value": current}]


def _apply_changes(state, changes):
    if not isinstance(changes, list):
        raise ValueError("raw projection delta list required")
    for change in changes:
        if not isinstance(change, dict) or set(change) not in ({"op", "path"}, {"op", "path", "value"}):
            raise ValueError("malformed raw projection delta")
        path = change.get("path")
        if not isinstance(path, list) or not path or path[0] not in _STATE_KEYS:
            raise ValueError("raw projection delta path outside projected state")
        parent = state
        for key in path[:-1]:
            if isinstance(parent, dict) and isinstance(key, str) and key in parent:
                parent = parent[key]
            elif isinstance(parent, list) and type(key) is int and 0 <= key < len(parent):
                parent = parent[key]
            else:
                raise ValueError("raw projection delta parent unavailable")
        key, op = path[-1], change["op"]
        if isinstance(parent, dict) and isinstance(key, str):
            if op == "set" and "value" in change:
                parent[key] = change["value"]
            elif op == "remove" and "value" not in change and key in parent:
                del parent[key]
            else:
                raise ValueError("invalid raw projection dictionary delta")
        elif isinstance(parent, list) and type(key) is int and 0 <= key < len(parent) and op == "set" and "value" in change:
            parent[key] = change["value"]
        else:
            raise ValueError("invalid raw projection list delta")
    if set(state) != _STATE_KEYS:
        raise ValueError("raw projected state keys changed")


def _changed_receipt_subtrees(state, changes):
    """Nearest surviving delta parents, including the whole edited fact.

    Source records and network ticks advance monotonically, so a previously
    checked unchanged receipt cannot become future evidence at a later prefix.
    """
    parents, seen = [], set()
    for change in changes:
        parent = state
        for key in change["path"][:-1]:
            if isinstance(parent, dict) and isinstance(key, str) and key in parent:
                parent = parent[key]
            elif isinstance(parent, list) and type(key) is int and 0 <= key < len(parent):
                parent = parent[key]
            else:
                break
        if id(parent) not in seen:
            seen.add(id(parent))
            parents.append(parent)
    return parents


def _encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))+"\n").encode("utf-8")


def write_constraint_source(trace_path: str | Path, extraction: TraceResult, output_path: str | Path,
                            *, resource_slot: int, actor: str,
                            expected_account_id: int | None = None) -> dict:
    """Atomically publish a sidecar after the complete source has been verified.

    No action or one-second timeline captures are requested. The shared decoder
    calls the sink after each changed own/link/identity/clock operand record.
    Prefixes before a requested account is observed contain no hero/item data.
    """
    if expected_account_id is not None and (type(expected_account_id) is not int or not 0 < expected_account_id <= 0xffffffff):
        raise ValueError("positive exact account ID required")
    if type(extraction.replay.match_id) is not int or not 0 < extraction.replay.match_id < 2**64 or extraction.audit.get("match_id") != extraction.replay.match_id or extraction.replay.manifest.match_id != extraction.replay.match_id or extraction.replay.manifest.replay_hash != extraction.audit.get("replay_sha256"):
        raise ValueError("extraction manifest and source binding differ")
    for field in ("replay_sha256", "trace_sha256"):
        _sha(extraction.audit.get(field), field)
    if type(resource_slot) is not int or not 0 <= resource_slot <= 9 or not isinstance(actor, str) or not re.fullmatch(r"npc_dota_hero_[a-z0-9_]{1,100}", actor):
        raise ValueError("raw constraint subject scope invalid")
    source, target = Path(trace_path), Path(output_path)
    if source.resolve() == target.resolve() or (target.exists() and os.path.samefile(source, target)):
        raise ValueError("output must not overwrite source trace")
    target.parent.mkdir(parents=True, exist_ok=True)
    counts, reasons, bindings = Counter(), Counter(), Counter()
    first_record = last_record = None
    item_ids = set()
    digest = hashlib.sha256()
    header = {"t": "meta", "schema_version": SCHEMA,
              "match_id": extraction.replay.match_id, "resource_slot": resource_slot,
              "actor": actor, "expected_account_id": expected_account_id,
              "replay_sha256": extraction.audit["replay_sha256"],
              "trace_sha256": extraction.audit["trace_sha256"],
              "source_extraction_hash": content_hash(asdict(extraction)),
              "record_index_domain": DOMAIN,
              "projection_encoding": ENCODING, "projection_fields": FIELD_MANIFEST,
              "validation": "unverified", "training_eligible": False,
              "coverage": COVERAGE, "limitations": LIMITATIONS}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent,
                                         prefix=target.name+".", suffix=".partial", delete=False) as stream:
            temporary = Path(stream.name)
            def append(value):
                raw = _encoded(value)
                stream.write(raw)
                digest.update(raw)
            append(header)
            previous_state = previous_identity = None

            def observe(observation):
                nonlocal first_record, last_record, previous_state, previous_identity
                row = dict(observation)
                rid = row["source_record_index"]
                row.update(cutoff_net_tick=row["net_tick"], sampled_net_tick=row["net_tick"],
                           cutoff_policy="prefix_record_inclusive")
                if last_record is not None and rid <= last_record:
                    raise ValueError("raw transition observations must advance source records")
                first_record = rid if first_record is None else first_record
                last_record = rid
                account = row["prefix_account_id"]
                if expected_account_id is None:
                    binding = "declared_resource_slot_only"
                else:
                    binding = "prefix_resource_account_match" if account == expected_account_id else "prefix_account_unavailable_or_different"
                    if account != expected_account_id:
                        row.update(hero=None, inventory=[], abilities=[],
                                   reason_codes=["requested_account_not_bound_at_prefix"])
                row.update(t="raw_constraint_observation", subject_binding=binding,
                           raw_validation="unverified", training_eligible=False)
                counts["observations"] += 1
                counts["hero_observations"] += row.get("hero") is not None
                reasons[row["transition_reason"]] += 1
                bindings[binding] += 1
                for item in row["inventory"]:
                    if item.get("item_id"):
                        item_ids.add(item["item_id"])
                state = {key: row.pop(key) for key in _STATE_KEYS}
                hero = state["hero"]
                identity = (binding, state["prefix_account_id"], state["primary_mapping"].get("value"),
                            (hero["entity_index"], hero["generation"]) if hero else None,
                            tuple((kind, item["slot"], item.get("entity_index"), item.get("generation"), item.get("relation_status"))
                                  for kind in ("inventory", "abilities") for item in state[kind]))
                if previous_state is None or identity != previous_identity:
                    row["projection"] = state
                    counts["full_projections"] += 1
                else:
                    row["projection_changes"] = _differences(previous_state, state)
                    counts["delta_projections"] += 1
                previous_state, previous_identity = state, identity
                row["payload_sha256"] = content_hash(row)
                append(row)

            dossier = build_action_states(source, extraction, resource_slot=resource_slot, actor=actor,
                                          action_ids=(), include_timeline=False, transition_sink=observe)
            footer = {"t": "source_end", "schema_version": SCHEMA, "source_verified": True,
                      "parser_completed": True, "validation": "unverified", "training_eligible": False,
                      "counts": dict(counts), "transition_reasons": dict(reasons),
                      "subject_bindings": dict(bindings), "first_source_record_index": first_record,
                      "last_source_record_index": last_record, "observed_item_ids": sorted(item_ids),
                      "projection_audit_counts": dossier["audit_counts"],
                      "prefix_sha256": digest.hexdigest()}
            append(footer)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
        return header | footer | {"path": str(target), "file_sha256": digest.hexdigest()}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def inspect_constraint_source(path: str | Path, *, extraction: TraceResult | None = None) -> dict:
    """Validate the complete sidecar while retaining only its compact summary."""
    digest, whole = hashlib.sha256(), hashlib.sha256()
    metadata = footer = None
    counts, reasons, bindings = Counter(), Counter(), Counter()
    item_ids = set()
    first_record = last_record = None
    state = None
    last_tick = None
    with Path(path).open("rb") as stream:
        while raw := stream.readline(MAX_RECORD_BYTES+1):
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError("raw constraint record exceeds bounded reader limit")
            whole.update(raw)
            if footer is not None:
                raise ValueError("data after raw constraint footer")
            row = strict_json(raw.decode("utf-8-sig"))
            kind = row.get("t")
            if kind == "meta":
                if metadata is not None or row.get("schema_version") != SCHEMA or row.get("record_index_domain") != DOMAIN:
                    raise ValueError("raw constraint metadata mismatch")
                if set(row) != {"t", "schema_version", "match_id", "resource_slot", "actor", "expected_account_id",
                                 "replay_sha256", "trace_sha256", "source_extraction_hash", "record_index_domain",
                                 "projection_encoding", "projection_fields", "validation", "training_eligible",
                                 "coverage", "limitations"}:
                    raise ValueError("raw constraint metadata fields mismatch")
                if row.get("validation") != "unverified" or row.get("training_eligible") is not False:
                    raise ValueError("raw observations cannot self-promote")
                if row.get("coverage") != COVERAGE or row.get("projection_encoding") != ENCODING or row.get("projection_fields") != FIELD_MANIFEST or row.get("limitations") != LIMITATIONS:
                    raise ValueError("raw constraint coverage and finite projection contract mismatch")
                if type(row.get("match_id")) is not int or not 0 < row["match_id"] < 2**64 or type(row.get("resource_slot")) is not int or not 0 <= row["resource_slot"] <= 9 or not isinstance(row.get("actor"), str) or not re.fullmatch(r"npc_dota_hero_[a-z0-9_]{1,100}", row["actor"]):
                    raise ValueError("raw constraint subject scope invalid")
                account = row.get("expected_account_id")
                if account is not None and (type(account) is not int or not 0 < account <= 0xffffffff):
                    raise ValueError("raw constraint account scope invalid")
                for field in ("trace_sha256", "replay_sha256", "source_extraction_hash"):
                    _sha(row.get(field), field)
                metadata = row
            elif kind == "raw_constraint_observation":
                if metadata is None:
                    raise ValueError("raw constraint metadata required first")
                rid = row.get("source_record_index")
                if type(rid) is not int or not 1 <= rid < 2**64 or (last_record is not None and rid <= last_record):
                    raise ValueError("raw constraint source records must advance")
                tick = row.get("net_tick")
                if type(tick) is not int or not 0 <= tick <= 0xffffffff or (last_tick is not None and tick < last_tick):
                    raise ValueError("raw constraint network clock invalid or regressed")
                last_tick = tick
                for field, upper in (("demo_tick", 2**32), ("sequence_in_tick", 2**64)):
                    value = row.get(field)
                    if value is not None and (type(value) is not int or not 0 <= value < upper):
                        raise ValueError("raw constraint source clock outside declared uint32/uint64 bounds")
                if row.get("cutoff_record_index") != rid+1 or row.get("raw_validation") != "unverified" or row.get("training_eligible") is not False:
                    raise ValueError("raw observation cutoff or validation invalid")
                if any(type(row.get(field)) is not int or row[field] != tick for field in ("cutoff_net_tick", "sampled_net_tick")) or row.get("cutoff_policy") != "prefix_record_inclusive":
                    raise ValueError("raw observation network cutoff must match inclusive source tick")
                if content_hash({k: v for k, v in row.items() if k != "payload_sha256"}) != row.get("payload_sha256"):
                    raise ValueError("raw constraint observation hash mismatch")
                allowed = {"t", "cutoff_record_index", "cutoff_net_tick", "sampled_net_tick", "cutoff_policy",
                           "source_record_index", "net_tick", "demo_tick", "sequence_in_tick", "source_kind",
                           "transition_reason", "subject_binding", "raw_validation", "training_eligible", "payload_sha256",
                           "projection", "projection_changes"}
                if set(row)-allowed:
                    raise ValueError("unexpected raw observation field")
                if ("projection" in row) == ("projection_changes" in row):
                    raise ValueError("exactly one raw projection encoding required")
                if "projection" in row:
                    state = row["projection"]
                    if not isinstance(state, dict) or set(state) != _STATE_KEYS:
                        raise ValueError("raw projected state keys mismatch")
                    counts["full_projections"] += 1
                    receipt_subtrees = [state]
                else:
                    if state is None:
                        raise ValueError("raw projection baseline required before deltas")
                    _apply_changes(state, row["projection_changes"])
                    counts["delta_projections"] += 1
                    receipt_subtrees = _changed_receipt_subtrees(state, row["projection_changes"])
                row = {k: v for k, v in row.items() if k not in ("projection", "projection_changes")} | state
                if row.get("feasibility") != "unknown":
                    raise ValueError("raw constraint projection cannot grant feasibility")
                steam_value = row.get("resource_steam_id", {}).get("value")
                try:
                    steam_number = int(steam_value) if type(steam_value) in (int, str) else None
                except ValueError:
                    steam_number = None
                account = steam_number-STEAM_ACCOUNT_BASE if steam_number is not None and STEAM_ACCOUNT_BASE < steam_number <= STEAM_ACCOUNT_BASE+0xffffffff else None
                if row.get("prefix_account_id") != account:
                    raise ValueError("prefix account arithmetic differs from receipt")
                expected_account = metadata.get("expected_account_id")
                expected_binding = "declared_resource_slot_only" if expected_account is None else ("prefix_resource_account_match" if account == expected_account else "prefix_account_unavailable_or_different")
                if row.get("subject_binding") != expected_binding:
                    raise ValueError("prefix subject binding differs from receipt")
                first_record = rid if first_record is None else first_record
                last_record = rid
                hero = row.get("hero")
                if expected_binding == "prefix_account_unavailable_or_different" and (hero is not None or row.get("inventory") or row.get("abilities")):
                    raise ValueError("requested account must be bound before hero projection")
                if hero is not None and set(hero.get("fields", {}))-set(HERO_FIELDS):
                    raise ValueError("unexpected hero projection field")
                if hero is not None and set(hero)-{"entity_index", "generation", "class", "mapping_source_record_index", "fields"}:
                    raise ValueError("unexpected hero projection attributes")
                if hero is not None and (type(hero.get("entity_index")) is not int or not 0 <= hero["entity_index"] < 2**14 or type(hero.get("generation")) is not int or not 0 <= hero["generation"] < 2**32):
                    raise ValueError("raw hero identity requires exact uint types")
                if hero is not None and (type(hero.get("mapping_source_record_index")) is not int or hero["mapping_source_record_index"] > rid):
                    raise ValueError("future hero mapping receipt")
                if hero is not None and list(row.get("primary_mapping", {}).get("value") or ()) != [hero.get("entity_index"), hero.get("generation")]:
                    raise ValueError("hero differs from exact prefix primary mapping")
                if hero is not None and (not isinstance(hero.get("class"), str) or not hero["class"].startswith("CDOTA_Unit_Hero_") or hero["class"].removeprefix("CDOTA_Unit_Hero_").replace("_", "").lower() != metadata["actor"].removeprefix("npc_dota_hero_").replace("_", "").lower()):
                    raise ValueError("prefix hero class differs from declared actor")
                if set(row.get("clock", {})) - {"tick_interval", "start_time", "paused_ticks", "paused", "pause_start_tick", "evidence_records", "semantic_validation"} or row.get("clock", {}).get("semantic_validation") != "unverified":
                    raise ValueError("raw clock projection schema invalid")
                clock_refs = row.get("clock", {}).get("evidence_records", [])
                if not isinstance(clock_refs, list) or any(type(ref) is not int or ref < 1 or ref > rid for ref in clock_refs):
                    raise ValueError("future clock receipt in raw constraint prefix")
                for item in row.get("inventory", [])+row.get("abilities", []):
                    if set(item.get("fields", {}))-set(ACTION_FIELDS) or "checks" in item:
                        raise ValueError("unexpected linked constraint projection")
                    if set(item)-{"slot", "handle", "handle_fact", "relation_status", "entity_index", "generation", "class", "item_id", "identity_method", "fields"}:
                        raise ValueError("unexpected linked projection attributes")
                    if type(item.get("slot")) is not int or not 0 <= item["slot"] < 2**32 or any(item.get(field) is not None and (type(item[field]) is not int or not 0 <= item[field] < upper) for field, upper in (("entity_index", 2**14), ("generation", 2**32))):
                        raise ValueError("raw linked identity requires exact uint types")
                    if item.get("item_id"):
                        item_ids.add(item["item_id"])
                    if item.get("relation_status") == "resolved_exact_handle" and _relation(item.get("handle")) != (item.get("entity_index"), item.get("generation")):
                        raise ValueError("linked constraint handle generation mismatch")
                def prefix(value):
                    if isinstance(value, dict):
                        ref = value.get("source_record_index")
                        if ref is not None and (type(ref) is not int or ref > rid):
                            raise ValueError("future field receipt in raw constraint prefix")
                        observed_tick = value.get("net_tick")
                        if observed_tick is not None and (type(observed_tick) is not int or not 0 <= observed_tick <= tick):
                            raise ValueError("future or invalid field clock in raw constraint prefix")
                        for child in value.values():
                            prefix(child)
                    elif isinstance(value, list):
                        for child in value:
                            prefix(child)
                for subtree in receipt_subtrees:
                    prefix(subtree)
                counts["observations"] += 1
                counts["hero_observations"] += hero is not None
                reasons[row["transition_reason"]] += 1
                bindings[row["subject_binding"]] += 1
            elif kind == "source_end":
                if set(row) != {"t", "schema_version", "source_verified", "parser_completed", "validation",
                                 "training_eligible", "counts", "transition_reasons", "subject_bindings",
                                 "first_source_record_index", "last_source_record_index", "observed_item_ids",
                                 "projection_audit_counts", "prefix_sha256"}:
                    raise ValueError("raw constraint footer fields mismatch")
                if metadata is None or row.get("schema_version") != SCHEMA or row.get("source_verified") is not True or row.get("parser_completed") is not True or row.get("validation") != "unverified" or row.get("training_eligible") is not False:
                    raise ValueError("complete unverified raw constraint footer required")
                for field in ("counts", "transition_reasons", "subject_bindings", "projection_audit_counts"):
                    counters = row.get(field)
                    if not isinstance(counters, dict) or any(not isinstance(key, str) or type(value) is not int or value < 0 for key, value in counters.items()):
                        raise ValueError("raw source counters require nonnegative exact integers")
                if row.get("prefix_sha256") != digest.hexdigest():
                    raise ValueError("raw constraint prefix digest mismatch")
                expected = {"counts": dict(counts), "transition_reasons": dict(reasons),
                            "subject_bindings": dict(bindings), "first_source_record_index": first_record,
                            "last_source_record_index": last_record, "observed_item_ids": sorted(item_ids)}
                if any(row.get(k) != v for k, v in expected.items()):
                    raise ValueError("raw constraint footer census mismatch")
                footer = row
            else:
                raise ValueError("unexpected raw constraint record")
            if footer is None:
                digest.update(raw)
    if metadata is None or footer is None:
        raise ValueError("complete raw constraint sidecar required")
    if extraction is not None and (metadata["match_id"] != extraction.replay.match_id
            or extraction.audit.get("match_id") != extraction.replay.match_id
            or metadata["trace_sha256"] != extraction.audit["trace_sha256"]
            or metadata["replay_sha256"] != extraction.audit["replay_sha256"]
            or metadata["source_extraction_hash"] != content_hash(asdict(extraction))):
        raise ValueError("raw constraint sidecar bound to another extraction")
    if extraction is not None and (extraction.replay.manifest.match_id != extraction.replay.match_id
            or extraction.replay.manifest.replay_hash != extraction.audit["replay_sha256"]):
        raise ValueError("extraction manifest and source binding differ")
    return metadata | footer | {"path": str(path), "file_sha256": whole.hexdigest()}


def load_constraint_source(path: str | Path, *, extraction: TraceResult,
                           account_id: int | None = None) -> dict:
    """Return a verified, bounded summary for a requested extraction/account."""
    if account_id is not None and (type(account_id) is not int or not 0 < account_id <= 0xffffffff):
        raise ValueError("positive exact account ID required")
    summary = inspect_constraint_source(path, extraction=extraction)
    if account_id is not None and summary.get("expected_account_id") != account_id:
        raise ValueError("raw constraint account scope differs from request")
    return summary
