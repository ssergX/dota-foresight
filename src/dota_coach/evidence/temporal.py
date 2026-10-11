"""Availability- and age-aware knowledge from explicit typed observations.

Unlike the legacy own-state adapter, this engine accepts only observations with
explicit observer/perspective, prefix clock intervals, and a versioned predicate
allowlist/TTL. It creates last-known/stale/conflict states; it never manufactures
visibility events from retrospective world data. Raw whole-file source receipts
stay in the caller's evidence store; projected references bind prefix operands.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from dota_coach.evidence.contracts import EntityRef, Fact, SourceRef, TimeRef, content_hash


@dataclass(frozen=True)
class TemporalKnowledgePolicy:
    version: str
    predicate_max_age_ms: tuple[tuple[str, float | None], ...]

    def __post_init__(self):
        if not isinstance(self.version, str) or not self.version or len(self.version) > 128:
            raise ValueError("temporal policy requires a bounded version")
        if not isinstance(self.predicate_max_age_ms, tuple):
            raise ValueError("temporal predicate policy must be immutable")
        seen = set()
        for pair in self.predicate_max_age_ms:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError("predicate TTL requires an immutable pair")
            predicate, ttl = pair
            if not isinstance(predicate, str) or not predicate or predicate in seen:
                raise ValueError("predicate policy is missing or duplicated")
            seen.add(predicate)
            if ttl is not None:
                try:
                    valid = type(ttl) in (int, float) and math.isfinite(ttl) and ttl >= 0
                except (ValueError, OverflowError):
                    valid = False
                if not valid:
                    raise ValueError("predicate TTL must be finite nonnegative or explicitly static")


@dataclass(frozen=True)
class TemporalKnowledgeState:
    subject_ref: str
    predicate: str
    status: str
    value: str | int | float | bool | None
    evidence_fact_ids: tuple[str, ...]
    min_age_ms: float | None
    max_age_ms: float | None
    max_age_policy_ms: float | None
    reason: str | None
    entity_refs: tuple[EntityRef, ...] = ()


@dataclass(frozen=True)
class TemporalKnowledgeSnapshot:
    subject_player: str
    cutoff: TimeRef
    policy: TemporalKnowledgePolicy
    dataset_kind: str
    states: tuple[TemporalKnowledgeState, ...]
    facts: tuple[Fact, ...]
    schema_version: str = "foresight.temporal-knowledge.v1"
    limitations: tuple[str, ...] = (
        "source_extraction_accuracy_not_validated_by_temporal_projection",
        "availability_is_caller_supplied_not_inferred_from_world",
        "raw_source_receipts_retained_in_caller_evidence_store",
        "last_known_is_not_current_visibility_or_attention")

    @property
    def input_hash(self):
        return content_hash(self)

    @property
    def snapshot_id(self):
        return "temporal-knowledge:" + self.input_hash


def _interval(time):
    if (time.game_time_ms is None or time.uncertainty_ms is None or
            time.clock_mapping_version in ("legacy/unverified", "unknown", "unavailable")):
        return None
    lower = time.game_time_ms - time.uncertainty_ms
    upper = time.game_time_ms + time.uncertainty_ms
    if not math.isfinite(lower) or not math.isfinite(upper):
        return None
    return lower, upper


def _before(time, cutoff):
    left, right = _interval(time), _interval(cutoff)
    if left is None or right is None or not time.definitely_available_before(cutoff):
        return False
    if left[1] < right[0]:
        return True
    if time.replay_tick is None or cutoff.replay_tick is None:
        return False
    if time.replay_tick < cutoff.replay_tick:
        return True
    return (time.replay_tick == cutoff.replay_tick and time.sequence_in_tick is not None
            and cutoff.sequence_in_tick is not None and time.sequence_in_tick < cutoff.sequence_in_tick)


def _later(left, right):
    """True only when right's validity definitely follows left's validity."""
    a, b = _interval(left.valid_at), _interval(right.valid_at)
    if left.valid_at.clock_mapping_version != right.valid_at.clock_mapping_version:
        return False
    if a[1] < b[0]:
        return True
    if a[1] == b[0] and left.valid_at.replay_tick is not None and right.valid_at.replay_tick is not None:
        if right.valid_at.replay_tick > left.valid_at.replay_tick:
            return True
        if right.valid_at.replay_tick == left.valid_at.replay_tick:
            return (left.valid_at.sequence_in_tick is not None and right.valid_at.sequence_in_tick is not None
                    and right.valid_at.sequence_in_tick > left.valid_at.sequence_in_tick)
    return False


def _projected_ref(fact, entity):
    values = asdict(fact)
    operand = {key: values[key] for key in ("subject_ref", "predicate", "value", "status",
        "valid_at", "available_at", "perspective", "observer_ref", "method_version", "quality_flags", "unknown_reason")}
    operand["entity_ref"] = asdict(entity) if entity is not None else None
    digest = content_hash(operand)
    # A raw source's complete-file digest is a provenance receipt, not a
    # decision-time operand. Its changes cannot change this projection digest.
    return SourceRef("temporal-operand:" + digest, digest, "available_fact_projection",
                     "foresight.temporal-operand.v1", "fact:" + fact.fact_id,
                     "temporal-knowledge.v1")


def project_temporal_knowledge(facts: tuple[Fact, ...], *, subject_player: str,
                               cutoff: TimeRef, policy: TemporalKnowledgePolicy,
                               dataset_kind: str = "unknown",
                               entity_bindings: tuple[tuple[str, EntityRef], ...] = (),
                               queries: tuple[tuple[str, str], ...] = ()) -> TemporalKnowledgeSnapshot:
    """Resolve only definitely available observations under explicit TTL policy.

    Overlapping contradictory validity intervals remain conflict. A later
    available callback carrying older validity does not overwrite newer facts.
    World/future/unavailable observations do not contribute counts or hashes.
    `queries` explicitly requests missing states without deriving subjects from
    excluded hidden/future observations. Entity bindings refer to exact fact IDs.
    """
    if not isinstance(facts, tuple) or not all(isinstance(f, Fact) for f in facts):
        raise ValueError("observations must be an immutable tuple of typed Fact")
    if not isinstance(subject_player, str) or not subject_player:
        raise ValueError("observer subject is required")
    if not isinstance(cutoff, TimeRef) or not isinstance(policy, TemporalKnowledgePolicy):
        raise ValueError("typed cutoff and policy are required")
    if dataset_kind not in ("replay", "synthetic", "unknown"):
        raise ValueError("dataset kind cannot be promoted")
    if not isinstance(entity_bindings, tuple) or not isinstance(queries, tuple):
        raise ValueError("entity bindings and queries must be immutable")
    entities = {}
    for binding in entity_bindings:
        if not isinstance(binding, tuple) or len(binding) != 2 or not isinstance(binding[1], EntityRef):
            raise ValueError("entity binding requires exact fact ID and typed EntityRef")
        fid, entity = binding
        if not isinstance(fid, str) or not fid or fid in entities:
            raise ValueError("entity binding fact ID missing or duplicated")
        entities[fid] = entity
    ttls = dict(policy.predicate_max_age_ms)
    groups = {}
    for query in queries:
        if not isinstance(query, tuple) or len(query) != 2 or not all(isinstance(x, str) and x for x in query):
            raise ValueError("knowledge query requires subject and predicate")
        if query[1] not in ttls:
            raise ValueError("query predicate absent from explicit temporal policy")
        groups.setdefault(query, [])
    selected_ids = set()
    for fact in facts:
        # Do not examine values, subjects or source receipts of excluded facts.
        if fact.perspective == "world" or fact.available_at is None or not _before(fact.available_at, cutoff):
            continue
        if fact.predicate not in ttls or not _before(fact.valid_at, cutoff):
            continue
        if fact.perspective in ("screen", "team") and fact.observer_ref != subject_player:
            continue
        if fact.perspective == "public" and fact.observer_ref not in (None, subject_player):
            continue
        if fact.predicate.startswith("self.") and fact.subject_ref != subject_player:
            continue
        if fact.fact_id in selected_ids:
            raise ValueError("duplicate available fact ID")
        selected_ids.add(fact.fact_id)
        groups.setdefault((fact.subject_ref, fact.predicate), []).append(fact)
    states, resolved = [], []
    for (subject, predicate), candidates in sorted(groups.items()):
        ttl = ttls[predicate]
        frontier = sorted((f for f in candidates if not any(_later(f, other) for other in candidates)), key=lambda f: f.fact_id)
        bound = tuple(sorted({entities[f.fact_id] for f in frontier if f.fact_id in entities},
                             key=lambda e: (e.replay_id, e.entity_index, e.generation)))
        reason, value, min_age, max_age = None, None, None, None
        if not frontier:
            status, reason = "unknown", "no_definitely_available_observation"
        elif len(bound) > 1:
            status, reason = "conflict", "entity_generation_or_identity_conflict"
        elif any(f.status in ("unknown", "conflict") for f in frontier):
            status = "conflict" if any(f.status == "conflict" for f in frontier) else "unknown"
            reason = "explicit_observation_" + status
        elif len({content_hash((type(f.value).__name__, f.value)) for f in frontier}) > 1:
            status, reason = "conflict", "contradictory_overlapping_last_known_values"
        else:
            cmin, cmax = _interval(cutoff)
            min_age = max(0, min(cmin - _interval(f.valid_at)[1] for f in frontier))
            max_age = max(0, max(cmax - _interval(f.valid_at)[0] for f in frontier))
            if not math.isfinite(min_age) or not math.isfinite(max_age):
                status, reason, min_age, max_age = "unknown", "age_interval_overflow", None, None
            elif ttl is not None and min_age > ttl:
                status, reason = "stale", "explicit_predicate_age_policy_exceeded"
            elif ttl is not None and max_age > ttl:
                status, reason = "unknown", "staleness_boundary_overlaps_uncertainty"
            else:
                status = "last_known"
                value = frontier[0].value
        evidence = tuple(f.fact_id for f in frontier)
        states.append(TemporalKnowledgeState(subject, predicate, status, value, evidence,
            min_age, max_age, ttl, reason, bound))
        projected_refs = tuple(_projected_ref(f, entities.get(f.fact_id)) for f in frontier)
        resolved_status = ("estimated" if any(f.status == "estimated" for f in frontier) else
            "derived" if any(f.status == "derived" for f in frontier) else "observed") if status == "last_known" else "conflict" if status == "conflict" else "unknown"
        flags = tuple(sorted({"last_known_not_current_visibility"} |
                             {flag for fact in frontier for flag in fact.quality_flags}))
        valid_at = frontier[0].valid_at if status == "last_known" else cutoff
        available_at = frontier[0].available_at if status == "last_known" else None
        resolved.append(Fact("temporal:" + content_hash((subject_player, subject, predicate, asdict(cutoff), policy.version, evidence)),
            subject, predicate, value, resolved_status, valid_at, available_at,
            "public" if frontier and all(f.perspective == "public" for f in frontier) else "team",
            projected_refs, derived_from=evidence, observer_ref=subject_player,
            method_version=policy.version, quality_flags=flags,
            unknown_reason=reason if value is None else None))
    return TemporalKnowledgeSnapshot(subject_player, cutoff, policy, dataset_kind, tuple(states), tuple(resolved))
