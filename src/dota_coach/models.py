from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventType(str, Enum):
    TEAMFIGHT = "teamfight"
    DEATH = "death"
    OBJECTIVE = "objective"
    NETWORTH_SWING = "networth_swing"
    ITEM_TIMING = "item_timing"
    WARD = "ward"


class Confidence(str, Enum):
    HIGH = "high"
    LOW = "low"


class Verdict(str, Enum):
    MISTAKE = "mistake"
    FINE_VARIANCE = "fine_variance"
    NOT_ENOUGH_INFO = "not_enough_info"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class PlayerMatch:
    account_id: int | None
    player_slot: int
    hero_id: int
    is_radiant: bool
    kills: int
    deaths: int
    assists: int
    gold_per_min: int
    xp_per_min: int
    last_hits: int
    gold_t: list[int] = field(default_factory=list)
    xp_t: list[int] = field(default_factory=list)
    lh_t: list[int] = field(default_factory=list)
    kills_log: list[dict] = field(default_factory=list)
    purchase_log: list[dict] = field(default_factory=list)
    obs_log: list[dict] = field(default_factory=list)
    sen_log: list[dict] = field(default_factory=list)
    benchmarks: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Teamfight:
    start: int
    end: int
    deaths: int
    players: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class Objective:
    time: int
    type: str
    slot: int | None = None
    key: str | None = None


@dataclass(frozen=True)
class Match:
    match_id: int
    duration: int
    radiant_win: bool
    players: list[PlayerMatch]
    teamfights: list[Teamfight] = field(default_factory=list)
    objectives: list[Objective] = field(default_factory=list)
    parsed: bool = True

    def player_by_account(self, account_id: int | None) -> PlayerMatch | None:
        for p in self.players:
            if p.account_id == account_id:
                return p
        return None


@dataclass
class EventCandidate:
    type: EventType
    game_time: int
    involves_me: bool
    summary: str
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MetricBenchmark:
    metric: str
    raw: float
    pct: float


@dataclass
class ScoredMoment:
    event: EventCandidate
    score: float
    confidence: Confidence
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)


@dataclass
class Leak:
    key: str
    title: str
    magnitude: str
    example_matches: list[int] = field(default_factory=list)
    confidence: Confidence = Confidence.LOW


@dataclass(frozen=True)
class ClockRead:
    t_video: float
    t_game: int
