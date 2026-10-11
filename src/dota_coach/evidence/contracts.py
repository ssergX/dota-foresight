from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from dataclasses import asdict, dataclass, is_dataclass
from typing import Literal

SCHEMA_VERSION = "foresight.evidence.v1"


def canonical_json(value) -> str:
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def content_hash(value) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TimeRef:
    game_time_ms: float | None
    replay_tick: int | None = None
    sequence_in_tick: int | None = None
    uncertainty_ms: float | None = None
    clock_mapping_version: str = "legacy/unverified"
    order_status: Literal["verified", "partial", "unknown"] = "unknown"

    def __post_init__(self):
        if self.game_time_ms is not None and (type(self.game_time_ms) not in (int, float)
                                             or not math.isfinite(self.game_time_ms)):
            raise ValueError("non-finite game time")
        if self.uncertainty_ms is not None and (
                type(self.uncertainty_ms) not in (int, float) or
                not math.isfinite(self.uncertainty_ms) or self.uncertainty_ms < 0):
            raise ValueError("invalid time uncertainty")
        for value in (self.replay_tick, self.sequence_in_tick):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("tick and sequence must be nonnegative integers or unknown")
        if self.order_status not in ("verified", "partial", "unknown"):
            raise ValueError("invalid time order status")

    def definitely_available_before(self, cutoff: TimeRef) -> bool:
        if self.game_time_ms is None or cutoff.game_time_ms is None:
            return False
        if self.uncertainty_ms is None or cutoff.uncertainty_ms is None:
            return False
        if self.clock_mapping_version != cutoff.clock_mapping_version:
            return False
        # Compare the declared decimal intervals without rounding away a small
        # positive uncertainty at a large clock boundary.
        latest = Fraction(str(self.game_time_ms)) + Fraction(str(self.uncertainty_ms))
        earliest = Fraction(str(cutoff.game_time_ms)) - Fraction(str(cutoff.uncertainty_ms))
        if latest > earliest:
            return False
        if self.replay_tick is not None and cutoff.replay_tick is not None:
            if self.replay_tick > cutoff.replay_tick:
                return False
            if self.replay_tick == cutoff.replay_tick:
                if self.sequence_in_tick is None or cutoff.sequence_in_tick is None:
                    return False
                if self.sequence_in_tick > cutoff.sequence_in_tick:
                    return False
        return True


@dataclass(frozen=True)
class SourceRef:
    artifact_id: str
    content_hash: str
    provider: str
    schema_version: str
    locator: str
    extractor_version: str = "unknown"

    def __post_init__(self):
        if not all((self.artifact_id, self.content_hash, self.provider, self.locator)):
            raise ValueError("source must identify an artifact and locator")


@dataclass(frozen=True)
class EntityRef:
    replay_id: str
    entity_index: int
    generation: int

    def __post_init__(self):
        if not self.replay_id or self.entity_index < 0 or self.generation < 0:
            raise ValueError("invalid entity identity")


@dataclass(frozen=True)
class Fact:
    fact_id: str
    subject_ref: str
    predicate: str
    value: str | int | float | bool | None
    status: Literal["observed", "derived", "estimated", "unknown", "conflict"]
    valid_at: TimeRef
    available_at: TimeRef | None
    perspective: Literal["world", "team", "screen", "public"]
    source_refs: tuple[SourceRef, ...]
    derived_from: tuple[str, ...] = ()
    observer_ref: str | None = None
    method_version: str = "legacy/unverified"
    quality_flags: tuple[str, ...] = ()
    unknown_reason: str | None = None

    def __post_init__(self):
        if not self.fact_id or not self.predicate or not self.subject_ref:
            raise ValueError("fact identity is required")
        if self.status not in ("observed", "derived", "estimated", "unknown", "conflict"):
            raise ValueError("invalid fact status")
        if self.perspective not in ("world", "team", "screen", "public"):
            raise ValueError("invalid fact perspective")
        if self.status in ("unknown", "conflict"):
            if self.value is not None or not self.unknown_reason:
                raise ValueError("unknown/conflicting fact requires null and reason")
        elif self.value is None or not self.source_refs:
            raise ValueError("known fact requires a value and source")
        if self.value is not None and not isinstance(self.value, (str, int, float, bool)):
            raise ValueError("fact value must be a scalar; nested world payload is forbidden")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("non-finite fact value")
        if not isinstance(self.source_refs, tuple) or not isinstance(self.derived_from, tuple):
            raise ValueError("evidence references must be immutable tuples")
        if not all(isinstance(s, SourceRef) for s in self.source_refs):
            raise ValueError("fact source must be SourceRef")
        if not isinstance(self.quality_flags, tuple):
            raise ValueError("quality flags must be immutable")


@dataclass(frozen=True)
class CapabilityStatus:
    capability_id: str
    implementation: Literal["absent", "implemented"] = "absent"
    validation: Literal["unverified", "validated", "regressed"] = "unverified"
    limitations: tuple[str, ...] = ()
    validation_refs: tuple[str, ...] = ()
    patch: str | None = None

    def __post_init__(self):
        if self.implementation not in ("absent", "implemented"):
            raise ValueError("invalid implementation status")
        if self.validation not in ("unverified", "validated", "regressed"):
            raise ValueError("invalid validation status")
        if self.validation == "validated" and (
                self.implementation != "implemented" or not self.validation_refs or not self.patch):
            raise ValueError("validated capability requires implementation, patch and proofs")


@dataclass(frozen=True)
class ReplayManifest:
    replay_hash: str
    match_id: int
    schema_version: str = "legacy-jsonl"
    extractor_name: str = "unknown"
    extractor_version: str = "unknown"
    timebase_version: str = "legacy/unverified"
    game_build: str | None = None
    patch: str | None = None
    completeness: Literal["complete", "partial", "unknown"] = "unknown"
    parse_warnings: tuple[str, ...] = ()
    capabilities: tuple[CapabilityStatus, ...] = ()
    dataset_kind: Literal["replay", "synthetic", "unknown"] = "unknown"

    def __post_init__(self):
        if not self.replay_hash or self.completeness not in ("complete", "partial", "unknown"):
            raise ValueError("invalid replay manifest")
        if self.dataset_kind not in ("replay", "synthetic", "unknown"):
            raise ValueError("invalid dataset kind")
        if len({c.capability_id for c in self.capabilities}) != len(self.capabilities):
            raise ValueError("duplicate capability")

    def supports(self, capability_id: str) -> bool:
        return any(c.capability_id == capability_id and c.implementation == "implemented"
                   and c.validation == "validated" and c.patch == self.patch
                   for c in self.capabilities)


def legacy_manifest(replay_hash: str, match_id: int) -> ReplayManifest:
    return ReplayManifest(
        replay_hash=replay_hash, match_id=match_id,
        parse_warnings=("legacy_schema", "unverified_player_mapping", "unverified_timebase"),
        capabilities=tuple(CapabilityStatus(name, "implemented", limitations=("unverified",))
                           for name in ("primary_hero_identity", "positions_resources",
                                        "game_clock", "ward_lifecycle")) + (
            CapabilityStatus("exact_team_visibility"), CapabilityStatus("inventory_abilities"),
            CapabilityStatus("cast_control_events"),
            CapabilityStatus("reaction_cue_available_to_subject")))
