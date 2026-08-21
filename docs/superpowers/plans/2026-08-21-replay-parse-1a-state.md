# Срез 1a-state — экстрактор состояния реплея. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Достать из `.dem`-реплея снимки состояния всех 10 героев (позиция/HP/мана/уровень/опыт/жив) раз в игровую секунду и отдать в Python как `ParsedReplay`, с кешем и мягкой деградацией при недоступном реплее.

**Architecture:** Go-бинарь (`replay_tool`, парсер manta) — тупой экстрактор: `.dem` → JSONL в stdout, ноль логики. Python (`ingest/replay.py`) качает `.dem.bz2` (тело zstd), распаковывает, гоняет бинарь, парсит JSONL в `ParsedReplay`, кеширует. Реплей-слой строго опционален — сбой не роняет `analyze`.

**Tech Stack:** Go 1.24 + `github.com/dotabuff/manta` v1.5.0; Python 3.12 + `zstandard`; pytest. Всё уже установлено (проверено спайком).

## Global Constraints

- **Реплей-слой опционален:** любой сбой (нет реплея / zstd / бинарь) → `ReplayUnavailable`, существующий разбор рендерится без слоя. Verbatim из спеки: «никакой сбой парсинга не должен ронять существующий разбор».
- **Граница Go/Python:** Go только извлекает и печатает JSONL; вся аналитика — Python. Go не содержит доменной логики.
- **Кеш на диске** как `opendota.py`: `cache/replay_<match_id>.jsonl`; `cache/` уже в `.gitignore`.
- **Слот игрока = `m_iPlayerID / 2`** (наблюдение спайка: replay pid = 2×индекс игрока; 0–4 Radiant team=2, 5–9 Dire team=3).
- **Отсев иллюзий:** пропускаем героя, только если `m_hReplicatingOtherHeroModel` присутствует И != `16777215` (валидный хэндл на оригинал). Отсутствует/invalid = реальный герой.
- **Координаты мира:** `world = cell*128 + vec - 16384` по X/Y.
- **Игровое время:** `game_time = currentTick/30 - m_flGameStartTime` (0 на хорне); эмитим только `game_time >= 0`.
- Русский интерфейс в пользовательских строках. Спайк-артефакты (`spike_replay/`) в репозиторий не идут.

---

## File Structure

```
replay_tool/
  go.mod                     NEW — модуль экстрактора (manta)
  main.go                    NEW — .dem → JSONL (meta + state @1Hz)
src/dota_coach/
  models.py                  MODIFY — + UnitState, ReplayFrame, ParsedReplay
  ingest/replay.py           NEW — parse_replay_jsonl + parse_replay + ReplayUnavailable
tests/
  test_replay_models.py      NEW — frame_at
  test_replay_parse.py       NEW — JSONL → ParsedReplay, кеш-хит, деградация
  fixtures/replay_sample.jsonl NEW — 3-кадровый рукотворный JSONL
```

---

### Task 1: Модели данных реплея

**Files:**
- Modify: `src/dota_coach/models.py` (добавить в конец)
- Test: `tests/test_replay_models.py`

**Interfaces:**
- Produces:
  - `UnitState(slot:int, x:float, y:float, hp:int, max_hp:int, mana:float, level:int, xp:int, alive:bool)` (frozen)
  - `ReplayFrame(time:int, units:dict[int,UnitState])` (frozen)
  - `ParsedReplay(match_id:int, game_start_time:float, heroes:dict[int,str], frames:list[ReplayFrame])` с методом `frame_at(t:int)->ReplayFrame|None` — последний кадр с `time <= t`, иначе `None`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_replay_models.py
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState


def _u(slot, x=0.0, y=0.0):
    return UnitState(slot=slot, x=x, y=y, hp=100, max_hp=100, mana=50.0, level=1, xp=0, alive=True)


def _frame(t):
    return ReplayFrame(time=t, units={0: _u(0), 5: _u(5)})


def _replay(times):
    return ParsedReplay(match_id=1, game_start_time=200.0,
                        heroes={0: "CDOTA_Unit_Hero_Axe"},
                        frames=[_frame(t) for t in times])


def test_frame_at_exact():
    r = _replay([0, 10, 20])
    assert r.frame_at(10).time == 10


def test_frame_at_between_returns_latest_leq():
    r = _replay([0, 10, 20])
    assert r.frame_at(15).time == 10


def test_frame_at_before_first_returns_none():
    r = _replay([10, 20])
    assert r.frame_at(5) is None


def test_frame_at_after_last_returns_last():
    r = _replay([0, 10, 20])
    assert r.frame_at(999).time == 20
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_replay_models.py -v`
Expected: FAIL (ImportError: UnitState).

- [ ] **Step 3: Реализовать (в конец `models.py`)**

```python
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
class ParsedReplay:
    match_id: int
    game_start_time: float
    heroes: dict[int, str]
    frames: list[ReplayFrame]

    def frame_at(self, t: int) -> "ReplayFrame | None":
        best = None
        for f in self.frames:            # frames отсортированы по time на парсинге
            if f.time <= t:
                best = f
            else:
                break
        return best
```

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_replay_models.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/models.py tests/test_replay_models.py
git commit -m "feat(replay): модели UnitState/ReplayFrame/ParsedReplay + frame_at"
```

---

### Task 2: JSONL-парсер → ParsedReplay

**Files:**
- Create: `src/dota_coach/ingest/replay.py`
- Create: `tests/fixtures/replay_sample.jsonl`
- Test: `tests/test_replay_parse.py`

**Interfaces:**
- Consumes: `ParsedReplay`, `ReplayFrame`, `UnitState` из `models.py`.
- Produces: `parse_replay_jsonl(lines: Iterable[str], match_id: int) -> ParsedReplay` — читает JSONL (одна `meta`-строка + N `state`-строк), собирает `ParsedReplay`, `frames` сортирует по `time`. Нет `meta` → `ValueError`.

Формат JSONL (контракт с Go-экстрактором):
```
{"t":"meta","game_start_time":221.3,"tick_rate":30,"heroes":[{"slot":0,"team":2,"hero":"CDOTA_Unit_Hero_PhantomLancer"}, ...]}
{"t":"state","time":0,"units":[{"slot":0,"x":557.0,"y":-1708.0,"hp":648,"max_hp":648,"mana":300.0,"level":1,"xp":0,"alive":true}, ...]}
```

- [ ] **Step 1: Фикстура**

```
# tests/fixtures/replay_sample.jsonl  (3 units × 3 frames, компактно)
{"t":"meta","game_start_time":200.0,"tick_rate":30,"heroes":[{"slot":0,"team":2,"hero":"CDOTA_Unit_Hero_Axe"},{"slot":5,"team":3,"hero":"CDOTA_Unit_Hero_Pudge"}]}
{"t":"state","time":2,"units":[{"slot":0,"x":10.0,"y":20.0,"hp":600,"max_hp":600,"mana":100.0,"level":1,"xp":0,"alive":true},{"slot":5,"x":-30.0,"y":40.0,"hp":700,"max_hp":700,"mana":200.0,"level":1,"xp":0,"alive":true}]}
{"t":"state","time":0,"units":[{"slot":0,"x":1.0,"y":2.0,"hp":650,"max_hp":650,"mana":110.0,"level":1,"xp":0,"alive":true}]}
{"t":"state","time":1,"units":[{"slot":0,"x":5.0,"y":6.0,"hp":640,"max_hp":650,"mana":105.0,"level":1,"xp":10,"alive":false}]}
```

- [ ] **Step 2: Написать падающий тест**

```python
# tests/test_replay_parse.py
from pathlib import Path

import pytest

from dota_coach.ingest.replay import parse_replay_jsonl

_FIX = Path(__file__).parent / "fixtures" / "replay_sample.jsonl"


def _lines():
    return _FIX.read_text(encoding="utf-8").splitlines()


def test_parse_meta():
    r = parse_replay_jsonl(_lines(), match_id=42)
    assert r.match_id == 42
    assert r.game_start_time == 200.0
    assert r.heroes[0] == "CDOTA_Unit_Hero_Axe"
    assert r.heroes[5] == "CDOTA_Unit_Hero_Pudge"


def test_frames_sorted_by_time():
    r = parse_replay_jsonl(_lines(), match_id=42)
    assert [f.time for f in r.frames] == [0, 1, 2]   # фикстура нарочно вперемешку


def test_unit_fields_parsed():
    r = parse_replay_jsonl(_lines(), match_id=42)
    u = r.frame_at(2).units[5]
    assert u.slot == 5 and u.x == -30.0 and u.hp == 700 and u.alive is True
    dead = r.frame_at(1).units[0]
    assert dead.alive is False and dead.xp == 10


def test_missing_meta_raises():
    with pytest.raises(ValueError):
        parse_replay_jsonl(['{"t":"state","time":0,"units":[]}'], match_id=1)
```

- [ ] **Step 3: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_replay_parse.py -v`
Expected: FAIL (ModuleNotFoundError: ingest.replay).

- [ ] **Step 4: Реализовать `parse_replay_jsonl`**

```python
# src/dota_coach/ingest/replay.py
from __future__ import annotations

import json
from typing import Iterable

from dota_coach.models import ParsedReplay, ReplayFrame, UnitState


def parse_replay_jsonl(lines: Iterable[str], match_id: int) -> ParsedReplay:
    meta: dict | None = None
    frames: list[ReplayFrame] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        kind = obj.get("t")
        if kind == "meta":
            meta = obj
        elif kind == "state":
            units = {
                u["slot"]: UnitState(
                    slot=u["slot"], x=float(u["x"]), y=float(u["y"]),
                    hp=int(u["hp"]), max_hp=int(u["max_hp"]), mana=float(u["mana"]),
                    level=int(u["level"]), xp=int(u["xp"]), alive=bool(u["alive"]),
                )
                for u in obj["units"]
            }
            frames.append(ReplayFrame(time=int(obj["time"]), units=units))
    if meta is None:
        raise ValueError("в JSONL нет meta-строки — реплей не распарсен")
    frames.sort(key=lambda f: f.time)
    heroes = {h["slot"]: h["hero"] for h in meta["heroes"]}
    return ParsedReplay(match_id=match_id, game_start_time=float(meta["game_start_time"]),
                        heroes=heroes, frames=frames)
```

Также создать `tests/fixtures/` если нет и `src/dota_coach/ingest/__init__.py` уже существует (пакет есть).

- [ ] **Step 5: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_replay_parse.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/ingest/replay.py tests/test_replay_parse.py tests/fixtures/replay_sample.jsonl
git commit -m "feat(replay): parse_replay_jsonl — JSONL контракт -> ParsedReplay"
```

---

### Task 3: Go-экстрактор `replay_tool`

**Files:**
- Create: `replay_tool/go.mod`
- Create: `replay_tool/main.go`

**Interfaces:**
- Produces: бинарь `replay_tool`, вызов `replay_tool <path.dem>` → JSONL в stdout (одна `meta` + N `state`), ошибки в stderr + ненулевой код. Контракт JSONL — как в Task 2.

Проверяется НЕ pytest, а сборкой + прогоном на зафиксированном реплее из спайка (`spike_replay/8944053733.dem`), как сетевой путь `opendota.py` не юнит-тестится. Логика (поля/слоты/координаты/время/иллюзии) уже доказана спайком.

- [ ] **Step 1: `go.mod`**

```
module replay_tool

go 1.24

require github.com/dotabuff/manta v1.5.0
```

- [ ] **Step 2: `main.go`**

```go
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math"
	"os"

	"github.com/dotabuff/manta"
	"github.com/dotabuff/manta/dota"
)

const (
	tickRate      = 30.0
	cellWidth     = 128.0
	mapHalf       = 16384.0
	invalidHandle = 16777215
	heroPrefix    = "CDOTA_Unit_Hero_"
)

func f64(m map[string]interface{}, k string) (float64, bool) {
	v, ok := m[k]
	if !ok {
		return 0, false
	}
	switch x := v.(type) {
	case float32:
		return float64(x), true
	case float64:
		return x, true
	case int32:
		return float64(x), true
	case int64:
		return float64(x), true
	case uint32:
		return float64(x), true
	case uint64:
		return float64(x), true
	default:
		return 0, false
	}
}

type unitOut struct {
	Slot  int     `json:"slot"`
	X     float64 `json:"x"`
	Y     float64 `json:"y"`
	HP    int     `json:"hp"`
	MaxHP int     `json:"max_hp"`
	Mana  float64 `json:"mana"`
	Level int     `json:"level"`
	XP    int     `json:"xp"`
	Alive bool    `json:"alive"`
}

type stateLine struct {
	T     string    `json:"t"`
	Time  int       `json:"time"`
	Units []unitOut `json:"units"`
}

type heroMeta struct {
	Slot int    `json:"slot"`
	Team int    `json:"team"`
	Hero string `json:"hero"`
}

type metaLine struct {
	T         string     `json:"t"`
	GameStart float64    `json:"game_start_time"`
	TickRate  float64    `json:"tick_rate"`
	Heroes    []heroMeta `json:"heroes"`
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: replay_tool <path.dem>")
		os.Exit(2)
	}
	f, err := os.Open(os.Args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, "open:", err)
		os.Exit(1)
	}
	defer f.Close()

	p, err := manta.NewStreamParser(f)
	if err != nil {
		fmt.Fprintln(os.Stderr, "parser:", err)
		os.Exit(1)
	}

	var curTick int
	var gameStart float64
	heroes := map[int]heroMeta{}
	state := map[int]unitOut{}
	lastEmit := math.MinInt32
	var frames []stateLine

	p.Callbacks.OnCNETMsg_Tick(func(t *dota.CNETMsg_Tick) error {
		curTick = int(t.GetTick())
		return nil
	})

	p.OnEntity(func(e *manta.Entity, op manta.EntityOp) error {
		cn := e.GetClassName()
		if cn == "CDOTAGamerulesProxy" {
			if v, ok := f64(e.Map(), "m_pGameRules.m_flGameStartTime"); ok && v > 0 {
				gameStart = v
			}
			return nil
		}
		if len(cn) < len(heroPrefix) || cn[:len(heroPrefix)] != heroPrefix {
			return nil
		}
		m := e.Map()
		if repl, ok := f64(m, "m_hReplicatingOtherHeroModel"); ok && int(repl) != invalidHandle {
			return nil // иллюзия
		}
		pidF, ok := f64(m, "m_iPlayerID")
		if !ok {
			return nil
		}
		slot := int(pidF) / 2 // m_iPlayerID = 2×индекс игрока -> слот 0..9
		if slot < 0 || slot > 9 {
			return nil
		}
		cellX, _ := f64(m, "CBodyComponent.m_cellX")
		cellY, _ := f64(m, "CBodyComponent.m_cellY")
		vecX, _ := f64(m, "CBodyComponent.m_vecX")
		vecY, _ := f64(m, "CBodyComponent.m_vecY")
		hp, _ := f64(m, "m_iHealth")
		maxHP, _ := f64(m, "m_iMaxHealth")
		mana, _ := f64(m, "m_flMana")
		lvl, _ := f64(m, "m_iCurrentLevel")
		xp, _ := f64(m, "m_iCurrentXP")
		life, _ := f64(m, "m_lifeState")
		team, _ := f64(m, "m_iTeamNum")
		heroes[slot] = heroMeta{Slot: slot, Team: int(team), Hero: cn}
		state[slot] = unitOut{
			Slot: slot, X: cellX*cellWidth + vecX - mapHalf, Y: cellY*cellWidth + vecY - mapHalf,
			HP: int(hp), MaxHP: int(maxHP), Mana: mana, Level: int(lvl), XP: int(xp), Alive: int(life) == 0,
		}

		if gameStart <= 0 {
			return nil
		}
		gt := float64(curTick)/tickRate - gameStart
		if gt < 0 || len(state) < 10 {
			return nil
		}
		sec := int(math.Floor(gt))
		if sec <= lastEmit {
			return nil
		}
		lastEmit = sec
		units := make([]unitOut, 0, 10)
		for s := 0; s < 10; s++ {
			if u, ok := state[s]; ok {
				units = append(units, u)
			}
		}
		frames = append(frames, stateLine{T: "state", Time: sec, Units: units})
		return nil
	})

	if err := p.Start(); err != nil {
		fmt.Fprintln(os.Stderr, "parse:", err)
		os.Exit(1)
	}

	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	enc := json.NewEncoder(w)

	hs := make([]heroMeta, 0, 10)
	for s := 0; s < 10; s++ {
		if h, ok := heroes[s]; ok {
			hs = append(hs, h)
		}
	}
	if err := enc.Encode(metaLine{T: "meta", GameStart: gameStart, TickRate: tickRate, Heroes: hs}); err != nil {
		fmt.Fprintln(os.Stderr, "encode meta:", err)
		os.Exit(1)
	}
	for _, fr := range frames {
		if err := enc.Encode(fr); err != nil {
			fmt.Fprintln(os.Stderr, "encode state:", err)
			os.Exit(1)
		}
	}
}
```

- [ ] **Step 3: Собрать**

Run: `cd replay_tool && go mod tidy && go build -o replay_tool.exe .`
Expected: бинарь `replay_tool/replay_tool.exe` создан, ошибок сборки нет.

- [ ] **Step 4: Прогнать на реальном реплее (смок, не unit)**

Run: `cd replay_tool && ./replay_tool.exe ../spike_replay/8944053733.dem > /tmp/out.jsonl && head -1 /tmp/out.jsonl && echo "frames:" && grep -c '"t":"state"' /tmp/out.jsonl`
Expected: первая строка — `meta` с 10 героями и `game_start_time` ≈ 221.3; число `state`-строк ≈ 2400.

- [ ] **Step 5: Проверить контракт Python-парсером**

Run: `cd /c/Users/user/PycharmProjects/dota-coach && PYTHONPATH=src python -c "from dota_coach.ingest.replay import parse_replay_jsonl; r=parse_replay_jsonl(open('/tmp/out.jsonl',encoding='utf-8'),8944053733); print('heroes',len(r.heroes),'frames',len(r.frames)); f=r.frame_at(600); print('t600 slot0', f.units[0])"`
Expected: `heroes 10 frames ~2400`, slot0 в кадре 600 с разумными координатами (|x|,|y| < 16384). Экстрактор ↔ Python-контракт замкнут.

- [ ] **Step 6: Commit**

```bash
git add replay_tool/go.mod replay_tool/go.sum replay_tool/main.go
git commit -m "feat(replay): Go-экстрактор replay_tool (.dem -> state JSONL @1Hz)"
```

---

### Task 4: Python-обвязка `parse_replay` (скачать+zstd+бинарь+кеш)

**Files:**
- Modify: `src/dota_coach/ingest/replay.py`
- Test: `tests/test_replay_parse.py` (добавить)

**Interfaces:**
- Consumes: `parse_replay_jsonl`; `fetch_match` из `ingest.opendota` (для `replay_url`).
- Produces:
  - `class ReplayUnavailable(Exception)`
  - `parse_replay(match_id:int, cache_dir=Path("cache"), tool_path=None, downloader=None, runner=None) -> ParsedReplay`
    - Кеш-хит: `cache/replay_<id>.jsonl` есть → парсит его, без сети.
    - Кеш-мисс: `replay_url` из `fetch_match` → `downloader(url)->bytes` (zstd) → распаковать → временный `.dem` → `runner([tool, dem])->str` (stdout JSONL) → записать в кеш → распарсить.
    - Любой сбой (нет url / HTTP / zstd / бинарь rc!=0) → `ReplayUnavailable`.
  - `downloader`/`runner`/`tool_path` инъектируются (дефолты — реальные), сеть/бинарь без юнит-тестов (как `ClaudeCliLLM`).

- [ ] **Step 1: Написать падающие тесты**

```python
# tests/test_replay_parse.py (добавить)
import pytest

from dota_coach.ingest.replay import ReplayUnavailable, parse_replay


def test_parse_replay_cache_hit(tmp_path):
    # положить готовый JSONL в кеш -> parse_replay читает его без сети
    (tmp_path / "replay_5.jsonl").write_text(_FIX.read_text(encoding="utf-8"), encoding="utf-8")
    r = parse_replay(5, cache_dir=tmp_path,
                     downloader=lambda url: (_ for _ in ()).throw(AssertionError("сети быть не должно")),
                     runner=lambda argv: (_ for _ in ()).throw(AssertionError("бинарь не звать")))
    assert r.match_id == 5 and len(r.heroes) == 2


def test_parse_replay_runner_failure_raises_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("dota_coach.ingest.replay.fetch_match",
                        lambda mid: {"replay_url": "http://x/y.dem.bz2"})

    def bad_runner(argv):
        raise RuntimeError("бинарь упал")

    with pytest.raises(ReplayUnavailable):
        parse_replay(7, cache_dir=tmp_path,
                     downloader=lambda url: b"\x28\xb5\x2f\xfd",  # неважно, runner упадёт раньше проверки
                     runner=bad_runner)


def test_parse_replay_no_replay_url_raises_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("dota_coach.ingest.replay.fetch_match", lambda mid: {})
    with pytest.raises(ReplayUnavailable):
        parse_replay(9, cache_dir=tmp_path)
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_replay_parse.py -k parse_replay -v`
Expected: FAIL (ImportError: parse_replay / ReplayUnavailable).

- [ ] **Step 3: Реализовать (добавить в `ingest/replay.py`)**

```python
import os
import subprocess
import tempfile
from pathlib import Path

import zstandard as zstd

from dota_coach.ingest.opendota import fetch_match


class ReplayUnavailable(Exception):
    """Реплей нельзя достать/распарсить — разбор продолжается без реплей-слоя."""


def _default_downloader(url: str) -> bytes:
    import requests
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def _default_runner(argv: list[str]) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"replay_tool rc={proc.returncode}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _tool_default() -> str:
    exe = "replay_tool.exe" if os.name == "nt" else "replay_tool"
    return str(Path(__file__).resolve().parents[3] / "replay_tool" / exe)


def parse_replay(match_id: int, cache_dir: Path = Path("cache"), tool_path: str | None = None,
                 downloader=None, runner=None) -> ParsedReplay:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"replay_{match_id}.jsonl"
    if cached.exists():
        return parse_replay_jsonl(cached.read_text(encoding="utf-8").splitlines(), match_id)

    downloader = downloader or _default_downloader
    runner = runner or _default_runner
    tool_path = tool_path or _tool_default()

    try:
        url = (fetch_match(match_id) or {}).get("replay_url")
        if not url:
            raise ReplayUnavailable(f"нет replay_url для матча {match_id}")
        blob = downloader(url)
        dem = zstd.ZstdDecompressor().decompress(blob, max_output_size=1 << 30)
        with tempfile.NamedTemporaryFile(suffix=".dem", delete=False) as tf:
            tf.write(dem)
            dem_path = tf.name
        try:
            out = runner([tool_path, dem_path])
        finally:
            os.unlink(dem_path)
        cached.write_text(out, encoding="utf-8")
        return parse_replay_jsonl(out.splitlines(), match_id)
    except ReplayUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - граница реплей-слоя: любой сбой -> опциональная деградация
        raise ReplayUnavailable(f"реплей матча {match_id} недоступен: {exc}") from exc
```

Note про `zstd.decompress` без размера контента: Valve-фреймы обычно без `content_size` → используем `max_output_size=1<<30` (1 ГБ потолок; распакованный `.dem` ~100 МБ). Если API `decompress` упрётся в streaming-фрейм, деградация в `ReplayUnavailable` покроет — но на реальном матче спайк распаковал `copy_stream`; при сбое — заменить на `stream_reader`. Проверяется живым смоком (Step 5).

- [ ] **Step 4: Прогнать юнит-тесты**

Run: `PYTHONPATH=src python -m pytest tests/test_replay_parse.py -v`
Expected: PASS (все, включая 3 новых parse_replay).

- [ ] **Step 5: Живой смок end-to-end (реальная сеть+бинарь)**

Run: `cd /c/Users/user/PycharmProjects/dota-coach && rm -f cache/replay_8944053733.jsonl && PYTHONPATH=src python -c "from dota_coach.ingest.replay import parse_replay; r=parse_replay(8944053733); print('heroes',len(r.heroes),'frames',len(r.frames)); print(r.heroes)"`
Expected: скачивает, распаковывает, гоняет бинарь, кеширует; `heroes 10`, `frames ~2400`. Второй прогон — из кеша, мгновенно.

- [ ] **Step 6: Полный набор тестов**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS (155 старых + новые replay-тесты; ничего не сломано).

- [ ] **Step 7: Commit**

```bash
git add src/dota_coach/ingest/replay.py tests/test_replay_parse.py
git commit -m "feat(replay): parse_replay — скачать+zstd+бинарь+кеш, деградация ReplayUnavailable"
```

---

## Self-Review (выполнено при написании)

- **Покрытие спеки (срез 1a-state):** экстрактор состояния @1Hz (Task 3, доказан спайком) → JSONL-контракт (Task 2) → модель `ParsedReplay`+`frame_at` (Task 1) → обвязка скачать/zstd/кеш/деградация (Task 4). Опциональность реплей-слоя = `ReplayUnavailable` (Task 4). Слот=pid/2, отсев иллюзий, координаты, время — в Global Constraints и коде Task 3.
- **Отклонения от спеки (осознанные):** (1) yaw/направление героя выкинут — вижн в Доте круговой, facing не влияет на «что видел»; (2) hero хранится как класс `CDOTA_Unit_Hero_*`, не `npc_dota_hero_*` — конверсия в hero_id не нужна для 1a-state, отложена в 1b при линковке к аккаунту.
- **Плейсхолдеров нет:** весь Go и Python код полный. Единственная отмеченная неопределённость — API zstd (`decompress` vs `stream_reader`) — с явным фолбэком и покрытием живым смоком.
- **Согласованность типов:** JSONL-контракт (meta/state/units поля) идентичен в Go-эмите (Task 3), Python-парсере (Task 2) и фикстуре; `UnitState`/`ReplayFrame`/`ParsedReplay` (Task 1) ↔ конструкторы в Task 2 ↔ `frame_at` в смоках Task 3/4. `parse_replay` инъекции (downloader/runner/tool_path) ↔ тесты Task 4.
- **Вне области (следующие срезы):** события (combat log/варды/касты) = 1a-events; вижн/last-seen/инфо-состояние = 1b; интеграция в разбор = 1c.
```
