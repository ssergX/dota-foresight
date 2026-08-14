# Dota Coach MVP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Построить пост-матч анализатор игр в Dota 2, который по одному матчу выдаёт топ ранжированных ключевых моментов с прыжком в видеозапись, а по серии матчей — системные лики. Без ЛЛМ (фаза 1).

**Architecture:** Чистый пайплайн `match_id (+video) → отчёт`. Данные тянутся из OpenDota API и маппятся в собственную модель (`models.py`), поэтому остальные модули не знают про источник. События извлекаются из распарсенного матча, ранжируются скорером (с метками уверенности и анти-результатническим вердиктом), агрегируются в лики по многим матчам. Видео привязывается к игровому времени через OCR часов с HUD. Отчёт — статический HTML.

**Tech Stack:** Python 3.12, `requests` (OpenDota), `opencv-python` + `pytesseract` (OCR часов), `ffmpeg` (внешний бинарник, нарезка клипов), `pytest`. Без БД в MVP — сырой JSON матчей кешируется на диск.

## Global Constraints

- **Python 3.12**, платформа **Windows** (пути через `pathlib`, не хардкодить `/`).
- **OpenDota free API** (`https://api.opendota.com/api`) — без ключа. Уважать rate-limit (≤60 req/min): между запросами пауза.
- **Никаких вызовов ЛЛМ в MVP** — инференс $0. Модуль `coach` (Claude, `claude-sonnet-5`/`claude-haiku-4-5`) — фаза 2, вне этого плана.
- **Отчёт — статический HTML** (одиночный файл), без сервера.
- **Код и идентификаторы — на английском; текст в отчёте, видимый пользователю — на русском.**
- Приватность: OpenDota отдаёт только публичные матчи (нужен «Expose Public Match Data» в Dota). Если матч не распарсен (`teamfights`/`objectives` пустые) — код это обрабатывает, а не падает.
- Каждый модуль — отдельный файл с одной ответственностью. Внутренняя модель (`models.py`) — единственный контракт между модулями.

---

## File Structure

```
dota-coach/
  pyproject.toml                       # проект + зависимости + pytest
  .gitignore
  src/dota_coach/
    __init__.py
    models.py                          # dataclasses: Match, PlayerMatch, Teamfight, Objective,
                                        #   EventCandidate, ScoredMoment, MetricBenchmark, Leak, ClockRead + enums
    ingest/
      __init__.py
      opendota.py                      # fetch_match(match_id) + дисковый кеш; fetch_recent(account_id, n)
      normalize.py                     # normalize(raw: dict) -> Match
    events.py                          # extract_events(match, account_id) -> list[EventCandidate]
    benchmarks.py                      # player_benchmarks(match, account_id) -> list[MetricBenchmark]
    scoring.py                         # score_events(events, benchmarks, match, account_id, top_n) -> list[ScoredMoment]
    leaks.py                           # detect_leaks(matches, account_id) -> list[Leak]
    video/
      __init__.py
      align.py                         # compute_offset, video_time_for, sample_clock_reads
      clip.py                          # build_clip_command
    report.py                          # render_report(...) -> str (HTML)
    cli.py                             # analyze / leaks entrypoints
  tests/
    fixtures/opendota_match_sample.json
    test_models.py
    test_normalize.py
    test_events.py
    test_benchmarks.py
    test_scoring.py
    test_leaks.py
    test_align.py
    test_clip.py
    test_report.py
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/dota_coach/__init__.py`
- Create: `src/dota_coach/ingest/__init__.py`
- Create: `src/dota_coach/video/__init__.py`
- Create: `tests/__init__.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: —
- Produces: importable package `dota_coach`; `pytest` runs green.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "dota-coach"
version = "0.1.0"
description = "Личный пост-матч AI-тренер по Dota 2 (MVP без ЛЛМ)"
requires-python = ">=3.12"
dependencies = [
    "requests>=2.31",
    "opencv-python>=4.9",
    "pytesseract>=0.3.10",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
dota-coach = "dota_coach.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dota_coach"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.venv/
build/
dist/
# runtime artifacts
cache/
out/
*.mp4
report.html
```

- [ ] **Step 3: Create empty package init files**

Create `src/dota_coach/__init__.py`, `src/dota_coach/ingest/__init__.py`, `src/dota_coach/video/__init__.py`, `tests/__init__.py` — each an empty file (0 bytes).

- [ ] **Step 4: Write the smoke test**

```python
# tests/test_smoke.py
def test_package_imports():
    import dota_coach
    assert dota_coach is not None
```

- [ ] **Step 5: Run the smoke test**

Run: `pytest tests/test_smoke.py -v`
Expected: 1 passed. (If `pythonpath = ["src"]` works, import resolves.)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore src tests
git commit -m "chore: scaffold dota-coach package and pytest"
```

---

### Task 2: Core data model

**Files:**
- Create: `src/dota_coach/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: —
- Produces (used by every later task):
  - Enums: `EventType`, `Confidence`, `Verdict`.
  - `PlayerMatch(account_id: int|None, player_slot: int, hero_id: int, is_radiant: bool, kills, deaths, assists, gold_per_min, xp_per_min, last_hits, gold_t: list[int], xp_t: list[int], lh_t: list[int], kills_log: list[dict], purchase_log: list[dict], obs_log: list[dict], sen_log: list[dict], benchmarks: dict)`
  - `Teamfight(start: int, end: int, deaths: int, players: list[dict])` — each `players[i]` keyed by array index = `player_slot` order, holds `{"deaths","gold_delta","xp_delta","damage"}`.
  - `Objective(time: int, type: str, slot: int|None, key: str|None)`
  - `Match(match_id, duration, radiant_win, players: list[PlayerMatch], teamfights: list[Teamfight], objectives: list[Objective], parsed: bool)` with method `player_by_account(account_id) -> PlayerMatch | None`.
  - `EventCandidate(type: EventType, game_time: int, involves_me: bool, summary: str, data: dict)`
  - `MetricBenchmark(metric: str, raw: float, pct: float)`
  - `ScoredMoment(event: EventCandidate, score: float, confidence: Confidence, verdict: Verdict, reasons: list[str])`
  - `Leak(key: str, title: str, magnitude: str, example_matches: list[int], confidence: Confidence)`
  - `ClockRead(t_video: float, t_game: int)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from dota_coach.models import Match, PlayerMatch, EventType, EventCandidate, Confidence, Verdict


def _player(account_id, slot):
    return PlayerMatch(
        account_id=account_id, player_slot=slot, hero_id=1, is_radiant=slot < 128,
        kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
        gold_t=[], xp_t=[], lh_t=[], kills_log=[], purchase_log=[], obs_log=[], sen_log=[],
        benchmarks={},
    )


def test_player_by_account_returns_matching_player():
    m = Match(match_id=1, duration=100, radiant_win=True,
              players=[_player(111, 0), _player(222, 128)],
              teamfights=[], objectives=[], parsed=True)
    assert m.player_by_account(222).player_slot == 128
    assert m.player_by_account(999) is None


def test_event_candidate_holds_signals():
    ev = EventCandidate(type=EventType.DEATH, game_time=842, involves_me=True,
                        summary="умер первым", data={"teamfight": True})
    assert ev.type == EventType.DEATH
    assert ev.data["teamfight"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dota_coach.models'`.

- [ ] **Step 3: Write `src/dota_coach/models.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/models.py tests/test_models.py
git commit -m "feat(models): core data model for match/events/moments/leaks"
```

---

### Task 3: Ingest — normalize OpenDota JSON into Match

Split into two files: a pure `normalize()` (fully testable against a fixture) and a thin `opendota.py` fetch+cache glue (network, not unit-tested).

**Files:**
- Create: `tests/fixtures/opendota_match_sample.json`
- Create: `src/dota_coach/ingest/normalize.py`
- Create: `src/dota_coach/ingest/opendota.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: `models.Match`, `PlayerMatch`, `Teamfight`, `Objective`.
- Produces:
  - `normalize(raw: dict) -> Match` — maps OpenDota match JSON to `Match`. `parsed = raw.get("version") is not None`. `is_radiant = player_slot < 128`.
  - `fetch_match(match_id: int, cache_dir: Path = Path("cache")) -> dict` — returns raw JSON, disk-cached at `cache/<match_id>.json`; requests a parse only if unparsed (out of scope to block on — just return what OpenDota gives).
  - `fetch_recent(account_id: int, n: int, cache_dir=Path("cache")) -> list[int]` — returns up to `n` recent match_ids.

- [ ] **Step 1: Write the fixture `tests/fixtures/opendota_match_sample.json`**

Minimal but shape-accurate parsed match: 2 players (me = account_id 111 on slot 0, enemy on slot 128), one teamfight, one tower objective, per-minute series, one death of me, one item purchase, one ward.

```json
{
  "match_id": 8001,
  "duration": 1800,
  "radiant_win": false,
  "version": 21,
  "teamfights": [
    {
      "start": 820,
      "end": 860,
      "deaths": 3,
      "players": [
        {"deaths": 1, "gold_delta": -400, "xp_delta": -200, "damage": 500},
        {"deaths": 0, "gold_delta": 300, "xp_delta": 250, "damage": 900}
      ]
    }
  ],
  "objectives": [
    {"time": 610, "type": "CHAT_MESSAGE_TOWER_KILL", "slot": 1, "key": null},
    {"time": 1500, "type": "CHAT_MESSAGE_ROSHAN_KILL", "slot": null, "key": "3"}
  ],
  "players": [
    {
      "account_id": 111,
      "player_slot": 0,
      "hero_id": 8,
      "kills": 4,
      "deaths": 9,
      "assists": 6,
      "gold_per_min": 420,
      "xp_per_min": 480,
      "last_hits": 140,
      "gold_t": [0, 300, 900, 1500],
      "xp_t": [0, 400, 1100, 1700],
      "lh_t": [0, 8, 22, 40],
      "kills_log": [{"time": 842, "key": "npc_dota_hero_lion"}],
      "purchase_log": [{"time": 900, "key": "black_king_bar"}],
      "obs_log": [{"time": 240, "x": 120, "y": 118, "z": 0}],
      "sen_log": [],
      "benchmarks": {
        "gold_per_min": {"raw": 420, "pct": 0.32},
        "xp_per_min": {"raw": 480, "pct": 0.35},
        "last_hits_per_min": {"raw": 4.6, "pct": 0.28},
        "hero_damage_per_min": {"raw": 320, "pct": 0.4}
      }
    },
    {
      "account_id": 222,
      "player_slot": 128,
      "hero_id": 26,
      "kills": 9,
      "deaths": 4,
      "assists": 10,
      "gold_per_min": 560,
      "xp_per_min": 610,
      "last_hits": 210,
      "gold_t": [0, 400, 1200, 2100],
      "xp_t": [0, 500, 1400, 2300],
      "lh_t": [0, 12, 34, 62],
      "kills_log": [],
      "purchase_log": [{"time": 700, "key": "blink"}],
      "obs_log": [],
      "sen_log": [],
      "benchmarks": {"gold_per_min": {"raw": 560, "pct": 0.78}}
    }
  ]
}
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_normalize.py
import json
from pathlib import Path

from dota_coach.ingest.normalize import normalize
from dota_coach.models import Match

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def _raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_normalize_builds_match_with_players_and_events():
    m = normalize(_raw())
    assert isinstance(m, Match)
    assert m.match_id == 8001
    assert m.parsed is True
    assert len(m.players) == 2
    me = m.player_by_account(111)
    assert me.is_radiant is True
    assert me.deaths == 9
    assert me.benchmarks["gold_per_min"]["pct"] == 0.32
    assert len(m.teamfights) == 1
    assert m.teamfights[0].players[0]["gold_delta"] == -400
    assert m.objectives[0].type == "CHAT_MESSAGE_TOWER_KILL"


def test_normalize_handles_unparsed_match():
    raw = _raw()
    raw.pop("version")
    raw["teamfights"] = None
    raw["objectives"] = None
    m = normalize(raw)
    assert m.parsed is False
    assert m.teamfights == []
    assert m.objectives == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dota_coach.ingest.normalize'`.

- [ ] **Step 4: Write `src/dota_coach/ingest/normalize.py`**

```python
from __future__ import annotations

from dota_coach.models import Match, Objective, PlayerMatch, Teamfight


def _player(raw: dict) -> PlayerMatch:
    slot = raw["player_slot"]
    return PlayerMatch(
        account_id=raw.get("account_id"),
        player_slot=slot,
        hero_id=raw.get("hero_id", 0),
        is_radiant=slot < 128,
        kills=raw.get("kills", 0),
        deaths=raw.get("deaths", 0),
        assists=raw.get("assists", 0),
        gold_per_min=raw.get("gold_per_min", 0),
        xp_per_min=raw.get("xp_per_min", 0),
        last_hits=raw.get("last_hits", 0),
        gold_t=raw.get("gold_t") or [],
        xp_t=raw.get("xp_t") or [],
        lh_t=raw.get("lh_t") or [],
        kills_log=raw.get("kills_log") or [],
        purchase_log=raw.get("purchase_log") or [],
        obs_log=raw.get("obs_log") or [],
        sen_log=raw.get("sen_log") or [],
        benchmarks=raw.get("benchmarks") or {},
    )


def normalize(raw: dict) -> Match:
    teamfights = [
        Teamfight(start=t["start"], end=t["end"], deaths=t.get("deaths", 0),
                  players=t.get("players") or [])
        for t in (raw.get("teamfights") or [])
    ]
    objectives = [
        Objective(time=o["time"], type=o["type"], slot=o.get("slot"), key=o.get("key"))
        for o in (raw.get("objectives") or [])
    ]
    return Match(
        match_id=raw["match_id"],
        duration=raw.get("duration", 0),
        radiant_win=raw.get("radiant_win", False),
        players=[_player(p) for p in raw.get("players", [])],
        teamfights=teamfights,
        objectives=objectives,
        parsed=raw.get("version") is not None,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_normalize.py -v`
Expected: 2 passed.

- [ ] **Step 6: Write `src/dota_coach/ingest/opendota.py` (network glue — no unit test)**

```python
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

BASE = "https://api.opendota.com/api"
_MIN_INTERVAL = 1.1  # ~<60 req/min
_last_call = 0.0


def _throttle() -> None:
    global _last_call
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def fetch_match(match_id: int, cache_dir: Path = Path("cache")) -> dict:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{match_id}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    _throttle()
    resp = requests.get(f"{BASE}/matches/{match_id}", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    cached.write_text(json.dumps(data), encoding="utf-8")
    return data


def fetch_recent(account_id: int, n: int, cache_dir: Path = Path("cache")) -> list[int]:
    _throttle()
    resp = requests.get(f"{BASE}/players/{account_id}/matches",
                        params={"limit": n}, timeout=30)
    resp.raise_for_status()
    return [row["match_id"] for row in resp.json()]
```

- [ ] **Step 7: Commit**

```bash
git add src/dota_coach/ingest tests/test_normalize.py tests/fixtures/opendota_match_sample.json
git commit -m "feat(ingest): normalize OpenDota JSON to Match + cached fetch client"
```

---

### Task 4: Event extraction

**Files:**
- Create: `src/dota_coach/events.py`
- Test: `tests/test_events.py`

**Interfaces:**
- Consumes: `models.Match`, `EventCandidate`, `EventType`; `normalize` (in test).
- Produces: `extract_events(match: Match, account_id: int | None) -> list[EventCandidate]`.
  - Emits `EventCandidate`s for: my deaths (from my `kills_log`? no — deaths come from teamfights and objectives; here use teamfight deaths + my kills_log victims are enemies). For MVP: teamfights, objectives, my per-minute networth swings, my item purchases, my wards.
  - `involves_me`: teamfight → my slot has `deaths>0` or `damage>0`; objective → always team-level (involves_me=False unless `slot` is mine); networth/item/ward → mine only.
  - `game_time` in seconds.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_events.py
import json
from pathlib import Path

from dota_coach.events import extract_events
from dota_coach.ingest.normalize import normalize
from dota_coach.models import EventType

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def _match():
    return normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_extract_events_finds_teamfight_objective_item_ward():
    events = extract_events(_match(), account_id=111)
    types = {e.type for e in events}
    assert EventType.TEAMFIGHT in types
    assert EventType.OBJECTIVE in types
    assert EventType.ITEM_TIMING in types
    assert EventType.WARD in types


def test_teamfight_event_marks_my_involvement_and_time():
    events = extract_events(_match(), account_id=111)
    tf = next(e for e in events if e.type == EventType.TEAMFIGHT)
    assert tf.game_time == 820           # teamfight start
    assert tf.involves_me is True        # my slot index 0 had deaths=1
    assert tf.data["my_gold_delta"] == -400


def test_networth_swing_emitted_for_sharp_drop():
    # my gold_t = [0,300,900,1500]; deltas per min = [300,600,600] -> no drop.
    # Force a drop to assert the rule triggers.
    m = _match()
    me = m.player_by_account(111)
    object.__setattr__(me, "gold_t", [0, 1000, 400, 900])  # min2->min3 drop of 600
    events = extract_events(m, account_id=111)
    swings = [e for e in events if e.type == EventType.NETWORTH_SWING]
    assert any(e.data["delta"] <= -500 for e in swings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_events.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dota_coach.events'`.

- [ ] **Step 3: Write `src/dota_coach/events.py`**

```python
from __future__ import annotations

from dota_coach.models import EventCandidate, EventType, Match, PlayerMatch

_NETWORTH_DROP = -500  # gold drop within one minute flagged as a swing


def _my_index(match: Match, me: PlayerMatch) -> int:
    return match.players.index(me)


def _teamfight_events(match: Match, me: PlayerMatch) -> list[EventCandidate]:
    idx = _my_index(match, me)
    out: list[EventCandidate] = []
    for tf in match.teamfights:
        mine = tf.players[idx] if idx < len(tf.players) else {}
        involves = bool(mine.get("deaths", 0)) or bool(mine.get("damage", 0))
        out.append(EventCandidate(
            type=EventType.TEAMFIGHT, game_time=tf.start, involves_me=involves,
            summary=f"тимфайт {tf.start // 60}:{tf.start % 60:02d}, погибло {tf.deaths}",
            data={
                "deaths": tf.deaths,
                "my_deaths": mine.get("deaths", 0),
                "my_gold_delta": mine.get("gold_delta", 0),
                "my_xp_delta": mine.get("xp_delta", 0),
                "my_damage": mine.get("damage", 0),
            },
        ))
    return out


def _objective_events(match: Match, me: PlayerMatch) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for o in match.objectives:
        out.append(EventCandidate(
            type=EventType.OBJECTIVE, game_time=o.time,
            involves_me=(o.slot is not None and o.slot == me.player_slot),
            summary=f"{o.type} на {o.time // 60}:{o.time % 60:02d}",
            data={"objective_type": o.type},
        ))
    return out


def _networth_swings(me: PlayerMatch) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for minute in range(1, len(me.gold_t)):
        delta = me.gold_t[minute] - me.gold_t[minute - 1]
        if delta <= _NETWORTH_DROP:
            t = minute * 60
            out.append(EventCandidate(
                type=EventType.NETWORTH_SWING, game_time=t, involves_me=True,
                summary=f"просадка нетворса {delta} на {minute}-й минуте",
                data={"delta": delta},
            ))
    return out


def _item_events(me: PlayerMatch) -> list[EventCandidate]:
    return [
        EventCandidate(
            type=EventType.ITEM_TIMING, game_time=p["time"], involves_me=True,
            summary=f"куплен {p['key']} на {p['time'] // 60}:{p['time'] % 60:02d}",
            data={"item": p["key"]},
        )
        for p in me.purchase_log
    ]


def _ward_events(me: PlayerMatch) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for w in me.obs_log:
        out.append(EventCandidate(
            type=EventType.WARD, game_time=w["time"], involves_me=True,
            summary=f"обс-вард на {w['time'] // 60}:{w['time'] % 60:02d}",
            data={"kind": "obs", "x": w.get("x"), "y": w.get("y")},
        ))
    return out


def extract_events(match: Match, account_id: int | None) -> list[EventCandidate]:
    me = match.player_by_account(account_id)
    if me is None:
        return []
    events = (
        _teamfight_events(match, me)
        + _objective_events(match, me)
        + _networth_swings(me)
        + _item_events(me)
        + _ward_events(me)
    )
    events.sort(key=lambda e: e.game_time)
    return events
```

Note: the test mutates a frozen dataclass via `object.__setattr__` — acceptable in tests to exercise the rule; production data comes from `normalize`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_events.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/events.py tests/test_events.py
git commit -m "feat(events): extract candidate events with timestamps from a match"
```

---

### Task 5: Benchmarks

**Files:**
- Create: `src/dota_coach/benchmarks.py`
- Test: `tests/test_benchmarks.py`

**Interfaces:**
- Consumes: `models.Match`, `MetricBenchmark`.
- Produces: `player_benchmarks(match: Match, account_id: int | None) -> list[MetricBenchmark]` — reads `player.benchmarks` (OpenDota's per-player `{metric: {raw, pct}}`) into a list; empty list if player/benchmarks missing. Also `weak_metrics(benchmarks, threshold=0.4) -> list[MetricBenchmark]` (pct below threshold = weakness).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmarks.py
import json
from pathlib import Path

from dota_coach.benchmarks import player_benchmarks, weak_metrics
from dota_coach.ingest.normalize import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def _match():
    return normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_player_benchmarks_reads_pct():
    benches = player_benchmarks(_match(), account_id=111)
    by_metric = {b.metric: b for b in benches}
    assert by_metric["gold_per_min"].pct == 0.32
    assert by_metric["gold_per_min"].raw == 420


def test_weak_metrics_below_threshold():
    benches = player_benchmarks(_match(), account_id=111)
    weak = {b.metric for b in weak_metrics(benches, threshold=0.4)}
    assert "gold_per_min" in weak          # 0.32 < 0.4
    assert "hero_damage_per_min" not in weak  # 0.4 not < 0.4


def test_missing_player_returns_empty():
    assert player_benchmarks(_match(), account_id=999) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_benchmarks.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/dota_coach/benchmarks.py`**

```python
from __future__ import annotations

from dota_coach.models import Match, MetricBenchmark


def player_benchmarks(match: Match, account_id: int | None) -> list[MetricBenchmark]:
    me = match.player_by_account(account_id)
    if me is None or not me.benchmarks:
        return []
    out: list[MetricBenchmark] = []
    for metric, values in me.benchmarks.items():
        if not isinstance(values, dict) or "pct" not in values:
            continue
        out.append(MetricBenchmark(metric=metric,
                                   raw=float(values.get("raw", 0.0)),
                                   pct=float(values["pct"])))
    return out


def weak_metrics(benchmarks: list[MetricBenchmark], threshold: float = 0.4) -> list[MetricBenchmark]:
    return [b for b in benchmarks if b.pct < threshold]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_benchmarks.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/benchmarks.py tests/test_benchmarks.py
git commit -m "feat(benchmarks): read OpenDota per-player percentiles + weakness filter"
```

---

### Task 6: Scoring

**Files:**
- Create: `src/dota_coach/scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `models.EventCandidate`, `ScoredMoment`, `Confidence`, `Verdict`, `Match`, `MetricBenchmark`; `extract_events`, `player_benchmarks` (in test).
- Produces: `score_events(events: list[EventCandidate], benchmarks: list[MetricBenchmark], match: Match, account_id: int|None, top_n: int = 10) -> list[ScoredMoment]`.
  - Scoring per event (see §5 of spec): impact + my-involvement + mistake-signal + benchmark-deviation.
  - Dedup teamfight-clustered events (drop non-teamfight events within ±20s of a scored teamfight).
  - Verdict: teamfight death where I have no vision signal → `NOT_ENOUGH_INFO` (low confidence, anti-outcome-bias); measurable networth swing / weak benchmark → `MISTAKE` (high confidence). Default `NEUTRAL`.
  - Returns top_n by score, descending.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoring.py
import json
from pathlib import Path

from dota_coach.benchmarks import player_benchmarks
from dota_coach.events import extract_events
from dota_coach.ingest.normalize import normalize
from dota_coach.models import Confidence, EventType, Verdict
from dota_coach.scoring import score_events

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def _match():
    return normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_scoring_returns_sorted_top_n():
    m = _match()
    events = extract_events(m, 111)
    benches = player_benchmarks(m, 111)
    moments = score_events(events, benches, m, 111, top_n=3)
    assert len(moments) <= 3
    scores = [mm.score for mm in moments]
    assert scores == sorted(scores, reverse=True)


def test_involving_teamfight_scores_above_neutral_ward():
    m = _match()
    events = extract_events(m, 111)
    benches = player_benchmarks(m, 111)
    moments = score_events(events, benches, m, 111, top_n=20)
    by_type = {}
    for mm in moments:
        by_type.setdefault(mm.event.type, mm.score)
    assert by_type[EventType.TEAMFIGHT] > by_type.get(EventType.WARD, 0)


def test_teamfight_death_without_vision_is_not_outcome_biased():
    m = _match()
    events = extract_events(m, 111)
    benches = player_benchmarks(m, 111)
    moments = score_events(events, benches, m, 111, top_n=20)
    tf = next(mm for mm in moments if mm.event.type == EventType.TEAMFIGHT)
    # lost fight (my_gold_delta<0) but no proof it was a misplay -> not a hard "mistake"
    assert tf.verdict in (Verdict.NOT_ENOUGH_INFO, Verdict.NEUTRAL)
    assert tf.confidence == Confidence.LOW
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/dota_coach/scoring.py`**

```python
from __future__ import annotations

from dota_coach.models import (
    Confidence, EventCandidate, EventType, Match, MetricBenchmark, ScoredMoment, Verdict,
)

_DEDUP_WINDOW = 20  # seconds around a teamfight to drop minor events


def _impact(ev: EventCandidate) -> float:
    if ev.type == EventType.TEAMFIGHT:
        return abs(ev.data.get("my_gold_delta", 0)) / 100.0 + ev.data.get("deaths", 0)
    if ev.type == EventType.NETWORTH_SWING:
        return abs(ev.data.get("delta", 0)) / 100.0
    if ev.type == EventType.OBJECTIVE:
        return 3.0
    if ev.type == EventType.ITEM_TIMING:
        return 1.5
    return 0.5  # ward, misc


def _score_one(ev: EventCandidate, weak_count: int) -> ScoredMoment:
    score = _impact(ev)
    reasons: list[str] = []
    if ev.involves_me:
        score += 3.0
        reasons.append("ты вовлечён")

    verdict = Verdict.NEUTRAL
    confidence = Confidence.LOW

    if ev.type == EventType.NETWORTH_SWING:
        verdict = Verdict.MISTAKE
        confidence = Confidence.HIGH
        reasons.append("измеримая просадка нетворса")
    elif ev.type == EventType.TEAMFIGHT and ev.data.get("my_gold_delta", 0) < 0:
        # lost fight, but no vision/positioning proof -> do NOT call it a mistake
        verdict = Verdict.NOT_ENOUGH_INFO
        reasons.append("слитая драка — нужен ручной разбор (нет данных о позиции/вижене)")

    if weak_count and ev.type == EventType.ITEM_TIMING:
        reasons.append("на фоне слабых бенчмарков фарма")

    return ScoredMoment(event=ev, score=score, confidence=confidence,
                        verdict=verdict, reasons=reasons)


def _dedup(moments: list[ScoredMoment]) -> list[ScoredMoment]:
    tf_times = [m.event.game_time for m in moments if m.event.type == EventType.TEAMFIGHT]
    kept: list[ScoredMoment] = []
    for m in moments:
        if m.event.type == EventType.TEAMFIGHT:
            kept.append(m)
            continue
        near_tf = any(abs(m.event.game_time - t) <= _DEDUP_WINDOW for t in tf_times)
        if not near_tf:
            kept.append(m)
    return kept


def score_events(events: list[EventCandidate], benchmarks: list[MetricBenchmark],
                 match: Match, account_id: int | None, top_n: int = 10) -> list[ScoredMoment]:
    weak_count = sum(1 for b in benchmarks if b.pct < 0.4)
    scored = [_score_one(ev, weak_count) for ev in events]
    scored = _dedup(scored)
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:top_n]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/scoring.py tests/test_scoring.py
git commit -m "feat(scoring): rank events, dedup, anti-outcome-bias verdict + confidence"
```

---

### Task 7: Leaks (cross-match)

**Files:**
- Create: `src/dota_coach/leaks.py`
- Test: `tests/test_leaks.py`

**Interfaces:**
- Consumes: `models.Match`, `Leak`, `Confidence`; `player_benchmarks`.
- Produces: `detect_leaks(matches: list[Match], account_id: int | None) -> list[Leak]`.
  - MVP leaks (pure over the match list, no LLM):
    1. `farm_below_bracket` — median `gold_per_min` percentile across matches < 0.4 → leak, magnitude = "медиана GPM в p{XX}".
    2. `feeding` — mean deaths per match above a threshold (8) → leak.
    3. `low_warding` — mean obs wards per match below 4 → leak.
  - Each leak lists up to 3 `example_matches` (match_ids that most exhibit it). High confidence (all measurable).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_leaks.py
from dota_coach.leaks import detect_leaks
from dota_coach.models import Match, PlayerMatch


def _p(account_id, gpm_pct, deaths, obs):
    return PlayerMatch(
        account_id=account_id, player_slot=0, hero_id=1, is_radiant=True,
        kills=0, deaths=deaths, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
        gold_t=[], xp_t=[], lh_t=[], kills_log=[], purchase_log=[],
        obs_log=[{"time": 60}] * obs, sen_log=[],
        benchmarks={"gold_per_min": {"raw": 400, "pct": gpm_pct}},
    )


def _m(mid, account_id, gpm_pct, deaths, obs):
    return Match(match_id=mid, duration=1800, radiant_win=True,
                 players=[_p(account_id, gpm_pct, deaths, obs)],
                 teamfights=[], objectives=[], parsed=True)


def test_detects_farm_feeding_and_warding_leaks():
    matches = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=1) for i in range(5)]
    leaks = detect_leaks(matches, 111)
    keys = {l.key for l in leaks}
    assert "farm_below_bracket" in keys
    assert "feeding" in keys
    assert "low_warding" in keys
    farm = next(l for l in leaks if l.key == "farm_below_bracket")
    assert len(farm.example_matches) <= 3


def test_clean_player_has_no_leaks():
    matches = [_m(i, 111, gpm_pct=0.7, deaths=3, obs=8) for i in range(5)]
    assert detect_leaks(matches, 111) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_leaks.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/dota_coach/leaks.py`**

```python
from __future__ import annotations

from statistics import mean, median

from dota_coach.benchmarks import player_benchmarks
from dota_coach.models import Confidence, Leak, Match

_FARM_PCT = 0.4
_DEATHS_MAX = 8.0
_OBS_MIN = 4.0


def _gpm_pct(match: Match, account_id: int | None) -> float | None:
    for b in player_benchmarks(match, account_id):
        if b.metric == "gold_per_min":
            return b.pct
    return None


def detect_leaks(matches: list[Match], account_id: int | None) -> list[Leak]:
    rows = []
    for m in matches:
        me = m.player_by_account(account_id)
        if me is None:
            continue
        rows.append({
            "match_id": m.match_id,
            "gpm_pct": _gpm_pct(m, account_id),
            "deaths": me.deaths,
            "obs": len(me.obs_log),
        })
    if not rows:
        return []

    leaks: list[Leak] = []

    gpms = [r["gpm_pct"] for r in rows if r["gpm_pct"] is not None]
    if gpms and median(gpms) < _FARM_PCT:
        worst = sorted((r for r in rows if r["gpm_pct"] is not None),
                       key=lambda r: r["gpm_pct"])[:3]
        leaks.append(Leak(
            key="farm_below_bracket",
            title="Фарм ниже бракета",
            magnitude=f"медиана GPM в p{int(median(gpms) * 100)}",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
        ))

    avg_deaths = mean(r["deaths"] for r in rows)
    if avg_deaths > _DEATHS_MAX:
        worst = sorted(rows, key=lambda r: r["deaths"], reverse=True)[:3]
        leaks.append(Leak(
            key="feeding",
            title="Слишком много смертей",
            magnitude=f"в среднем {avg_deaths:.1f} смертей за игру (порог {_DEATHS_MAX:.0f})",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
        ))

    avg_obs = mean(r["obs"] for r in rows)
    if avg_obs < _OBS_MIN:
        worst = sorted(rows, key=lambda r: r["obs"])[:3]
        leaks.append(Leak(
            key="low_warding",
            title="Мало вардов",
            magnitude=f"в среднем {avg_obs:.1f} обс-вардов за игру (порог {_OBS_MIN:.0f})",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
        ))

    return leaks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_leaks.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/leaks.py tests/test_leaks.py
git commit -m "feat(leaks): cross-match systemic leak detection (farm/feeding/warding)"
```

---

### Task 8: Video alignment (offset + reads)

**Files:**
- Create: `src/dota_coach/video/align.py`
- Test: `tests/test_align.py`

**Interfaces:**
- Consumes: `models.ClockRead`.
- Produces:
  - `compute_offset(reads: list[ClockRead]) -> float` — robust `offset = median(t_video - t_game)`; raises `ValueError` if empty.
  - `video_time_for(game_time: int, offset: float) -> float` — `game_time + offset`, clamped to `>= 0`.
  - `sample_clock_reads(sample_times: list[float], frame_at, ocr, crop) -> list[ClockRead]` — pure orchestration over injected callables (`frame_at(t)->frame`, `crop(frame)->frame`, `ocr(frame)->int|None`); skips frames where OCR returns `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_align.py
import pytest

from dota_coach.models import ClockRead
from dota_coach.video.align import compute_offset, sample_clock_reads, video_time_for


def test_compute_offset_is_median_of_video_minus_game():
    reads = [ClockRead(t_video=100.0, t_game=40),
             ClockRead(t_video=160.0, t_game=100),
             ClockRead(t_video=600.0, t_game=540)]
    # offsets: 60, 60, 60
    assert compute_offset(reads) == 60.0


def test_compute_offset_robust_to_one_bad_read():
    reads = [ClockRead(t_video=100.0, t_game=40),
             ClockRead(t_video=160.0, t_game=100),
             ClockRead(t_video=999.0, t_game=100)]  # outlier
    # offsets: 60, 60, 899 -> median 60
    assert compute_offset(reads) == 60.0


def test_compute_offset_empty_raises():
    with pytest.raises(ValueError):
        compute_offset([])


def test_video_time_for_clamps_to_zero():
    assert video_time_for(game_time=100, offset=60.0) == 160.0
    assert video_time_for(game_time=10, offset=-50.0) == 0.0


def test_sample_clock_reads_skips_none_ocr():
    frames = {0.0: "f0", 30.0: "f30", 60.0: "f60"}
    ocr_map = {"f0": 0, "f30": None, "f60": 60}
    reads = sample_clock_reads(
        sample_times=[0.0, 30.0, 60.0],
        frame_at=lambda t: frames[t],
        ocr=lambda f: ocr_map[f],
        crop=lambda f: f,
    )
    assert [r.t_game for r in reads] == [0, 60]
    assert [r.t_video for r in reads] == [0.0, 60.0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_align.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dota_coach.video.align'`.

- [ ] **Step 3: Write `src/dota_coach/video/align.py`**

```python
from __future__ import annotations

from statistics import median
from typing import Callable

from dota_coach.models import ClockRead


def compute_offset(reads: list[ClockRead]) -> float:
    if not reads:
        raise ValueError("need at least one ClockRead to compute offset")
    return median(r.t_video - r.t_game for r in reads)


def video_time_for(game_time: int, offset: float) -> float:
    return max(0.0, game_time + offset)


def sample_clock_reads(
    sample_times: list[float],
    frame_at: Callable[[float], object],
    ocr: Callable[[object], int | None],
    crop: Callable[[object], object],
) -> list[ClockRead]:
    reads: list[ClockRead] = []
    for t in sample_times:
        game = ocr(crop(frame_at(t)))
        if game is not None:
            reads.append(ClockRead(t_video=t, t_game=game))
    return reads
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_align.py -v`
Expected: 5 passed.

- [ ] **Step 5: Write the opencv/tesseract IO helpers (glue — no unit test)**

Append to `src/dota_coach/video/align.py`:

```python
def opencv_frame_at(video_path: str) -> Callable[[float], object]:
    """Return frame_at(t) that grabs a BGR frame at second t via OpenCV."""
    import cv2

    cap = cv2.VideoCapture(video_path)

    def frame_at(t: float):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"cannot read frame at {t}s from {video_path}")
        return frame

    return frame_at


def crop_hud_clock(frame, box=(0.46, 0.0, 0.54, 0.04)):
    """Crop the top-center HUD clock. box = (x0,y0,x1,y1) as fractions of w/h."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def tesseract_clock_ocr(frame) -> int | None:
    """OCR a 'MM:SS' clock crop -> seconds, or None if unreadable."""
    import pytesseract

    text = pytesseract.image_to_string(
        frame, config="--psm 7 -c tessedit_char_whitelist=0123456789:"
    ).strip()
    if ":" not in text:
        return None
    mm, _, ss = text.partition(":")
    if not (mm.isdigit() and ss.isdigit()):
        return None
    return int(mm) * 60 + int(ss)
```

The `box` fraction default is a starting guess; it is a documented calibration knob (spec §11 — OCR may need per-resolution tuning).

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/video/align.py tests/test_align.py
git commit -m "feat(video): clock->video offset (pure) + opencv/tesseract HUD readers"
```

---

### Task 9: Video clip command builder

**Files:**
- Create: `src/dota_coach/video/clip.py`
- Test: `tests/test_clip.py`

**Interfaces:**
- Consumes: —
- Produces: `build_clip_command(video_path: str, start_video: float, end_video: float, out_path: str) -> list[str]` — an `ffmpeg` argv list (fast seek before `-i`, stream copy). Pure; execution is the caller's job.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clip.py
from dota_coach.video.clip import build_clip_command


def test_build_clip_command_shape():
    cmd = build_clip_command("game.mp4", start_video=155.0, end_video=170.0,
                             out_path="out/clip.mp4")
    assert cmd[0] == "ffmpeg"
    assert "-i" in cmd and cmd[cmd.index("-i") + 1] == "game.mp4"
    assert "155.000" in cmd          # fast seek value
    assert cmd[-1] == "out/clip.mp4"
    # -ss must precede -i for fast seek
    assert cmd.index("-ss") < cmd.index("-i")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_clip.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/dota_coach/video/clip.py`**

```python
from __future__ import annotations


def build_clip_command(video_path: str, start_video: float, end_video: float,
                       out_path: str) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-ss", f"{start_video:.3f}",
        "-to", f"{end_video:.3f}",
        "-i", video_path,
        "-c", "copy",
        out_path,
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_clip.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/video/clip.py tests/test_clip.py
git commit -m "feat(video): ffmpeg clip command builder"
```

---

### Task 10: HTML report

**Files:**
- Create: `src/dota_coach/report.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `models.ScoredMoment`, `Leak`; `video_time_for`.
- Produces: `render_report(match_id: int, moments: list[ScoredMoment], leaks: list[Leak], video_filename: str | None, offset: float) -> str`.
  - Returns a self-contained HTML string.
  - If `video_filename` given: an HTML5 `<video>` and each moment is a button that seeks `video.currentTime` to `video_time_for(game_time, offset)`.
  - Each moment shows summary, verdict, confidence, reasons. Leaks listed in their own section.
  - User-facing text in Russian.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
from dota_coach.models import (
    Confidence, EventCandidate, EventType, Leak, ScoredMoment, Verdict,
)
from dota_coach.report import render_report


def _moment(t, summary, verdict=Verdict.NEUTRAL):
    ev = EventCandidate(type=EventType.TEAMFIGHT, game_time=t, involves_me=True,
                        summary=summary, data={})
    return ScoredMoment(event=ev, score=9.0, confidence=Confidence.LOW,
                        verdict=verdict, reasons=["ты вовлечён"])


def test_report_contains_moment_and_seek_time():
    moments = [_moment(100, "тимфайт 1:40")]
    html = render_report(8001, moments, leaks=[], video_filename="game.mp4", offset=60.0)
    assert "тимфайт 1:40" in html
    assert "game.mp4" in html
    assert "160" in html            # video_time_for(100, 60) = 160.0 seek target
    assert "8001" in html


def test_report_lists_leaks():
    leak = Leak(key="feeding", title="Слишком много смертей",
                magnitude="в среднем 11.0 смертей за игру", example_matches=[1, 2],
                confidence=Confidence.HIGH)
    html = render_report(8001, moments=[], leaks=[leak], video_filename=None, offset=0.0)
    assert "Слишком много смертей" in html
    assert "в среднем 11.0" in html


def test_report_without_video_has_no_video_tag():
    html = render_report(8001, moments=[_moment(50, "x")], leaks=[],
                         video_filename=None, offset=0.0)
    assert "<video" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/dota_coach/report.py`**

```python
from __future__ import annotations

import html as _html

from dota_coach.models import Leak, ScoredMoment
from dota_coach.video.align import video_time_for

_VERDICT_RU = {
    "mistake": "ошибка",
    "fine_variance": "норм, вария",
    "not_enough_info": "нужен ручной разбор",
    "neutral": "нейтрально",
}
_CONF_RU = {"high": "высокая уверенность", "low": "низкая уверенность"}


def _moment_row(m: ScoredMoment, video_filename: str | None, offset: float) -> str:
    summary = _html.escape(m.event.summary)
    verdict = _VERDICT_RU.get(m.verdict.value, m.verdict.value)
    conf = _CONF_RU.get(m.confidence.value, m.confidence.value)
    reasons = "; ".join(_html.escape(r) for r in m.reasons)
    meta = f"<span class='meta'>[{verdict} · {conf}]</span>"
    body = f"{summary} {meta}<div class='reasons'>{reasons}</div>"
    if video_filename:
        t = video_time_for(m.event.game_time, offset)
        return (f"<li><button onclick=\"seek({t:.3f})\">▶ {m.event.game_time}s</button> "
                f"{body}</li>")
    return f"<li>{m.event.game_time}s — {body}</li>"


def _leak_row(l: Leak) -> str:
    ex = ", ".join(str(x) for x in l.example_matches)
    return (f"<li><b>{_html.escape(l.title)}</b>: {_html.escape(l.magnitude)}"
            f"<div class='reasons'>примеры матчей: {ex}</div></li>")


def render_report(match_id: int, moments: list[ScoredMoment], leaks: list[Leak],
                  video_filename: str | None, offset: float) -> str:
    video_block = ""
    script = ""
    if video_filename:
        src = _html.escape(video_filename)
        video_block = f"<video id='vid' src='{src}' controls width='900'></video>"
        script = ("<script>function seek(t){var v=document.getElementById('vid');"
                  "v.currentTime=t;v.play();}</script>")

    moment_items = "\n".join(_moment_row(m, video_filename, offset) for m in moments)
    leak_items = "\n".join(_leak_row(l) for l in leaks)
    leaks_section = (f"<h2>Системные лики</h2><ul>{leak_items}</ul>" if leaks else "")

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Dota Coach — матч {match_id}</title>
<style>
  body{{font-family:sans-serif;max-width:960px;margin:24px auto;color:#eee;background:#1b1b1f}}
  button{{cursor:pointer;background:#2d6cdf;color:#fff;border:0;border-radius:4px;padding:4px 8px}}
  .meta{{color:#9ab}} .reasons{{color:#9a9;font-size:13px;margin:2px 0 10px}}
  li{{margin:8px 0}}
</style></head><body>
<h1>Разбор матча {match_id}</h1>
{video_block}
<h2>Ключевые моменты</h2>
<ul>{moment_items}</ul>
{leaks_section}
{script}
</body></html>"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_report.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/report.py tests/test_report.py
git commit -m "feat(report): static HTML report with video-seek moments and leaks"
```

---

### Task 11: CLI wiring

Ties the pipeline together. IO-heavy (network, video, filesystem), so it is thin glue with one seam test (the pure assembly function).

**Files:**
- Create: `src/dota_coach/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `build_match_report(match: Match, account_id: int|None, video_filename: str|None, offset: float, top_n: int=10) -> str` — pure assembly (normalize→events→benchmarks→score→render); unit-tested against the fixture.
  - `main(argv: list[str] | None = None) -> int` — argparse CLI:
    - `analyze --match-id ID --account-id ID [--video PATH] [--out report.html]`
    - `leaks --account-id ID [--n 20]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
import json
from pathlib import Path

from dota_coach.cli import build_match_report
from dota_coach.ingest.normalize import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def test_build_match_report_end_to_end():
    match = normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))
    html = build_match_report(match, account_id=111, video_filename=None,
                              offset=0.0, top_n=5)
    assert "Разбор матча 8001" in html
    assert "Ключевые моменты" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `src/dota_coach/cli.py`**

```python
from __future__ import annotations

import argparse
from pathlib import Path

from dota_coach.benchmarks import player_benchmarks
from dota_coach.events import extract_events
from dota_coach.ingest.normalize import normalize
from dota_coach.ingest.opendota import fetch_match, fetch_recent
from dota_coach.leaks import detect_leaks
from dota_coach.models import Match
from dota_coach.report import render_report
from dota_coach.scoring import score_events
from dota_coach.video.align import (
    compute_offset, crop_hud_clock, opencv_frame_at, sample_clock_reads, tesseract_clock_ocr,
)


def build_match_report(match: Match, account_id: int | None, video_filename: str | None,
                       offset: float, top_n: int = 10) -> str:
    events = extract_events(match, account_id)
    benches = player_benchmarks(match, account_id)
    moments = score_events(events, benches, match, account_id, top_n=top_n)
    return render_report(match.match_id, moments, leaks=[],
                         video_filename=video_filename, offset=offset)


def _video_offset(video_path: str, duration: int) -> float:
    # sample the HUD clock at a few evenly-spread points
    sample_times = [duration * f for f in (0.15, 0.4, 0.65, 0.9)]
    reads = sample_clock_reads(
        sample_times,
        frame_at=opencv_frame_at(video_path),
        ocr=tesseract_clock_ocr,
        crop=crop_hud_clock,
    )
    return compute_offset(reads)


def _cmd_analyze(args: argparse.Namespace) -> int:
    match = normalize(fetch_match(args.match_id))
    offset = 0.0
    video_filename = None
    if args.video:
        video_filename = Path(args.video).name
        offset = _video_offset(args.video, match.duration)
    html = build_match_report(match, args.account_id, video_filename, offset, args.top_n)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"report -> {args.out}")
    return 0


def _cmd_leaks(args: argparse.Namespace) -> int:
    ids = fetch_recent(args.account_id, args.n)
    matches = [normalize(fetch_match(mid)) for mid in ids]
    leaks = detect_leaks(matches, args.account_id)
    html = render_report(match_id=0, moments=[], leaks=leaks,
                         video_filename=None, offset=0.0)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"leaks over {len(matches)} matches -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dota-coach")
    sub = parser.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="разбор одного матча")
    a.add_argument("--match-id", type=int, required=True, dest="match_id")
    a.add_argument("--account-id", type=int, required=True, dest="account_id")
    a.add_argument("--video", default=None)
    a.add_argument("--out", default="report.html")
    a.add_argument("--top-n", type=int, default=10, dest="top_n")
    a.set_defaults(func=_cmd_analyze)

    l = sub.add_parser("leaks", help="системные лики по последним матчам")
    l.add_argument("--account-id", type=int, required=True, dest="account_id")
    l.add_argument("--n", type=int, default=20)
    l.add_argument("--out", default="leaks.html")
    l.set_defaults(func=_cmd_leaks)

    args = parser.parse_args(argv)
    return args.func(args)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all tests pass (models, normalize, events, benchmarks, scoring, leaks, align, clip, report, cli, smoke).

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/cli.py tests/test_cli.py
git commit -m "feat(cli): analyze + leaks entrypoints wiring the pipeline"
```

---

## Manual verification (after all tasks)

Not automated (needs a real account + video); run once to confirm the MVP works end-to-end:

1. In Dota settings enable **Expose Public Match Data**. Find your `account_id` (32-bit) via your Steam profile / OpenDota.
2. Pick a recent **parsed** match id (if unparsed: `curl -X POST https://api.opendota.com/api/request/<match_id>` and wait).
3. `dota-coach analyze --match-id <id> --account-id <you>` → open `report.html`, confirm 8–12 ranked moments render.
4. Record a match to mp4 (OBS), then `dota-coach analyze --match-id <id> --account-id <you> --video game.mp4` → click a moment, confirm the video seeks within ±1–2s (if off, tune `crop_hud_clock`'s `box`).
5. `dota-coach leaks --account-id <you> --n 20` → open `leaks.html`, confirm 0–3 systemic leaks with example match ids.

---

## Notes for the executor

- **TDD rhythm:** write test → watch it fail → minimal code → watch it pass → commit. Don't gold-plate.
- **Frozen dataclasses:** production data flows through `normalize`; only tests mutate via `object.__setattr__`.
- **No LLM here.** The `coach` module (Claude) is phase 2 and out of scope — do not add API calls.
- **Windows paths:** always `pathlib.Path`, never string-concatenate `/`.
- **OpenDota fixture** is hand-built to the known schema; when you first hit the live API, diff a real match JSON against `opendota_match_sample.json` and adjust `normalize.py` mappings if OpenDota changed a field name.
