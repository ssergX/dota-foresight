"""Stream explicitly supplied combat-event visibility flags, without a FoW model.

An optional combat flag is an observation about that event's source payload.
Missing flags remain unknown. These records do not establish which entity was
visible, when a player received the event, screen attention, or continuous sight.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from dota_coach.decisions.batch import strict_json
from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.trace import TraceResult, _sha

SCHEMA = "foresight.event-visibility.v1"
MAX_RECORD_BYTES = 16 * 1024 * 1024
LIMITATIONS = (
    "combat_flags_are_not_verified_entity_fog_of_war",
    "missing_optional_flag_is_unknown_not_false",
    "combat_names_ordinals_are_not_trace_ordinals",
    "names_do_not_identify_entity_generation",
    "event_time_and_player_delivery_time_are_not_aligned",
    "screen_attention_and_reaction_cues_unavailable",
    "continuous_visibility_and_opportunity_coverage_unknown",
)


def _integer(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} requires a nonnegative integer")
    return value


def _count_event_type(counts, value):
    key = str(value)
    if key not in counts and len(counts) >= 256:
        raise ValueError("combat event type cardinality exceeds summary limit")
    counts[key] += 1


def _number(data, key):
    value = data.get(key)
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError(f"{key} requires a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        raise ValueError(f"{key} requires a finite number")
    return value


def _flag(data, key):
    if key not in data:
        return {"value": None, "status": "unknown_optional_field_absent"}
    value = data[key]
    if type(value) is not bool:
        raise ValueError(f"{key} requires an explicit boolean")
    return {"value": value, "status": "explicit_raw_flag_unverified"}


def _observation(record, match_id):
    data, names = record.get("data"), record.get("resolved_names")
    if not isinstance(data, dict) or not isinstance(names, dict):
        raise ValueError("combat event data and callback names must be objects")
    if record.get("name_resolution") != "CombatLogNames_at_callback/v1":
        raise ValueError("callback-scoped name resolution required")
    if any(not isinstance(k, str) or not isinstance(v, str) or len(v) > 512 for k, v in names.items()):
        raise ValueError("callback names require bounded strings")
    event_type = data.get("type")
    if not isinstance(event_type, str) and type(event_type) is not int:
        raise ValueError("combat event type required")
    if isinstance(event_type, str) and len(event_type) > 128:
        raise ValueError("combat event type exceeds size limit")
    raw_ids = {key: _integer(data[key], key) for key in
               ("attacker_name", "target_name", "inflictor_name", "target_source_name", "damage_source_name")
               if key in data}
    raw_flags = {key: _flag(data, key)["value"] for key in
                 ("is_attacker_hero", "is_target_hero", "is_attacker_illusion", "is_target_illusion")
                 if key in data}
    rid = record["record_index"]
    row = {"t": "event_visibility", "source_domain": "combat_names",
        "source_record_index": rid, "source_ref": f"combat-names:{match_id}:record:{rid}",
        "event_type": event_type,
        "raw_name_ids": raw_ids,
        "resolved_names": {key: names[key] for key in raw_ids if key in names},
        "raw_actor_target_flags": raw_flags,
        "raw_teams": {key: _integer(data[key], key) for key in ("attacker_team", "target_team") if key in data},
        "raw_target_health": _number(data, "health"),
        "raw_timestamp": _number(data, "timestamp"),
        "raw_timestamp_raw": _number(data, "timestamp_raw"),
        "net_tick": _integer(record.get("net_tick"), "net tick"),
        "sequence_in_tick": _integer(record.get("sequence_in_tick"), "sequence in tick"),
        "raw_visibility": {"radiant": _flag(data, "is_visible_radiant"),
                           "dire": _flag(data, "is_visible_dire")},
        "game_time": None, "available_to_player_at": None,
        "entity_identity": None, "screen_cue": None,
        "perspective": "retrospective_world_observation", "validation": "unverified"}
    # Prefix features contain only this callback's selected operands. The full
    # file/extraction receipts live in metadata and never determine this hash.
    row["prefix_input_hash"] = content_hash(row)
    return row


def extract_event_visibility(
    source_path: str | Path, extraction: TraceResult, output_path: str | Path, *,
    expected_replay_sha256: str, expected_source_sha256: str,
    expected_extraction_sha256: str,
) -> dict:
    """Validate a complete names sidecar, atomically publish JSONL, return counts.

    Expected SHA256 values are mandatory source receipts. Match identity comes
    from the bound extraction; the names sidecar embeds replay SHA, not match ID.
    The source is scanned once, with bounded memory and no full-trace reparse.
    """
    for value, label in ((expected_replay_sha256, "replay SHA256"),
                         (expected_source_sha256, "combat source SHA256"),
                         (expected_extraction_sha256, "extraction SHA256")):
        _sha(value, label)
    match_id = _integer(extraction.replay.match_id, "match ID")
    manifest = extraction.replay.manifest
    if (manifest is None or manifest.match_id != match_id or manifest.replay_hash != expected_replay_sha256
            or extraction.audit.get("match_id") != match_id
            or extraction.audit.get("replay_sha256") != expected_replay_sha256
            or content_hash(asdict(extraction)) != expected_extraction_sha256):
        raise ValueError("extraction match/replay/hash binding mismatch")
    _sha(extraction.audit.get("trace_sha256"), "bound trace SHA256")
    if manifest.dataset_kind not in ("replay", "synthetic", "unknown"):
        raise ValueError("unsupported extraction dataset kind")
    source, target = Path(source_path), Path(output_path)
    if source.resolve() == target.resolve() or (target.exists() and os.path.samefile(source, target)):
        raise ValueError("output cannot overwrite combat source")
    target.parent.mkdir(parents=True, exist_ok=True)
    binding = {"match_id": match_id, "replay_sha256": expected_replay_sha256,
        "source_sha256": expected_source_sha256, "source_extraction_hash": expected_extraction_sha256,
        "bound_trace_sha256": extraction.audit["trace_sha256"], "dataset_kind": manifest.dataset_kind,
        "match_binding": "extraction_match_and_replay_sha_not_sidecar_embedded_match"}
    descriptor, temporary = tempfile.mkstemp(prefix="event-visibility-", suffix=".tmp", dir=target.parent)
    source_digest, output_digest = hashlib.sha256(), hashlib.sha256()
    counts, event_types = Counter(), Counter()
    flag_counts = {team: Counter() for team in ("radiant", "dire")}
    seen, footer, metadata = 0, None, None
    try:
        with os.fdopen(descriptor, "wb") as output:
            def write(row):
                encoded = (json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8")
                output.write(encoded)
                output_digest.update(encoded)

            write({"t": "meta", "schema_version": SCHEMA, "source_binding": binding,
                   "validation": "unverified", "limitations": list(LIMITATIONS)})
            with source.open("rb") as stream:
                for line in iter(lambda: stream.readline(MAX_RECORD_BYTES + 1), b""):
                    source_digest.update(line)
                    if len(line) > MAX_RECORD_BYTES:
                        raise ValueError("combat source record exceeds size limit")
                    if not line.strip():
                        continue
                    rec = strict_json(line.decode("utf-8-sig"))
                    if not isinstance(rec, dict) or type(rec.get("record_index")) is not int or rec["record_index"] != seen + 1:
                        raise ValueError("combat source requires consecutive record indices")
                    if footer is not None:
                        raise ValueError("combat source records follow completion footer")
                    seen += 1
                    kind = rec.get("t")
                    if not isinstance(kind, str):
                        raise ValueError("combat source record kind required")
                    counts[kind] += 1
                    if seen == 1:
                        if kind != "meta" or rec.get("schema_version") != "replay-combat-names.v1" or rec.get("replay_sha256") != expected_replay_sha256:
                            raise ValueError("combat source metadata replay/schema mismatch")
                        metadata = rec
                    elif kind == "trace_end":
                        footer = rec
                    elif kind == "combat_log":
                        row = _observation(rec, match_id)
                        for team, flag in row["raw_visibility"].items():
                            flag_counts[team]["unknown" if flag["value"] is None else "true" if flag["value"] else "false"] += 1
                        _count_event_type(event_types, row["event_type"])
                        write(row)
                    else:
                        raise ValueError("unsupported combat source record")
            if metadata is None or footer is None or footer.get("parser_completed") is not True:
                raise ValueError("completed combat source parser footer required")
            supplied = footer.get("counts")
            without_footer = dict(counts)
            without_footer.pop("trace_end", None)
            if not isinstance(supplied, dict) or any(type(v) is not int or v < 0 for v in supplied.values()) or supplied not in (without_footer, dict(counts)):
                raise ValueError("combat source footer counts mismatch")
            if source_digest.hexdigest() != expected_source_sha256:
                raise ValueError("combat source SHA256 mismatch")
            # The extraction need not share sidecar ordinals, but it must have
            # observed the same complete combat callback population.
            combat_count = extraction.audit.get("record_counts", {}).get("combat_log")
            if type(combat_count) is not int or combat_count != counts["combat_log"]:
                raise ValueError("combat callback population differs from bound extraction")
            summary = {"schema_version": SCHEMA, "source_binding": binding,
                "source_counts": dict(counts), "observation_count": counts["combat_log"],
                "raw_flag_counts": {team: {key: flag_counts[team][key] for key in ("true", "false", "unknown")} for team in flag_counts},
                "event_type_counts": dict(event_types), "validation": "unverified",
                "continuous_visibility_coverage": None, "screen_cue_count": 0,
                "training_eligible": False, "limitations": list(LIMITATIONS)}
            write({"t": "trace_end", "parser_completed": True, "summary": summary,
                   "records_sha256": output_digest.hexdigest(), "summary_sha256": content_hash(summary)})
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
        summary["output_sha256"] = output_digest.hexdigest()
        summary["payload_sha256"] = content_hash(summary)
        return summary
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_event_visibility_source(sidecarpath: str | Path, *, extraction: TraceResult) -> dict:
    """Validate the extracted JSONL seal and binding, return bounded counts only.

    The seal detects accidental edits, not human/external source verification.
    Original combat receipts remain declared provenance in this derivative.
    """
    complete_digest, record_digest = hashlib.sha256(), hashlib.sha256()
    meta, footer = None, None
    flag_counts = {team: Counter() for team in ("radiant", "dire")}
    event_types, observations, prior_rid = Counter(), 0, 1
    with Path(sidecarpath).open("rb") as stream:
        for line in iter(lambda: stream.readline(MAX_RECORD_BYTES + 1), b""):
            complete_digest.update(line)
            if len(line) > MAX_RECORD_BYTES:
                raise ValueError("event visibility record exceeds size limit")
            row = strict_json(line.decode("utf-8-sig"))
            if not isinstance(row, dict) or footer is not None:
                raise ValueError("invalid event visibility record/completion order")
            kind = row.get("t")
            if meta is None:
                if kind != "meta" or row.get("schema_version") != SCHEMA:
                    raise ValueError("event visibility metadata/schema required")
                meta = row
                binding = row.get("source_binding")
                manifest = extraction.replay.manifest
                if (not isinstance(binding, dict) or manifest is None
                        or binding.get("match_id") != extraction.replay.match_id
                        or manifest.match_id != extraction.replay.match_id
                        or extraction.audit.get("match_id") != extraction.replay.match_id
                        or binding.get("source_extraction_hash") != content_hash(asdict(extraction))
                        or binding.get("replay_sha256") != extraction.audit.get("replay_sha256")
                        or binding.get("replay_sha256") != manifest.replay_hash
                        or binding.get("bound_trace_sha256") != extraction.audit.get("trace_sha256")
                        or binding.get("dataset_kind") != manifest.dataset_kind
                        or row.get("validation") != "unverified" or row.get("limitations") != list(LIMITATIONS)):
                    raise ValueError("event visibility extraction binding mismatch")
                for key in ("source_extraction_hash", "replay_sha256", "bound_trace_sha256", "source_sha256"):
                    _sha(binding.get(key), key)
                _integer(binding["match_id"], "match ID")
                record_digest.update(line)
            elif kind == "trace_end":
                footer = row
                if row.get("parser_completed") is not True or row.get("records_sha256") != record_digest.hexdigest():
                    raise ValueError("event visibility completion/records seal mismatch")
            elif kind == "event_visibility":
                rid = _integer(row.get("source_record_index"), "source record index")
                if rid != prior_rid + 1:
                    raise ValueError("event visibility source ordinals must be consecutive")
                prior_rid = rid
                if (row.get("source_domain") != "combat_names"
                        or row.get("source_ref") != f"combat-names:{binding['match_id']}:record:{rid}"
                        or row.get("perspective") != "retrospective_world_observation"
                        or row.get("validation") != "unverified"
                        or any(row.get(key) is not None for key in ("entity_identity", "screen_cue", "game_time", "available_to_player_at"))):
                    raise ValueError("event visibility observation scope mismatch")
                expected_prefix = content_hash({key: value for key, value in row.items() if key != "prefix_input_hash"})
                if row.get("prefix_input_hash") != expected_prefix:
                    raise ValueError("event visibility prefix input hash mismatch")
                flags = row.get("raw_visibility")
                if not isinstance(flags, dict) or set(flags) != set(flag_counts):
                    raise ValueError("raw visibility flags required")
                for team, flag in flags.items():
                    if not isinstance(flag, dict) or set(flag) != {"value", "status"}:
                        raise ValueError("raw visibility flag shape mismatch")
                    value = flag["value"]
                    if value is not None and type(value) is not bool:
                        raise ValueError("raw visibility requires boolean or unknown")
                    if flag["status"] != ("unknown_optional_field_absent" if value is None else "explicit_raw_flag_unverified"):
                        raise ValueError("raw visibility status mismatch")
                    flag_counts[team]["unknown" if value is None else "true" if value else "false"] += 1
                event_type = row.get("event_type")
                if not isinstance(event_type, str) and type(event_type) is not int:
                    raise ValueError("event type required")
                _count_event_type(event_types, event_type)
                observations += 1
                record_digest.update(line)
            else:
                raise ValueError("unsupported event visibility record")
    if footer is None:
        raise ValueError("event visibility completion footer required")
    summary = footer.get("summary")
    source_counts = {"meta": 1, "combat_log": observations, "trace_end": 1}
    # Counter serialisation omits the combat key on a genuinely empty stream.
    if observations == 0:
        source_counts.pop("combat_log")
    actual_flags = {team: {key: flag_counts[team][key] for key in ("true", "false", "unknown")} for team in flag_counts}
    if (not isinstance(summary, dict) or footer.get("summary_sha256") != content_hash(summary)
            or summary.get("schema_version") != SCHEMA or summary.get("source_binding") != binding
            or summary.get("source_counts") != source_counts or summary.get("observation_count") != observations
            or summary.get("raw_flag_counts") != actual_flags or summary.get("event_type_counts") != dict(event_types)
            or summary.get("training_eligible") is not False or summary.get("validation") != "unverified"
            or summary.get("continuous_visibility_coverage") is not None or summary.get("screen_cue_count") != 0
            or summary.get("limitations") != list(LIMITATIONS)
            or extraction.audit.get("record_counts", {}).get("combat_log") != observations):
        raise ValueError("event visibility summary/extraction population mismatch")
    result = summary | {"output_sha256": complete_digest.hexdigest()}
    result["payload_sha256"] = content_hash(result)
    return result
