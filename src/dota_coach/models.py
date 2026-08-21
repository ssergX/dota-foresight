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
    # --- ролевые сигналы ---
    position_est: int | None = None      # 1..5, парс-зависимое
    lane_role: int | None = None         # 1 safe / 2 mid / 3 off / 4 jungle
    is_roaming: bool = False
    lane: int | None = None
    # --- всегда-присутствующие базовые числа (есть и у непропарсенных) ---
    denies: int = 0
    net_worth: int = 0
    level: int = 0
    hero_damage: int = 0
    tower_damage: int = 0
    killed_by: dict = field(default_factory=dict)
    # --- парс-зависимые (None = нет данных, requires исключит матч; НИКОГДА не 0) ---
    lane_efficiency_pct: int | None = None
    life_state_dead: int | None = None
    teamfight_participation: float | None = None
    stuns: float | None = None
    obs_placed: int | None = None
    sen_placed: int | None = None
    camps_stacked: int | None = None
    neutral_kills: int | None = None
    rune_pickups: int | None = None
    observer_kills: int | None = None
    sentry_uses: int | None = None
    towers_killed: int | None = None
    roshans_killed: int | None = None
    dn_t: list[int] = field(default_factory=list)
    obs_left_log: list[dict] = field(default_factory=list)
    buyback_log: list[dict] = field(default_factory=list)


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
    # числа для петли подотчётности и metric_ref (заполняются кодом):
    metric: str = ""
    value: float = 0.0
    threshold: float = 0.0
    direction: str = "lower_is_better"
    role: int | None = None
    source: str = "manual"       # bench | manual | personal
    sample_size: int = 0         # N: матчей после requires-фильтра
    considered: int = 0          # M: матчей в роли до фильтра (для строки покрытия)
    severity: float = 0.0
    phase: str = ""              # laning|economy|deaths|fights|vision|objectives
    family: str = ""


@dataclass(frozen=True)
class ClockRead:
    t_video: float
    t_game: int


@dataclass(frozen=True)
class UnitState:
    slot: int
    x: float
    y: float
    hp: int
    max_hp: int
    mana: float
    level: int
    xp: int
    alive: bool


@dataclass(frozen=True)
class ReplayFrame:
    time: int
    units: dict[int, UnitState]


@dataclass(frozen=True)
class WardEvent:
    id: int
    time: int
    kind: str      # "obs" | "sentry"
    team: int      # 2 Radiant / 3 Dire
    x: float
    y: float
    op: str        # "placed" | "gone"


@dataclass(frozen=True)
class ParsedReplay:
    match_id: int
    game_start_time: float
    heroes: dict[int, str]
    frames: list[ReplayFrame]
    teams: dict[int, int] = field(default_factory=dict)   # slot -> team (2/3)
    wards: list[WardEvent] = field(default_factory=list)

    def frame_at(self, t: int) -> "ReplayFrame | None":
        best = None
        for f in self.frames:            # frames отсортированы по time на парсинге
            if f.time <= t:
                best = f
            else:
                break
        return best
