"""Source-local brackets of TP/smoke modifier observations.

These are callback brackets, not verified buff lifetimes. A removal callback
does not establish arrival, interruption, expiration, or smoke break. Item-use
markers are retained separately: no cross-source or temporal proximity join is
performed. Exact names are not entity generations and do not prove visibility.
"""
from __future__ import annotations

from copy import deepcopy
import math

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.semantic_events import SCHEMA as EVENTS_SCHEMA

SCHEMA = "foresight.semantic-lifecycles.v1"
DOMAINS = ("trace", "combat_names", "provider")
REPLAY_DOMAINS = DOMAINS[:2]
MODIFIERS = {"tp": "modifier_teleporting", "smoke": "modifier_smoke_of_deceit"}
USES = {"tp_use_observed": {"item_tpscroll", "item_travel_boots", "item_travel_boots_2"},
        "smoke_use_observed": {"item_smoke_of_deceit"}}
MODIFIER_KINDS = frozenset(f"{category}_modifier_{suffix}" for category in MODIFIERS
                         for suffix in ("applied", "removed"))
OTHER_KINDS = frozenset({"buyback_observed", "building_destroyed_observed", "roshan_killed_observed"})
EVENT_FIELDS = ("event_id", "source_ref", "source_domain", "source_record_index", "kind", "actor",
                "target", "ability_or_item", "game_time", "raw_timestamp", "timestamp_source",
                "timing_evidence_records", "dataset_kind", "validation", "perspective",
                "quality_flags", "unknown_fields")
DETAIL_FIELDS = ("modifier_purged", "modifier_elapsed_duration", "modifier_duration",
                 "is_target_illusion", "is_attacker_illusion", "value", "type", "key", "unit",
                 "player_slot", "team", "account_id", "hero_id")
UNKNOWN = ["historical_modifier_semantics", "player_visibility", "choice_time",
           "feasibility", "entity_generation", "lifecycle_outcome", "removal_reason"]
SUBJECT_RULE = "modifier_target_only_no_attacker_fallback_caster_is_not_subject"


def _integer(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} requires a nonnegative integer")
    return value


def _text(value, label, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"{label} requires a bounded nonempty string")
    return value


def _finite(value, label):
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError(f"{label} requires a finite number or null")
    try:
        valid = math.isfinite(value)
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        raise ValueError(f"{label} requires a finite number or null")
    return value


def _header(report):
    if not isinstance(report, dict) or report.get("schema_version") != EVENTS_SCHEMA:
        raise ValueError("semantic events schema mismatch")
    _integer(report.get("match_id"), "match ID")
    sha = report.get("replay_sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("replay SHA256 requires lowercase hexadecimal")
    if report.get("dataset_kind") not in ("replay", "synthetic", "unknown"):
        raise ValueError("dataset kind cannot be promoted")
    if report.get("validation") != "unverified":
        raise ValueError("semantic markers cannot grant validation")
    if not isinstance(report.get("lanes"), dict):
        raise ValueError("semantic lanes must be an object")
    return {key: report[key] for key in ("match_id", "replay_sha256", "dataset_kind")}


def _event(row, domain, header):
    if not isinstance(row, dict) or row.get("source_domain") != domain:
        raise ValueError("source ordinal domains cannot be mixed")
    if row.get("dataset_kind") != header["dataset_kind"]:
        raise ValueError("event dataset kind contradicts source")
    if row.get("validation") != "unverified":
        raise ValueError("semantic markers cannot grant gameplay validation")
    if row.get("perspective") != "retrospective_world_observation":
        raise ValueError("semantic markers cannot grant player perspective")
    _text(row.get("event_id"), "event ID")
    ref = _text(row.get("source_ref"), "source ref")
    for key in ("actor", "target", "ability_or_item"):
        _text(row.get(key), key, optional=True)
    _text(row.get("kind"), "kind")
    _text(row.get("timestamp_source"), "timestamp source")
    time = _finite(row.get("game_time"), "game time")
    _finite(row.get("raw_timestamp"), "raw timestamp")
    refs = row.get("timing_evidence_records")
    if not isinstance(refs, list):
        raise ValueError("timing evidence records must be an array")
    for index in refs:
        _integer(index, "timing record")
    if domain in REPLAY_DOMAINS:
        rid = _integer(row.get("source_record_index"), "source record")
        prefix = "trace" if domain == "trace" else "combat-names"
        if ref != f"{prefix}:{header['match_id']}:record:{rid}":
            raise ValueError("source reference/replay identity mismatch")
        if any(index > rid for index in refs):
            raise ValueError("future clock evidence is forbidden")
        if time is not None and (not refs or row["timestamp_source"] == "unavailable"):
            raise ValueError("game time requires prefix clock evidence")
        if domain == "combat_names" and time is not None:
            raise ValueError("combat names engine clock is not a game clock")
    else:
        if row.get("source_record_index") is not None or refs:
            raise ValueError("provider is not a source-local replay ordinal")
        if not ref.startswith(f"provider:{header['match_id']}:"):
            raise ValueError("provider replay identity mismatch")
    for key in ("quality_flags", "unknown_fields"):
        if not isinstance(row.get(key), list) or not all(isinstance(v, str) for v in row[key]):
            raise ValueError(f"{key} must be an array of strings")
    if not isinstance(row.get("raw_details"), dict):
        raise ValueError("raw details must be an object")
    for key in ("is_target_illusion", "is_attacker_illusion"):
        if key in row["raw_details"] and type(row["raw_details"][key]) is not bool:
            raise ValueError("illusion provenance requires a boolean")
    kind = row["kind"]
    if kind not in set(USES) | MODIFIER_KINDS | OTHER_KINDS:
        raise ValueError("unsupported semantic marker kind")
    if domain == "provider" and (kind in USES or kind in MODIFIER_KINDS):
        raise ValueError("provider cannot supply replay-local TP/smoke markers")
    if kind in USES and row["ability_or_item"] not in USES[kind]:
        raise ValueError("item-use marker/item identity mismatch")
    for category, modifier in MODIFIERS.items():
        if kind in (f"{category}_modifier_applied", f"{category}_modifier_removed"):
            if row["ability_or_item"] != modifier:
                raise ValueError("modifier marker identity mismatch")
    # Complete source hashes or hidden/post-match metadata embedded in an event
    # are not clock-local operands and cannot alter the prefix projection.
    result = {key: deepcopy(row.get(key)) for key in EVENT_FIELDS}
    result["raw_details"] = {key: deepcopy(row["raw_details"][key]) for key in DETAIL_FIELDS
                             if key in row["raw_details"]}
    return result


def _clock(event):
    return {key: event.get(key) for key in
            ("game_time", "raw_timestamp", "timestamp_source", "timing_evidence_records")}


def _bracket(event, category, *, starts, prefix, header):
    modifier = MODIFIERS[category]
    origin = starts[0] if starts else event
    return {"interval_id": "modifier-bracket:" + content_hash({
                **header, "domain": event["source_domain"], "origin_source_ref": origin["source_ref"],
                "category": category, "subject": event["target"], "modifier": modifier,
                "illusion": event["raw_details"].get("is_target_illusion")}),
            "category": category, "modifier": modifier, "subject": event["target"],
            "subject_rule": SUBJECT_RULE,
            "subject_identity_quality": "exact_callback_name_without_entity_generation",
            "subject_is_illusion": event["raw_details"].get("is_target_illusion"),
            "source_domain": event["source_domain"], "apply_refs": [], "remove_ref": None,
            "start_clock": _clock(starts[0]) if starts else None, "end_clock": None,
            "observed_timestamp_delta": None, "timestamp_delta_status": "unknown",
            "status": "right_censored_at_prefix_boundary" if prefix else "right_censored_at_observed_marker_end",
            "left_censored": not bool(starts), "right_censored": True,
            "ambiguity": [], "quality_flags": ["historical_modifier_semantics_unverified",
                "callback_order_not_verified_simulation_order", "entity_generation_unresolved"],
            "lifecycle_outcome": "unknown", "removal_reason": "unknown",
            "arrival": "unknown" if category == "tp" else "not_applicable",
            "interruption": "unknown" if category == "tp" else "not_applicable",
            "smoke_break": "unknown" if category == "smoke" else "not_applicable",
            "validation": "unverified", "training_eligible": False,
            "unknown_fields": list(UNKNOWN)}


def _fold(rows, domain, *, header, prefix=False):
    rows = sorted(rows, key=lambda e: (e["source_record_index"], e["event_id"])) if domain in REPLAY_DOMAINS else rows
    uses, brackets, unresolved, active = [], [], [], {}
    seen_ids, seen_refs = set(), set()
    for event in rows:
        if event["event_id"] in seen_ids or event["source_ref"] in seen_refs:
            raise ValueError("duplicate semantic marker identity/source ref")
        seen_ids.add(event["event_id"])
        seen_refs.add(event["source_ref"])
        kind = event["kind"]
        if kind in USES:
            uses.append({"use_id": "observed-use:" + content_hash({**header, "source_ref": event["source_ref"],
                "domain": domain, "kind": kind}), "category": "tp" if kind.startswith("tp_") else "smoke",
                "actor": event["actor"], "actor_is_illusion": event["raw_details"].get("is_attacker_illusion"),
                "source_ref": event["source_ref"], "clock": _clock(event),
                "interval_association": "not_established", "lifecycle_outcome": "unknown",
                "validation": "unverified", "training_eligible": False})
            continue
        if kind not in MODIFIER_KINDS:
            continue
        category = "tp" if kind.startswith("tp_") else "smoke"
        if event["target"] is None:
            unresolved.append({"source_ref": event["source_ref"], "kind": kind,
                "actor": event["actor"], "reason": "modifier_subject_unknown_no_caster_fallback",
                "clock": _clock(event), "lifecycle_outcome": "unknown"})
            continue
        key = (category, event["ability_or_item"], event["target"], event["raw_details"].get("is_target_illusion"))
        if kind.endswith("applied"):
            if key not in active:
                bracket = _bracket(event, category, starts=[event], prefix=prefix, header=header)
                brackets.append(bracket)
                active[key] = bracket
            bracket = active[key]
            bracket["apply_refs"].append(event["source_ref"])
            if len(bracket["apply_refs"]) > 1:
                bracket["ambiguity"] = ["repeated_apply_refresh_stack_duplicate_or_entity_collision_unresolved"]
        else:
            bracket = active.pop(key, None)
            if bracket is None:
                bracket = _bracket(event, category, starts=[], prefix=prefix, header=header)
                brackets.append(bracket)
                bracket["quality_flags"].append("remove_without_prior_apply_in_observed_window")
            bracket["remove_ref"] = event["source_ref"]
            bracket["end_clock"] = _clock(event)
            bracket["right_censored"] = False
            bracket["status"] = "left_censored_removal_observed" if bracket["left_censored"] else "apply_remove_markers_bracketed"
            start_clock, end_clock = bracket["start_clock"], bracket["end_clock"]
            if (start_clock and not bracket["ambiguity"] and
                    start_clock["timestamp_source"] != "unavailable" and
                    start_clock["timestamp_source"] == end_clock["timestamp_source"]):
                start, end = start_clock["raw_timestamp"], end_clock["raw_timestamp"]
                if start is not None and end is not None:
                    if end >= start:
                        difference = end - start
                        if math.isfinite(difference):
                            bracket["observed_timestamp_delta"] = difference
                            bracket["timestamp_delta_status"] = "raw_clock_difference_not_verified_modifier_duration"
                        else:
                            bracket["quality_flags"].append("raw_clock_difference_overflow")
                    else:
                        bracket["quality_flags"].append("raw_clock_regression")
            # Raw purged/duration fields remain evidence only, never an end reason.
    return {"source_domain": domain, "subject_rule": SUBJECT_RULE,
            "events": rows, "uses": uses, "intervals": brackets, "unresolved_markers": unresolved,
            "coverage": {"observed_markers": len(rows), "uses": len(uses),
                "modifier_brackets": len(brackets), "unresolved_modifier_markers": len(unresolved)},
            "causal_joins": "not_performed", "validation": "unverified", "training_eligible": False}


def _result(header, lanes, *, scope, cutoff=None):
    result = {"schema_version": SCHEMA, **header, "scope": scope, "lanes": lanes,
              "subject_rule": SUBJECT_RULE, "perspective": "retrospective_world_observation",
              "validation": "unverified", "training_eligible": False,
              "cross_source_deduplication": "not_performed_identity_and_clock_join_unverified",
              "opportunity_coverage": "unknown", "unknown_fields": list(UNKNOWN),
              "boundary": "strictly_before_source_callback_record" if cutoff is not None else "observed_semantic_marker_window",
              "censoring_semantics": "observed_window_boundary_not_verified_effect_start_or_end"}
    if cutoff is not None:
        result["cutoff_record_index"] = cutoff
    return result


def build_semantic_lifecycles(semantic_events: dict) -> dict:
    """Fold each lane independently; preserve complete retrospective receipts."""
    header = _header(semantic_events)
    lanes = {}
    for domain, values in semantic_events["lanes"].items():
        if domain not in DOMAINS or not isinstance(values, list):
            raise ValueError("unsupported semantic source lane")
        rows = [_event(row, domain, header) for row in values]
        lanes[domain] = _fold(rows, domain, header=header)
    result = _result(header, lanes, scope="retrospective_source_local")
    result["source_receipts"] = {key: semantic_events[key] for key in
        ("payload_sha256", "source_sha256", "source_match_binding") if key in semantic_events}
    result["payload_sha256"] = content_hash(result)
    return result


def project_semantic_lifecycles(semantic_events: dict, source_domain: str,
                               cutoff_record_index: int) -> dict:
    """Project exactly one ordinal domain without reading future payloads.

    Full artifact hashes, coverage metadata and other source lanes are omitted.
    Replay binary identity is retained. This is a world-observation projection,
    never a claim that the player knew the projected facts.
    """
    header = _header(semantic_events)
    _integer(cutoff_record_index, "cutoff record")
    if source_domain not in REPLAY_DOMAINS:
        raise ValueError("provider cannot be used as replay prefix evidence")
    values = semantic_events["lanes"].get(source_domain)
    if not isinstance(values, list):
        raise ValueError("selected source lane is unavailable")
    selected = []
    for row in values:
        if not isinstance(row, dict):
            raise ValueError("source marker must be an object")
        rid = _integer(row.get("source_record_index"), "source record")
        if rid >= cutoff_record_index:
            continue
        selected.append(_event(row, source_domain, header))
    result = _result(header, {source_domain: _fold(selected, source_domain, header=header, prefix=True)},
                     scope="source_local_prefix", cutoff=cutoff_record_index)
    result["source_domain"] = source_domain
    result["prefix_sha256"] = content_hash(result)
    return result
