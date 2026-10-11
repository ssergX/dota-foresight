"""Offline descriptive adapters; imported declarations never grant validation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from dota_coach.learning.builds import PurchaseObservation, PurchaseSequence, describe_purchase_sequence
from dota_coach.learning.study import MatchSource, StudyMatch


@dataclass(frozen=True)
class PlayerPortfolio:
    match_id: int
    account_id: int
    hero_id: int | None
    role: str
    patch: str
    purchases: PurchaseSequence
    reason_codes: tuple[str, ...]
    lane_role: int | None = None
    data_status: str = "descriptive_unverified"


def _positive_int(value, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field}: positive numeric id required")
    return value


def build_descriptive_portfolio(raw_match: dict, account_id: int) -> PlayerPortfolio:
    if not isinstance(raw_match, dict):
        raise TypeError("raw match object required")
    _positive_int(account_id, "account_id")
    match_id = _positive_int(raw_match.get("match_id"), "match_id")
    players = raw_match.get("players")
    if not isinstance(players, list) or any(not isinstance(p, dict) for p in players):
        raise ValueError("raw match requires player objects")
    own = [p for p in players if type(p.get("account_id")) is int and p["account_id"] == account_id]
    if len(own) != 1:
        raise ValueError("exactly one player matching account_id required")
    player = own[0]
    hero_id = player.get("hero_id")
    if hero_id is not None:
        _positive_int(hero_id, "hero_id")
    lane_role = player.get("lane_role")
    if lane_role is not None and (type(lane_role) is not int or lane_role not in (1, 2, 3, 4)):
        raise ValueError("invalid provider lane_role")
    patch_id = raw_match.get("patch")
    if patch_id is not None and (type(patch_id) is not int or patch_id < 0):
        raise ValueError("provider patch must be a numeric identifier")
    # OpenDota lane_role identifies lane, not a validated position/role inference.
    patch = "unknown" if patch_id is None else f"opendota_patch_id:{patch_id}"
    encoded = json.dumps(raw_match, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    source = MatchSource(match_id, f"https://www.opendota.com/matches/{match_id}", "",
                         hashlib.sha256(encoded).hexdigest(), "unverified")
    log = player.get("purchase_log")
    if log is not None and not isinstance(log, list):
        raise ValueError("purchase_log must be an array or absent")
    purchases = []
    for ordinal, event in enumerate(log or []):
        if not isinstance(event, dict) or not isinstance(event.get("key"), str) or not event["key"]:
            raise ValueError("purchase event requires an item key")
        purchases.append(PurchaseObservation(match_id, event["key"], event.get("time"), source,
                                             f"/players/{players.index(player)}/purchase_log/{ordinal}"))
    reasons = ["raw_match_source_unverified", "player_role_not_verified", "purchase_sequence_not_build_evaluation"]
    if hero_id is None:
        reasons.append("hero_unknown")
    if patch_id is None:
        reasons.append("patch_unknown")
    else:
        reasons.append("patch_identifier_not_mechanics_version")
    if log is None:
        reasons.append("purchase_log_unavailable")
    return PlayerPortfolio(match_id, account_id, hero_id, "unknown", patch,
                           describe_purchase_sequence(tuple(purchases)), tuple(reasons), lane_role)


@dataclass(frozen=True)
class CatalogImport:
    matches: tuple[StudyMatch, ...]
    warnings: tuple[str, ...]


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strings(value, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v for v in value):
        raise ValueError(f"{field}: array of nonempty strings required")
    return tuple(value)


def load_study_catalog(text: str) -> CatalogImport:
    """Strictly load candidates, demoting unverifiable source/expertise claims.

    Root may be a list or {"schema_version":"study-catalog.v1","matches":[...] }.
    This function does not fetch a source or resolve a validation receipt. Thus
    even imported status=verified, dataset_kind=real and replay=available remain
    unverified candidates until a provenance adapter checks the actual source.
    """
    def invalid_number(value):
        raise ValueError(f"non-finite JSON number: {value}")
    raw = json.loads(text, object_pairs_hook=_object_pairs, parse_constant=invalid_number)
    if isinstance(raw, dict):
        if set(raw) != {"schema_version", "matches"} or raw["schema_version"] != "study-catalog.v1":
            raise ValueError("invalid study catalog envelope")
        raw = raw["matches"]
    if not isinstance(raw, list):
        raise ValueError("study catalog must contain an array")
    allowed = {"match_id", "hero_id", "role", "patch", "sources", "replay_availability",
               "expertise_status", "expertise_evidence_refs", "episode_refs", "learning_task",
               "transfer_limitations", "dataset_kind"}
    source_allowed = {"match_id", "url", "checked_at", "content_sha256", "status"}
    matches, warnings = [], []
    for item in raw:
        if not isinstance(item, dict) or not set(item) <= allowed:
            raise ValueError("unknown study match fields")
        mid = _positive_int(item.get("match_id"), "match_id")
        hero = _positive_int(item.get("hero_id"), "hero_id")
        if not isinstance(item.get("role"), str) or not isinstance(item.get("patch"), str):
            raise ValueError("study role and patch must be strings")
        raw_sources = item.get("sources", [])
        if not isinstance(raw_sources, list):
            raise ValueError("sources must be an array")
        sources = []
        for src in raw_sources:
            if not isinstance(src, dict) or not set(src) <= source_allowed:
                raise ValueError("unknown source fields")
            source_mid = _positive_int(src.get("match_id", mid), "source.match_id")
            if source_mid != mid or not isinstance(src.get("url"), str):
                raise ValueError("study source linkage mismatch")
            for field in ("checked_at", "content_sha256"):
                if not isinstance(src.get(field, ""), str):
                    raise ValueError(f"source {field} must be a string")
            if src.get("status", "unverified") not in ("verified", "unverified"):
                raise ValueError("invalid source status")
            sources.append(MatchSource(mid, src["url"], src.get("checked_at", ""),
                                       src.get("content_sha256", ""), "unverified"))
        if item.get("expertise_status", "unknown") not in ("pro", "high_mmr", "unknown") or item.get("dataset_kind", "unknown") not in ("real", "synthetic", "unknown") or item.get("replay_availability", "unknown") not in ("available", "unavailable", "unknown"):
            raise ValueError("invalid imported study status")
        _strings(item.get("expertise_evidence_refs", []), "expertise_evidence_refs")
        task = item.get("learning_task", "")
        if not isinstance(task, str):
            raise ValueError("learning_task must be a string")
        matches.append(StudyMatch(mid, hero, item["role"], item["patch"], tuple(sources),
                                  "unknown", "unknown", (),
                                  _strings(item.get("episode_refs", []), "episode_refs"), task,
                                  _strings(item.get("transfer_limitations", []), "transfer_limitations"),
                                  "synthetic" if item.get("dataset_kind") == "synthetic" else "unknown"))
        warnings.append(f"match:{mid}:imported_declarations_require_provenance_adapter")
    if len({m.match_id for m in matches}) != len(matches):
        raise ValueError("duplicate catalog match id")
    return CatalogImport(tuple(matches), tuple(warnings))
