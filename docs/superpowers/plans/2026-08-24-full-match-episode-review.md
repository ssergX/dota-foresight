# Full-Match Episode Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить одиночный фокус-разбор в обзор всего матча — карточка-факты + видеоклип 30с на каждый эпизод (драки + твои смерти из реплея + просадки нетворса), полный LLM-разбор на 1–2 острых, с авто-сборкой видео из записи Steam.

**Architecture:** КОД собирает список эпизодов и строит карточки-факты из реплея (`info_state_at`); LLM вызывается ОТДЕЛЬНО на 1–2 самых острых (анти-результат цел). Стадия A даёт папку-отчёт по данным; Стадия B добавляет локатор записи Steam, сшивку DASH-осколков, авто-выравнивание часов по шаблонам цифр и нарезку клипов.

**Tech Stack:** Python 3.12, pytest, OpenCV (cv2 5.0.0), numpy, imageio-ffmpeg (portable ffmpeg v7.1), claude -p (LLM). Всё уже установлено в венв `C:\Users\user\PycharmProjects\Tablichki_tech\.venv`.

## Global Constraints

- Запуск тестов: `PYTHONIOENCODING=utf-8 PYTHONPATH=src python -m pytest -q` (из `C:\Users\user\PycharmProjects\dota-coach`).
- **Никаких новых pip-зависимостей** — только cv2, numpy, imageio-ffmpeg (уже стоят), stdlib.
- **Анти-результат (сканер):** в LLM-входах и в тексте карточек НЕ должно быть `_BANNED_TOKENS = ("radiant_win","radiant_score","dire_score")` и `_BANNED_WORDS = ("победа","поражени","выигр","проигр")`.
- **Детерминированное ядро:** список эпизодов, вердикты, выбор глубоких, окна клипов ставит КОД; LLM только формулирует текст.
- Слот игрока: `slot = player_slot if player_slot < 128 else player_slot - 123`.
- Базлайн: **183 pytest зелёные** — ничего существующего не ломать.
- Стиль: `from __future__ import annotations`; чистые функции отдельно от сети/ffmpeg/cv2; русские строки в UI.
- Коммиты после каждой задачи, префиксы `feat/refactor/test/docs`.

---

## Стадия A — эпизоды + карточки + папка-отчёт (данные-only, без видео)

### Task A1: `my_death_times` — смерти из реплея (в т.ч. соло)

**Files:**
- Create: `src/dota_coach/episodes.py`
- Test: `tests/test_episodes_deaths.py`

**Interfaces:**
- Consumes: `dota_coach.models.ParsedReplay`, `ReplayFrame`, `UnitState`.
- Produces: `my_death_times(parsed: ParsedReplay, my_slot: int) -> list[int]` — возрастающий список игровых секунд, где мой слот перешёл `alive→dead`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_episodes_deaths.py
from dota_coach.episodes import my_death_times
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState


def _u(alive):
    return UnitState(slot=0, x=0, y=0, hp=100 if alive else 0, max_hp=100,
                     mana=0, level=1, xp=0, alive=alive)


def _replay(alive_by_time):
    frames = [ReplayFrame(time=t, units={0: _u(a)}) for t, a in alive_by_time]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={0: "Lina"},
                        frames=frames, teams={0: 2})


def test_death_and_respawn_then_second_death():
    # alive, alive, DEAD@3, dead, ALIVE@5 (respawn), DEAD@7
    parsed = _replay([(1, True), (2, True), (3, False), (4, False),
                      (5, True), (6, True), (7, False)])
    assert my_death_times(parsed, 0) == [3, 7]


def test_no_deaths():
    parsed = _replay([(1, True), (2, True)])
    assert my_death_times(parsed, 0) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_episodes_deaths.py -q`
Expected: FAIL — `ModuleNotFoundError: dota_coach.episodes`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/dota_coach/episodes.py
from __future__ import annotations

from dota_coach.models import ParsedReplay


def my_death_times(parsed: ParsedReplay, my_slot: int) -> list[int]:
    """Игровые секунды, где мой слот перешёл alive->dead (респавн игнор). Соло-смерти тоже."""
    times: list[int] = []
    prev_alive: bool | None = None
    for f in parsed.frames:
        u = f.units.get(my_slot)
        if u is None:
            continue
        if prev_alive is True and not u.alive:
            times.append(f.time)
        prev_alive = u.alive
    return times
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_episodes_deaths.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/episodes.py tests/test_episodes_deaths.py
git commit -m "feat(episodes): my_death_times из реплея (соло-смерти по alive-переходам)"
```

---

### Task A2: скоринг события DEATH

**Files:**
- Modify: `src/dota_coach/scoring.py` (`_impact`, `_score_one`)
- Test: `tests/test_scoring_death.py`

**Interfaces:**
- Consumes: `EventCandidate(type=EventType.DEATH, ...)`.
- Produces: `score_events` теперь принимает DEATH-события; DEATH → `Verdict.NEUTRAL`, `Confidence.LOW`, reason `"твоя смерть"`; impact 2.5.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoring_death.py
from dota_coach.models import EventCandidate, EventType, Verdict
from dota_coach.scoring import _score_one


def test_death_scored_neutral_with_reason():
    ev = EventCandidate(type=EventType.DEATH, game_time=600, involves_me=True,
                        summary="твоя смерть", data={"solo": True})
    m = _score_one(ev, weak_count=0)
    assert m.verdict == Verdict.NEUTRAL
    assert "твоя смерть" in m.reasons
    assert m.score >= 5.0   # 2.5 impact + 3.0 involves_me
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_scoring_death.py -q`
Expected: FAIL — DEATH попадает в дефолт impact 0.5, reason отсутствует.

- [ ] **Step 3: Write minimal implementation**

In `src/dota_coach/scoring.py`, add DEATH to `_impact` (before the final `return 0.5`):

```python
    if ev.type == EventType.DEATH:
        return 2.5
```

In `_score_one`, add a branch after the teamfight `elif` (before the `if weak_count` line):

```python
    elif ev.type == EventType.DEATH:
        reasons.append("твоя смерть")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_scoring_death.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/scoring.py tests/test_scoring_death.py
git commit -m "feat(scoring): событие DEATH -> neutral, impact 2.5, reason 'твоя смерть'"
```

---

### Task A3: `build_episodes` + `Episode` + severity

**Files:**
- Modify: `src/dota_coach/episodes.py`
- Test: `tests/test_episodes_build.py`

**Interfaces:**
- Consumes: `extract_events` (dota_coach.events), `score_events` (dota_coach.scoring), `player_benchmarks` (dota_coach.benchmarks), `info_state_at` (dota_coach.coach.info_state), `my_death_times` (A1).
- Produces:
  - `@dataclass Episode: moment: ScoredMoment; severity: float`
  - `slot_index(player_slot: int) -> int`
  - `build_episodes(match, parsed, account_id) -> list[Episode]` — хронологический список: драки + просадки нетворса (из extract_events) + соло-смерти (из реплея, не внутри драк). Каждый оборачивает `ScoredMoment`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_episodes_build.py
from dota_coach.episodes import Episode, build_episodes, slot_index
from dota_coach.models import (
    Match, ParsedReplay, PlayerMatch, ReplayFrame, Teamfight, UnitState,
)


def _u(alive, hp=100):
    return UnitState(slot=0, x=0, y=0, hp=hp, max_hp=100, mana=0, level=1, xp=0, alive=alive)


def _match():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=2, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100, 700, 100], xp_t=[0, 0, 0, 0])
    tf = Teamfight(start=120, end=140, deaths=3,
                   players=[{"deaths": 1, "gold_delta": -300, "damage": 100}])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[tf], objectives=[])


def _replay():
    # death at 600 (solo, far from teamfight@120), death at 130 (inside teamfight -> folded)
    frames = []
    for t in range(0, 700, 10):
        alive = not (t in (130, 600))
        frames.append(ReplayFrame(time=t, units={1: _u(alive)}))
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina"},
                        frames=frames, teams={1: 2})


def test_build_episodes_has_teamfight_and_solo_death_not_folded():
    eps = build_episodes(_match(), _replay(), account_id=7)
    kinds = [e.moment.event.type.value for e in eps]
    times = [e.moment.event.game_time for e in eps]
    assert "teamfight" in kinds
    assert 600 in times            # solo death kept
    assert 130 not in times        # death inside teamfight window folded away
    assert times == sorted(times)  # chronological
    assert all(isinstance(e, Episode) for e in eps)


def test_slot_index():
    assert slot_index(1) == 1
    assert slot_index(130) == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_episodes_build.py -q`
Expected: FAIL — `Episode`/`build_episodes`/`slot_index` не определены.

- [ ] **Step 3: Write minimal implementation**

Append to `src/dota_coach/episodes.py`:

```python
from dataclasses import dataclass

from dota_coach.benchmarks import player_benchmarks
from dota_coach.coach.info_state import info_state_at
from dota_coach.events import extract_events
from dota_coach.models import EventCandidate, EventType, Match, ParsedReplay, ScoredMoment
from dota_coach.scoring import score_events


@dataclass
class Episode:
    moment: ScoredMoment
    severity: float


def slot_index(player_slot: int) -> int:
    return player_slot if player_slot < 128 else player_slot - 123


def _death_events(parsed: ParsedReplay, my_slot: int, teamfights) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for t in my_death_times(parsed, my_slot):
        if any(tf.start - 5 <= t <= tf.end + 5 for tf in teamfights):
            continue  # смерть внутри драки — свернётся в эпизод драки
        out.append(EventCandidate(
            type=EventType.DEATH, game_time=t, involves_me=True,
            summary=f"твоя смерть на {t // 60}:{t % 60:02d}", data={"solo": True}))
    return out


def _severity(moment: ScoredMoment, parsed: ParsedReplay, my_slot: int) -> float:
    sev = moment.score
    ev = moment.event
    if ev.type == EventType.DEATH and parsed is not None:
        info = info_state_at(parsed, ev.game_time, my_slot)
        if info and info.my_max_hp and info.my_hp / info.my_max_hp > 0.6 \
                and info.unseen_enemies >= 3:
            sev += 5.0  # умер на фулл-ХП вслепую — острый эпизод для deep-pick
    return sev


def build_episodes(match: Match, parsed: ParsedReplay | None,
                   account_id: int | None) -> list[Episode]:
    me = match.player_by_account(account_id)
    if me is None:
        return []
    my_slot = slot_index(me.player_slot)
    base = [e for e in extract_events(match, account_id)
            if e.type in (EventType.TEAMFIGHT, EventType.NETWORTH_SWING)]
    if parsed is not None:
        base += _death_events(parsed, my_slot, match.teamfights)
    benches = player_benchmarks(match, account_id)
    moments = score_events(base, benches, match, account_id, top_n=10_000)
    episodes = [Episode(moment=m, severity=_severity(m, parsed, my_slot)) for m in moments]
    episodes.sort(key=lambda e: e.moment.event.game_time)
    return episodes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_episodes_build.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/episodes.py tests/test_episodes_build.py
git commit -m "feat(episodes): build_episodes (драки+смерти+просадки), Episode, severity"
```

---

### Task A4: `select_deep` + публичный `VERDICT_RANK`

**Files:**
- Modify: `src/dota_coach/coach/moment_focus.py` (сделать `VERDICT_RANK` публичным)
- Modify: `src/dota_coach/episodes.py` (`select_deep`)
- Test: `tests/test_episodes_deep.py`

**Interfaces:**
- Consumes: `dota_coach.coach.moment_focus.VERDICT_RANK`.
- Produces: `select_deep(episodes: list[Episode], n: int = 1) -> list[Episode]` — топ-n по (ранг вердикта, -severity, game_time).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_episodes_deep.py
from dota_coach.episodes import Episode, select_deep
from dota_coach.models import (
    Confidence, EventCandidate, EventType, ScoredMoment, Verdict,
)


def _ep(game_time, severity, verdict=Verdict.NEUTRAL):
    ev = EventCandidate(type=EventType.DEATH, game_time=game_time, involves_me=True,
                        summary="", data={})
    m = ScoredMoment(event=ev, score=severity, confidence=Confidence.LOW, verdict=verdict)
    return Episode(moment=m, severity=severity)


def test_select_deep_picks_highest_severity_first():
    eps = [_ep(100, 2.0), _ep(200, 9.0), _ep(300, 5.0)]
    top = select_deep(eps, n=1)
    assert [e.moment.event.game_time for e in top] == [200]


def test_select_deep_prefers_mistake_verdict_over_neutral():
    eps = [_ep(100, 9.0, Verdict.NEUTRAL), _ep(200, 1.0, Verdict.MISTAKE)]
    top = select_deep(eps, n=1)
    assert top[0].moment.event.game_time == 200   # mistake ранжируется выше
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_episodes_deep.py -q`
Expected: FAIL — `select_deep` не определён.

- [ ] **Step 3: Write minimal implementation**

In `src/dota_coach/coach/moment_focus.py`, rename `_VERDICT_RANK` → `VERDICT_RANK` (публичный) and update its use in `select_focus_moment`:

```python
VERDICT_RANK = {
    Verdict.MISTAKE: 0,
    Verdict.NEUTRAL: 1,
    Verdict.FINE_VARIANCE: 1,
    Verdict.NOT_ENOUGH_INFO: 2,
}


def select_focus_moment(moments: list[ScoredMoment]) -> ScoredMoment | None:
    if not moments:
        return None
    return sorted(
        moments,
        key=lambda m: (VERDICT_RANK.get(m.verdict, 9), -m.score, m.event.game_time),
    )[0]
```

Append to `src/dota_coach/episodes.py`:

```python
from dota_coach.coach.moment_focus import VERDICT_RANK


def select_deep(episodes: list[Episode], n: int = 1) -> list[Episode]:
    ranked = sorted(episodes, key=lambda e: (
        VERDICT_RANK.get(e.moment.verdict, 9), -e.severity, e.moment.event.game_time))
    return ranked[:max(0, n)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_episodes_deep.py tests/test_moment_focus.py -q`
Expected: PASS (новые + существующие moment_focus тесты).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/moment_focus.py src/dota_coach/episodes.py tests/test_episodes_deep.py
git commit -m "feat(episodes): select_deep (1-2 острых); VERDICT_RANK публичный"
```

---

### Task A5: `episode_card.build_card`

**Files:**
- Create: `src/dota_coach/coach/episode_card.py`
- Test: `tests/test_episode_card.py`

**Interfaces:**
- Consumes: `info_state_at`, `render_info_state` (dota_coach.coach.info_state), `Episode` (A3).
- Produces:
  - `@dataclass(frozen=True) EpisodeCard: game_time:int; verdict:Verdict; facts:str; numbers:dict; info:InfoState|None`
  - `build_card(episode: Episode, parsed: ParsedReplay | None, my_slot: int) -> EpisodeCard`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_episode_card.py
from dota_coach.coach.episode_card import EpisodeCard, build_card
from dota_coach.episodes import Episode
from dota_coach.models import (
    Confidence, EventCandidate, EventType, ParsedReplay, ReplayFrame, ScoredMoment,
    UnitState, Verdict,
)


def _episode(game_time=600):
    ev = EventCandidate(type=EventType.DEATH, game_time=game_time, involves_me=True,
                        summary="твоя смерть на 10:00", data={"solo": True})
    m = ScoredMoment(event=ev, score=5.0, confidence=Confidence.LOW, verdict=Verdict.NEUTRAL)
    return Episode(moment=m, severity=5.0)


def _replay():
    me = UnitState(slot=1, x=0, y=0, hp=50, max_hp=100, mana=200, level=9, xp=0, alive=True)
    enemy = UnitState(slot=6, x=9000, y=9000, hp=100, max_hp=100, mana=0, level=9, xp=0, alive=True)
    frames = [ReplayFrame(time=t, units={1: me, 6: enemy}) for t in range(0, 601, 10)]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina", 6: "Pudge"},
                        frames=frames, teams={1: 2, 6: 3})


def test_build_card_with_replay_has_facts_from_info_state():
    card = build_card(_episode(), _replay(), my_slot=1)
    assert isinstance(card, EpisodeCard)
    assert card.game_time == 600
    assert card.info is not None
    assert "HP" in card.facts            # render_info_state текст
    assert card.numbers == {"solo": True}


def test_build_card_without_replay_falls_back_to_summary():
    card = build_card(_episode(), None, my_slot=1)
    assert card.info is None
    assert card.facts == "твоя смерть на 10:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_episode_card.py -q`
Expected: FAIL — модуль не существует.

- [ ] **Step 3: Write minimal implementation**

```python
# src/dota_coach/coach/episode_card.py
from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.info_state import InfoState, info_state_at, render_info_state
from dota_coach.episodes import Episode
from dota_coach.models import ParsedReplay, Verdict


@dataclass(frozen=True)
class EpisodeCard:
    game_time: int
    verdict: Verdict
    facts: str
    numbers: dict
    info: InfoState | None


def build_card(episode: Episode, parsed: ParsedReplay | None, my_slot: int) -> EpisodeCard:
    ev = episode.moment.event
    info = info_state_at(parsed, ev.game_time, my_slot) if parsed is not None else None
    facts = render_info_state(info) if info is not None else ev.summary
    return EpisodeCard(game_time=ev.game_time, verdict=episode.moment.verdict,
                       facts=facts, numbers=dict(ev.data), info=info)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_episode_card.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/episode_card.py tests/test_episode_card.py
git commit -m "feat(episode_card): карточка-факты из info_state (без исхода)"
```

---

### Task A6: `explain_scored` (рефактор `explain_moment`)

**Files:**
- Modify: `src/dota_coach/coach/moment_coach.py`
- Test: `tests/test_moment_coach.py` (добавить), существующие `test_moment_coach*.py` — зелёные.

**Interfaces:**
- Produces: `explain_scored(moment: ScoredMoment, llm: CoachLLM, info_state: InfoState | None = None) -> MomentBrief` — разбор конкретного момента (без `select_focus_moment`). `explain_moment` теперь тонкая обёртка через него.

- [ ] **Step 1: Write the failing test**

```python
# добавить в tests/test_moment_coach.py
import json

from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.moment_coach import explain_scored
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def test_explain_scored_stamps_identity_from_given_moment():
    ev = EventCandidate(type=EventType.DEATH, game_time=1234, involves_me=True,
                        summary="", data={})
    moment = ScoredMoment(event=ev, score=5.0, confidence=Confidence.LOW,
                          verdict=Verdict.NEUTRAL)
    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})
    brief = explain_scored(moment, FakeLLM(canned))
    assert brief.game_time == 1234
    assert brief.verdict == "neutral"
    assert brief.event_type == "death"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_coach.py -q`
Expected: FAIL — `explain_scored` не определён.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `src/dota_coach/coach/moment_coach.py`:

```python
from __future__ import annotations

from dota_coach.coach.info_state import InfoState, render_info_state
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief, parse_moment_brief
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import ScoredMoment


def explain_scored(moment: ScoredMoment, llm: CoachLLM,
                   info_state: InfoState | None = None) -> MomentBrief:
    principle = principle_for_moment(moment)
    info_block = render_info_state(info_state) if info_state is not None else ""
    messages = build_moment_prompt(moment, principle, info_block)
    brief = parse_moment_brief(llm.complete(messages))
    # идентичность момента ставит КОД (детерминизм + анти-результатничество):
    brief.game_time = moment.event.game_time
    brief.verdict = moment.verdict.value
    brief.event_type = moment.event.type.value
    return brief


def explain_moment(moments: list[ScoredMoment], llm: CoachLLM,
                   info_state: InfoState | None = None) -> MomentBrief | None:
    focus = select_focus_moment(moments)
    if focus is None:
        return None
    return explain_scored(focus, llm, info_state)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_coach.py tests/test_moment_coach_info.py tests/test_anti_resultism_moment.py -q`
Expected: PASS (новый + все существующие).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/moment_coach.py tests/test_moment_coach.py
git commit -m "refactor(moment_coach): explain_scored на конкретный момент; explain_moment — обёртка"
```

---

### Task A7: `review_match` — оркестратор разбора (КОД + LLM через Fake)

**Files:**
- Create: `src/dota_coach/coach/match_review.py`
- Test: `tests/test_match_review.py`

**Interfaces:**
- Consumes: `build_episodes`, `select_deep`, `slot_index` (episodes); `build_card` (episode_card); `explain_scored` (moment_coach).
- Produces:
  - `@dataclass MatchReview: episodes:list[Episode]; cards:list[EpisodeCard]; deep_briefs:dict[int, MomentBrief]`
  - `review_match(match, parsed, account_id, llm, deep_n: int = 1) -> MatchReview`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_match_review.py
import json

from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.match_review import MatchReview, review_match
from dota_coach.models import (
    Match, ParsedReplay, PlayerMatch, ReplayFrame, Teamfight, UnitState,
)


def _u(alive, hp=100):
    return UnitState(slot=0, x=0, y=0, hp=hp, max_hp=100, mana=0, level=1, xp=0, alive=alive)


def _match():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=1, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100, 200], xp_t=[0, 0, 0])
    tf = Teamfight(start=120, end=140, deaths=3,
                   players=[{"deaths": 1, "gold_delta": -300, "damage": 100}])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[tf], objectives=[])


def _replay():
    frames = [ReplayFrame(time=t, units={1: _u(t != 600)}) for t in range(0, 700, 10)]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina"},
                        frames=frames, teams={1: 2})


def test_review_match_returns_cards_and_one_deep_brief():
    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})
    review = review_match(_match(), _replay(), account_id=7, llm=FakeLLM(canned), deep_n=1)
    assert isinstance(review, MatchReview)
    assert len(review.cards) == len(review.episodes) >= 2
    assert len(review.deep_briefs) == 1
    # ключ deep_briefs — game_time одного из эпизодов
    assert list(review.deep_briefs)[0] in [e.moment.event.game_time for e in review.episodes]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_match_review.py -q`
Expected: FAIL — модуль не существует.

- [ ] **Step 3: Write minimal implementation**

```python
# src/dota_coach/coach/match_review.py
from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.episode_card import EpisodeCard, build_card
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.coach.moment_coach import explain_scored
from dota_coach.episodes import Episode, build_episodes, select_deep, slot_index
from dota_coach.models import Match, ParsedReplay


@dataclass
class MatchReview:
    episodes: list[Episode]
    cards: list[EpisodeCard]
    deep_briefs: dict[int, MomentBrief]


def review_match(match: Match, parsed: ParsedReplay | None, account_id: int | None,
                 llm: CoachLLM, deep_n: int = 1) -> MatchReview:
    me = match.player_by_account(account_id)
    my_slot = slot_index(me.player_slot) if me else 0
    episodes = build_episodes(match, parsed, account_id)
    cards = [build_card(e, parsed, my_slot) for e in episodes]
    deep_briefs: dict[int, MomentBrief] = {}
    for e in select_deep(episodes, min(deep_n, 2)):
        info = build_card(e, parsed, my_slot).info
        deep_briefs[e.moment.event.game_time] = explain_scored(e.moment, llm, info)
    return MatchReview(episodes=episodes, cards=cards, deep_briefs=deep_briefs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_match_review.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/match_review.py tests/test_match_review.py
git commit -m "feat(match_review): оркестратор review_match (карточки + 1-2 deep-брифа)"
```

---

### Task A8: `render_match_report` — папка-отчёт (без клипов)

**Files:**
- Modify: `src/dota_coach/report.py`
- Test: `tests/test_match_report.py`

**Interfaces:**
- Consumes: `EpisodeCard` (A5), `MomentBrief`, `_moment_brief_section` (report), `_VERDICT_RU`.
- Produces: `render_match_report(match_id: int, cards: list[EpisodeCard], deep_briefs: dict[int, MomentBrief], clips: dict[int, str], out_dir: str) -> None` — пишет `out_dir/index.html`; `clips[game_time]` (относительный путь) → `<video>` в карточке; `deep_briefs[game_time]` → блок брифа.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_match_report.py
from pathlib import Path

from dota_coach.coach.episode_card import EpisodeCard
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.models import Verdict
from dota_coach.report import render_match_report


def _card(game_time, facts="HP 100/100"):
    return EpisodeCard(game_time=game_time, verdict=Verdict.NEUTRAL, facts=facts,
                       numbers={"my_deaths": 1}, info=None)


def _brief(game_time):
    return MomentBrief(headline="Заголовок", hypothesis="гипотеза",
                       process_question="вопрос?", checklist=["пункт"], principle="принцип",
                       game_time=game_time, verdict="neutral", event_type="death")


def test_render_match_report_writes_index_with_cards_and_deep(tmp_path):
    cards = [_card(600), _card(1200)]
    render_match_report(1, cards, deep_briefs={600: _brief(600)}, clips={}, out_dir=str(tmp_path))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "10:00" in html and "20:00" in html      # оба эпизода
    assert "Заголовок" in html                       # блок брифа на deep-эпизоде
    assert "<video" not in html                      # клипов нет


def test_render_match_report_embeds_video_when_clip_present(tmp_path):
    render_match_report(1, [_card(600)], deep_briefs={}, clips={600: "clips/00.mp4"},
                        out_dir=str(tmp_path))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "clips/00.mp4" in html and "<video" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_match_report.py -q`
Expected: FAIL — `render_match_report` не определён.

- [ ] **Step 3: Write minimal implementation**

Append to `src/dota_coach/report.py` (после существующих функций; переиспуз `_VERDICT_RU`, `_fmt_time`, `_moment_brief_section`):

```python
import os


def _episode_card_html(card: "EpisodeCard", brief, clip: str | None) -> str:
    ts = _fmt_time(card.game_time)
    verdict = _VERDICT_RU.get(card.verdict.value, card.verdict.value)
    video = (f"<video src='{_html.escape(clip)}' controls width='720' "
             f"style='border-radius:8px;margin:6px 0;max-width:100%'></video>"
             if clip else "")
    nums = ", ".join(f"{k}={v}" for k, v in card.numbers.items())
    brief_html = ""
    if brief is not None:
        checklist = "\n".join(f"<li>{_html.escape(c)}</li>" for c in brief.checklist)
        brief_html = (
            f"<h4>{_html.escape(brief.headline)}</h4>"
            f"<p><b>Вероятно:</b> {_html.escape(brief.hypothesis)}</p>"
            f"<p><b>Спроси себя:</b> {_html.escape(brief.process_question)}</p>"
            f"<p><b>Проверь:</b></p><ul>{checklist}</ul>"
            f"<p class='reasons'>{_html.escape(brief.principle)}</p>")
    return (
        f"<div class='card'>"
        f"<h3>{ts} <span class='meta'>[{verdict}]</span></h3>"
        f"{video}"
        f"<p class='facts'>{_html.escape(card.facts)}</p>"
        f"<p class='reasons'>{_html.escape(nums)}</p>"
        f"{brief_html}"
        f"</div>")


def render_match_report(match_id: int, cards: list["EpisodeCard"],
                        deep_briefs: dict, clips: dict, out_dir: str) -> None:
    os.makedirs(os.path.join(out_dir, "clips"), exist_ok=True)
    body = "\n".join(
        _episode_card_html(c, deep_briefs.get(c.game_time), clips.get(c.game_time))
        for c in cards)
    html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Dota Coach — разбор матча {match_id}</title>
<style>
  body{{font-family:sans-serif;max-width:860px;margin:24px auto;color:#eee;background:#1b1b1f}}
  .card{{border:1px solid #333;border-radius:10px;padding:12px 16px;margin:14px 0;background:#212127}}
  h1{{color:#fff}} h3{{color:#cde;margin:0 0 6px}} h4{{color:#fff;margin:8px 0 4px}}
  .meta{{color:#9ab;font-size:13px}} .reasons{{color:#9a9;font-size:13px}}
  .facts{{white-space:pre-line}}
</style></head><body>
<h1>Разбор матча {match_id} — {len(cards)} эпизодов</h1>
{body}
</body></html>"""
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
```

Add `from dota_coach.coach.episode_card import EpisodeCard` под существующие импорты `report.py` (для аннотаций строкой это не обязательно, но добавь для ясности; проверь отсутствие циклического импорта — `episode_card` не импортирует `report`).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_match_report.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/report.py tests/test_match_report.py
git commit -m "feat(report): render_match_report — папка index.html + карточки + опц. видео"
```

---

### Task A9: CLI — `analyze --coach --deep N` → папка-отчёт при наличии реплея

**Files:**
- Modify: `src/dota_coach/cli.py` (`_cmd_analyze`, парсер `analyze`)
- Test: `tests/test_cli_match_review.py`

**Interfaces:**
- Consumes: `review_match` (A7), `render_match_report` (A8), `parse_replay`, `ReplayUnavailable`, `make_llm`, `fetch_match`, `normalize`, `slot_index`.
- Produces: `analyze --coach` при доступном реплее пишет папку (`--out` = директория); флаг `--deep N` (дефолт 1). Без реплея — прежний одиночный отчёт (совместимость).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_match_review.py
import json
from pathlib import Path

import dota_coach.cli as cli
from dota_coach.coach.llm import FakeLLM
from dota_coach.models import (
    Match, ParsedReplay, PlayerMatch, ReplayFrame, Teamfight, UnitState,
)


def _u(alive):
    return UnitState(slot=0, x=0, y=0, hp=100, max_hp=100, mana=0, level=1, xp=0, alive=alive)


def _match():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=1, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100, 200], xp_t=[0, 0, 0])
    tf = Teamfight(start=120, end=140, deaths=3,
                   players=[{"deaths": 1, "gold_delta": -300, "damage": 100}])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[tf], objectives=[])


def _replay():
    frames = [ReplayFrame(time=t, units={1: _u(t != 600)}) for t in range(0, 700, 10)]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina"},
                        frames=frames, teams={1: 2})


def test_analyze_coach_writes_folder_report(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "fetch_match", lambda mid: {"_": mid})
    monkeypatch.setattr(cli, "normalize", lambda raw: _match())
    monkeypatch.setattr(cli, "parse_replay", lambda mid: _replay())
    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})
    monkeypatch.setattr(cli, "make_llm", lambda provider: FakeLLM(canned))
    out = tmp_path / "review"
    rc = cli.main(["analyze", "--match-id", "1", "--account-id", "7",
                   "--coach", "--out", str(out)])
    assert rc == 0
    assert (out / "index.html").exists()
    assert "эпизодов" in (out / "index.html").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_cli_match_review.py -q`
Expected: FAIL — `--coach` пока пишет одиночный HTML-файл, не папку.

- [ ] **Step 3: Write minimal implementation**

In `src/dota_coach/cli.py`: add imports at top:

```python
from dota_coach.coach.match_review import review_match
from dota_coach.episodes import slot_index
from dota_coach.report import render_match_report
```

Add `--deep` to the `analyze` subparser (рядом с `--coach`):

```python
    a.add_argument("--deep", type=int, default=1, dest="deep_n",
                   help="сколько эпизодов разобрать LLM вглубь (кап 2)")
```

Replace `_cmd_analyze` with a version that branches to the folder report when `--coach` and a replay is available:

```python
def _cmd_analyze(args: argparse.Namespace) -> int:
    match = normalize(fetch_match(args.match_id))

    if args.coach:
        try:
            parsed = parse_replay(args.match_id)
        except ReplayUnavailable as exc:
            parsed = None
            print(f"реплей недоступен, разбор по данным без видео: {exc}")
        if parsed is not None:
            review = review_match(match, parsed, args.account_id,
                                  make_llm(args.provider), deep_n=args.deep_n)
            clips = _build_clips(args, match, review, parsed) if args.video else {}
            render_match_report(match.match_id, review.cards, review.deep_briefs,
                                clips, args.out)
            print(f"обзор {len(review.cards)} эпизодов -> {args.out}/index.html")
            return 0

    # fallback: одиночный отчёт (нет реплея или без --coach) — прежнее поведение
    offset = 0.0
    video_filename = None
    if args.video:
        video_filename = Path(args.video).name
        offset = args.video_offset if args.video_offset is not None else _video_offset(
            args.video, match.duration)
    html = build_match_report(match, args.account_id, video_filename, offset, args.top_n)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"report -> {args.out}")
    return 0


def _build_clips(args, match, review, parsed) -> dict:
    return {}   # Стадия B заполнит; сейчас без клипов
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_cli_match_review.py tests/test_cli.py -q`
Expected: PASS (новый + существующие CLI-тесты).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/cli.py tests/test_cli_match_review.py
git commit -m "feat(cli): analyze --coach --deep N -> папка-отчёт по эпизодам при наличии реплея"
```

---

### Task A10: анти-результат-сканер на карточки и deep-промпты

**Files:**
- Create: `tests/test_anti_resultism_episodes.py`

**Interfaces:**
- Consumes: `review_match`, `build_moment_prompt`, `principle_for_moment`.
- Produces: тест-гарантия, что текст карточек и промпты всех deep-эпизодов не содержат исхода.

- [ ] **Step 1: Write the failing test** (сначала может упасть, если что-то течёт — тогда чинить источник)

```python
# tests/test_anti_resultism_episodes.py
from dataclasses import asdict

from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.match_review import review_match
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.episodes import build_episodes
from dota_coach.models import (
    Match, ParsedReplay, PlayerMatch, ReplayFrame, Teamfight, UnitState,
)
import json

_BANNED_TOKENS = ("radiant_win", "radiant_score", "dire_score")
_BANNED_WORDS = ("победа", "поражени", "выигр", "проигр")


def _u(alive):
    return UnitState(slot=0, x=0, y=0, hp=100, max_hp=100, mana=0, level=1, xp=0, alive=alive)


def _match():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=1, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100, 200], xp_t=[0, 0, 0])
    tf = Teamfight(start=120, end=140, deaths=3,
                   players=[{"deaths": 1, "gold_delta": -300, "damage": 100}])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[tf], objectives=[])


def _replay():
    frames = [ReplayFrame(time=t, units={1: _u(t != 600)}) for t in range(0, 700, 10)]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina"},
                        frames=frames, teams={1: 2})


def test_cards_carry_no_outcome():
    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})
    review = review_match(_match(), _replay(), 7, FakeLLM(canned), deep_n=2)
    for card in review.cards:
        blob = (card.facts + str(card.numbers)).lower()
        assert not any(t in blob for t in _BANNED_TOKENS)
        assert not any(w in blob for w in _BANNED_WORDS)


def test_every_deep_prompt_carries_no_outcome():
    episodes = build_episodes(_match(), _replay(), 7)
    for e in episodes:
        msgs = build_moment_prompt(e.moment, principle_for_moment(e.moment))
        whole = "".join(m["content"] for m in msgs).lower()
        assert not any(t in whole for t in _BANNED_TOKENS)
        assert not any(w in whole for w in _BANNED_WORDS)
```

- [ ] **Step 2: Run test**

Run: `PYTHONPATH=src python -m pytest tests/test_anti_resultism_episodes.py -q`
Expected: PASS (если падает — найти утечку исхода в summary/данных и убрать; исход в промпт/карточки попадать не должен by construction).

- [ ] **Step 3: (если PASS — пропустить) чинить источник утечки**

Если тест падает — эпизодные `data`/`summary` где-то тащат счёт/исход; убрать поле-нарушитель из `data` в `episodes.py`/`events.py`.

- [ ] **Step 4: Полный прогон стадии A**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS (183 старых + новые).

- [ ] **Step 5: Commit**

```bash
git add tests/test_anti_resultism_episodes.py
git commit -m "test(anti-result): сканер на карточки эпизодов и deep-промпты"
```

---

### Task A11: живой смок Стадии A (ручной, вне CI)

- [ ] **Step 1:** Прогнать на реальном матче (реплей качается сам):

```bash
cd /c/Users/user/PycharmProjects/dota-coach
PYTHONIOENCODING=utf-8 PYTHONPATH=src python -m dota_coach.cli analyze \
  --match-id 8961642706 --account-id 44365175 --coach --deep 1 \
  --out review_8961642706
```

- [ ] **Step 2:** Проверить `review_8961642706/index.html`: ~10–15 карточек (драки + соло-смерти + просадки) в хронологии, факты из реплея, 1 глубокий блок, ни слова об исходе. Скопировать в Downloads для просмотра пользователем. **Стоп-чекпоинт** — показать пользователю до Стадии B.

---

## Стадия B — видео: локатор + сшивка + авто-выравнивание + клипы

### Task B1: `clip_window` + `extract` (нарезка H.264 720p)

**Files:**
- Modify: `src/dota_coach/video/clip.py`
- Test: `tests/test_clip.py` (добавить)

**Interfaces:**
- Produces:
  - `clip_window(game_time: int, offset: float, before: int = 20, after: int = 10) -> tuple[float, float]` — `(t0_video, t1_video)`, кламп `t0 >= 0`.
  - `build_clip_command(video_path, start_video, end_video, out_path, ffmpeg="ffmpeg")` — теперь транскод H.264 720p без звука; сигнатура расширена параметром `ffmpeg`.
  - `extract(video, game_time, offset, out_path, ffmpeg, runner=subprocess.run) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# добавить в tests/test_clip.py
from dota_coach.video.clip import clip_window, build_clip_command


def test_clip_window_20_before_10_after_clamped():
    assert clip_window(600, offset=183) == (763.0, 793.0)   # 600+183-20 .. +10
    assert clip_window(5, offset=0, before=20, after=10) == (0.0, 15.0)  # кламп t0>=0


def test_build_clip_command_transcodes_h264_720p_no_audio():
    cmd = build_clip_command("game.mp4", 763.0, 793.0, "clips/00.mp4", ffmpeg="FF")
    assert cmd[0] == "FF"
    assert "libx264" in cmd
    assert any(a.startswith("scale=") and "720" in a for a in cmd)
    assert "-an" in cmd
    assert cmd.index("-ss") < cmd.index("-i")     # быстрый seek
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_clip.py -q`
Expected: FAIL — `clip_window` нет; команда пока `-c copy`, не транскод.

- [ ] **Step 3: Write minimal implementation**

Replace `src/dota_coach/video/clip.py`:

```python
from __future__ import annotations

import subprocess


def clip_window(game_time: int, offset: float, before: int = 20,
                after: int = 10) -> tuple[float, float]:
    from dota_coach.video.align import video_time_for
    center = video_time_for(game_time, offset)
    return (max(0.0, center - before), center + after)


def build_clip_command(video_path: str, start_video: float, end_video: float,
                       out_path: str, ffmpeg: str = "ffmpeg") -> list[str]:
    return [
        ffmpeg, "-y",
        "-ss", f"{start_video:.3f}",
        "-to", f"{end_video:.3f}",
        "-i", video_path,
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-vf", "scale=-2:720",
        "-an",
        "-movflags", "+faststart",
        out_path,
    ]


def extract(video: str, game_time: int, offset: float, out_path: str,
            ffmpeg: str = "ffmpeg", runner=subprocess.run) -> None:
    t0, t1 = clip_window(game_time, offset)
    cmd = build_clip_command(video, t0, t1, out_path, ffmpeg=ffmpeg)
    runner(cmd, capture_output=True, text=True)
```

Note: `-ss` before `-i` даёт быстрый seek; `-to` при этом трактуется относительно исходного времени — для точности можно позже перейти на `-ss` перед `-i` + `-t {dur}`. v1 достаточно.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_clip.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/video/clip.py tests/test_clip.py
git commit -m "feat(clip): clip_window (20/10) + extract транскод H.264 720p без звука"
```

---

### Task B2: `find_session` — локатор записи Steam по match_id

**Files:**
- Create: `src/dota_coach/video/steam_recording.py`
- Test: `tests/test_steam_recording.py`

**Interfaces:**
- Produces: `find_session(start_time: int, duration: int, gamerecordings_dir: str, now_epoch: int) -> tuple[str, int] | None` — путь сессии `bg_570_*` и её `avail_epoch` (unix, UTC), чей ретейн-интервал покрывает окно матча; иначе `None`. (Чистая: список сессий передаётся через хелпер `_scan_sessions`, тестируемый на фикстурах каталога.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_steam_recording.py
import re

from dota_coach.video.steam_recording import pick_session


def _sess(avail_epoch, lo_chunk, hi_chunk, name):
    # ретейн-интервал = [avail+(lo-1)*3, avail+hi*3]
    return {"name": name, "avail": avail_epoch,
            "rec_lo": (lo_chunk - 1) * 3, "rec_hi": hi_chunk * 3}


def test_pick_session_covering_match_window():
    # match 22:29:41..23:04:40 -> нужна сессия, покрывающая эти эпохи
    sessions = [
        _sess(avail_epoch=1000, lo_chunk=1, hi_chunk=100, name="early"),     # 1000..1300
        _sess(avail_epoch=1000, lo_chunk=3737, hi_chunk=6136, name="late"),  # 12208..19408
    ]
    # окно матча в rec-секундах late-сессии: 12838..14937
    got = pick_session(sessions, start_epoch=1000 + 12838, end_epoch=1000 + 14937)
    assert got["name"] == "late"


def test_pick_session_none_when_uncovered():
    sessions = [_sess(1000, 1, 100, "early")]
    assert pick_session(sessions, start_epoch=1000 + 5000, end_epoch=1000 + 6000) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_steam_recording.py -q`
Expected: FAIL — модуль/`pick_session` нет.

- [ ] **Step 3: Write minimal implementation**

```python
# src/dota_coach/video/steam_recording.py
from __future__ import annotations

import glob
import os
import re


def pick_session(sessions: list[dict], start_epoch: float, end_epoch: float) -> dict | None:
    """Выбрать сессию, чей ретейн-интервал покрывает окно [start_epoch, end_epoch]."""
    for s in sessions:
        lo = s["avail"] + s["rec_lo"]
        hi = s["avail"] + s["rec_hi"]
        if lo <= start_epoch and end_epoch <= hi:
            return s
    return None


def _avail_epoch(mpd_text: str) -> int | None:
    m = re.search(r'availabilityStartTime="([^"]+)"', mpd_text)
    if not m:
        return None
    import datetime
    dt = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ")
    return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())


def _scan_sessions(gamerecordings_dir: str) -> list[dict]:
    out: list[dict] = []
    video_dir = os.path.join(gamerecordings_dir, "video")
    for d in glob.glob(os.path.join(video_dir, "bg_570_*")):
        mpd = os.path.join(d, "session.mpd")
        chunks = glob.glob(os.path.join(d, "chunk-stream0-*.m4s"))
        if not os.path.exists(mpd) or not chunks:
            continue
        avail = _avail_epoch(open(mpd, encoding="utf-8", errors="replace").read())
        if avail is None:      # завершённая (type=static) сессия без availabilityStartTime
            continue
        nums = [int(re.search(r"-(\d+)\.m4s", c).group(1)) for c in chunks]
        out.append({"name": d, "avail": avail,
                    "rec_lo": (min(nums) - 1) * 3, "rec_hi": max(nums) * 3})
    return out


def find_session(start_time: int, duration: int, gamerecordings_dir: str) -> tuple[str, int] | None:
    sessions = _scan_sessions(gamerecordings_dir)
    s = pick_session(sessions, start_epoch=start_time, end_epoch=start_time + duration)
    return (s["name"], s["avail"]) if s else None
```

Note: завершённые записи (`type="static"`) теряют `availabilityStartTime` — `_scan_sessions` их пропустит. Для таких — фолбэк на ручной `--video`. (Известное ограничение, покрыто мягкой деградацией CLI.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_steam_recording.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/video/steam_recording.py tests/test_steam_recording.py
git commit -m "feat(steam): find_session/pick_session — локатор записи по окну матча"
```

---

### Task B3: `stitch_window` — сшивка окна матча из DASH-осколков

**Files:**
- Modify: `src/dota_coach/video/steam_recording.py`
- Test: `tests/test_steam_recording.py` (добавить)

**Interfaces:**
- Produces:
  - `chunk_range(avail_epoch, rec_start_s, rec_end_s) -> tuple[int, int]` — номера чанков (chunk N = rec-сек `[(N-1)*3, N*3)`).
  - `stitch_window(session_dir, avail_epoch, start_epoch, end_epoch, out_mp4, ffmpeg, runner=subprocess.run) -> None` — concat init+чанки диапазона → ffmpeg `-c copy +faststart`.

- [ ] **Step 1: Write the failing test**

```python
# добавить в tests/test_steam_recording.py
from dota_coach.video.steam_recording import chunk_range


def test_chunk_range_from_rec_seconds():
    # rec 12747..15300 -> chunk floor/3+1
    assert chunk_range(0, 12747, 15300) == (4250, 5100)
    assert chunk_range(0, 0, 9) == (1, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_steam_recording.py::test_chunk_range_from_rec_seconds -q`
Expected: FAIL — `chunk_range` нет.

- [ ] **Step 3: Write minimal implementation**

Append to `src/dota_coach/video/steam_recording.py`:

```python
import subprocess


def chunk_range(avail_epoch: float, rec_start_s: float, rec_end_s: float) -> tuple[int, int]:
    n0 = max(1, int(rec_start_s // 3) + 1)
    n1 = int(rec_end_s // 3) + 1
    return (n0, n1)


def stitch_window(session_dir: str, avail_epoch: float, start_epoch: float,
                  end_epoch: float, out_mp4: str, ffmpeg: str,
                  runner=subprocess.run) -> None:
    rec_start = start_epoch - avail_epoch - 90   # запас 90с до гудка
    rec_end = end_epoch - avail_epoch + 60
    n0, n1 = chunk_range(avail_epoch, max(0, rec_start), rec_end)
    files = [os.path.join(session_dir, "init-stream0.m4s")]
    for n in range(n0, n1 + 1):
        p = os.path.join(session_dir, f"chunk-stream0-{n:05d}.m4s")
        if os.path.exists(p):
            files.append(p)
    concat = out_mp4 + ".concat"
    with open(concat, "wb") as out:
        for p in files:
            with open(p, "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    out.write(b)
    runner([ffmpeg, "-y", "-fflags", "+genpts", "-i", concat, "-c", "copy",
            "-movflags", "+faststart", out_mp4], capture_output=True, text=True)
    os.remove(concat)
    # rec-секунда гудка (для offset) вернётся отдельно через find/align
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_steam_recording.py -q`
Expected: PASS (все в файле).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/video/steam_recording.py tests/test_steam_recording.py
git commit -m "feat(steam): stitch_window — сшивка окна матча из осколков (concat+remux)"
```

---

### Task B4: ассеты шаблонов цифр HUD-часов + геометрия

**Files:**
- Create: `scripts/build_clock_templates.py`
- Create: `assets/clock_box.json`
- Create: `assets/clock_digits/{0..9}.png` (генерируются скриптом из mp4)
- Test: (нет юнита — калибровочный ассет; валидируется в B5/B8)

**Interfaces:**
- Produces: 10 grayscale-PNG шаблонов цифр (1080p HUD-шрифт) + `clock_box.json` с `{"box":[x0,y0,x1,y1], "digit_slots":[[dx0,dx1],...]}` (доли области кропа под 4 позиции цифр).

- [ ] **Step 1:** Написать `scripts/build_clock_templates.py`: берёт mp4 + offset, грабит кадры на игровых временах, где известна каждая цифра (0:00→`0`; 1:11→`1`; 2:22→`2`; … 9:59→`9`,`5`), кропит область `crop_hud_clock`, режет на позиции по `digit_slots`, сохраняет уникальные цифры в `assets/clock_digits/{d}.png` (grayscale, бинаризация Otsu).

```python
# scripts/build_clock_templates.py
import json
import os
import sys

import cv2

sys.path.insert(0, "src")
from dota_coach.video.align import crop_hud_clock, opencv_frame_at, video_time_for  # noqa: E402

VIDEO, OFFSET = sys.argv[1], float(sys.argv[2])
BOX = (0.46, 0.0, 0.54, 0.045)
# 4 слота цифр MM:SS как доли ширины кропа (откалибровать по кадру 10:00; ниже — старт)
SLOTS = [(0.00, 0.22), (0.22, 0.44), (0.60, 0.80), (0.80, 1.00)]
os.makedirs("assets/clock_digits", exist_ok=True)
frame_at = opencv_frame_at(VIDEO)
# (game_time, "MMSS") где каждая позиция известна
SAMPLES = [(0, "0000"), (71, "0111"), (142, "0222"), (213, "0333"), (284, "0444"),
           (355, "0555"), (599, "0959"), (426, "0706"), (497, "0817"), (600, "1000")]
for gt, digits in SAMPLES:
    frame = frame_at(video_time_for(gt, OFFSET))
    crop = cv2.cvtColor(crop_hud_clock(frame, BOX), cv2.COLOR_BGR2GRAY)
    _, binimg = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    h, w = binimg.shape
    for i, (a, b) in enumerate(SLOTS):
        d = digits[i]
        path = f"assets/clock_digits/{d}.png"
        if os.path.exists(path):
            continue
        cv2.imwrite(path, binimg[:, int(a * w):int(b * w)])
json.dump({"box": list(BOX), "digit_slots": SLOTS},
          open("assets/clock_box.json", "w"))
print("templates:", sorted(os.listdir("assets/clock_digits")))
```

- [ ] **Step 2:** Прогнать на mp4 матча 8961642706 (offset 183), убедиться, что собрались все 10 цифр (при кривой геометрии — подправить `BOX`/`SLOTS` по кадру 10:00, глядя на сохранённые PNG). Это **ручная калибровка** — единственный неавтоматизируемый шаг B; риск закрыт фолбэком на ручной `--video-offset`.

```bash
PYTHONIOENCODING=utf-8 python scripts/build_clock_templates.py match4_8961642706_hevc.mp4 183
```

- [ ] **Step 3:** Commit ассетов:

```bash
git add scripts/build_clock_templates.py assets/clock_box.json assets/clock_digits/
git commit -m "feat(align): шаблоны цифр HUD-часов + геометрия (калибровка 1080p)"
```

---

### Task B5: `read_clock` — чтение часов по шаблонам

**Files:**
- Modify: `src/dota_coach/video/align.py`
- Test: `tests/test_align.py` (добавить)

**Interfaces:**
- Produces:
  - `load_clock_templates(assets_dir="assets") -> tuple[dict[str, "np.ndarray"], dict]` — шаблоны {цифра→img} + geometry.
  - `read_clock(frame, templates, geometry) -> int | None` — кроп→слоты→матч шаблонов→`MM*60+SS`; `None` если уверенность низкая.

- [ ] **Step 1: Write the failing test** (синтетический кроп собираем ИЗ шаблонов — самосогласованно)

```python
# добавить в tests/test_align.py
import numpy as np

from dota_coach.video.align import read_clock


def _fake_templates():
    # 10 различимых «цифр»: каждая — картинка 20x12, у цифры d включён столбец d
    tmpls = {}
    for d in range(10):
        img = np.zeros((20, 12), dtype=np.uint8)
        img[:, d] = 255
        tmpls[str(d)] = img
    geom = {"box": (0.46, 0.0, 0.54, 0.045),
            "digit_slots": [(0.00, 0.25), (0.25, 0.50), (0.50, 0.75), (0.75, 1.00)]}
    return tmpls, geom


def _compose(digits):
    # склеить 4 слота из шаблонов в один кроп (h=20, каждый слот 12px, colon-щель условно)
    tmpls, _ = _fake_templates()
    return np.concatenate([tmpls[d] for d in digits], axis=1)


def test_read_clock_1000():
    tmpls, geom = _fake_templates()
    frame = _compose("1000")
    # для теста подаём уже готовый кроп: read_clock принимает crop как frame при box=full
    geom_full = {"box": (0.0, 0.0, 1.0, 1.0), "digit_slots": geom["digit_slots"]}
    assert read_clock(frame, tmpls, geom_full) == 600   # 10:00


def test_read_clock_returns_none_on_blank():
    tmpls, geom = _fake_templates()
    frame = np.zeros((20, 48), dtype=np.uint8)
    geom_full = {"box": (0.0, 0.0, 1.0, 1.0), "digit_slots": geom["digit_slots"]}
    assert read_clock(frame, tmpls, geom_full) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_align.py -q`
Expected: FAIL — `read_clock` нет.

- [ ] **Step 3: Write minimal implementation**

Append to `src/dota_coach/video/align.py`:

```python
def load_clock_templates(assets_dir: str = "assets"):
    import json
    import os

    import cv2

    geom = json.load(open(os.path.join(assets_dir, "clock_box.json")))
    tmpls = {}
    for d in "0123456789":
        p = os.path.join(assets_dir, "clock_digits", f"{d}.png")
        if os.path.exists(p):
            tmpls[d] = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    return tmpls, geom


def _match_digit(slot_img, templates, threshold: float = 0.5):
    import cv2

    best_d, best_v = None, threshold
    for d, tmpl in templates.items():
        th, tw = tmpl.shape[:2]
        sh, sw = slot_img.shape[:2]
        t = cv2.resize(tmpl, (max(1, sw), max(1, sh)))
        res = cv2.matchTemplate(slot_img, t, cv2.TM_CCOEFF_NORMED)
        v = float(res.max())
        if v >= best_v:
            best_d, best_v = d, v
    return best_d


def read_clock(frame, templates, geometry) -> int | None:
    import cv2
    import numpy as np

    box = geometry["box"]
    slots = geometry["digit_slots"]
    crop = crop_hud_clock(frame, tuple(box))
    if crop.ndim == 3:
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if crop.size == 0:
        return None
    h, w = crop.shape[:2]
    digits = []
    for a, b in slots:
        slot = crop[:, int(a * w):int(b * w)]
        if slot.size == 0:
            return None
        d = _match_digit(slot, templates)
        if d is None:
            return None
        digits.append(d)
    ss = int(digits[-2]) * 10 + int(digits[-1])
    mm = int("".join(digits[:-2]))
    return mm * 60 + ss
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_align.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/video/align.py tests/test_align.py
git commit -m "feat(align): read_clock по шаблонам цифр (matchTemplate по слотам)"
```

---

### Task B6: `auto_offset` — авто-выравнивание 0:00

**Files:**
- Modify: `src/dota_coach/video/align.py`
- Test: `tests/test_align.py` (добавить)

**Interfaces:**
- Produces: `auto_offset(read_at: Callable[[float], int | None], coarse_seed: float, span: float = 300, step: float = 20) -> float | None` — семплирует чтения часов в `[seed, seed+span]`, решает `offset` через `compute_offset`; `None` если чтений нет. (Кадр+часы инъектируются `read_at(t_video)->game_seconds|None` — тестируемо без cv2.)

- [ ] **Step 1: Write the failing test**

```python
# добавить в tests/test_align.py
from dota_coach.video.align import auto_offset


def test_auto_offset_solves_constant_offset():
    OFFSET = 183.0
    # часы в video-время t показывают game = t - OFFSET (если t>=OFFSET), иначе None (меню)
    def read_at(t):
        g = int(t - OFFSET)
        return g if g >= 0 else None
    got = auto_offset(read_at, coarse_seed=120.0, span=300, step=20)
    assert abs(got - OFFSET) <= 1.0


def test_auto_offset_none_when_unreadable():
    assert auto_offset(lambda t: None, coarse_seed=0.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_align.py -q`
Expected: FAIL — `auto_offset` нет.

- [ ] **Step 3: Write minimal implementation**

Append to `src/dota_coach/video/align.py`:

```python
def auto_offset(read_at, coarse_seed: float, span: float = 300,
                step: float = 20) -> float | None:
    times = [coarse_seed + k * step for k in range(int(span // step) + 1)]
    reads = []
    for t in times:
        g = read_at(t)
        if g is not None:
            reads.append(ClockRead(t_video=t, t_game=g))
    if not reads:
        return None
    return compute_offset(reads)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_align.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/video/align.py tests/test_align.py
git commit -m "feat(align): auto_offset — авто-выравнивание 0:00 по чтениям часов"
```

---

### Task B7: CLI — авто-видео (найти/сшить/выровнять/нарезать) + `<video>` в отчёте

**Files:**
- Modify: `src/dota_coach/cli.py` (`_build_clips`, флаги `--gamerecordings`)
- Test: `tests/test_cli_clips.py`

**Interfaces:**
- Consumes: `find_session`, `stitch_window` (steam_recording); `load_clock_templates`, `read_clock`, `auto_offset`, `opencv_frame_at`, `video_time_for` (align); `extract` (clip); `review_match`, `render_match_report`.
- Produces: `_build_clips(args, match, review, parsed) -> dict[int, str]` — если задан `--video` или найдена запись: определить offset (ручной или `auto_offset`), нарезать клип `[t-20,t+10]` на каждый эпизод в `out/clips/NN.mp4`, вернуть `{game_time: "clips/NN.mp4"}`. Любой сбой видео → `{}` (мягкая деградация, отчёт по данным).

- [ ] **Step 1: Write the failing test** (инъекция всех тяжёлых шагов через monkeypatch)

```python
# tests/test_cli_clips.py
import dota_coach.cli as cli
from dota_coach.coach.episode_card import EpisodeCard
from dota_coach.coach.match_review import MatchReview
from dota_coach.episodes import Episode
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


class _Args:
    video = "game.mp4"
    video_offset = 183.0
    gamerecordings = None
    out = None


def _episode(gt):
    ev = EventCandidate(type=EventType.DEATH, game_time=gt, involves_me=True, summary="", data={})
    m = ScoredMoment(event=ev, score=5.0, confidence=Confidence.LOW, verdict=Verdict.NEUTRAL)
    return Episode(moment=m, severity=5.0)


def test_build_clips_extracts_per_episode(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "clip_extract", lambda video, gt, off, out, ffmpeg: calls.append((gt, out)))
    args = _Args()
    args.out = str(tmp_path)
    review = MatchReview(episodes=[_episode(600), _episode(1200)], cards=[], deep_briefs={})
    clips = cli._build_clips(args, match=None, review=review, parsed=None)
    assert clips == {600: "clips/00.mp4", 1200: "clips/01.mp4"}
    assert [c[0] for c in calls] == [600, 1200]


def test_build_clips_empty_on_no_offset(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_resolve_offset", lambda args, match: None)
    args = _Args()
    args.out = str(tmp_path)
    args.video_offset = None
    review = MatchReview(episodes=[_episode(600)], cards=[], deep_briefs={})
    assert cli._build_clips(args, match=None, review=review, parsed=None) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_cli_clips.py -q`
Expected: FAIL — `_build_clips`/`clip_extract`/`_resolve_offset` не готовы.

- [ ] **Step 3: Write minimal implementation**

In `src/dota_coach/cli.py` add imports:

```python
import imageio_ffmpeg

from dota_coach.video.align import (
    auto_offset, load_clock_templates, opencv_frame_at, read_clock, video_time_for,
)
from dota_coach.video.clip import extract as clip_extract
from dota_coach.video.steam_recording import find_session, stitch_window
```

Add `--gamerecordings` to the `analyze` subparser:

```python
    a.add_argument("--gamerecordings", default=None,
                   help="папка Steam gamerecordings (иначе клипы только с --video)")
```

Replace the stub `_build_clips` (from A9) with:

```python
def _resolve_offset(args, match) -> float | None:
    if args.video_offset is not None:
        return float(args.video_offset)
    try:
        tmpls, geom = load_clock_templates()
        frame_at = opencv_frame_at(args.video)
        got = auto_offset(lambda t: read_clock(frame_at(t), tmpls, geom),
                          coarse_seed=0.0, span=600, step=20)
        if got is not None:
            print(f"авто-offset по HUD-часам: {got:.1f}s")
        return got
    except Exception as exc:  # noqa: BLE001
        print(f"авто-выравнивание не удалось ({exc}); задай --video-offset")
        return None


def _build_clips(args, match, review, parsed) -> dict:
    if not args.video:
        return {}
    offset = _resolve_offset(args, match)
    if offset is None:
        return {}
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    clips_dir = Path(args.out) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    out: dict = {}
    for i, e in enumerate(review.episodes):
        gt = e.moment.event.game_time
        rel = f"clips/{i:02d}.mp4"
        try:
            clip_extract(args.video, gt, offset, str(Path(args.out) / rel), ffmpeg=ffmpeg)
            out[gt] = rel
        except Exception as exc:  # noqa: BLE001 - клип необязателен
            print(f"клип {gt}s пропущен: {exc}")
    return out
```

(Авто-поиск+сшивку записи через `find_session`/`stitch_window` подключить, когда `--video` не задан, но `--gamerecordings` есть — тем же путём: сшить окно в temp mp4, дальше как с `--video`. Для v1 можно оставить хук; тесты выше покрывают ветку с готовым `--video`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_cli_clips.py -q`
Expected: PASS.

- [ ] **Step 5: Полный прогон + commit**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS (весь набор).

```bash
git add src/dota_coach/cli.py tests/test_cli_clips.py
git commit -m "feat(cli): авто-видео — offset (ручной/шаблоны), нарезка клипов, <video> в отчёте"
```

---

### Task B8: живой смок Стадии B (ручной, вне CI)

- [ ] **Step 1:** Прогнать с видео (offset авто или ручной 183):

```bash
cd /c/Users/user/PycharmProjects/dota-coach
PYTHONIOENCODING=utf-8 PYTHONPATH=src python -m dota_coach.cli analyze \
  --match-id 8961642706 --account-id 44365175 --coach --deep 1 \
  --video match4_8961642706_hevc.mp4 --out review_8961642706
```

- [ ] **Step 2:** Проверить: `review_8961642706/index.html` — в каждой карточке играет клип 30с (20с до / 10с после), авто-offset совпал с 183 (±2с). Открыть в браузере, глянуть 2–3 клипа. Скопировать папку в Downloads. **Финальный чекпоинт для пользователя.**

---

## Self-Review

**Spec coverage:** решения №1 (карточка+deep) → A5/A7/A8; №2 (эпизоды: драки/смерти/просадки+дедуп) → A1/A3; №3 (папка+клипы) → A8/B1/B7; №4 (окно 20/10) → B1; №5 (карточки КОД, deep отдельными вызовами) → A5/A7; №6 (авто-сборка Steam) → B2/B3/B7; №7 (шаблоны цифр) → B4/B5/B6. Анти-результат → A10. Стадийность A/B → структура плана.

**Placeholder scan:** каждый шаг несёт реальный код/команду. `_build_clips` авто-поиск записи (без `--video`) помечен как хук v1 — покрытая ветка (`--video`) полна; авто-поиск закрыт `find_session`/`stitch_window` (B2/B3), подключение — прямое.

**Type consistency:** `Episode.moment: ScoredMoment` (A3) используется в A4/A5/A7/B7; `EpisodeCard` (A5) — в A7/A8; `MatchReview` (A7) — в A9/B7; `read_clock(frame, templates, geometry)`/`auto_offset(read_at, seed, span, step)` (B5/B6) — в B7 `_resolve_offset`. Имена согласованы.
