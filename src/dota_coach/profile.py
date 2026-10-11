"""Descriptive series profile; raw missing measurements stay missing."""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median

from dota_coach.evidence.contracts import content_hash

METRICS = ("gold_per_min", "xp_per_min", "last_hits", "denies", "deaths", "obs_placed",
    "camps_stacked", "teamfight_participation", "hero_damage", "tower_damage")


@dataclass(frozen=True)
class ItemPreference:
    item: str
    matches_with_purchase: int
    matches_with_purchase_log: int
    considered_matches: int
    median_first_purchase_seconds: float | None


def _opponent_proxy(raw, player):
    slot=player.get('player_slot')
    if type(slot) is not int or slot not in (*range(5),*range(128,133)):
        return 'unknown'
    enemies=[p for p in raw['players'] if type(p.get('player_slot')) is int
        and (p['player_slot']<128)!=(slot<128)]
    ranks=[p['rank_tier'] for p in enemies if type(p.get('rank_tier')) is int and 10<=p['rank_tier']<=85]
    return f'provider_rank_tier_median:{median(ranks):g}/not_numeric_mmr' if len(enemies)==5 and len(ranks)==5 else 'unknown'


def _preferences(entries):
    times={}
    observed=0
    for _,player in entries:
        log=player.get('purchase_log')
        if not isinstance(log,list) or any(not isinstance(p,dict) or not isinstance(p.get('key'),str) for p in log):
            continue
        observed+=1
        first={}
        for p in log:
            t=p.get('time')
            if type(t) in (int,float) and math.isfinite(t):
                prior=first.get(p['key'])
                first[p['key']]=min(prior,t) if prior is not None else t
            else:
                first.setdefault(p['key'],None)
        for key,t in first.items():
            times.setdefault(key,[]).append(t)
    return tuple(ItemPreference(k,len(values),observed,len(entries),
        median([v for v in values if v is not None]) if any(v is not None for v in values) else None)
        for k,values in sorted(times.items()))


@dataclass(frozen=True)
class ProfileMetric:
    metric: str
    median_value: float | None
    measured_matches: int
    considered_matches: int


@dataclass(frozen=True)
class ProfileGroup:
    role: str
    hero_id: int | None
    patch: str
    match_ids: tuple[int, ...]
    metrics: tuple[ProfileMetric, ...]
    source_hashes: tuple[str, ...]
    quality: str = "descriptive/source_validation_pending"
    opponent_level_proxy: str = 'unknown'
    item_preferences: tuple[ItemPreference, ...] = ()
    style_status: str = 'descriptive_features_no_stable_label'


def describe_series(raw_matches: list[dict], account_id: int) -> tuple[ProfileGroup, ...]:
    if type(account_id) is not int or account_id <= 0:
        raise ValueError("positive account id required")
    grouped = {}
    seen = set()
    for raw in raw_matches:
        if not isinstance(raw, dict) or not isinstance(raw.get("players"), list) or any(
                not isinstance(p, dict) for p in raw["players"]):
            raise ValueError("series requires match objects with player objects")
        mid = raw.get("match_id")
        if type(mid) is not int or mid <= 0 or mid in seen:
            raise ValueError("distinct positive match IDs required")
        seen.add(mid)
        players = [p for p in raw["players"] if type(p.get("account_id")) is int
                   and p["account_id"] == account_id]
        if len(players) != 1:
            raise ValueError("series player identity missing or ambiguous")
        p = players[0]
        role = p.get("position_est")
        role = f"estimated:{role}" if type(role) is int and 1 <= role <= 5 else "unknown"
        hero = p.get("hero_id")
        if type(hero) is not int or hero <= 0:
            hero = None
        patch = raw.get("patch")
        patch = f"source-patch-id:{patch}" if type(patch) is int and patch >= 0 else "unknown"
        grouped.setdefault((role, hero, patch, _opponent_proxy(raw,p)), []).append((raw, p))
    groups = []
    for (role, hero, patch, opponent_proxy), entries in grouped.items():
        metrics = []
        for name in METRICS:
            values = [p[name] for _, p in entries if type(p.get(name)) in (int, float)
                      and math.isfinite(p[name]) and p[name] >= 0]
            metrics.append(ProfileMetric(name, median(values) if values else None,
                                         len(values), len(entries)))
        groups.append(ProfileGroup(role, hero, patch, tuple(r["match_id"] for r, _ in entries),
                                  tuple(metrics), tuple(content_hash(r) for r, _ in entries),
                                  opponent_level_proxy=opponent_proxy,item_preferences=_preferences(entries)))
    return tuple(groups)
