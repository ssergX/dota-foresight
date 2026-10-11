from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal
from urllib.parse import parse_qs, urlsplit


def match_url(url: str, match_id: int) -> bool:
    """Check linkage syntax only; existence must be checked by a source adapter."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        segments = parsed.path.strip("/").split("/")
        linked = str(match_id) in segments or any(str(match_id) in values
                 for key, values in parse_qs(parsed.query).items() if key in ("match_id", "matchId"))
        return linked
    except ValueError:
        return False


@dataclass(frozen=True)
class MatchSource:
    match_id: int
    url: str
    checked_at: str
    content_sha256: str
    status: Literal["verified", "unverified"] = "unverified"

    def __post_init__(self):
        if any(not isinstance(value, str) for value in (self.url, self.checked_at, self.content_sha256)):
            raise TypeError("string source fields required")
        if type(self.match_id) is not int or self.match_id <= 0 or not match_url(self.url, self.match_id):
            raise ValueError("source requires positive numeric match id and matching HTTPS link")
        if self.status not in ("verified", "unverified"):
            raise ValueError("invalid source verification")
        if self.status == "verified":
            try:
                stamp = datetime.fromisoformat(self.checked_at.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                raise ValueError("verified source requires a checked timestamp") from None
            if stamp.tzinfo is None or not re.fullmatch(r"[0-9a-fA-F]{64}", self.content_sha256):
                raise ValueError("verified source requires timezone and immutable source hash")


@dataclass(frozen=True)
class StudyMatch:
    match_id: int
    hero_id: int
    role: str
    patch: str
    sources: tuple[MatchSource, ...]
    replay_availability: Literal["available", "unavailable", "unknown"] = "unknown"
    expertise_status: Literal["pro", "high_mmr", "unknown"] = "unknown"
    expertise_evidence_refs: tuple[str, ...] = ()
    episode_refs: tuple[str, ...] = ()
    learning_task: str = ""
    transfer_limitations: tuple[str, ...] = ()
    dataset_kind: Literal["real", "synthetic", "unknown"] = "unknown"

    def __post_init__(self):
        if type(self.match_id) is not int or self.match_id <= 0 or type(self.hero_id) is not int or self.hero_id <= 0:
            raise ValueError("positive numeric match and hero ids required")
        if any(not isinstance(value, str) or not value for value in (self.role, self.patch)) or not isinstance(self.learning_task, str):
            raise ValueError("study context required")
        for value in (self.sources, self.expertise_evidence_refs, self.episode_refs, self.transfer_limitations):
            if not isinstance(value, tuple):
                raise TypeError("immutable study references required")
        if any(not isinstance(ref, str) or not ref for ref in self.expertise_evidence_refs + self.episode_refs + self.transfer_limitations):
            raise TypeError("string study references required")
        if any(not isinstance(s, MatchSource) or s.match_id != self.match_id for s in self.sources):
            raise ValueError("study source mismatch")
        if self.replay_availability not in ("available", "unavailable", "unknown") or self.expertise_status not in ("pro", "high_mmr", "unknown") or self.dataset_kind not in ("real", "synthetic", "unknown"):
            raise ValueError("invalid study status")
        if self.expertise_status != "unknown" and not self.expertise_evidence_refs:
            raise ValueError("expertise label requires source evidence")


@dataclass(frozen=True)
class StudySelection:
    status: Literal["available", "unavailable"]
    matches: tuple[StudyMatch, ...]
    exclusions: tuple[tuple[int, tuple[str, ...]], ...]
    reason_codes: tuple[str, ...]
    limitations: tuple[str, ...] = ("Совпадение героя, роли и патча не доказывает переносимость решений.",)


def select_study_matches(catalog: tuple[StudyMatch, ...], *, hero_id: int, role: str,
                         patch: str, limit: int = 3,
                         require_expert: bool = True) -> StudySelection:
    if not isinstance(catalog, tuple):
        raise TypeError("immutable catalog required")
    if any(not isinstance(study, StudyMatch) for study in catalog):
        raise TypeError("typed study catalog required")
    if type(hero_id) is not int or hero_id <= 0 or not role or not patch or type(limit) is not int or limit <= 0:
        raise ValueError("valid study context and limit required")
    if len({s.match_id for s in catalog}) != len(catalog):
        raise ValueError("duplicate catalog match id")
    selected, exclusions = [], []
    for study in catalog:
        reasons = []
        if study.dataset_kind != "real" or not any(s.status == "verified" for s in study.sources):
            reasons.append("real_match_source_not_verified")
        if study.hero_id != hero_id:
            reasons.append("hero_mismatch")
        if study.role != role or role == "unknown":
            reasons.append("role_mismatch_or_unknown")
        if study.patch != patch or patch == "unknown":
            reasons.append("patch_mismatch_or_unknown")
        if study.replay_availability != "available":
            reasons.append("replay_not_available")
        if require_expert and study.expertise_status == "unknown":
            reasons.append("expertise_not_sourced")
        if not study.learning_task or not study.episode_refs:
            reasons.append("learning_task_or_episode_missing")
        if reasons:
            exclusions.append((study.match_id, tuple(reasons)))
        else:
            selected.append(study)
    # Stable source identities, not popularity or fabricated similarity scores.
    chosen = tuple(sorted(selected, key=lambda s: s.match_id)[:limit])
    return StudySelection("available" if chosen else "unavailable", chosen, tuple(exclusions),
                          () if chosen else ("no_source_backed_suitable_study_matches",))
