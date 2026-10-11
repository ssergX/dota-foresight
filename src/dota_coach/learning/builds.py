from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from dota_coach.learning.study import MatchSource


@dataclass(frozen=True)
class PurchaseObservation:
    match_id: int
    item_id: str
    game_time_seconds: float | None
    source: MatchSource
    source_event_id: str

    def __post_init__(self):
        if not isinstance(self.source, MatchSource) or type(self.match_id) is not int or self.match_id <= 0 or self.source.match_id != self.match_id:
            raise ValueError("purchase source match mismatch")
        if any(not isinstance(value, str) or not value for value in (self.item_id, self.source_event_id)):
            raise ValueError("purchase item and source event required")
        t = self.game_time_seconds
        if t is not None and (isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t)):
            raise ValueError("finite purchase time or unknown required")


@dataclass(frozen=True)
class PurchaseSequence:
    match_id: int | None
    status: Literal["descriptive", "unavailable"]
    purchases: tuple[PurchaseObservation, ...]
    temporal_order: Literal["partial", "known", "unknown"]
    optimality: Literal["not_established"] = "not_established"
    limitations: tuple[str, ...] = ("Покупки описывают этот матч; популярность и победа не доказывают оптимальность билда.",)


def describe_purchase_sequence(purchases: tuple[PurchaseObservation, ...]) -> PurchaseSequence:
    if not isinstance(purchases, tuple):
        raise TypeError("immutable purchase sequence required")
    if any(not isinstance(p, PurchaseObservation) for p in purchases):
        raise TypeError("typed purchase observations required")
    ids = {p.match_id for p in purchases}
    if len(ids) > 1 or len({p.source_event_id for p in purchases}) != len(purchases):
        raise ValueError("purchase sequence requires one match and unique source events")
    if not purchases:
        return PurchaseSequence(None, "unavailable", (), "unknown")
    timed = tuple(p for p in purchases if p.game_time_seconds is not None)
    # Equal timestamps do not establish command/purchase ordering.
    order = "known" if len(timed) == len(purchases) and len({p.game_time_seconds for p in timed}) == len(timed) else "partial"
    ordered = tuple(sorted(timed, key=lambda p: p.game_time_seconds)) + tuple(p for p in purchases if p.game_time_seconds is None)
    return PurchaseSequence(next(iter(ids)), "descriptive", ordered, order)


@dataclass(frozen=True)
class ContextFact:
    key: str
    value: str | int | float | bool | None
    status: Literal["known", "unknown"]
    evidence_refs: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.key, str) or not self.key or self.status not in ("known", "unknown") or not isinstance(self.evidence_refs, tuple):
            raise ValueError("invalid context fact")
        if any(not isinstance(ref, str) or not ref for ref in self.evidence_refs):
            raise TypeError("string context references required")
        if self.value is not None and type(self.value) not in (str, int, float, bool):
            raise TypeError("scalar context value required")
        if type(self.value) is float and not math.isfinite(self.value):
            raise ValueError("finite context value required")
        if self.status == "known" and (self.value is None or not self.evidence_refs):
            raise ValueError("known context requires evidence")
        if self.status == "unknown" and self.value is not None:
            raise ValueError("unknown context must not invent a value")


@dataclass(frozen=True)
class BuildRule:
    rule_id: str
    version: str
    patch: str
    hero_id: int
    role: str
    conditions: tuple[tuple[str, str | int | float | bool], ...]
    options: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    revisit_conditions: tuple[str, ...]
    mechanics_refs: tuple[str, ...]
    validation_status: Literal["validated", "unverified", "synthetic"] = "unverified"
    validation_refs: tuple[str, ...] = ()

    def __post_init__(self):
        if any(not isinstance(value, str) or not value for value in (self.rule_id, self.version, self.patch, self.role)) or type(self.hero_id) is not int or self.hero_id <= 0:
            raise ValueError("versioned build scope required")
        for v in (self.conditions, self.options, self.tradeoffs, self.revisit_conditions, self.mechanics_refs, self.validation_refs):
            if not isinstance(v, tuple):
                raise TypeError("immutable build rule required")
        if any(not isinstance(ref, str) or not ref for ref in self.options + self.tradeoffs + self.revisit_conditions + self.mechanics_refs + self.validation_refs):
            raise TypeError("string build references required")
        if self.validation_status not in ("validated", "unverified", "synthetic"):
            raise ValueError("invalid build validation")
        if any(not isinstance(c, tuple) or len(c) != 2 or not isinstance(c[0], str) or not c[0]
               or type(c[1]) not in (str, int, float, bool) or (type(c[1]) is float and not math.isfinite(c[1])) for c in self.conditions):
            raise ValueError("typed scalar build conditions required")
        if len({c[0] for c in self.conditions}) != len(self.conditions):
            raise ValueError("duplicate build condition")
        if self.validation_status == "validated" and (not self.conditions or not self.options or not self.tradeoffs
                or not self.revisit_conditions or not self.mechanics_refs or not self.validation_refs):
            raise ValueError("validated build rule requires context, tradeoffs and validation evidence")


@dataclass(frozen=True)
class BuildRuleResult:
    rule_id: str
    status: Literal["conditional_analysis", "not_applicable", "insufficient_evidence"]
    options: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    revisit_conditions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]
    optimality: Literal["not_established"] = "not_established"


def evaluate_build_rule(rule: BuildRule, facts: tuple[ContextFact, ...], *, patch: str,
                        hero_id: int, role: str) -> BuildRuleResult:
    """Return sourced conditional analysis, never a universal optimal purchase."""
    if not isinstance(facts, tuple) or any(not isinstance(f, ContextFact) for f in facts) or len({f.key for f in facts}) != len(facts):
        raise ValueError("immutable unique context facts required")
    reasons = []
    if rule.validation_status != "validated":
        reasons.append("build_rule_not_validated")
    if (patch, hero_id, role) != (rule.patch, rule.hero_id, rule.role) or patch == "unknown" or role == "unknown":
        reasons.append("build_scope_mismatch_or_unknown")
    lookup = {f.key: f for f in facts}
    mismatch = False
    evidence = list(rule.mechanics_refs + rule.validation_refs)
    for key, expected in rule.conditions:
        fact = lookup.get(key)
        if fact is None or fact.status != "known":
            reasons.append(f"context_unknown:{key}")
        elif type(fact.value) is not type(expected) or fact.value != expected:
            mismatch = True
        else:
            evidence.extend(fact.evidence_refs)
    status = "insufficient_evidence" if reasons else "not_applicable" if mismatch else "conditional_analysis"
    if mismatch:
        reasons.append("rule_conditions_not_met")
    allowed = status == "conditional_analysis"
    return BuildRuleResult(rule.rule_id, status, rule.options if allowed else (),
                           rule.tradeoffs if allowed else (), rule.revisit_conditions if allowed else (),
                           tuple(dict.fromkeys(evidence)), tuple(reasons))


def evaluate_build_rules(rules: tuple[BuildRule, ...], facts: tuple[ContextFact, ...], *,
                         patch: str, hero_id: int, role: str) -> tuple[BuildRuleResult, ...]:
    if not isinstance(rules, tuple) or any(not isinstance(r, BuildRule) for r in rules) or len({r.rule_id for r in rules}) != len(rules):
        raise ValueError("immutable unique build registry required")
    return tuple(evaluate_build_rule(rule, facts, patch=patch, hero_id=hero_id, role=role) for rule in rules)
