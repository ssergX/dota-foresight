# Dota Coach — фаза 2: системный ЛЛМ-тренер (`coach`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** По серии последних матчей выдать связный тренерский бриф (главный лик → диагноз → почему топит → 1-2 дрилла) с петлёй подотчётности (сравнение метрики лика-фокуса между прогонами).

**Architecture:** Детерминированное ядро (чистые функции, TDD) считает все факты — лики с числами, выбор фокуса, дельты прогресса; ЛЛМ только формулирует разбор и возвращает структурный JSON, который парсится и рендерится. Сетевой вызов ЛЛМ — тонкая склейка (как `opendota.py`), провайдер-агностик через OpenAI-совместимый `/chat/completions`, дефолт GLM, кеш ответа по хешу входа.

**Tech Stack:** Python 3.12, `requests` (уже есть), `pytest`. Без новых зависимостей.

**Spec:** `docs/superpowers/specs/2026-08-15-dota-coach-phase2-coach-design.md`.

## Global Constraints

- **Python 3.12**, платформа **Windows** — пути через `pathlib`, не хардкодить `/`.
- **Анти-результатничество:** win/loss (`radiant_win`) НИКОГДА не попадает в промпт ЛЛМ. Прогресс между прогонами считает код, не ЛЛМ.
- **Заземление:** ЛЛМ рассуждает только по переданным числам + курируемым принципам; не выдумывает числа; каждый дрилл привязан к метрике (`metric_ref`).
- **Провайдер-агностик:** ЛЛМ через тонкий интерфейс; конфиг из env `DOTA_COACH_LLM_BASE_URL`, `DOTA_COACH_LLM_API_KEY`, `DOTA_COACH_LLM_MODEL`.
- **Чистое ядро отдельно от сетевой склейки.** Реальный HTTP-клиент юнит-тестами не покрывается (как `opendota.py`); тестируется `FakeLLM`.
- **Код и идентификаторы — на английском; текст, видимый пользователю — на русском.**
- Один файл — одна ответственность. Новый пакет `src/dota_coach/coach/`.
- Форматирование: black line-length 120 (проект уже так).

---

### Task 1: Обогатить `Leak` числами

**Files:**
- Modify: `src/dota_coach/models.py` (dataclass `Leak`)
- Modify: `src/dota_coach/leaks.py` (заполнить поля в `detect_leaks`)
- Test: `tests/test_leaks.py` (добавить тест числовых полей)

**Interfaces:**
- Consumes: —
- Produces: `Leak` с новыми полями `metric: str`, `value: float`, `threshold: float`, `direction: str` (`"lower_is_better"`/`"higher_is_better"`), заполненными для всех трёх ликов.

- [ ] **Step 1: Write the failing test** — добавить в конец `tests/test_leaks.py`:

```python
def test_leaks_carry_numeric_fields():
    matches = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=1) for i in range(5)]
    leaks = {l.key: l for l in detect_leaks(matches, 111)}

    feeding = leaks["feeding"]
    assert feeding.metric == "deaths_per_game"
    assert feeding.value == 11.0
    assert feeding.threshold == 8.0
    assert feeding.direction == "lower_is_better"

    farm = leaks["farm_below_bracket"]
    assert farm.metric == "gpm_pct"
    assert farm.value == 0.25
    assert farm.threshold == 0.4
    assert farm.direction == "higher_is_better"

    warding = leaks["low_warding"]
    assert warding.metric == "obs_per_game"
    assert warding.value == 1.0
    assert warding.threshold == 4.0
    assert warding.direction == "higher_is_better"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_leaks.py::test_leaks_carry_numeric_fields -v`
Expected: FAIL — `assert '' == 'deaths_per_game'` (поля пустые/дефолтные).

- [ ] **Step 3: Add fields to `Leak`** — в `src/dota_coach/models.py` заменить dataclass `Leak`:

```python
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
```

- [ ] **Step 4: Fill fields in `detect_leaks`** — в `src/dota_coach/leaks.py` дополнить три конструкции `Leak`:

В `farm_below_bracket` (после `median(gpms)` уже посчитан):
```python
        leaks.append(Leak(
            key="farm_below_bracket",
            title="Фарм ниже бракета",
            magnitude=f"медиана GPM в p{int(median(gpms) * 100)}",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
            metric="gpm_pct",
            value=float(median(gpms)),
            threshold=_FARM_PCT,
            direction="higher_is_better",
        ))
```

В `feeding`:
```python
        leaks.append(Leak(
            key="feeding",
            title="Слишком много смертей",
            magnitude=f"в среднем {avg_deaths:.1f} смертей за игру (порог {_DEATHS_MAX:.0f})",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
            metric="deaths_per_game",
            value=float(avg_deaths),
            threshold=_DEATHS_MAX,
            direction="lower_is_better",
        ))
```

В `low_warding`:
```python
        leaks.append(Leak(
            key="low_warding",
            title="Мало вардов",
            magnitude=f"в среднем {avg_obs:.1f} обс-вардов за игру (порог {_OBS_MIN:.0f})",
            example_matches=[r["match_id"] for r in worst],
            confidence=Confidence.HIGH,
            metric="obs_per_game",
            value=float(avg_obs),
            threshold=_OBS_MIN,
            direction="higher_is_better",
        ))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_leaks.py -v`
Expected: PASS (все, включая существующие — поля добавлены с дефолтами, старые проверки не затронуты).

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/models.py src/dota_coach/leaks.py tests/test_leaks.py
git commit -m "feat(leaks): нести числа лика (metric/value/threshold/direction) для петли прогресса"
```

---

### Task 2: Пакет `coach` + модель брифа (`brief.py`)

**Files:**
- Create: `src/dota_coach/coach/__init__.py` (пустой, 0 байт)
- Create: `src/dota_coach/coach/brief.py`
- Test: `tests/test_coach_brief.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `Drill(text: str, metric_ref: str = "")`
  - `CoachBrief(focus_leak_key, headline, diagnosis, why_it_costs, drills: list[Drill], progress_note: str|None, generated_for_matches: list[int], focus_metric: str, focus_value: float, focus_direction: str)`
  - `parse_brief(raw: str | dict) -> CoachBrief` — валидирует форму, `ValueError` на битую.
  - `brief_to_dict(b: CoachBrief) -> dict` — для истории (round-trip с `parse_brief`).

- [ ] **Step 1: Write the failing test** — `tests/test_coach_brief.py`:

```python
import json

import pytest

from dota_coach.coach.brief import CoachBrief, Drill, brief_to_dict, parse_brief


def test_parse_brief_good_json():
    raw = json.dumps({
        "focus_leak_key": "feeding",
        "headline": "Слишком часто умираешь",
        "diagnosis": "11 смертей за игру",
        "why_it_costs": "отдаёшь темп",
        "drills": [{"text": "перед движением проверь миникарту", "metric_ref": "deaths_per_game"}],
    })
    b = parse_brief(raw)
    assert isinstance(b, CoachBrief)
    assert b.focus_leak_key == "feeding"
    assert b.drills[0].metric_ref == "deaths_per_game"


def test_parse_brief_missing_focus_raises():
    with pytest.raises(ValueError):
        parse_brief(json.dumps({"headline": "x", "drills": []}))


def test_parse_brief_drills_not_list_raises():
    with pytest.raises(ValueError):
        parse_brief({"focus_leak_key": "feeding", "drills": "nope"})


def test_brief_dict_round_trip_preserves_focus_snapshot():
    b = CoachBrief(
        focus_leak_key="low_warding", headline="h", diagnosis="d", why_it_costs="w",
        drills=[Drill(text="ставь обс на руну", metric_ref="obs_per_game")],
        progress_note="варды p1 → p3 — прогресс", generated_for_matches=[1, 2],
        focus_metric="obs_per_game", focus_value=1.0, focus_direction="higher_is_better",
    )
    again = parse_brief(brief_to_dict(b))
    assert again.focus_leak_key == "low_warding"
    assert again.focus_value == 1.0
    assert again.focus_direction == "higher_is_better"
    assert again.progress_note == "варды p1 → p3 — прогресс"
    assert again.drills[0].text == "ставь обс на руну"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_brief.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dota_coach.coach'`.

- [ ] **Step 3: Create `src/dota_coach/coach/__init__.py`** — пустой файл (0 байт).

- [ ] **Step 4: Write `src/dota_coach/coach/brief.py`**

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Drill:
    text: str
    metric_ref: str = ""


@dataclass
class CoachBrief:
    focus_leak_key: str
    headline: str
    diagnosis: str
    why_it_costs: str
    drills: list[Drill] = field(default_factory=list)
    progress_note: str | None = None
    generated_for_matches: list[int] = field(default_factory=list)
    # снимок лика-фокуса для петли подотчётности (ставит код, не ЛЛМ):
    focus_metric: str = ""
    focus_value: float = 0.0
    focus_direction: str = "lower_is_better"


def parse_brief(raw: str | dict) -> CoachBrief:
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("coach brief должен быть JSON-объектом")
    if "focus_leak_key" not in data:
        raise ValueError("coach brief без focus_leak_key")
    drills_raw = data.get("drills", [])
    if not isinstance(drills_raw, list):
        raise ValueError("coach brief drills должен быть списком")

    drills: list[Drill] = []
    for d in drills_raw:
        if isinstance(d, dict):
            drills.append(Drill(text=str(d.get("text", "")), metric_ref=str(d.get("metric_ref", ""))))
        else:
            drills.append(Drill(text=str(d), metric_ref=""))
    if drills and all(not d.metric_ref for d in drills):
        print("warning: ни один дрилл не привязан к метрике (metric_ref пуст)")

    return CoachBrief(
        focus_leak_key=str(data["focus_leak_key"]),
        headline=str(data.get("headline", "")),
        diagnosis=str(data.get("diagnosis", "")),
        why_it_costs=str(data.get("why_it_costs", "")),
        drills=drills,
        progress_note=data.get("progress_note"),
        generated_for_matches=list(data.get("generated_for_matches", [])),
        focus_metric=str(data.get("focus_metric", "")),
        focus_value=float(data.get("focus_value", 0.0)),
        focus_direction=str(data.get("focus_direction", "lower_is_better")),
    )


def brief_to_dict(b: CoachBrief) -> dict:
    return {
        "focus_leak_key": b.focus_leak_key,
        "headline": b.headline,
        "diagnosis": b.diagnosis,
        "why_it_costs": b.why_it_costs,
        "drills": [{"text": d.text, "metric_ref": d.metric_ref} for d in b.drills],
        "progress_note": b.progress_note,
        "generated_for_matches": b.generated_for_matches,
        "focus_metric": b.focus_metric,
        "focus_value": b.focus_value,
        "focus_direction": b.focus_direction,
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_coach_brief.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/coach/__init__.py src/dota_coach/coach/brief.py tests/test_coach_brief.py
git commit -m "feat(coach): модель брифа (CoachBrief/Drill) + parse_brief/brief_to_dict"
```

---

### Task 3: Сравнение прогресса (`progress.py`)

**Files:**
- Create: `src/dota_coach/coach/progress.py`
- Test: `tests/test_coach_progress.py`

**Interfaces:**
- Consumes: `models.Leak`, `coach.brief.CoachBrief`.
- Produces:
  - `ProgressNote(status: str, metric: str, prev_value: float|None, curr_value: float|None, text: str)` — `status ∈ {"improved","regressed","flat","resolved","no_history"}`.
  - `compare_focus(prev_brief: CoachBrief | None, current_leaks: list[Leak]) -> ProgressNote` — чистая, детерминированная.

- [ ] **Step 1: Write the failing test** — `tests/test_coach_progress.py`:

```python
from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.progress import compare_focus
from dota_coach.models import Confidence, Leak


def _leak(key, metric, value, threshold, direction):
    return Leak(key=key, title=key, magnitude="", example_matches=[],
                confidence=Confidence.HIGH, metric=metric, value=value,
                threshold=threshold, direction=direction)


def _prior(focus_key, metric, value, direction):
    return CoachBrief(focus_leak_key=focus_key, headline="", diagnosis="", why_it_costs="",
                      focus_metric=metric, focus_value=value, focus_direction=direction)


def test_no_history_when_no_prior():
    note = compare_focus(None, [_leak("feeding", "deaths_per_game", 11.0, 8.0, "lower_is_better")])
    assert note.status == "no_history"


def test_feeding_improved_lower_is_better():
    prior = _prior("feeding", "deaths_per_game", 11.0, "lower_is_better")
    curr = [_leak("feeding", "deaths_per_game", 8.5, 8.0, "lower_is_better")]
    note = compare_focus(prior, curr)
    assert note.status == "improved"
    assert "прогресс" in note.text


def test_feeding_regressed_lower_is_better():
    prior = _prior("feeding", "deaths_per_game", 8.5, "lower_is_better")
    curr = [_leak("feeding", "deaths_per_game", 12.0, 8.0, "lower_is_better")]
    note = compare_focus(prior, curr)
    assert note.status == "regressed"
    assert "регресс" in note.text


def test_gpm_improved_higher_is_better():
    prior = _prior("farm_below_bracket", "gpm_pct", 0.25, "higher_is_better")
    curr = [_leak("farm_below_bracket", "gpm_pct", 0.35, 0.4, "higher_is_better")]
    note = compare_focus(prior, curr)
    assert note.status == "improved"


def test_resolved_when_leak_absent():
    prior = _prior("low_warding", "obs_per_game", 1.0, "higher_is_better")
    note = compare_focus(prior, [_leak("feeding", "deaths_per_game", 9.0, 8.0, "lower_is_better")])
    assert note.status == "resolved"


def test_flat_when_same_value():
    prior = _prior("feeding", "deaths_per_game", 9.0, "lower_is_better")
    curr = [_leak("feeding", "deaths_per_game", 9.0, 8.0, "lower_is_better")]
    assert compare_focus(prior, curr).status == "flat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_progress.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dota_coach.coach.progress'`.

- [ ] **Step 3: Write `src/dota_coach/coach/progress.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from dota_coach.coach.brief import CoachBrief
from dota_coach.models import Leak

_FLAT_EPS = 1e-9

_METRIC_RU = {
    "deaths_per_game": "смерти за игру",
    "gpm_pct": "GPM-перцентиль",
    "obs_per_game": "варды за игру",
}


@dataclass
class ProgressNote:
    status: str
    metric: str
    prev_value: float | None
    curr_value: float | None
    text: str


def _find_leak(leaks: list[Leak], key: str) -> Leak | None:
    for leak in leaks:
        if leak.key == key:
            return leak
    return None


def _fmt(metric: str, value: float) -> str:
    if metric == "gpm_pct":
        return f"p{int(value * 100)}"
    return f"{value:.1f}"


def compare_focus(prev_brief: CoachBrief | None, current_leaks: list[Leak]) -> ProgressNote:
    if prev_brief is None or not prev_brief.focus_leak_key:
        return ProgressNote("no_history", "", None, None,
                            "Первый разбор — базовая точка отсчёта.")

    key = prev_brief.focus_leak_key
    metric = prev_brief.focus_metric
    metric_ru = _METRIC_RU.get(metric, metric)
    prev_value = prev_brief.focus_value
    direction = prev_brief.focus_direction or "lower_is_better"

    curr_leak = _find_leak(current_leaks, key)
    if curr_leak is None:
        return ProgressNote("resolved", metric, prev_value, None,
                            f"Лик «{key}» больше не срабатывает — прогресс.")

    curr_value = curr_leak.value
    delta = curr_value - prev_value
    if direction == "higher_is_better":
        improved = delta > _FLAT_EPS
        regressed = delta < -_FLAT_EPS
    else:
        improved = delta < -_FLAT_EPS
        regressed = delta > _FLAT_EPS

    if not improved and not regressed:
        status, word = "flat", "без сдвига"
    elif improved:
        status, word = "improved", "прогресс"
    else:
        status, word = "regressed", "регресс"

    text = f"{metric_ru}: {_fmt(metric, prev_value)} → {_fmt(metric, curr_value)} — {word}."
    return ProgressNote(status, metric, prev_value, curr_value, text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_progress.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/progress.py tests/test_coach_progress.py
git commit -m "feat(coach): compare_focus — детерминированная дельта метрики лика-фокуса"
```

---

### Task 4: История брифов (`history.py`)

**Files:**
- Create: `src/dota_coach/coach/history.py`
- Test: `tests/test_coach_history.py`

**Interfaces:**
- Consumes: `coach.brief.CoachBrief`, `brief_to_dict`, `parse_brief`.
- Produces:
  - `load_history(account_id, cache_dir=Path("cache")) -> list[CoachBrief]`
  - `save_brief(account_id, brief, cache_dir=Path("cache")) -> None` (дозапись)
  - `latest_brief(account_id, cache_dir=Path("cache")) -> CoachBrief | None`
  - Файл: `cache/coach_history_<account_id>.json`.

- [ ] **Step 1: Write the failing test** — `tests/test_coach_history.py`:

```python
from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.history import latest_brief, load_history, save_brief


def _brief(key, value):
    return CoachBrief(focus_leak_key=key, headline="h", diagnosis="d", why_it_costs="w",
                      focus_metric="deaths_per_game", focus_value=value,
                      focus_direction="lower_is_better")


def test_load_history_empty_when_no_file(tmp_path):
    assert load_history(111, cache_dir=tmp_path) == []
    assert latest_brief(111, cache_dir=tmp_path) is None


def test_save_then_load_round_trip(tmp_path):
    save_brief(111, _brief("feeding", 11.0), cache_dir=tmp_path)
    save_brief(111, _brief("feeding", 8.0), cache_dir=tmp_path)
    hist = load_history(111, cache_dir=tmp_path)
    assert len(hist) == 2
    assert hist[0].focus_value == 11.0
    assert latest_brief(111, cache_dir=tmp_path).focus_value == 8.0


def test_history_is_per_account(tmp_path):
    save_brief(111, _brief("feeding", 11.0), cache_dir=tmp_path)
    assert load_history(222, cache_dir=tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_history.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dota_coach.coach.history'`.

- [ ] **Step 3: Write `src/dota_coach/coach/history.py`**

```python
from __future__ import annotations

import json
from pathlib import Path

from dota_coach.coach.brief import CoachBrief, brief_to_dict, parse_brief


def _history_path(account_id: int | None, cache_dir: Path) -> Path:
    return cache_dir / f"coach_history_{account_id}.json"


def load_history(account_id: int | None, cache_dir: Path = Path("cache")) -> list[CoachBrief]:
    path = _history_path(account_id, cache_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [parse_brief(item) for item in data]


def save_brief(account_id: int | None, brief: CoachBrief, cache_dir: Path = Path("cache")) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _history_path(account_id, cache_dir)
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    existing.append(brief_to_dict(brief))
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


def latest_brief(account_id: int | None, cache_dir: Path = Path("cache")) -> CoachBrief | None:
    history = load_history(account_id, cache_dir)
    return history[-1] if history else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_history.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/history.py tests/test_coach_history.py
git commit -m "feat(coach): персист истории брифов per-account (load/save/latest)"
```

---

### Task 5: База принципов (`principles.md` + `principles.py`)

**Files:**
- Create: `src/dota_coach/coach/principles.md`
- Create: `src/dota_coach/coach/principles.py`
- Test: `tests/test_coach_principles.py`

**Interfaces:**
- Consumes: —
- Produces: `principles_for(leak_key: str, path: Path = _PRINCIPLES_PATH) -> str` — секция из `.md` по заголовку `## <leak_key>`; дефолт, если секции нет. Без RAG.

- [ ] **Step 1: Write the failing test** — `tests/test_coach_principles.py`:

```python
from dota_coach.coach.principles import principles_for


def test_principles_for_known_leak_returns_text():
    text = principles_for("feeding")
    assert isinstance(text, str)
    assert len(text) > 0
    assert "смерт" in text.lower()


def test_principles_for_unknown_leak_returns_default():
    text = principles_for("totally_unknown_leak_key")
    assert isinstance(text, str)
    assert len(text) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_principles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dota_coach.coach.principles'`.

- [ ] **Step 3: Write `src/dota_coach/coach/principles.md`**

```markdown
# База тренерских принципов

Разбирай процесс и решения, а не исход матча. Дай конкретное проверяемое действие.

## feeding
Смерть = потеря темпа, отдача золота и опыта врагу, минус пуш и вижн-контроль.
Перед любым движением проверь: есть ли вижн на карте, где враги на миникарте,
есть ли у тебя escape/CD ключевых заклинаний. Лишняя смерть почти всегда — это
жадность до фарма/килла без информации. Цель — резать смерти без потери участия.

## farm_below_bracket
Фарм — это ресурс под импакт: без золота нет таймингов предметов, без предметов
нет драк. Держи лейн/лес заполненными между движениями, стакай и подбирай крипов
по пути, не стой без дела. Считай: сколько «пустых» минут без ластхитов было.

## low_warding
Вижн = информация = меньше смертей и больше объектов. Правило: обс на руну и на
подходы к твоему таймингу фарма/объекта. Дешёвый обс окупается одной предотвращённой
смертью. Ставь варды ПЕРЕД тем, как заходишь в опасную зону, а не после.
```

- [ ] **Step 4: Write `src/dota_coach/coach/principles.py`**

```python
from __future__ import annotations

from pathlib import Path

_PRINCIPLES_PATH = Path(__file__).with_name("principles.md")
_DEFAULT = "Разбирай процесс и решения, а не исход. Дай конкретное проверяемое действие."


def _load_sections(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    sections: dict[str, str] = {}
    key: str | None = None
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if key is not None:
                sections[key] = "\n".join(buf).strip()
            key = line[3:].strip()
            buf = []
        elif key is not None:
            buf.append(line)
    if key is not None:
        sections[key] = "\n".join(buf).strip()
    return sections


def principles_for(leak_key: str, path: Path = _PRINCIPLES_PATH) -> str:
    section = _load_sections(path).get(leak_key)
    return section if section else _DEFAULT
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_coach_principles.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Ensure `.md` ships in the wheel** — проверить `pyproject.toml` секцию `[tool.hatch.build.targets.wheel]` (`packages = ["src/dota_coach"]`). Hatchling включает не-`.py` файлы внутри пакета по умолчанию — доп. настройка не нужна. (Проверка: файл лежит внутри `src/dota_coach/coach/`, значит попадёт в пакет.)

- [ ] **Step 7: Commit**

```bash
git add src/dota_coach/coach/principles.md src/dota_coach/coach/principles.py tests/test_coach_principles.py
git commit -m "feat(coach): курируемая база принципов (.md) + principles_for"
```

---

### Task 6: Сборка промпта (`prompt.py`)

**Files:**
- Create: `src/dota_coach/coach/prompt.py`
- Test: `tests/test_coach_prompt.py`

**Interfaces:**
- Consumes: `models.Leak`, `coach.brief.CoachBrief`, `coach.progress.ProgressNote`.
- Produces: `build_coach_prompt(leaks: list[Leak], progress: ProgressNote | None, principles: str, prior: CoachBrief | None, focus_key: str) -> list[dict]` — `[{"role":"system",...}, {"role":"user",...}]`.

- [ ] **Step 1: Write the failing test** — `tests/test_coach_prompt.py`:

```python
from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.progress import compare_focus
from dota_coach.coach.prompt import build_coach_prompt
from dota_coach.models import Confidence, Leak


def _leak(key, metric, value, threshold, direction):
    return Leak(key=key, title=key, magnitude="", example_matches=[7, 8],
                confidence=Confidence.HIGH, metric=metric, value=value,
                threshold=threshold, direction=direction)


def _leaks():
    return [_leak("feeding", "deaths_per_game", 11.0, 8.0, "lower_is_better")]


def test_prompt_has_system_and_user_roles():
    msgs = build_coach_prompt(_leaks(), None, "принципы фидинга", None, "feeding")
    assert [m["role"] for m in msgs] == ["system", "user"]


def test_prompt_contains_numbers_focus_and_principles():
    msgs = build_coach_prompt(_leaks(), None, "принципы фидинга", None, "feeding")
    user = msgs[1]["content"]
    assert "11.0" in user            # value
    assert "8.0" in user             # threshold
    assert "feeding" in user         # focus key
    assert "принципы фидинга" in user


def test_system_enforces_anti_outcome_rule():
    msgs = build_coach_prompt(_leaks(), None, "p", None, "feeding")
    assert "исход" in msgs[0]["content"].lower()


def test_user_prompt_has_no_winloss_data():
    # анти-результатничество: сырых исходов матча в данные не подаём
    msgs = build_coach_prompt(_leaks(), None, "p", None, "feeding")
    user = msgs[1]["content"]
    assert "radiant_win" not in user
    assert "победа" not in user.lower()
    assert "поражение" not in user.lower()


def test_prompt_includes_prior_progress():
    prior = CoachBrief(focus_leak_key="feeding", headline="", diagnosis="", why_it_costs="",
                       focus_metric="deaths_per_game", focus_value=14.0,
                       focus_direction="lower_is_better")
    progress = compare_focus(prior, _leaks())   # 14.0 -> 11.0, lower_is_better -> improved
    msgs = build_coach_prompt(_leaks(), progress, "p", prior, "feeding")
    assert "прогресс" in msgs[1]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dota_coach.coach.prompt'`.

- [ ] **Step 3: Write `src/dota_coach/coach/prompt.py`**

```python
from __future__ import annotations

from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.progress import ProgressNote
from dota_coach.models import Leak

_SYSTEM = (
    "Ты — строгий, честный тренер по Dota 2. Разбираешь СЕРИЮ последних игр игрока.\n"
    "Жёсткие правила:\n"
    "1. Судишь процесс и решения по входным метрикам, НИКОГДА по исходу матча. "
    "Побед/поражений тебе не дают — не рассуждай о них.\n"
    "2. Не выдумывай числа. Используй только приведённые метрики. Каждый тезис и "
    "каждый дрилл привязывай к конкретной метрике (её ключ клади в metric_ref).\n"
    "3. Дай 1–2 конкретных, проверяемых дрилла на следующие игры. Без воды.\n"
    "4. Пиши по-русски.\n"
    "Верни СТРОГО JSON-объект такой формы (без markdown-обёртки):\n"
    '{"focus_leak_key": str, "headline": str, "diagnosis": str, '
    '"why_it_costs": str, "drills": [{"text": str, "metric_ref": str}]}'
)


def _leaks_block(leaks: list[Leak]) -> str:
    if not leaks:
        return "(ликов не обнаружено)"
    lines = [
        f"- key={leak.key} | {leak.title} | metric={leak.metric} | "
        f"value={leak.value:.3f} | threshold={leak.threshold:.3f} | "
        f"direction={leak.direction} | примеры_матчей={leak.example_matches}"
        for leak in leaks
    ]
    return "\n".join(lines)


def _progress_block(progress: ProgressNote | None, prior: CoachBrief | None) -> str:
    if prior is None or progress is None or progress.status == "no_history":
        return "Прошлого разбора нет — это базовая точка отсчёта."
    return f"Прошлый фокус: {prior.focus_leak_key}. Динамика метрики: {progress.text}"


def build_coach_prompt(leaks: list[Leak], progress: ProgressNote | None,
                       principles: str, prior: CoachBrief | None,
                       focus_key: str) -> list[dict]:
    user = (
        f"Лики по серии (детерминированный детектор):\n{_leaks_block(leaks)}\n\n"
        f"Главный лик-фокус: {focus_key}\n\n"
        f"Прогресс с прошлого разбора:\n{_progress_block(progress, prior)}\n\n"
        f"Тренерские принципы по этому лику:\n{principles}\n\n"
        "Сформулируй разбор строго по фокус-лику в заданном JSON-формате."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_prompt.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/prompt.py tests/test_coach_prompt.py
git commit -m "feat(coach): build_coach_prompt — заземлённый промпт без win/loss"
```

---

### Task 7: ЛЛМ-клиент (`llm.py`)

**Files:**
- Create: `src/dota_coach/coach/llm.py`
- Test: `tests/test_coach_llm.py`

**Interfaces:**
- Consumes: —
- Produces:
  - `CoachLLM` (Protocol) с `complete(messages: list[dict]) -> str`.
  - `FakeLLM(canned: str)` — возвращает `canned`, пишет вызовы в `.calls`.
  - `_messages_hash(messages: list[dict]) -> str` — детерминированный SHA-256.
  - `OpenAICompatibleLLM(base_url=None, api_key=None, model=None, cache_dir=Path("cache")/"coach_llm", timeout=60.0)` — сетевая склейка (юнит-тестами не покрывается).

- [ ] **Step 1: Write the failing test** — `tests/test_coach_llm.py`:

```python
from dota_coach.coach.llm import FakeLLM, _messages_hash


def test_fake_llm_returns_canned_and_records_calls():
    llm = FakeLLM('{"focus_leak_key": "feeding"}')
    msgs = [{"role": "user", "content": "hi"}]
    out = llm.complete(msgs)
    assert out == '{"focus_leak_key": "feeding"}'
    assert llm.calls == [msgs]


def test_messages_hash_is_stable_and_order_sensitive():
    a = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    b = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    c = [{"role": "system", "content": "x"}, {"role": "user", "content": "z"}]
    assert _messages_hash(a) == _messages_hash(b)
    assert _messages_hash(a) != _messages_hash(c)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dota_coach.coach.llm'`.

- [ ] **Step 3: Write `src/dota_coach/coach/llm.py`**

```python
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol

import requests


class CoachLLM(Protocol):
    def complete(self, messages: list[dict]) -> str: ...


def _messages_hash(messages: list[dict]) -> str:
    blob = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class FakeLLM:
    """Тестовый двойник: отдаёт заранее заданный JSON, пишет вызовы."""

    def __init__(self, canned: str):
        self._canned = canned
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        return self._canned


class OpenAICompatibleLLM:
    """Сетевая склейка (без юнит-тестов, как opendota.py). Дисковый кеш по хешу входа."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, cache_dir: Path = Path("cache") / "coach_llm",
                 timeout: float = 60.0):
        self.base_url = (base_url or os.environ["DOTA_COACH_LLM_BASE_URL"]).rstrip("/")
        self.api_key = api_key or os.environ["DOTA_COACH_LLM_API_KEY"]
        self.model = model or os.environ.get("DOTA_COACH_LLM_MODEL")
        if not self.model:
            raise ValueError("не задана модель: DOTA_COACH_LLM_MODEL или аргумент model")
        self.cache_dir = cache_dir
        self.timeout = timeout

    def complete(self, messages: list[dict]) -> str:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cache_dir / f"{_messages_hash(messages)}.json"
        if cached.exists():
            return cached.read_text(encoding="utf-8")
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.4,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        cached.write_text(content, encoding="utf-8")
        return content
```

Примечание: `response_format={"type":"json_object"}` поддерживают GLM и большинство OpenAI-совместимых бэкендов. Если конкретный бэкенд его не принимает — убрать это поле (JSON всё равно затребован в system-промпте).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_llm.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/llm.py tests/test_coach_llm.py
git commit -m "feat(coach): провайдер-агностик ЛЛМ-клиент + FakeLLM + кеш по хешу"
```

---

### Task 8: Оркестратор (`coach.py`)

**Files:**
- Create: `src/dota_coach/coach/coach.py`
- Test: `tests/test_coach_orchestrator.py`

**Interfaces:**
- Consumes: `leaks.detect_leaks`, `models.Match/Leak`, `coach.brief`, `coach.history`, `coach.llm.CoachLLM`, `coach.principles`, `coach.progress`, `coach.prompt`.
- Produces:
  - `_select_focus(leaks: list[Leak]) -> Leak | None` — худший нарушитель по `abs(value-threshold)/abs(threshold)`, тай-брейк фикс. приоритетом `["feeding","farm_below_bracket","low_warding"]`.
  - `run_coach(matches: list[Match], account_id: int|None, llm: CoachLLM, cache_dir=Path("cache")) -> CoachBrief`.

- [ ] **Step 1: Write the failing test** — `tests/test_coach_orchestrator.py`:

```python
import json

from dota_coach.coach.coach import run_coach
from dota_coach.coach.history import latest_brief
from dota_coach.coach.llm import FakeLLM
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


_CANNED = json.dumps({
    "focus_leak_key": "ignored-by-code",
    "headline": "Мало вардов",
    "diagnosis": "варды в p1",
    "why_it_costs": "нет информации — лишние смерти",
    "drills": [{"text": "ставь обс на руну перед фармом", "metric_ref": "obs_per_game"}],
})


def test_run_coach_builds_brief_and_saves(tmp_path):
    # obs=1 -> low_warding имеет наибольшее отклонение от порога -> фокус
    matches = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=1) for i in range(5)]
    llm = FakeLLM(_CANNED)
    brief = run_coach(matches, 111, llm, cache_dir=tmp_path)

    assert brief.focus_leak_key == "low_warding"      # фокус ставит код, не ЛЛМ
    assert brief.focus_metric == "obs_per_game"
    assert brief.focus_value == 1.0
    assert brief.drills[0].metric_ref == "obs_per_game"
    assert brief.progress_note is None                # первый прогон
    assert len(llm.calls) == 1
    # сохранён в историю
    assert latest_brief(111, cache_dir=tmp_path).focus_leak_key == "low_warding"


def test_run_coach_no_leaks_skips_llm(tmp_path):
    matches = [_m(i, 111, gpm_pct=0.7, deaths=3, obs=8) for i in range(5)]
    llm = FakeLLM(_CANNED)
    brief = run_coach(matches, 111, llm, cache_dir=tmp_path)
    assert brief.focus_leak_key == ""
    assert "не найдено" in brief.headline
    assert llm.calls == []                            # ЛЛМ не вызывался


def test_run_coach_second_run_reports_progress(tmp_path):
    first = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=1) for i in range(5)]
    run_coach(first, 111, FakeLLM(_CANNED), cache_dir=tmp_path)   # focus low_warding, obs=1
    second = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=3) for i in range(5)]  # obs 1 -> 3
    brief2 = run_coach(second, 111, FakeLLM(_CANNED), cache_dir=tmp_path)
    assert brief2.progress_note is not None
    assert "прогресс" in brief2.progress_note         # higher_is_better, 1 -> 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dota_coach.coach.coach'`.

- [ ] **Step 3: Write `src/dota_coach/coach/coach.py`**

```python
from __future__ import annotations

from pathlib import Path

from dota_coach.coach.brief import CoachBrief, parse_brief
from dota_coach.coach.history import latest_brief, save_brief
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.principles import principles_for
from dota_coach.coach.progress import compare_focus
from dota_coach.coach.prompt import build_coach_prompt
from dota_coach.leaks import detect_leaks
from dota_coach.models import Leak, Match

_FOCUS_PRIORITY = ["feeding", "farm_below_bracket", "low_warding"]


def _select_focus(leaks: list[Leak]) -> Leak | None:
    if not leaks:
        return None

    def deviation(leak: Leak) -> float:
        if not leak.threshold:
            return abs(leak.value)
        return abs(leak.value - leak.threshold) / abs(leak.threshold)

    def priority(leak: Leak) -> int:
        return _FOCUS_PRIORITY.index(leak.key) if leak.key in _FOCUS_PRIORITY else len(_FOCUS_PRIORITY)

    return sorted(leaks, key=lambda leak: (-deviation(leak), priority(leak)))[0]


def run_coach(matches: list[Match], account_id: int | None, llm: CoachLLM,
              cache_dir: Path = Path("cache")) -> CoachBrief:
    leaks = detect_leaks(matches, account_id)
    match_ids = [m.match_id for m in matches]
    prior = latest_brief(account_id, cache_dir)
    progress = compare_focus(prior, leaks)
    focus = _select_focus(leaks)

    if focus is None:
        brief = CoachBrief(
            focus_leak_key="",
            headline="Системных ликов по этой серии не найдено",
            diagnosis="",
            why_it_costs="",
            drills=[],
            progress_note=(progress.text if progress.status != "no_history" else None),
            generated_for_matches=match_ids,
        )
        save_brief(account_id, brief, cache_dir)
        return brief

    principles = principles_for(focus.key)
    messages = build_coach_prompt(leaks, progress, principles, prior, focus.key)
    brief = parse_brief(llm.complete(messages))

    # фокус и снимок метрики ставит КОД (не ЛЛМ) — чтобы петля была детерминированной:
    brief.focus_leak_key = focus.key
    brief.focus_metric = focus.metric
    brief.focus_value = focus.value
    brief.focus_direction = focus.direction
    brief.progress_note = progress.text if progress.status != "no_history" else None
    brief.generated_for_matches = match_ids

    save_brief(account_id, brief, cache_dir)
    return brief
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_orchestrator.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/coach.py tests/test_coach_orchestrator.py
git commit -m "feat(coach): run_coach — оркестратор с детерминированным выбором фокуса и петлёй"
```

---

### Task 9: Тренерский HTML-отчёт (`render_coach_html`)

**Files:**
- Modify: `src/dota_coach/report.py`
- Test: `tests/test_coach_report.py`

**Interfaces:**
- Consumes: `coach.brief.CoachBrief`, `models.Leak`, `coach.progress.ProgressNote`.
- Produces: `render_coach_html(brief: CoachBrief, leaks: list[Leak], progress: ProgressNote | None = None) -> str` — самодостаточный HTML, русский, HTML-escape.

- [ ] **Step 1: Write the failing test** — `tests/test_coach_report.py`:

```python
from dota_coach.coach.brief import CoachBrief, Drill
from dota_coach.models import Confidence, Leak
from dota_coach.report import render_coach_html


def _leak():
    return Leak(key="low_warding", title="Мало вардов",
                magnitude="в среднем 1.0 обс-вардов за игру (порог 4)",
                example_matches=[1, 2], confidence=Confidence.HIGH,
                metric="obs_per_game", value=1.0, threshold=4.0, direction="higher_is_better")


def _brief():
    return CoachBrief(
        focus_leak_key="low_warding", headline="Тебя топит вижн",
        diagnosis="варды в p1", why_it_costs="нет информации — лишние смерти",
        drills=[Drill(text="ставь обс на руну", metric_ref="obs_per_game")],
        progress_note="варды p1 → p3 — прогресс",
        focus_metric="obs_per_game", focus_value=1.0, focus_direction="higher_is_better",
    )


def test_coach_report_shows_headline_drills_and_progress():
    html = render_coach_html(_brief(), [_leak()])
    assert "Тебя топит вижн" in html
    assert "ставь обс на руну" in html
    assert "варды p1 → p3 — прогресс" in html
    assert "Мало вардов" in html


def test_coach_report_escapes_html():
    brief = _brief()
    brief.headline = "<script>alert(1)</script>"
    html = render_coach_html(brief, [_leak()])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_coach_report_no_leaks_message():
    empty = CoachBrief(focus_leak_key="", headline="Системных ликов по этой серии не найдено",
                       diagnosis="", why_it_costs="", drills=[])
    html = render_coach_html(empty, [])
    assert "не найдено" in html
    assert "<script>" not in html  # без инъекций
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_coach_report.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_coach_html'`.

- [ ] **Step 3: Add `render_coach_html` to `src/dota_coach/report.py`** — добавить импорты и функцию в конец файла:

Вверху файла, к существующему `from dota_coach.models import Leak, ScoredMoment` добавить отдельные импорты (модель coach):
```python
from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.progress import ProgressNote
```

В конец файла:
```python
def _coach_drill_row(text: str, metric_ref: str) -> str:
    ref = f" <span class='meta'>[{_html.escape(metric_ref)}]</span>" if metric_ref else ""
    return f"<li>{_html.escape(text)}{ref}</li>"


def _coach_leak_row(leak: Leak) -> str:
    return (f"<li><b>{_html.escape(leak.title)}</b>: {_html.escape(leak.magnitude)}</li>")


def render_coach_html(brief: CoachBrief, leaks: list[Leak],
                      progress: ProgressNote | None = None) -> str:
    headline = _html.escape(brief.headline)
    if not brief.focus_leak_key:
        body = f"<h1>{headline}</h1>"
    else:
        diagnosis = _html.escape(brief.diagnosis)
        why = _html.escape(brief.why_it_costs)
        drills = "\n".join(_coach_drill_row(d.text, d.metric_ref) for d in brief.drills)
        note = brief.progress_note or (progress.text if progress else None)
        progress_block = (f"<h2>Прогресс</h2><p class='progress'>{_html.escape(note)}</p>"
                          if note else "")
        leaks_block = "\n".join(_coach_leak_row(l) for l in leaks)
        body = (
            f"<h1>{headline}</h1>"
            f"<h2>Диагноз</h2><p>{diagnosis}</p>"
            f"<h2>Почему это топит</h2><p>{why}</p>"
            f"<h2>Дриллы на следующие игры</h2><ul>{drills}</ul>"
            f"{progress_block}"
            f"<h2>Все системные лики</h2><ul>{leaks_block}</ul>"
        )

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Dota Coach — системный разбор</title>
<style>
  body{{font-family:sans-serif;max-width:820px;margin:24px auto;color:#eee;background:#1b1b1f}}
  h1{{color:#fff}} h2{{color:#9ab;margin-top:22px}}
  .meta{{color:#9ab;font-size:12px}} .progress{{color:#9d9}}
  li{{margin:6px 0}}
</style></head><body>
{body}
</body></html>"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_coach_report.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/report.py tests/test_coach_report.py
git commit -m "feat(report): render_coach_html — тренерская страница (headline/диагноз/дриллы/прогресс)"
```

---

### Task 10: CLI-подкоманда `coach`

**Files:**
- Modify: `src/dota_coach/cli.py`
- Test: `tests/test_cli.py` (добавить тест dry-run)

**Interfaces:**
- Consumes: `coach.coach.run_coach`, `coach.coach._select_focus`, `coach.llm.OpenAICompatibleLLM`, `coach.principles.principles_for`, `coach.progress.compare_focus`, `coach.history.latest_brief`, `coach.prompt.build_coach_prompt`, `leaks.detect_leaks`, `report.render_coach_html`.
- Produces: подкоманда `dota-coach coach --account-id ID [--n 20] [--out coach.html] [--dry-run]`.

- [ ] **Step 1: Write the failing test** — добавить в `tests/test_cli.py`:

```python
def test_coach_dry_run_prints_prompt_without_llm(monkeypatch, capsys):
    from dota_coach.cli import main
    from dota_coach.models import Match, PlayerMatch

    def _p(deaths, obs, gpm):
        return PlayerMatch(
            account_id=111, player_slot=0, hero_id=1, is_radiant=True,
            kills=0, deaths=deaths, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
            gold_t=[], xp_t=[], lh_t=[], kills_log=[], purchase_log=[],
            obs_log=[{"time": 60}] * obs, sen_log=[],
            benchmarks={"gold_per_min": {"raw": 400, "pct": gpm}},
        )

    def _match(mid):
        return Match(match_id=mid, duration=1800, radiant_win=True,
                     players=[_p(11, 1, 0.25)], teamfights=[], objectives=[], parsed=True)

    monkeypatch.setattr("dota_coach.cli.fetch_recent", lambda acc, n: list(range(5)))
    monkeypatch.setattr("dota_coach.cli.fetch_match", lambda mid: {"id": mid})
    monkeypatch.setattr("dota_coach.cli.normalize", lambda raw: _match(raw["id"]))

    rc = main(["coach", "--account-id", "111", "--n", "5", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "system" in out
    assert "Главный лик-фокус" in out   # промпт напечатан, ЛЛМ не вызывался
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py::test_coach_dry_run_prints_prompt_without_llm -v`
Expected: FAIL — `SystemExit` / `invalid choice: 'coach'` (подкоманды ещё нет).

- [ ] **Step 3: Add `_cmd_coach` + parser wiring to `src/dota_coach/cli.py`**

Добавить импорт вверху (рядом с `from dota_coach.report import render_report`):
```python
from dota_coach.report import render_coach_html, render_report
```

Добавить функцию `_cmd_coach` (перед `def main`):
```python
def _cmd_coach(args: argparse.Namespace) -> int:
    ids = fetch_recent(args.account_id, args.n)
    matches = [normalize(fetch_match(mid)) for mid in ids]

    if args.dry_run:
        from dota_coach.coach.coach import _select_focus
        from dota_coach.coach.history import latest_brief
        from dota_coach.coach.principles import principles_for
        from dota_coach.coach.progress import compare_focus
        from dota_coach.coach.prompt import build_coach_prompt
        from dota_coach.leaks import detect_leaks

        leaks = detect_leaks(matches, args.account_id)
        focus = _select_focus(leaks)
        if focus is None:
            print("Системных ликов по этой серии не найдено — ЛЛМ не нужен.")
            return 0
        prior = latest_brief(args.account_id)
        progress = compare_focus(prior, leaks)
        messages = build_coach_prompt(leaks, progress, principles_for(focus.key), prior, focus.key)
        for msg in messages:
            print(f"--- {msg['role']} ---\n{msg['content']}\n")
        return 0

    from dota_coach.coach.coach import run_coach
    from dota_coach.coach.llm import OpenAICompatibleLLM
    from dota_coach.leaks import detect_leaks

    brief = run_coach(matches, args.account_id, OpenAICompatibleLLM())
    leaks = detect_leaks(matches, args.account_id)
    html = render_coach_html(brief, leaks)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"coach brief over {len(matches)} matches -> {args.out}")
    return 0
```

Зарегистрировать подкоманду внутри `main`, после блока `leaks`:
```python
    c = sub.add_parser("coach", help="системный ЛЛМ-разбор по серии матчей")
    c.add_argument("--account-id", type=int, required=True, dest="account_id")
    c.add_argument("--n", type=int, default=20)
    c.add_argument("--out", default="coach.html")
    c.add_argument("--dry-run", action="store_true", dest="dry_run")
    c.set_defaults(func=_cmd_coach)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (все, включая новый dry-run тест).

- [ ] **Step 5: Full suite green**

Run: `pytest -q`
Expected: все тесты зелёные (33 прежних + новые coach-тесты).

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/cli.py tests/test_cli.py
git commit -m "feat(cli): подкоманда coach (+ --dry-run печатает промпт без ЛЛМ)"
```

---

## Ручной смок (после всех задач, вне TDD)

С реальным GLM-эндпоинтом (не автотест):

```bash
export DOTA_COACH_LLM_BASE_URL="https://<твой-openai-совместимый-хост>/v1"
export DOTA_COACH_LLM_API_KEY="<ключ>"
export DOTA_COACH_LLM_MODEL="<модель, напр. glm-4-plus>"

# сначала посмотреть промпт без трат:
dota-coach coach --account-id <ID> --n 20 --dry-run

# затем реальный разбор:
dota-coach coach --account-id <ID> --n 20 --out coach.html
```

Проверить: `coach.html` открывается, есть headline/диагноз/дриллы; при повторном прогоне
появляется блок «Прогресс». Кеш ЛЛМ — в `cache/coach_llm/`.

---

## Self-Review

**Spec coverage:**
- Обогащение `Leak` числами → Task 1. ✅
- `principles.md`+`principles_for` (без RAG) → Task 5. ✅
- `progress.compare_focus` (код, не ЛЛМ) → Task 3. ✅
- `history` load/save/latest → Task 4. ✅
- `brief`/`parse_brief` контракт JSON → Task 2. ✅
- `llm` провайдер-агностик + кеш + FakeLLM → Task 7. ✅
- `prompt` заземление + анти-исход + без win/loss → Task 6. ✅
- `coach.run_coach` оркестратор + выбор фокуса + кейс «ликов нет» → Task 8. ✅
- `render_coach_html` → Task 9. ✅
- CLI `coach` + `--dry-run` → Task 10. ✅
- Env `DOTA_COACH_LLM_*`, 1 вызов/серию, кеш по хешу → Task 7 + смок. ✅

**Placeholder scan:** плейсхолдеров нет — во всех шагах реальный код и команды.

**Type consistency:** `CoachBrief`/`Drill`/`ProgressNote` поля и сигнатуры (`compare_focus`, `build_coach_prompt`, `_select_focus`, `run_coach`, `render_coach_html`, `principles_for`, `load/save/latest_brief`, `_messages_hash`, `parse_brief`/`brief_to_dict`) согласованы между задачами. `Leak` поля (`metric/value/threshold/direction`) из Task 1 используются в 3/6/8/9. `focus_*`-снимок в `CoachBrief` (Task 2) используется в `compare_focus` (Task 3) и `run_coach` (Task 8).
