"""Allowlist projection. Enemy world state is deliberately never inspected.

Legacy replay has no verified observation events. Only the subject's own state
and the public roster can be projected; enemy visibility remains unknown.
"""
from __future__ import annotations

from dataclasses import dataclass

from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, content_hash
from dota_coach.models import ParsedReplay

POLICY_VERSION = "knowledge-own-state.v1"
OWN_FIELDS = ("x", "y", "hp", "max_hp", "mana", "level", "xp", "alive")


@dataclass(frozen=True)
class KnowledgeSnapshot:
    snapshot_id: str
    subject_player: str
    cutoff: TimeRef
    facts: tuple[Fact, ...]
    policy_version: str = POLICY_VERSION
    limitations: tuple[str, ...] = ("enemy_observability_unavailable",
                                      "screen_and_attention_unavailable",
                                      "extraction_unverified")

    def __post_init__(self):
        if not isinstance(self.facts, tuple):
            raise ValueError("snapshot facts must be immutable")
        cutoff = self.cutoff.game_time_ms
        for fact in self.facts:
            if fact.perspective not in ("team", "screen", "public"):
                raise ValueError("world fact cannot enter knowledge snapshot")
            allowed_own = fact.predicate in {f"self.{k}" for k in OWN_FIELDS}
            allowed_unknown = fact.predicate == "enemy.visibility" and fact.status == "unknown"
            if not allowed_own and not allowed_unknown:
                raise ValueError("predicate is not permitted by knowledge-own-state.v1")
            if allowed_own and fact.subject_ref != self.subject_player:
                raise ValueError("self fact belongs to another subject")
            if fact.status not in ("unknown", "conflict"):
                available = fact.available_at
                if available is None or cutoff is None or available.game_time_ms is None:
                    raise ValueError("known fact requires an availability cutoff")
                uncertainty = available.uncertainty_ms or 0
                if available.game_time_ms + uncertainty > cutoff:
                    raise ValueError("future fact cannot enter knowledge snapshot")
                if available.replay_tick is not None and self.cutoff.replay_tick is not None:
                    if available.replay_tick > self.cutoff.replay_tick:
                        raise ValueError("future replay tick cannot enter knowledge snapshot")
                    if available.replay_tick == self.cutoff.replay_tick and (
                            available.sequence_in_tick is None or self.cutoff.sequence_in_tick is None or
                            available.sequence_in_tick > self.cutoff.sequence_in_tick):
                        raise ValueError("same-tick availability ordering is unknown or future")

    @property
    def input_hash(self) -> str:
        return content_hash(self)


def project_knowledge(parsed: ParsedReplay, t: float, my_slot: int,
                      max_age: float = 1.0) -> KnowledgeSnapshot:
    cutoff = TimeRef(t * 1000)
    subject = f"match:{parsed.match_id}:slot:{my_slot}"
    frame = parsed.frame_at(t, max_age=max_age)
    me = frame.units.get(my_slot) if frame else None
    # This projected artifact has its own hash, independent of hidden/future raw
    # payload. Raw replay provenance is linked outside the evaluator in dossier.
    payload = {"match_id": parsed.match_id, "slot": my_slot,
               "sample_time": frame.time if frame else None,
               "values": {k: getattr(me, k) if me else None for k in OWN_FIELDS}}
    projection_hash = content_hash(payload)
    sample_time = TimeRef(frame.time * 1000, frame.tick, frame.sequence) if frame else cutoff
    sources = ((SourceRef(f"projection:{projection_hash}", projection_hash,
                          "replay_own_state_projection", "foresight.projection.v1",
                          f"state@{frame.time}/slot/{my_slot}", POLICY_VERSION),)
               if frame else ())
    facts = []
    for key in OWN_FIELDS:
        value = payload["values"][key]
        reason = ("stale_or_missing_frame" if frame is None else
                  "missing_subject" if me is None else "missing_property")
        facts.append(Fact(
            fact_id=f"{subject}@{t}:{key}", subject_ref=subject, predicate=f"self.{key}",
            value=value, status="observed" if value is not None else "unknown",
            valid_at=sample_time, available_at=sample_time if value is not None else None,
            perspective="team", observer_ref=subject, source_refs=sources,
            quality_flags=("extraction_unverified",),
            unknown_reason=reason if value is None else None))
    # Do not infer life status, locations or last-seen from complete enemy units.
    for slot, team in sorted(parsed.teams.items()):
        if team == parsed.teams.get(my_slot):
            continue
        enemy = f"match:{parsed.match_id}:slot:{slot}"
        facts.append(Fact(
            fact_id=f"{enemy}@{t}:visibility", subject_ref=enemy,
            predicate="enemy.visibility", value=None, status="unknown",
            valid_at=cutoff, available_at=None, perspective="team", observer_ref=subject,
            source_refs=(), unknown_reason="exact_visibility_not_extracted"))
    return KnowledgeSnapshot(f"knowledge:{content_hash((subject, t, projection_hash))}",
                             subject, cutoff, tuple(facts))
