# Role-Aware Leaks (20 детекторов T1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Превратить плоский детектор из 3 ликов в ролевой пакет из ~20 детекторов, где набор ликов и пороги зависят от позиции (pos1–5), серия сегментируется по ролям, а severity выбирает один фокус.

**Architecture:** `leaks.py` (83 строки, три захардкоженных детектора) становится пакетом `leaks/`. Один Row = один матч глазами игрока. `build_rows → segment_by_role → applicable(role) → requires-filter → detector(rows, role, thresholds) → Leak`, затем `severity.rank → (фокус, «тоже видно»)`. Контракт с `coach/` не ломается: бриф, ЛЛМ-промпт, петля подотчётности и рендер живут, меняется только качество/объём входа.

**Tech Stack:** Python 3.12, dataclasses, `statistics`, pytest. Без новых зависимостей.

## Global Constraints

- **Анти-результатничество.** `win` / `lose` / `radiant_win` / `radiant_score` / `dire_score` НИКОГДА не попадают в объект `Leak` и в сериализованный ЛЛМ-промпт. Закрыто тестом-сканером (Task 13).
- **Детерминированное ядро.** Все факты считает код; ЛЛМ только формулирует. Двойной прогон `detect_leaks` на одних данных → идентичный порядок и идентичный фокус (тай-брейк по `key` алфавитно).
- **Заземление.** «Как чинить» — только из курируемой `principles.md`; у каждого зарегистрированного ключа есть своя секция (тест полноты, Task 12).
- **Никогда не подставляй ноль.** Отсутствующее поле → матч исключается из выборки детектора (`requires`), а не считается нулём.
- **Чистые функции отдельно от сетевой склейки.** Детекторы — чистые функции над `list[Row]`, тестируются без сети.
- **Порог включения роли:** роль разбирается от **5 игр**, иначе «данных мало».
- **Порог включения детектора:** после `requires`-фильтра должно остаться **≥ 5 матчей**, иначе детектор не запускается.
- Линтеры: black line-length 120, isort профиль black. Русский язык интерфейса.

---

## File Structure

```
src/dota_coach/
  models.py                    — MODIFY: расширить PlayerMatch и Leak
  ingest/normalize.py          — MODIFY: тянуть новые поля (с None-дефолтами)
  leaks/                       — NEW пакет (заменяет leaks.py)
    __init__.py                — фасад detect_leaks(matches, account_id) -> list[Leak]
    rows.py                    — Row + build_rows(matches, account_id) -> list[Row]
    roles.py                   — role_of(me) + segment_by_role(rows)
    thresholds.py              — Thresholds: ручные константы + bench-floor
    registry.py                — @detector, DETECTORS, applicable(role), filter_rows
    severity.py                — score() + rank(leaks) -> (focus, also_visible)
    detectors/
      __init__.py              — импорт всех модулей (регистрация side-effect)
      _common.py               — mean_of / median_pct / make_leak
      deaths.py laning.py economy.py vision.py fights.py objectives.py
  coach/coach.py               — MODIFY: фокус = топ-1 по severity
  coach/prompt.py              — MODIFY: роль, source, подтверждающие детали семьи
  coach/history.py             — MODIFY: schema_version + снимок всех ликов + мап low_warding→low_obs
  coach/principles.md          — MODIFY: 20 секций
  cli.py                       — MODIFY: --n по умолчанию 50
tests/
  test_leaks.py                — MODIFY под ролевую модель
  test_leaks_rows_roles.py     — NEW
  test_leaks_registry.py       — NEW
  test_leaks_thresholds.py     — NEW
  test_leaks_severity.py       — NEW
  test_leaks_detectors_*.py    — NEW по семьям
  test_coach_*.py              — MODIFY затронутые
  test_principles_coverage.py  — NEW
  test_anti_resultism.py       — NEW
```

Каждый детектор — чистая функция с сигнатурой `fn(rows: list[Row], role: int, th: Thresholds) -> Leak | None`. Матчи уже отфильтрованы фасадом по `requires`, поэтому детектор считает поля присутствующими.

---

### Task 0: Восстановить рабочий `leaks.py` и зафиксировать зелёный базлайн

Рабочее дерево содержит сломанный `leaks.py` (лишний отступ на первой строке → `SyntaxError`, импорт падает). Откатываем к закоммиченной версии и убеждаемся, что весь пакет тестов зелёный ДО рефакторинга.

**Files:**
- Modify: `src/dota_coach/leaks.py` (git restore committed version)

- [ ] **Step 1: Откатить незакоммиченную поломку**

Run:
```bash
cd /c/Users/user/PycharmProjects/dota-coach && git checkout -- src/dota_coach/leaks.py
```

- [ ] **Step 2: Убедиться, что импорт и тесты зелёные**

Run:
```bash
cd /c/Users/user/PycharmProjects/dota-coach && python -c "import dota_coach.leaks" && PYTHONPATH=src python -m pytest -q
```
Expected: import OK; `82 passed` (базлайн фазы 2).

- [ ] **Step 3: Ветка для работы**

Ветка `feat/role-aware-leaks` уже существует (репозиторий уже на ней) — не создаём заново, иначе `fatal: a branch already exists`.

```bash
git checkout feat/role-aware-leaks 2>/dev/null || git checkout -b feat/role-aware-leaks
git commit --allow-empty -m "chore(leaks): базлайн перед ролевым рефактором (leaks.py восстановлен)"
```

---

### Task 1: Расширить модель данных (`PlayerMatch`, `Leak`) и нормализацию

**Files:**
- Modify: `src/dota_coach/models.py` (PlayerMatch ~40-48, Leak ~108-119)
- Modify: `src/dota_coach/ingest/normalize.py:6-27` (`_player`)
- Test: `tests/test_normalize.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `PlayerMatch` с новыми полями (все с дефолтами; парс-зависимые числовые — `int | None = None`, списки — пустые). `Leak` с новыми полями `role`, `source`, `sample_size`, `severity`, `phase`, `family`.

Правило разделения дефолтов: поля, которые есть только у **пропарсенных** матчей, объявляются `| None = None` и нормализуются через `raw.get(field)` (без `, 0`), чтобы `requires` мог исключить матч. Всегда-присутствующие числа могут иметь `= 0`.

- [ ] **Step 1: Тест новых полей PlayerMatch и их дефолтов**

```python
# tests/test_models.py  (добавить)
from dota_coach.models import PlayerMatch

def test_playermatch_new_fields_have_safe_defaults():
    p = PlayerMatch(account_id=1, player_slot=0, hero_id=1, is_radiant=True,
                    kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    # парс-зависимые (в т.ч. счётчики вижна/леса) отсутствуют -> None (не 0),
    # чтобы requires исключил непропарсенный матч (инвариант «никогда не нолить»)
    assert p.position_est is None
    assert p.lane_efficiency_pct is None
    assert p.life_state_dead is None
    assert p.teamfight_participation is None
    assert p.obs_placed is None
    assert p.sen_placed is None
    assert p.camps_stacked is None
    assert p.neutral_kills is None
    assert p.observer_kills is None
    # всегда-присутствующие базовые числа -> 0 / пустые
    assert p.denies == 0
    assert p.hero_damage == 0
    assert p.killed_by == {}
    assert p.obs_left_log == []
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_models.py::test_playermatch_new_fields_have_safe_defaults -v`
Expected: FAIL (`unexpected keyword` / `AttributeError`).

- [ ] **Step 3: Расширить PlayerMatch**

```python
# models.py — добавить в PlayerMatch после benchmarks (сохранив существующие поля):
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
```

- [ ] **Step 4: Тест новых полей Leak**

```python
# tests/test_models.py (добавить)
from dota_coach.models import Leak

def test_leak_new_fields_defaults():
    l = Leak(key="k", title="t", magnitude="m")
    assert l.role is None
    assert l.source == "manual"
    assert l.sample_size == 0
    assert l.considered == 0
    assert l.severity == 0.0
    assert l.phase == ""
    assert l.family == ""
```

- [ ] **Step 5: Расширить Leak**

```python
# models.py — добавить в @dataclass class Leak после direction:
    role: int | None = None
    source: str = "manual"       # bench | manual | personal
    sample_size: int = 0         # N: матчей после requires-фильтра
    considered: int = 0          # M: матчей в роли до фильтра (для строки покрытия)
    severity: float = 0.0
    phase: str = ""              # laning|economy|deaths|fights|vision|objectives
    family: str = ""
```

- [ ] **Step 6: Тест нормализации новых полей**

```python
# tests/test_normalize.py (добавить)
from dota_coach.ingest.normalize import normalize

def test_normalize_pulls_role_and_parse_fields():
    raw = {"match_id": 1, "duration": 1800, "radiant_win": True, "version": 22,
           "players": [{"account_id": 7, "player_slot": 0, "position_est": 4,
                        "lane_role": 3, "is_roaming": False, "denies": 12,
                        "obs_placed": 7, "life_state_dead": 523,
                        "teamfight_participation": 0.52, "lane_efficiency_pct": 38}]}
    m = normalize(raw)
    me = m.players[0]
    assert me.position_est == 4 and me.denies == 12 and me.obs_placed == 7
    assert me.life_state_dead == 523 and me.teamfight_participation == 0.52

def test_normalize_absent_parse_fields_stay_none():
    raw = {"match_id": 2, "duration": 1800, "radiant_win": True,  # без version -> unparsed
           "players": [{"account_id": 7, "player_slot": 0}]}
    me = normalize(raw).players[0]
    assert me.position_est is None and me.life_state_dead is None
    assert me.teamfight_participation is None and me.denies == 0  # число -> 0
```

- [ ] **Step 7: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_normalize.py -v`
Expected: FAIL (поля не заполняются).

- [ ] **Step 8: Расширить `_player` в normalize.py**

```python
# normalize.py — внутри _player(...), добавить в конструктор PlayerMatch:
        position_est=raw.get("position_est"),
        lane_role=raw.get("lane_role"),
        is_roaming=bool(raw.get("is_roaming", False)),
        lane=raw.get("lane"),
        denies=raw.get("denies", 0),
        net_worth=raw.get("net_worth", 0),
        level=raw.get("level", 0),
        hero_damage=raw.get("hero_damage", 0),
        tower_damage=raw.get("tower_damage", 0),
        killed_by=raw.get("killed_by") or {},
        # парс-зависимые счётчики — БЕЗ дефолта 0: raw.get -> None, requires исключит матч
        observer_kills=raw.get("observer_kills"),
        sentry_uses=raw.get("sentry_uses"),
        obs_placed=raw.get("obs_placed"),
        sen_placed=raw.get("sen_placed"),
        camps_stacked=raw.get("camps_stacked"),
        neutral_kills=raw.get("neutral_kills"),
        rune_pickups=raw.get("rune_pickups"),
        towers_killed=raw.get("towers_killed"),
        roshans_killed=raw.get("roshans_killed"),
        lane_efficiency_pct=raw.get("lane_efficiency_pct"),
        life_state_dead=raw.get("life_state_dead"),
        teamfight_participation=raw.get("teamfight_participation"),
        stuns=raw.get("stuns"),
        dn_t=raw.get("dn_t") or [],
        obs_left_log=raw.get("obs_left_log") or [],
        buyback_log=raw.get("buyback_log") or [],
```

- [ ] **Step 9: Прогнать модель+нормализацию**

Run: `PYTHONPATH=src python -m pytest tests/test_models.py tests/test_normalize.py -v`
Expected: PASS. Существующие тесты не тронуты (только добавления).

- [ ] **Step 10: Commit**

```bash
git add src/dota_coach/models.py src/dota_coach/ingest/normalize.py tests/test_models.py tests/test_normalize.py
git commit -m "feat(leaks): расширить PlayerMatch и Leak под ролевые детекторы"
```

---

### Task 2: Превратить `leaks.py` в пакет `leaks/` (перенос без смены поведения)

Переносим текущий `detect_leaks` в `leaks/__init__.py` дословно, удаляем `leaks.py`, добавляем пустые модули-заготовки. Поведение и все тесты — идентичны. Реестр ещё не используется фасадом (флип в Task 10).

**Files:**
- Create: `src/dota_coach/leaks/__init__.py` (перенос текущего кода)
- Delete: `src/dota_coach/leaks.py`
- Create: `src/dota_coach/leaks/detectors/__init__.py` (пустой)

**Interfaces:**
- Produces: `from dota_coach.leaks import detect_leaks` продолжает работать с прежней сигнатурой `(matches, account_id) -> list[Leak]`.

- [ ] **Step 1: Создать пакет с текущей логикой**

Скопировать всё тело восстановленного `src/dota_coach/leaks.py` в `src/dota_coach/leaks/__init__.py` **без изменений** (импорты, `_FARM_PCT`, `detect_leaks` и т.д.).

- [ ] **Step 2: Удалить старый модуль и создать заготовку detectors**

```bash
git rm src/dota_coach/leaks.py
mkdir -p src/dota_coach/leaks/detectors
printf '' > src/dota_coach/leaks/detectors/__init__.py
```

- [ ] **Step 3: Тесты по-прежнему зелёные (поведение не изменилось)**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: `82 passed`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor(leaks): leaks.py -> пакет leaks/ (поведение без изменений)"
```

---

### Task 3: `rows.py` + `roles.py` — Row, сборка, определение и сегментация роли

**Files:**
- Create: `src/dota_coach/leaks/rows.py`
- Create: `src/dota_coach/leaks/roles.py`
- Test: `tests/test_leaks_rows_roles.py`

**Interfaces:**
- Produces:
  - `Row(match_id: int, duration: int, parsed: bool, role: int | None, me: PlayerMatch)` (frozen dataclass)
  - `build_rows(matches: list[Match], account_id: int | None) -> list[Row]`
  - `role_of(me: PlayerMatch) -> int | None`
  - `segment_by_role(rows: list[Row]) -> dict[int, list[Row]]`

- [ ] **Step 1: Тесты roles/rows**

```python
# tests/test_leaks_rows_roles.py
from dota_coach.leaks.rows import Row, build_rows
from dota_coach.leaks.roles import role_of, segment_by_role
from dota_coach.models import Match, PlayerMatch


def _me(**kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return PlayerMatch(**base)


def _match(mid, me, parsed=True):
    return Match(match_id=mid, duration=1800, radiant_win=True, players=[me], parsed=parsed)


def test_role_from_position_est_wins():
    assert role_of(_me(position_est=3, lane_role=1)) == 3


def test_role_fallback_lane_role_and_roaming():
    assert role_of(_me(position_est=None, lane_role=2)) == 2                      # mid
    assert role_of(_me(position_est=None, lane_role=1, is_roaming=False)) == 1    # safe carry
    assert role_of(_me(position_est=None, lane_role=1, is_roaming=True)) == 5     # roaming support
    assert role_of(_me(position_est=None, lane_role=3, is_roaming=False)) == 3    # offlane
    assert role_of(_me(position_est=None, lane_role=3, is_roaming=True)) == 4     # roaming pos4


def test_role_undetermined_returns_none():
    assert role_of(_me(position_est=None, lane_role=None)) is None


def test_build_rows_skips_missing_account():
    empty = Match(match_id=9, duration=1800, radiant_win=True, players=[], parsed=True)
    rows = build_rows([_match(1, _me(position_est=3)), empty], 7)
    assert [r.match_id for r in rows] == [1]
    assert rows[0].role == 3 and rows[0].parsed is True


def test_segment_by_role_groups_and_drops_none():
    rows = build_rows([
        _match(1, _me(position_est=3)),
        _match(2, _me(position_est=3)),
        _match(3, _me(position_est=4)),
        _match(4, _me(position_est=None, lane_role=None)),  # роль не определена
    ], 7)
    seg = segment_by_role(rows)
    assert sorted(seg) == [3, 4]
    assert len(seg[3]) == 2 and len(seg[4]) == 1
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_rows_roles.py -v`
Expected: FAIL (модулей нет).

- [ ] **Step 3: Реализовать rows.py**

```python
from __future__ import annotations

from dataclasses import dataclass

from dota_coach.leaks.roles import role_of
from dota_coach.models import Match, PlayerMatch


@dataclass(frozen=True)
class Row:
    match_id: int
    duration: int
    parsed: bool
    role: int | None
    me: PlayerMatch


def build_rows(matches: list[Match], account_id: int | None) -> list[Row]:
    rows: list[Row] = []
    for m in matches:
        me = m.player_by_account(account_id)
        if me is None:
            continue
        rows.append(Row(match_id=m.match_id, duration=m.duration,
                        parsed=m.parsed, role=role_of(me), me=me))
    return rows
```

- [ ] **Step 4: Реализовать roles.py**

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from dota_coach.models import PlayerMatch

if TYPE_CHECKING:  # НЕ импортировать Row в рантайме — иначе цикл rows<->roles
    from dota_coach.leaks.rows import Row


def role_of(me: PlayerMatch) -> int | None:
    if me.position_est in (1, 2, 3, 4, 5):
        return me.position_est
    lr = me.lane_role
    if lr == 2:
        return 2
    if lr == 1:
        return 5 if me.is_roaming else 1
    if lr == 3:
        return 4 if me.is_roaming else 3
    return None


def segment_by_role(rows: list["Row"]) -> dict[int, list["Row"]]:
    out: dict[int, list["Row"]] = {}
    for r in rows:
        if r.role is None:
            continue
        out.setdefault(r.role, []).append(r)
    return out
```

Note (БЛОКЕР — обязательно): `rows.py` импортирует `role_of` из `roles.py` в рантайме (нужен `build_rows`). Значит `roles.py` НЕ должен импортировать `Row` из `rows.py` на верхнем уровне — иначе жёсткий цикл `partially initialized module` → `ImportError` при любом импорте пакета (это не lint-варнинг, а падение на старте). `from __future__ import annotations` не спасает: он лишь стрингифицирует аннотации, а сам `import`-оператор исполняется при загрузке модуля. Импорт `Row` держим только под `TYPE_CHECKING`, аннотации — строковые.

- [ ] **Step 5: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_rows_roles.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/leaks/rows.py src/dota_coach/leaks/roles.py tests/test_leaks_rows_roles.py
git commit -m "feat(leaks): Row + сегментация серии по ролям (position_est с фолбэком)"
```

---

### Task 4: `registry.py` + `thresholds.py` — реестр детекторов, requires-фильтр, пороги

**Files:**
- Create: `src/dota_coach/leaks/registry.py`
- Create: `src/dota_coach/leaks/thresholds.py`
- Test: `tests/test_leaks_registry.py`, `tests/test_leaks_thresholds.py`

**Interfaces:**
- Produces:
  - `@detector(key, title, roles, requires, impact, phase, family)` — регистрирует функцию в `DETECTORS`.
  - `DetectorSpec` (frozen) с полями `fn, key, title, roles, requires, impact, phase, family`.
  - `applicable(role: int) -> list[DetectorSpec]`.
  - `filter_rows(rows: list[Row], requires: tuple[str, ...]) -> list[Row]` — исключает матчи, где любое требуемое поле «отсутствует» (None; для списков — пусто).
  - `Thresholds` с методами `manual(metric: str, role: int) -> float | None` и `bench_floor() -> float` (константа 0.4).

- [ ] **Step 1: Тесты реестра и фильтра**

```python
# tests/test_leaks_registry.py
from dota_coach.leaks.registry import DETECTORS, applicable, detector, filter_rows
from dota_coach.leaks.rows import Row
from dota_coach.models import PlayerMatch


def _row(mid, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=4, me=PlayerMatch(**base))


def test_detector_registers_and_applicable_filters_by_role():
    before = len(DETECTORS)

    @detector(key="t_only_pos4", title="x", roles=(4,), requires=(),
              impact=0.5, phase="vision", family="vision")
    def _d(rows, role, th):
        return None

    assert len(DETECTORS) == before + 1
    keys4 = {d.key for d in applicable(4)}
    keys3 = {d.key for d in applicable(3)}
    assert "t_only_pos4" in keys4 and "t_only_pos4" not in keys3


def test_filter_rows_excludes_missing_and_never_zeros():
    rows = [
        _row(1, life_state_dead=500),   # есть
        _row(2, life_state_dead=None),  # нет -> исключить
        _row(3, life_state_dead=0),     # ноль -> это данные, оставить
    ]
    kept = [r.match_id for r in filter_rows(rows, ("life_state_dead",))]
    assert kept == [1, 3]


def test_filter_rows_empty_list_field_is_absent():
    rows = [_row(1, dn_t=[1, 2]), _row(2, dn_t=[])]
    assert [r.match_id for r in filter_rows(rows, ("dn_t",))] == [1]
```

```python
# tests/test_leaks_thresholds.py
from dota_coach.leaks.thresholds import Thresholds


def test_bench_floor_is_04():
    assert Thresholds().bench_floor() == 0.4


def test_manual_is_role_specific():
    th = Thresholds()
    assert th.manual("obs_per_game", 5) > th.manual("obs_per_game", 4)  # pos5 требует больше обсов


def test_manual_unknown_metric_returns_none():
    assert Thresholds().manual("nope", 1) is None
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_registry.py tests/test_leaks_thresholds.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать registry.py**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak

Detector = Callable[[list[Row], int, Thresholds], "Leak | None"]


@dataclass(frozen=True)
class DetectorSpec:
    fn: Detector
    key: str
    title: str
    roles: tuple[int, ...]
    requires: tuple[str, ...]
    impact: float
    phase: str
    family: str


DETECTORS: list[DetectorSpec] = []


def detector(*, key: str, title: str, roles: tuple[int, ...], requires: tuple[str, ...],
             impact: float, phase: str, family: str):
    def deco(fn: Detector) -> Detector:
        def wrapper(rows, role, th):
            leak = fn(rows, role, th)
            if leak is not None:
                # идентичность лика ставит ОДНО место — обёртка, из метаданных декоратора.
                # Детекторы и make_leak key/title/phase/family НЕ задают.
                leak.key = key
                leak.title = title
                leak.phase = phase
                leak.family = family
            return leak
        DETECTORS.append(DetectorSpec(fn=wrapper, key=key, title=title, roles=tuple(roles),
                                      requires=tuple(requires), impact=impact,
                                      phase=phase, family=family))
        return wrapper
    return deco


def applicable(role: int) -> list[DetectorSpec]:
    return [d for d in DETECTORS if role in d.roles]


def _present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, dict, str)):
        return len(value) > 0
    return True


def filter_rows(rows: list[Row], requires: tuple[str, ...]) -> list[Row]:
    return [r for r in rows if all(_present(getattr(r.me, f)) for f in requires)]
```

- [ ] **Step 4: Реализовать thresholds.py**

```python
from __future__ import annotations

from dataclasses import dataclass

_BENCH_FLOOR = 0.4  # bench-детекторы срабатывают ниже перцентиля 0.4

# Ручные константы. Значения — стартовые инженерные оценки, калибруются на живом
# прогоне (Task 13). Ключ = metric-имя детектора; вложенно — переопределение по роли,
# "*" — дефолт для всех ролей детектора.
_MANUAL: dict[str, dict] = {
    "deaths_per_game":         {"*": 8.0},
    "time_dead_frac":          {"*": 0.13},   # доля игры мёртвым
    "repeat_victim_kills":     {"*": 2.5},    # в среднем один герой убивает ≥ N раз ЗА ИГРУ (scale-invariant)
    "cs_at_10":                {1: 45.0, 2: 45.0, 3: 35.0},  # ластхиты к 10 мин
    "denies_per_game":         {"*": 8.0},
    "lane_efficiency_pct":     {"*": 40.0},   # ниже — провален лейн
    "neutral_kills_per_game":  {1: 20.0, 2: 15.0, 3: 15.0},
    "camps_stacked_per_game":  {4: 2.0, 5: 2.0},
    "rune_pickups_per_game":   {2: 3.0},
    "obs_per_game":            {4: 4.0, 5: 6.0},
    "sen_per_game":            {4: 3.0, 5: 4.0},
    "obs_lifetime_s":          {4: 180.0, 5: 180.0},  # средняя жизнь варда
    "dewards_per_game":        {4: 1.0, 5: 1.0},
    "teamfight_participation": {3: 0.55, 4: 0.55, 5: 0.55},
}


@dataclass(frozen=True)
class Thresholds:
    def bench_floor(self) -> float:
        return _BENCH_FLOOR

    def manual(self, metric: str, role: int) -> float | None:
        table = _MANUAL.get(metric)
        if table is None:
            return None
        if role in table:
            return float(table[role])
        if "*" in table:
            return float(table["*"])
        return None
```

- [ ] **Step 5: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_registry.py tests/test_leaks_thresholds.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/leaks/registry.py src/dota_coach/leaks/thresholds.py tests/test_leaks_registry.py tests/test_leaks_thresholds.py
git commit -m "feat(leaks): реестр детекторов, requires-фильтр (никогда не нолит), таблица порогов"
```

---

### Task 5: `detectors/_common.py` + семья `deaths`

Общие помощники + первая семья детекторов. `deaths` v1 = `feeding`, `time_dead`, `repeat_victim`. **`early_deaths` НЕ входит в v1**: у игрока в объекте нет надёжного тайм-лайна собственных смертей (`kills_log` — это МОИ убийства, `killed_by` — карта без времени). Итог: **19 детекторов**, а не 20; `early_deaths` уходит в T2 (кросс-референс `life_state`-таймсерии). Это осознанное урезание против спеки — зафиксировать в отчёте приёмки.

**Files:**
- Create: `src/dota_coach/leaks/detectors/_common.py`
- Create: `src/dota_coach/leaks/detectors/deaths.py`
- Test: `tests/test_leaks_detectors_deaths.py`

**Interfaces:**
- Produces (`_common`):
  - `mean_of(rows, getter) -> float`
  - `median_pct(rows, metric) -> float | None` (медиана `me.benchmarks[metric]["pct"]`)
  - `make_leak(*, role, rows, metric, value, threshold, direction, source, magnitude, worst_key, worst_reverse) -> Leak` — заполняет `example_matches` (топ-3 худших), `sample_size=len(rows)`, `role`, числа. `key/title/phase/family` НЕ ставит — их штампует обёртка `@detector`.
- Produces (`deaths`): регистрирует `feeding`, `time_dead`, `repeat_victim`.

- [ ] **Step 1: Тесты семьи deaths (как чистых функций)**

```python
# tests/test_leaks_detectors_deaths.py
from dota_coach.leaks.detectors.deaths import feeding, repeat_victim, time_dead
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=4, me=PlayerMatch(**base))


def test_feeding_fires_above_threshold_with_worst_examples():
    rows = [_row(i, deaths=d) for i, d in enumerate([12, 9, 15, 8, 20])]
    leak = feeding(rows, 4, TH)
    assert leak is not None and leak.key == "feeding"
    assert leak.value == 12.8 and leak.threshold == 8.0
    assert leak.direction == "lower_is_better" and leak.family == "deaths"
    assert leak.example_matches == [4, 2, 0]  # 20,15,12 — худшие первыми
    assert leak.sample_size == 5


def test_feeding_silent_when_clean():
    rows = [_row(i, deaths=4) for i in range(5)]
    assert feeding(rows, 4, TH) is None


def test_time_dead_uses_fraction_of_duration():
    # 300с мёртв из 1800 = 0.1667 > 0.13
    rows = [Row(mid, 1800, True, 4,
                PlayerMatch(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                            kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0,
                            last_hits=0, life_state_dead=300)) for mid in range(5)]
    leak = time_dead(rows, 4, TH)
    assert leak is not None and leak.metric == "time_dead_frac"
    assert round(leak.value, 3) == 0.167 and leak.direction == "lower_is_better"


def test_repeat_victim_fires_on_per_game_mean():
    # один герой убивает 3/игру -> mean 3.0 > порог 2.5 -> лик (scale-invariant, не зависит от длины серии)
    rows = [_row(i, killed_by={"npc_dota_hero_lion": 3}) for i in range(5)]
    leak = repeat_victim(rows, 4, TH)
    assert leak is not None and leak.key == "repeat_victim" and leak.value == 3.0


def test_repeat_victim_silent_when_spread_out():
    # 2 смерти от худшего героя за игру -> mean 2.0 <= 2.5 -> молчит; крипы/вышки не в счёт
    rows = [_row(i, killed_by={"npc_dota_hero_lion": 2, "npc_dota_creep_badguys_melee": 5}) for i in range(5)]
    assert repeat_victim(rows, 4, TH) is None
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_deaths.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать `_common.py`**

```python
from __future__ import annotations

from statistics import mean, median
from typing import Callable

from dota_coach.leaks.rows import Row
from dota_coach.models import Confidence, Leak


def mean_of(rows: list[Row], getter: Callable[[Row], float]) -> float:
    return float(mean(getter(r) for r in rows))


def median_pct(rows: list[Row], metric: str) -> float | None:
    vals = []
    for r in rows:
        b = r.me.benchmarks.get(metric)
        if isinstance(b, dict) and "pct" in b:
            vals.append(float(b["pct"]))
    return float(median(vals)) if vals else None


def make_leak(*, role: int, rows: list[Row], metric: str, value: float,
              threshold: float, direction: str, source: str, magnitude: str,
              worst_key: Callable[[Row], float], worst_reverse: bool) -> Leak:
    # Идентичность (key/title/phase/family) НЕ ставится здесь — её проставит обёртка
    # @detector из метаданных декоратора. make_leak отвечает только за числа.
    worst = sorted(rows, key=worst_key, reverse=worst_reverse)[:3]
    return Leak(
        key="", title="", magnitude=magnitude,
        example_matches=[r.match_id for r in worst], confidence=Confidence.HIGH,
        metric=metric, value=value, threshold=threshold, direction=direction,
        role=role, source=source, sample_size=len(rows),
    )
```

- [ ] **Step 4: Реализовать `deaths.py`**

```python
from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, mean_of
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="feeding", title="Слишком много смертей", roles=(1, 2, 3, 4, 5),
          requires=("deaths",), impact=1.0, phase="deaths", family="deaths")
def feeding(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("deaths_per_game", role)
    avg = mean_of(rows, lambda r: r.me.deaths)
    if thr is None or avg <= thr:
        return None
    return make_leak(role=role, rows=rows, metric="deaths_per_game", value=round(avg, 1),
                     threshold=thr, direction="lower_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} смертей за игру (порог {thr:.0f})",
                     worst_key=lambda r: r.me.deaths, worst_reverse=True)


@detector(key="time_dead", title="Долго лежит мёртвым", roles=(1, 2, 3, 4, 5),
          requires=("life_state_dead",), impact=0.7, phase="deaths", family="deaths")
def time_dead(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("time_dead_frac", role)
    frac = mean_of(rows, lambda r: r.me.life_state_dead / r.duration if r.duration else 0.0)
    if thr is None or frac <= thr:
        return None
    return make_leak(role=role, rows=rows, metric="time_dead_frac", value=round(frac, 3),
                     threshold=thr, direction="lower_is_better", source="manual",
                     magnitude=f"в среднем {frac * 100:.0f}% игры мёртвым (порог {thr * 100:.0f}%)",
                     worst_key=lambda r: r.me.life_state_dead / (r.duration or 1), worst_reverse=True)


def _hero_max(r: Row) -> float:
    # killed_by содержит крипов/вышки/нейтралов — считаем только героев (npc_dota_hero_*)
    return float(max((v for k, v in r.me.killed_by.items() if k.startswith("npc_dota_hero_")),
                     default=0))


@detector(key="repeat_victim", title="Одна и та же жертва", roles=(1, 2, 3, 4, 5),
          requires=("killed_by",), impact=0.5, phase="deaths", family="deaths")
def repeat_victim(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("repeat_victim_kills", role)
    avg = mean_of(rows, _hero_max)
    if thr is None or avg <= thr:
        return None
    return make_leak(role=role, rows=rows, metric="repeat_victim_kills", value=round(avg, 1),
                     threshold=thr, direction="lower_is_better", source="manual",
                     magnitude=f"один герой убивает в среднем {avg:.1f} раз за игру",
                     worst_key=_hero_max, worst_reverse=True)
```

Note (решение по идентичности лика — единое для ВСЕХ семей, развилки нет): детектор и `make_leak` не задают `key/title/phase/family`. Их из метаданных `@detector` проставляет обёртка декоратора (Task 4, Step 3): она вызывает inner-функцию и штампует идентичность на возвращённый `Leak`. Поэтому во всех семьях (Tasks 5–9) `make_leak` вызывается одинаково — только с числами (`role/rows/metric/value/threshold/direction/source/magnitude/worst_key/worst_reverse`). Юнит-тесты импортируют декорированную функцию (обёртку), поэтому `leak.key`/`leak.family` в них проставлены. Никаких `_SPEC`-констант.

- [ ] **Step 5: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_deaths.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/leaks/detectors/_common.py src/dota_coach/leaks/detectors/deaths.py tests/test_leaks_detectors_deaths.py
git commit -m "feat(leaks): семья deaths (feeding/time_dead/repeat_victim) + общие помощники"
```

> **Решение об интерфейсе `@detector`/`make_leak` из Step 4 фиксируется здесь и переиспользуется в Tasks 6–9 без изменений.**

---

### Task 6: Семья `laning`

`farm_below_bracket` (bench), `cs_behind_at_10` (manual, `lh_t[10]`), `low_denies` (bench+manual), `lane_collapse` (manual, `lane_efficiency_pct`).

**Files:**
- Create: `src/dota_coach/leaks/detectors/laning.py`
- Test: `tests/test_leaks_detectors_laning.py`

**Interfaces:**
- Consumes: `_common.make_leak/mean_of/median_pct`, `Thresholds.manual/bench_floor`.
- Produces: регистрирует `farm_below_bracket`, `cs_behind_at_10`, `low_denies`, `lane_collapse` (роли `(1,2,3)`).

- [ ] **Step 1: Тесты**

```python
# tests/test_leaks_detectors_laning.py
from dota_coach.leaks.detectors.laning import (
    cs_behind_at_10, farm_below_bracket, lane_collapse, low_denies)
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, role=1, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=role, me=PlayerMatch(**base))


def test_farm_below_bracket_fires_on_low_median_percentile():
    rows = [_row(i, benchmarks={"gold_per_min": {"raw": 400, "pct": 0.19}}) for i in range(5)]
    leak = farm_below_bracket(rows, 1, TH)
    assert leak is not None and leak.metric == "gpm_pct"
    assert leak.value == 0.19 and leak.threshold == 0.4
    assert leak.direction == "higher_is_better" and leak.source == "bench"


def test_farm_below_bracket_silent_when_percentile_ok():
    rows = [_row(i, benchmarks={"gold_per_min": {"raw": 600, "pct": 0.7}}) for i in range(5)]
    assert farm_below_bracket(rows, 1, TH) is None


def test_cs_behind_at_10_reads_minute_10():
    rows = [_row(i, lh_t=[0, 5, 10, 14, 18, 22, 26, 30, 33, 36, 30]) for i in range(5)]  # lh_t[10]=30 < 45
    leak = cs_behind_at_10(rows, 1, TH)
    assert leak is not None and leak.metric == "cs_at_10" and leak.value == 30.0


def test_cs_behind_short_series_skips_when_no_minute_10():
    rows = [_row(i, lh_t=[0, 5, 10]) for i in range(5)]  # нет 10-й минуты
    assert cs_behind_at_10(rows, 1, TH) is None


def test_lane_collapse_uses_efficiency():
    rows = [_row(i, lane_efficiency_pct=30) for i in range(5)]  # 30 < 40
    leak = lane_collapse(rows, 3, TH)
    assert leak is not None and leak.metric == "lane_efficiency_pct"


def test_low_denies_fires_below_manual():
    rows = [_row(i, denies=3) for i in range(5)]  # 3 < 8
    assert low_denies(rows, 1, TH) is not None
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_laning.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать laning.py**

```python
from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, mean_of, median_pct
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="farm_below_bracket", title="Фарм ниже бракета", roles=(1, 2, 3, 4, 5),
          requires=("benchmarks",), impact=0.9, phase="laning", family="economy")
def farm_below_bracket(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    med = median_pct(rows, "gold_per_min")
    floor = th.bench_floor()
    if med is None or med >= floor:
        return None
    return make_leak(role=role, rows=rows, metric="gpm_pct", value=round(med, 3),
                     threshold=floor, direction="higher_is_better", source="bench",
                     magnitude=f"медиана GPM в p{round(med * 100)}",
                     worst_key=lambda r: r.me.benchmarks.get("gold_per_min", {}).get("pct", 1.0),
                     worst_reverse=False)


@detector(key="cs_behind_at_10", title="Мало ластхитов к 10 мин", roles=(1, 2, 3),
          requires=("lh_t",), impact=0.7, phase="laning", family="laning")
def cs_behind_at_10(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("cs_at_10", role)
    usable = [r for r in rows if len(r.me.lh_t) > 10]
    if thr is None or len(usable) < 5:
        return None
    avg = mean_of(usable, lambda r: r.me.lh_t[10])
    if avg >= thr:
        return None
    return make_leak(role=role, rows=usable, metric="cs_at_10", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.0f} ластхитов к 10 мин (планка {thr:.0f})",
                     worst_key=lambda r: r.me.lh_t[10], worst_reverse=False)


@detector(key="low_denies", title="Мало денаев", roles=(1, 2, 3),
          requires=("denies",), impact=0.4, phase="laning", family="laning")
def low_denies(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("denies_per_game", role)
    avg = mean_of(rows, lambda r: r.me.denies)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="denies_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} денаев за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.denies, worst_reverse=False)


@detector(key="lane_collapse", title="Проваленный лейн", roles=(1, 2, 3),
          requires=("lane_efficiency_pct",), impact=0.8, phase="laning", family="laning")
def lane_collapse(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("lane_efficiency_pct", role)
    avg = mean_of(rows, lambda r: r.me.lane_efficiency_pct)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="lane_efficiency_pct", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"эффективность лейна {avg:.0f}% (планка {thr:.0f}%)",
                     worst_key=lambda r: r.me.lane_efficiency_pct, worst_reverse=False)
```

Note: `make_leak` вызывается только с числами (без `spec`, без `key/title/phase/family`) — идентичность штампует обёртка `@detector` (см. Task 4/Task 5). Так во всех семьях.

Note про роли `farm_below_bracket`: спека в каталоге даёт `(1,2,3)`, но критерий приёмки №2 требует срабатывания на **pos4** (главная мотивация редизайна — скрытая дыра GPM pos4, перцентиль 0.19). GPM-перцентиль считается по герою, т.е. осмыслен и для саппортов → роли `(1,2,3,4,5)`. Внутреннее противоречие спеки решено в пользу приёмки.

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_laning.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/leaks/detectors/laning.py tests/test_leaks_detectors_laning.py
git commit -m "feat(leaks): семья laning (farm/cs@10/denies/lane_collapse)"
```

---

### Task 7: Семья `economy`

`idle_gold_gaps` (manual, `gold_t`-плато), `low_neutral_farm` (manual, `neutral_kills`), `no_stacks` (manual, `camps_stacked`, роли 4,5), `missing_runes` (manual, `rune_pickups`, роль 2), `level_behind` (bench, `xp_per_min`).

**Files:**
- Create: `src/dota_coach/leaks/detectors/economy.py`
- Test: `tests/test_leaks_detectors_economy.py`

**Interfaces:**
- Produces: `idle_gold_gaps`, `low_neutral_farm`, `no_stacks`, `missing_runes`, `level_behind`.
- Хелпер `_idle_fraction(gold_t) -> float` — доля соседних минутных интервалов с приростом золота ниже 200 (простой). Живёт в `economy.py`.

- [ ] **Step 1: Тесты**

```python
# tests/test_leaks_detectors_economy.py
from dota_coach.leaks.detectors.economy import (
    idle_gold_gaps, level_behind, low_neutral_farm, missing_runes, no_stacks)
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, role=1, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=role, me=PlayerMatch(**base))


def test_low_neutral_farm_fires():
    rows = [_row(i, neutral_kills=5) for i in range(5)]  # 5 < 20 (pos1)
    assert low_neutral_farm(rows, 1, TH) is not None


def test_no_stacks_only_supports():
    rows = [_row(i, role=5, camps_stacked=0) for i in range(5)]  # 0 < 2
    assert no_stacks(rows, 5, TH) is not None


def test_missing_runes_pos2():
    rows = [_row(i, role=2, rune_pickups=1) for i in range(5)]  # 1 < 3
    assert missing_runes(rows, 2, TH) is not None


def test_level_behind_uses_bench_percentile():
    rows = [_row(i, benchmarks={"xp_per_min": {"raw": 300, "pct": 0.2}}) for i in range(5)]
    leak = level_behind(rows, 1, TH)
    assert leak is not None and leak.metric == "xpm_pct" and leak.source == "bench"


def test_idle_gold_gaps_flags_flat_curve():
    # прирост золота почти нулевой между минутами -> простой
    flat = list(range(0, 300, 30)) + [270] * 15  # длинное плато в конце
    rows = [_row(i, gold_t=flat) for i in range(5)]
    assert idle_gold_gaps(rows, 1, TH) is not None
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_economy.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать economy.py**

```python
from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, mean_of, median_pct
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak

_IDLE_GOLD_STEP = 200  # прирост золота за минуту ниже этого = "простой"
_IDLE_FRAC_THRESHOLD = 0.35  # доля простойных минут, выше которой — лик


def _idle_fraction(gold_t: list[int]) -> float:
    if len(gold_t) < 2:
        return 0.0
    idle = sum(1 for a, b in zip(gold_t, gold_t[1:]) if (b - a) < _IDLE_GOLD_STEP)
    return idle / (len(gold_t) - 1)


@detector(key="idle_gold_gaps", title="Простой — золото не растёт", roles=(1, 2, 3),
          requires=("gold_t",), impact=0.6, phase="economy", family="economy")
def idle_gold_gaps(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    avg = mean_of(rows, lambda r: _idle_fraction(r.me.gold_t))
    if avg <= _IDLE_FRAC_THRESHOLD:
        return None
    return make_leak(role=role, rows=rows, metric="idle_gold_frac", value=round(avg, 3),
                     threshold=_IDLE_FRAC_THRESHOLD, direction="lower_is_better", source="manual",
                     magnitude=f"{avg * 100:.0f}% минут без прироста золота",
                     worst_key=lambda r: _idle_fraction(r.me.gold_t), worst_reverse=True)


@detector(key="low_neutral_farm", title="Не фармит лес", roles=(1, 2, 3),
          requires=("neutral_kills",), impact=0.5, phase="economy", family="economy")
def low_neutral_farm(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("neutral_kills_per_game", role)
    avg = mean_of(rows, lambda r: r.me.neutral_kills)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="neutral_kills_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.0f} лесных крипов за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.neutral_kills, worst_reverse=False)


@detector(key="no_stacks", title="Не стакает лес", roles=(4, 5),
          requires=("camps_stacked",), impact=0.4, phase="economy", family="economy")
def no_stacks(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("camps_stacked_per_game", role)
    avg = mean_of(rows, lambda r: r.me.camps_stacked)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="camps_stacked_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} стака за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.camps_stacked, worst_reverse=False)


@detector(key="missing_runes", title="Не берёт руны", roles=(2,),
          requires=("rune_pickups",), impact=0.4, phase="economy", family="economy")
def missing_runes(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("rune_pickups_per_game", role)
    avg = mean_of(rows, lambda r: r.me.rune_pickups)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="rune_pickups_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} руны за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.rune_pickups, worst_reverse=False)


@detector(key="level_behind", title="Отстаёт по опыту", roles=(1, 2, 3, 4, 5),
          requires=("benchmarks",), impact=0.6, phase="economy", family="economy")
def level_behind(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    med = median_pct(rows, "xp_per_min")
    floor = th.bench_floor()
    if med is None or med >= floor:
        return None
    return make_leak(role=role, rows=rows, metric="xpm_pct", value=round(med, 3),
                     threshold=floor, direction="higher_is_better", source="bench",
                     magnitude=f"медиана XPM в p{round(med * 100)}",
                     worst_key=lambda r: r.me.benchmarks.get("xp_per_min", {}).get("pct", 1.0),
                     worst_reverse=False)
```

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_economy.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/leaks/detectors/economy.py tests/test_leaks_detectors_economy.py
git commit -m "feat(leaks): семья economy (idle/neutral/stacks/runes/level)"
```

---

### Task 8: Семья `vision`

`low_obs` (был `low_warding`; manual, `obs_placed`, роли 4,5), `low_sentries` (manual, `sen_placed`), `wards_die_fast` (manual, средняя жизнь обса из `obs_left_log`/`obs_log`), `low_dewarding` (manual, `observer_kills`+`sentry_uses`).

**Files:**
- Create: `src/dota_coach/leaks/detectors/vision.py`
- Test: `tests/test_leaks_detectors_vision.py`

**Interfaces:**
- Produces: `low_obs`, `low_sentries`, `wards_die_fast`, `low_dewarding` (роли `(4,5)`).
- Хелпер `_avg_ward_lifetime(obs_log, obs_left_log) -> float | None` в `vision.py`: по парам «поставлен/снят» считает среднюю жизнь варда; `None` если данных нет.

- [ ] **Step 1: Тесты**

```python
# tests/test_leaks_detectors_vision.py
from dota_coach.leaks.detectors.vision import (
    low_dewarding, low_obs, low_sentries, wards_die_fast)
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, role=5, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=role, me=PlayerMatch(**base))


def test_low_obs_fires_pos5():
    rows = [_row(i, role=5, obs_placed=2) for i in range(5)]  # 2 < 6
    leak = low_obs(rows, 5, TH)
    assert leak is not None and leak.key == "low_obs" and leak.family == "vision"


def test_low_obs_silent_pos5_ok():
    rows = [_row(i, role=5, obs_placed=8) for i in range(5)]
    assert low_obs(rows, 5, TH) is None


def test_low_sentries_fires():
    rows = [_row(i, role=5, sen_placed=1) for i in range(5)]  # 1 < 4
    assert low_sentries(rows, 5, TH) is not None


def test_low_dewarding_counts_dewards():
    rows = [_row(i, role=5, observer_kills=0, sentry_uses=0) for i in range(5)]
    assert low_dewarding(rows, 5, TH) is not None


def test_wards_die_fast_when_short_lifetime():
    # поставлен на 60, снят на 120 -> жизнь 60с < 180
    log = [{"time": 60, "ehandle": 1}]
    left = [{"time": 120, "ehandle": 1}]
    rows = [_row(i, role=5, obs_log=log, obs_left_log=left) for i in range(5)]
    assert wards_die_fast(rows, 5, TH) is not None
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_vision.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать vision.py**

```python
from __future__ import annotations

from statistics import mean

from dota_coach.leaks.detectors._common import make_leak, mean_of
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="low_obs", title="Мало обсов", roles=(4, 5),
          requires=("obs_placed",), impact=0.8, phase="vision", family="vision")
def low_obs(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("obs_per_game", role)
    avg = mean_of(rows, lambda r: r.me.obs_placed)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="obs_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} обсов за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.obs_placed, worst_reverse=False)


@detector(key="low_sentries", title="Мало сентрей", roles=(4, 5),
          requires=("sen_placed",), impact=0.5, phase="vision", family="vision")
def low_sentries(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("sen_per_game", role)
    avg = mean_of(rows, lambda r: r.me.sen_placed)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="sen_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} сентрей за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.sen_placed, worst_reverse=False)


@detector(key="low_dewarding", title="Не снимает вражеский вижн", roles=(4, 5),
          requires=("observer_kills",), impact=0.5, phase="vision", family="vision")
def low_dewarding(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    # dewarding = снятые вражеские обсы (observer_kills). sentry_uses убран из requires:
    # был мёртвым условием (не влиял на фильтр) и не входит в метрику — считаем результат честно.
    thr = th.manual("dewards_per_game", role)
    avg = mean_of(rows, lambda r: float(r.me.observer_kills))
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="dewards_per_game", value=round(avg, 1),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"в среднем {avg:.1f} снятых вардов за игру (планка {thr:.0f})",
                     worst_key=lambda r: r.me.observer_kills, worst_reverse=False)


def _avg_ward_lifetime(obs_log: list[dict], obs_left_log: list[dict]) -> float | None:
    if not obs_log or not obs_left_log:
        return None
    left_by_handle = {e.get("ehandle"): e.get("time") for e in obs_left_log if "ehandle" in e}
    spans = []
    for e in obs_log:
        h, placed = e.get("ehandle"), e.get("time")
        removed = left_by_handle.get(h)
        if placed is not None and removed is not None and removed > placed:
            spans.append(removed - placed)
    return float(mean(spans)) if spans else None


@detector(key="wards_die_fast", title="Варды живут мало", roles=(4, 5),
          requires=("obs_log", "obs_left_log"), impact=0.5, phase="vision", family="vision")
def wards_die_fast(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("obs_lifetime_s", role)
    usable = [(r, _avg_ward_lifetime(r.me.obs_log, r.me.obs_left_log)) for r in rows]
    usable = [(r, v) for r, v in usable if v is not None]
    if thr is None or len(usable) < 5:
        return None
    avg = float(mean(v for _, v in usable))
    if avg >= thr:
        return None
    kept = [r for r, _ in usable]
    life = {r.match_id: v for r, v in usable}
    return make_leak(role=role, rows=kept, metric="obs_lifetime_s", value=round(avg, 0),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"варды живут в среднем {avg:.0f}с (планка {thr:.0f}с)",
                     worst_key=lambda r: life[r.match_id], worst_reverse=False)
```

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_vision.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/leaks/detectors/vision.py tests/test_leaks_detectors_vision.py
git commit -m "feat(leaks): семья vision (obs/sentries/dewarding/ward-lifetime), low_warding -> low_obs"
```

---

### Task 9: Семьи `fights` и `objectives`

`low_fight_participation` (manual, `teamfight_participation`, роли 3,4,5), `present_no_damage` (bench, `hero_damage`, роли 1,2,3), `low_tower_damage` (bench, `tower_damage`, роли 1,2,3).

**Files:**
- Create: `src/dota_coach/leaks/detectors/fights.py`
- Create: `src/dota_coach/leaks/detectors/objectives.py`
- Test: `tests/test_leaks_detectors_fights.py`

**Interfaces:**
- Produces: `low_fight_participation`, `present_no_damage`, `low_tower_damage`.

- [ ] **Step 1: Тесты**

```python
# tests/test_leaks_detectors_fights.py
from dota_coach.leaks.detectors.fights import low_fight_participation, present_no_damage
from dota_coach.leaks.detectors.objectives import low_tower_damage
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import PlayerMatch

TH = Thresholds()


def _row(mid, role=3, **kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return Row(match_id=mid, duration=1800, parsed=True, role=role, me=PlayerMatch(**base))


def test_low_fight_participation_fires():
    rows = [_row(i, role=4, teamfight_participation=0.35) for i in range(5)]  # 0.35 < 0.55
    leak = low_fight_participation(rows, 4, TH)
    assert leak is not None and leak.metric == "teamfight_participation"


def test_present_no_damage_uses_bench():
    rows = [_row(i, role=2, benchmarks={"hero_damage_per_min": {"raw": 100, "pct": 0.15}})
            for i in range(5)]
    leak = present_no_damage(rows, 2, TH)
    assert leak is not None and leak.source == "bench"


def test_low_tower_damage_uses_bench():
    rows = [_row(i, role=1, benchmarks={"tower_damage": {"raw": 500, "pct": 0.1}}) for i in range(5)]
    leak = low_tower_damage(rows, 1, TH)
    assert leak is not None and leak.metric == "tower_damage_pct" and leak.family == "objectives"
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_fights.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать fights.py**

```python
from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, mean_of, median_pct
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="low_fight_participation", title="Не участвует в драках", roles=(3, 4, 5),
          requires=("teamfight_participation",), impact=0.7, phase="fights", family="fights")
def low_fight_participation(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    thr = th.manual("teamfight_participation", role)
    avg = mean_of(rows, lambda r: r.me.teamfight_participation)
    if thr is None or avg >= thr:
        return None
    return make_leak(role=role, rows=rows, metric="teamfight_participation", value=round(avg, 2),
                     threshold=thr, direction="higher_is_better", source="manual",
                     magnitude=f"участие в драках {avg * 100:.0f}% (планка {thr * 100:.0f}%)",
                     worst_key=lambda r: r.me.teamfight_participation, worst_reverse=False)


@detector(key="present_no_damage", title="В драке, но без урона", roles=(1, 2, 3),
          requires=("benchmarks",), impact=0.6, phase="fights", family="fights")
def present_no_damage(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    med = median_pct(rows, "hero_damage_per_min")
    floor = th.bench_floor()
    if med is None or med >= floor:
        return None
    return make_leak(role=role, rows=rows, metric="hero_dmg_pct", value=round(med, 3),
                     threshold=floor, direction="higher_is_better", source="bench",
                     magnitude=f"медиана урона по героям в p{round(med * 100)}",
                     worst_key=lambda r: r.me.benchmarks.get("hero_damage_per_min", {}).get("pct", 1.0),
                     worst_reverse=False)
```

- [ ] **Step 4: Реализовать objectives.py**

```python
from __future__ import annotations

from dota_coach.leaks.detectors._common import make_leak, median_pct
from dota_coach.leaks.registry import detector
from dota_coach.leaks.rows import Row
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak


@detector(key="low_tower_damage", title="Мало урона по строениям", roles=(1, 2, 3),
          requires=("benchmarks",), impact=0.6, phase="objectives", family="objectives")
def low_tower_damage(rows: list[Row], role: int, th: Thresholds) -> Leak | None:
    med = median_pct(rows, "tower_damage")
    floor = th.bench_floor()
    if med is None or med >= floor:
        return None
    return make_leak(role=role, rows=rows, metric="tower_damage_pct", value=round(med, 3),
                     threshold=floor, direction="higher_is_better", source="bench",
                     magnitude=f"медиана урона по вышкам в p{round(med * 100)}",
                     worst_key=lambda r: r.me.benchmarks.get("tower_damage", {}).get("pct", 1.0),
                     worst_reverse=False)
```

- [ ] **Step 5: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_detectors_fights.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/leaks/detectors/fights.py src/dota_coach/leaks/detectors/objectives.py tests/test_leaks_detectors_fights.py
git commit -m "feat(leaks): семьи fights и objectives"
```

---

### Task 10: `severity.py` + флип фасада `detect_leaks` на реестр

Собираем всё: `severity.rank` ранжирует, фасад строит rows → сегментирует → прогоняет применимые детекторы с requires-фильтром → severity → возвращает упорядоченный список. `detectors/__init__.py` импортирует все модули ради регистрации.

**Files:**
- Create: `src/dota_coach/leaks/severity.py`
- Modify: `src/dota_coach/leaks/detectors/__init__.py` (импорт всех семей)
- Modify: `src/dota_coach/leaks/__init__.py` (новый фасад)
- Test: `tests/test_leaks_severity.py`, `tests/test_leaks.py` (перезаписать под ролевую модель)

**Interfaces:**
- Produces:
  - `score(leak: Leak) -> float` — `normalized_excess * impact * sample_confidence`.
  - `rank(leaks: list[Leak]) -> tuple[Leak | None, list[Leak]]` — `(focus, also_visible)`; в `also_visible` не более одного лика на `family`; тай-брейк по `key` алфавитно.
  - `detect_leaks(matches, account_id) -> list[Leak]` — упорядоченный по severity список (фокус первым). Роль с < 5 играми пропускается; детектор с < 5 матчей после requires — пропускается.
- Consumes: `registry.applicable/filter_rows/DETECTORS`, `severity`, `detectors` (регистрация).

Note про `impact`: `score` берёт `impact` из зарегистрированного `DetectorSpec` по `leak.key` (строим `{spec.key: spec.impact}` из `DETECTORS`). `sample_confidence` = `min(1.0, (sample_size - 4) / 8)` для `sample_size >= 5`, иначе 0. `normalized_excess`: для bench-ликов (`source == "bench"`) = `threshold - value` (перцентильное пространство); для остальных = `min(1.0, abs(value - threshold) / abs(threshold))`.

- [ ] **Step 1: Тесты severity**

```python
# tests/test_leaks_severity.py
from dota_coach.leaks.severity import rank, score
from dota_coach.models import Leak


def _leak(key, family, value, threshold, direction, source="manual", sample=12, severity=0.0):
    return Leak(key=key, title=key, magnitude="", metric=key, value=value, threshold=threshold,
                direction=direction, source=source, sample_size=sample, family=family, severity=severity)


def test_score_bench_uses_percentile_gap():
    s = score(_leak("farm_below_bracket", "economy", value=0.2, threshold=0.4, direction="higher_is_better", source="bench"))
    assert s > 0


def test_score_zero_below_min_sample():
    assert score(_leak("feeding", "deaths", 20, 8, "lower_is_better", sample=4)) == 0.0


def test_rank_picks_highest_severity_and_dedups_family():
    a = _leak("feeding", "deaths", 20, 8, "lower_is_better", severity=0.9)
    b = _leak("time_dead", "deaths", 0.3, 0.13, "lower_is_better", severity=0.6)  # та же семья
    c = _leak("low_obs", "vision", 1, 6, "higher_is_better", severity=0.5)
    focus, also = rank([b, a, c])
    assert focus.key == "feeding"
    also_keys = {l.key for l in also}
    assert "time_dead" not in also_keys      # семья deaths уже представлена фокусом
    assert "low_obs" in also_keys


def test_rank_deterministic_tiebreak_by_key():
    a = _leak("aaa", "f1", 10, 5, "lower_is_better", severity=0.5)
    b = _leak("bbb", "f2", 10, 5, "lower_is_better", severity=0.5)
    focus1, _ = rank([a, b])
    focus2, _ = rank([b, a])
    assert focus1.key == focus2.key == "aaa"
```

- [ ] **Step 2: Тесты нового фасада (перезапись test_leaks.py)**

```python
# tests/test_leaks.py  (ПОЛНОСТЬЮ заменить старое содержимое)
from dota_coach.leaks import detect_leaks
from dota_coach.models import Match, PlayerMatch


def _me(**kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return PlayerMatch(**base)


def _match(mid, me):
    return Match(match_id=mid, duration=1800, radiant_win=True, players=[me], parsed=True)


def test_role_below_five_games_not_analyzed():
    # 3 игры на pos5 -> роль не разбирается -> ликов нет
    matches = [_match(i, _me(position_est=5, deaths=20, obs_placed=0)) for i in range(3)]
    assert detect_leaks(matches, 7) == []


def test_pos3_zero_wards_is_not_a_leak():
    # 10 оффлейн-игр с 0 обсов: low_obs не применим к pos3 -> не срабатывает
    matches = [_match(i, _me(position_est=3, obs_placed=0, deaths=2,
                             benchmarks={"gold_per_min": {"raw": 500, "pct": 0.7}}))
               for i in range(10)]
    keys = {l.key for l in detect_leaks(matches, 7)}
    assert "low_obs" not in keys


def test_pos4_low_farm_surfaces():
    # pos4, GPM-перцентиль 0.19 -> farm_below_bracket срабатывает
    matches = [_match(i, _me(position_est=4, deaths=2, obs_placed=8,
                             benchmarks={"gold_per_min": {"raw": 300, "pct": 0.19}}))
               for i in range(6)]
    keys = {l.key for l in detect_leaks(matches, 7)}
    assert "farm_below_bracket" in keys


def test_leaks_are_ordered_by_severity_and_deterministic():
    matches = [_match(i, _me(position_est=4, deaths=18, obs_placed=1,
                             benchmarks={"gold_per_min": {"raw": 300, "pct": 0.19}}))
               for i in range(8)]
    a = detect_leaks(matches, 7)
    b = detect_leaks(matches, 7)
    assert [l.key for l in a] == [l.key for l in b]          # детерминизм
    assert a and a[0].severity >= a[-1].severity             # фокус первым
    assert all(l.role == 4 for l in a)                        # роль проставлена
```

- [ ] **Step 3: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_leaks_severity.py tests/test_leaks.py -v`
Expected: FAIL (нет severity; фасад ещё старый).

- [ ] **Step 4: Реализовать severity.py**

```python
from __future__ import annotations

from dota_coach.models import Leak


def _impacts() -> dict[str, float]:
    from dota_coach.leaks.registry import DETECTORS
    return {d.key: d.impact for d in DETECTORS}


def _normalized_excess(leak: Leak) -> float:
    if leak.source == "bench":
        return max(0.0, leak.threshold - leak.value)         # перцентильный зазор
    if not leak.threshold:
        return min(1.0, abs(leak.value))
    return min(1.0, abs(leak.value - leak.threshold) / abs(leak.threshold))


def _sample_confidence(sample_size: int) -> float:
    if sample_size < 5:
        return 0.0
    return min(1.0, (sample_size - 4) / 8.0)


def score(leak: Leak) -> float:
    impact = _impacts().get(leak.key, 0.5)
    return _normalized_excess(leak) * impact * _sample_confidence(leak.sample_size)


def rank(leaks: list[Leak]) -> tuple[Leak | None, list[Leak]]:
    for l in leaks:
        l.severity = score(l)
    ordered = sorted(leaks, key=lambda l: (-l.severity, l.key))
    ordered = [l for l in ordered if l.severity > 0]
    if not ordered:
        return None, []
    focus = ordered[0]
    also: list[Leak] = []
    seen_families = {focus.family}
    for l in ordered[1:]:
        if l.family in seen_families:
            continue
        seen_families.add(l.family)
        also.append(l)
    return focus, also
```

- [ ] **Step 5: Реализовать `detectors/__init__.py` (регистрация)**

```python
# импорт ради side-effect регистрации детекторов в DETECTORS
from dota_coach.leaks.detectors import (  # noqa: F401
    deaths, economy, fights, laning, objectives, vision,
)
```

- [ ] **Step 6: Переписать фасад `leaks/__init__.py`**

```python
from __future__ import annotations

from dota_coach.leaks import detectors as _detectors  # noqa: F401  (регистрация)
from dota_coach.leaks.registry import applicable, filter_rows
from dota_coach.leaks.rows import build_rows
from dota_coach.leaks.roles import segment_by_role
from dota_coach.leaks.severity import rank
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak, Match

_MIN_GAMES_PER_ROLE = 5
_MIN_SAMPLE_PER_DETECTOR = 5


def detect_leaks(matches: list[Match], account_id: int | None) -> list[Leak]:
    rows = build_rows(matches, account_id)
    th = Thresholds()
    found: list[Leak] = []
    for role, role_rows in segment_by_role(rows).items():
        if len(role_rows) < _MIN_GAMES_PER_ROLE:
            continue
        for spec in applicable(role):
            usable = filter_rows(role_rows, spec.requires)
            if len(usable) < _MIN_SAMPLE_PER_DETECTOR:
                continue
            leak = spec.fn(usable, role, th)
            if leak is not None:
                leak.considered = len(role_rows)   # M: матчей в роли до requires (строка покрытия)
                found.append(leak)
    focus, also = rank(found)
    if focus is None:
        return []
    # порядок: фокус, затем «тоже видно», затем прочие члены семей (severity desc)
    ordered = [focus, *also]
    rest = sorted((l for l in found if l is not focus and l not in also),
                  key=lambda l: (-l.severity, l.key))
    return [*ordered, *rest]
```

- [ ] **Step 7: Прогнать целевые + весь пакет**

Run:
```bash
PYTHONPATH=src python -m pytest tests/test_leaks_severity.py tests/test_leaks.py -v
PYTHONPATH=src python -m pytest -q
```
Expected: целевые PASS. Общий прогон ПОКАЖЕТ красные ровно там, где фикстуры строят матчи без ролевого сигнала (после флипа роль=None → пустой результат): `test_coach_orchestrator.py` и `test_cli.py::test_coach_dry_run_prints_prompt_without_llm` — обе мигрируются в Task 11. Тесты, завязанные на ключ `low_warding`, тоже правятся в Task 11. Между Task 2 и Task 10 они зелёные (поведение не менялось); краснеют строго на флипе — это ожидаемо, а не регресс.

- [ ] **Step 8: Commit**

```bash
git add src/dota_coach/leaks/severity.py src/dota_coach/leaks/__init__.py src/dota_coach/leaks/detectors/__init__.py tests/test_leaks_severity.py tests/test_leaks.py
git commit -m "feat(leaks): severity-ранжирование + флип фасада на ролевой реестр"
```

---

### Task 11: Интеграция с `coach/` (фокус по severity, роль/source в промпте, история)

**Files:**
- Modify: `src/dota_coach/coach/coach.py:14-29` (`_FOCUS_PRIORITY`, `_select_focus`)
- Modify: `src/dota_coach/coach/prompt.py:22-53`
- Modify: `src/dota_coach/coach/history.py`
- Modify: `src/dota_coach/coach/brief.py` (schema_version + leaks_snapshot)
- Test: `tests/test_coach_orchestrator.py`, `tests/test_coach_prompt.py`, `tests/test_coach_history.py`

**Interfaces:**
- Consumes: `detect_leaks` теперь возвращает ранжированный список (фокус первым).
- Produces:
  - `_select_focus(leaks) -> Leak | None` = `leaks[0] if leaks else None` (порядок уже задан severity).
  - `CoachBrief.schema_version: int = 2`, `CoachBrief.leaks_snapshot: list[dict]` (key, metric, value, direction, role) — сериализуется/десериализуется.
  - История при чтении мапит `focus_leak_key == "low_warding"` → `"low_obs"`.

- [ ] **Step 1: Тест — фокус берётся первым (severity), приоритетный список удалён**

```python
# tests/test_coach_orchestrator.py — заменить фикстуры на ролевые
import json

from dota_coach.coach.coach import run_coach
from dota_coach.coach.llm import FakeLLM
from dota_coach.models import Match, PlayerMatch

_CANNED = json.dumps({"focus_leak_key": "ignored", "headline": "h", "diagnosis": "d",
                      "why_it_costs": "w", "drills": [{"text": "t", "metric_ref": "obs_per_game"}]})


def _me(**kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return PlayerMatch(**base)


def _match(mid, me):
    return Match(match_id=mid, duration=1800, radiant_win=True, players=[me], parsed=True)


def test_focus_is_top_severity_leak(tmp_path):
    matches = [_match(i, _me(position_est=5, deaths=20, obs_placed=0,
                             benchmarks={"gold_per_min": {"raw": 500, "pct": 0.7}}))
               for i in range(8)]
    brief = run_coach(matches, 7, FakeLLM(_CANNED), cache_dir=tmp_path)
    assert brief.focus_leak_key in {"feeding", "low_obs"}   # оба лика pos5, фокус — сильнейший
    assert brief.focus_leak_key != ""


def test_no_leaks_skips_llm(tmp_path):
    # «Чистая» серия: ручные метрики выше порогов (denies=12>8), бенчи здоровые,
    # парс-зависимые счётчики отсутствуют (None -> requires исключает) -> ни один детектор не сработал.
    matches = [_match(i, _me(position_est=1, deaths=2, last_hits=300, denies=12,
                             benchmarks={"gold_per_min": {"raw": 700, "pct": 0.8}}))
               for i in range(6)]
    llm = FakeLLM(_CANNED)
    brief = run_coach(matches, 7, llm, cache_dir=tmp_path)
    assert brief.focus_leak_key == "" and llm.calls == []
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_coach_orchestrator.py -v`
Expected: FAIL.

- [ ] **Step 3: Упростить `_select_focus` в coach.py**

```python
# coach.py — удалить _FOCUS_PRIORITY и старый _select_focus; заменить на:
def _select_focus(leaks: list[Leak]) -> Leak | None:
    return leaks[0] if leaks else None
```

(Импорт `Leak` уже есть. `run_coach` ниже не меняется — он уже использует `_select_focus`, `focus.key/.metric/.value/.direction`, которые все присутствуют.)

- [ ] **Step 4: Тест — роль и source в промпте, анти-результатничество**

```python
# tests/test_coach_prompt.py (добавить)
from dota_coach.coach.prompt import build_coach_prompt
from dota_coach.models import Leak


def test_prompt_includes_role_and_source():
    leak = Leak(key="low_obs", title="Мало обсов", magnitude="1 обс", metric="obs_per_game",
                value=1.0, threshold=6.0, direction="higher_is_better", role=5, source="manual",
                sample_size=8, family="vision")
    msgs = build_coach_prompt([leak], None, "принципы", None, "low_obs")
    user = msgs[1]["content"]
    assert "pos5" in user or "роль" in user.lower()
    assert "разумной планк" in user.lower() or "manual" in user  # источник порога словами


def test_prompt_never_leaks_outcome():
    leak = Leak(key="feeding", title="Смерти", magnitude="20", metric="deaths_per_game",
                value=20.0, threshold=8.0, direction="lower_is_better", role=4, source="manual",
                sample_size=8, family="deaths")
    msgs = build_coach_prompt([leak], None, "p", None, "feeding")
    # системный промпт НАРОЧНО называет запрещённое («Побед/поражений тебе не дают»),
    # поэтому русские слова исхода проверяем только в user-сообщении (данные), а radiant_* — везде.
    user = msgs[1]["content"].lower()
    for banned in ("победа", "поражени", "выигр", "проигр"):
        assert banned not in user
    whole = "".join(m["content"] for m in msgs).lower()
    for banned in ("radiant_win", "radiant_score", "dire_score"):
        assert banned not in whole
```

- [ ] **Step 5: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_coach_prompt.py -v`
Expected: FAIL.

- [ ] **Step 6: Обновить prompt.py — роль + source + подтверждающие детали**

```python
# prompt.py — заменить _leaks_block и build_coach_prompt:
_SOURCE_RU = {
    "bench": "ниже, чем у ~60% игроков на этом герое (бенчмарк)",
    "manual": "ниже разумной планки для этой роли",
    "personal": "хуже твоего личного базлайна",
}


def _role_ru(role: int | None) -> str:
    return f"pos{role}" if role in (1, 2, 3, 4, 5) else "роль не определена"


def _leaks_block(leaks: list[Leak]) -> str:
    if not leaks:
        return "(ликов не обнаружено)"
    lines = []
    for leak in leaks:
        src = _SOURCE_RU.get(leak.source, leak.source)
        lines.append(
            f"- key={leak.key} | {leak.title} | {_role_ru(leak.role)} | metric={leak.metric} | "
            f"value={leak.value:.3f} | threshold={leak.threshold:.3f} | "
            f"direction={leak.direction} | оценка={src} | примеры={leak.example_matches}"
        )
    return "\n".join(lines)


def build_coach_prompt(leaks: list[Leak], progress: ProgressNote | None,
                       principles: str, prior: CoachBrief | None,
                       focus_key: str) -> list[dict]:
    focus = next((l for l in leaks if l.key == focus_key), None)
    family = focus.family if focus else ""
    confirming = [l for l in leaks if l.family == family and l.key != focus_key]
    conf_block = ("\n".join(f"- {l.title}: {l.metric}={l.value:.3f}" for l in confirming)
                  or "(нет)")
    role_line = _role_ru(focus.role) if focus else "роль не определена"
    user = (
        f"Роль разбора: {role_line}\n\n"
        f"Лики по серии (детерминированный детектор):\n{_leaks_block(leaks)}\n\n"
        f"Главный лик-фокус: {focus_key}\n"
        f"Подтверждающие детали той же семьи:\n{conf_block}\n\n"
        f"Прогресс с прошлого разбора:\n{_progress_block(progress, prior)}\n\n"
        f"Тренерские принципы по этому лику:\n{principles}\n\n"
        "Сформулируй разбор строго по фокус-лику в заданном JSON-формате."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
```

- [ ] **Step 7: Тест истории — schema_version, снимок, мап low_warding→low_obs**

```python
# tests/test_coach_history.py (добавить)
import json

from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.history import latest_brief, save_brief


def test_brief_roundtrip_keeps_snapshot_and_version(tmp_path):
    b = CoachBrief(focus_leak_key="low_obs", headline="h", diagnosis="d", why_it_costs="w",
                   leaks_snapshot=[{"key": "low_obs", "metric": "obs_per_game", "value": 1.0,
                                    "direction": "higher_is_better", "role": 5}])
    save_brief(7, b, cache_dir=tmp_path)
    got = latest_brief(7, cache_dir=tmp_path)
    assert got.schema_version == 2
    assert got.leaks_snapshot[0]["key"] == "low_obs"


def test_history_maps_legacy_low_warding_key(tmp_path):
    path = tmp_path / "coach_history_7.json"
    path.write_text(json.dumps([{"focus_leak_key": "low_warding", "headline": "h",
                                 "diagnosis": "", "why_it_costs": "", "drills": []}]),
                    encoding="utf-8")
    got = latest_brief(7, cache_dir=tmp_path)
    assert got.focus_leak_key == "low_obs"
    assert got.baseline_reset is True   # переименованный ключ -> сравнение прогресса с нуля
```

- [ ] **Step 8: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_coach_history.py -v`
Expected: FAIL.

- [ ] **Step 9: Расширить brief.py (schema_version + leaks_snapshot)**

```python
# brief.py — в @dataclass CoachBrief добавить:
    schema_version: int = 2
    leaks_snapshot: list[dict] = field(default_factory=list)
    baseline_reset: bool = False   # рантайм-флаг (НЕ сериализуется): прошлый фокус переименован

# в parse_brief(...) в конце конструктора CoachBrief добавить:
        schema_version=int(data.get("schema_version", 2)),
        leaks_snapshot=list(data.get("leaks_snapshot", [])),

# в brief_to_dict(...) добавить ключи:
        "schema_version": b.schema_version,
        "leaks_snapshot": b.leaks_snapshot,
```

- [ ] **Step 10: Мап legacy-ключа в history.py**

```python
# history.py — в load_history, после parse_brief каждого item, применить мап:
_LEGACY_KEY_MAP = {"low_warding": "low_obs"}


def load_history(account_id: int | None, cache_dir: Path = Path("cache")) -> list[CoachBrief]:
    path = _history_path(account_id, cache_dir)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    briefs = [parse_brief(item) for item in data]
    for b in briefs:
        if b.focus_leak_key in _LEGACY_KEY_MAP:
            b.focus_leak_key = _LEGACY_KEY_MAP[b.focus_leak_key]
            # старое значение считалось по всей серии без роли -> несравнимо с новым ролевым:
            b.baseline_reset = True
    return briefs
```

- [ ] **Step 11: run_coach — снимок ликов + сброс базлайна для переименованного low_obs**

```python
# coach.py — СРАЗУ ПОСЛЕ `progress = compare_focus(prior, leaks)` вставить сброс базлайна:
    if prior is not None and getattr(prior, "baseline_reset", False):
        from dota_coach.coach.progress import ProgressNote
        progress = ProgressNote("baseline_reset", "obs_per_game", None, None,
                                "Метрика вардов переведена на ролевую основу — сравнение начинается заново.")

# ... и ПЕРЕД save_brief(...) в обеих ветках проставить снимок всех ликов:
    brief.leaks_snapshot = [
        {"key": l.key, "metric": l.metric, "value": l.value,
         "direction": l.direction, "role": l.role}
        for l in leaks
    ]
```

Правка `run_coach` точечная: одна вставка после `compare_focus`, одна перед `save_brief`. `progress.py` не трогаем (спека: «работает без изменений») — сброс делаем в оркестраторе. Статус `baseline_reset != "no_history"`, поэтому нота показывается. В ветке «ликов не найдено» снимок пуст (корректно).

- [ ] **Step 12: Мигрировать оставшиеся безролевые фикстуры и прогнать всё**

Мигрировать `tests/test_cli.py::test_coach_dry_run_prints_prompt_without_llm`: в его `_p(...)` добавить ролевой сигнал `position_est=4`, иначе после флипа роль=None → лики пусты → dry-run печатает «не найдено» и `assert "Главный лик-фокус" in out` краснеет (deaths=11 → feeding сработает на pos4):

```python
# tests/test_cli.py — в _p(...) добавить position_est=4:
    def _p(deaths, obs, gpm):
        return PlayerMatch(
            account_id=111, player_slot=0, hero_id=1, is_radiant=True, position_est=4,
            kills=0, deaths=deaths, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
            gold_t=[], xp_t=[], lh_t=[], kills_log=[], purchase_log=[],
            obs_log=[{"time": 60}] * obs, sen_log=[],
            benchmarks={"gold_per_min": {"raw": 400, "pct": gpm}},
        )
```

Затем свип: `grep -rn "detect_leaks\|run_coach" tests/` → у каждой фикстуры проверить наличие `position_est`/`lane_role`; где нет — добавить (≥5 матчей). Общий прогон:

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS. `test_coach_report.py`/`test_coach_progress.py`, завязанные на старый ключ, обновить (`low_warding`→`low_obs`; магнитуды feeding/farm не менялись).

- [ ] **Step 13: Commit**

```bash
git add src/dota_coach/coach tests/test_coach_orchestrator.py tests/test_coach_prompt.py tests/test_coach_history.py
git commit -m "feat(coach): фокус по severity, роль+source в промпте, история v2 (снимок ликов, low_warding->low_obs)"
```

---

### Task 12: `principles.md` — секции под все ключи + отчёт «тоже видно» в рендере

**Files:**
- Modify: `src/dota_coach/coach/principles.md`
- Modify: `src/dota_coach/report.py:80-100` (`render_coach_html` — блок «тоже видно» + строка покрытия)
- Test: `tests/test_principles_coverage.py`, `tests/test_coach_report.py`

**Interfaces:**
- Consumes: `registry.DETECTORS` (набор ключей), `severity.rank` (also_visible).
- Produces: `render_coach_html(brief, leaks, progress=None, also_visible=None)` — новый необязательный аргумент со свёрнутым списком.

- [ ] **Step 1: Тест полноты принципов**

```python
# tests/test_principles_coverage.py
from dota_coach.coach.principles import principles_for
from dota_coach.leaks import detectors as _reg  # noqa: F401  (регистрация)
from dota_coach.leaks.registry import DETECTORS


def test_every_registered_key_has_a_principle_section():
    default = "Разбирай процесс и решения, а не исход. Дай конкретное проверяемое действие."
    missing = [d.key for d in DETECTORS if principles_for(d.key) == default]
    assert missing == [], f"нет секции принципов для ключей: {missing}"
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_principles_coverage.py -v`
Expected: FAIL (для новых ключей секций нет).

- [ ] **Step 3: Дописать `principles.md` — по секции `## <key>` на каждый зарегистрированный ключ**

Ключи (должны совпадать с `key=` в декораторах): `feeding`, `time_dead`, `repeat_victim`, `farm_below_bracket`, `cs_behind_at_10`, `low_denies`, `lane_collapse`, `idle_gold_gaps`, `low_neutral_farm`, `no_stacks`, `missing_runes`, `level_behind`, `low_obs`, `low_sentries`, `low_dewarding`, `wards_die_fast`, `low_fight_participation`, `present_no_damage`, `low_tower_damage`.

Существующую секцию `## low_warding` переименовать в `## low_obs`. Каждая секция — 2–4 строки: что за лик, почему топит, конкретное проверяемое действие (не «исход»). Пример новой секции:

```markdown
## time_dead
Мёртвый герой не фармит, не давит и не участвует — это чистый простой. Считай
не только число смертей, но и цену каждой: длинный респ на поздней стадии стоит
дороже. Действие: перед рискованным заходом прикинь таймер респа и что он отдаёт.

## no_stacks
Стак лагеря — бесплатное золото и опыт для кора без потери твоего темпа. На
пути между вардами и рунами стакай ближайший лагерь на :53. Действие: держи в
голове один «свой» лагерь под стак каждую минуту фарма кора.
```

(Аналогично для остальных 17 ключей — по одной секции, 2–4 строки, всегда с проверяемым действием.)

- [ ] **Step 4: Прогнать полноту**

Run: `PYTHONPATH=src python -m pytest tests/test_principles_coverage.py -v`
Expected: PASS.

- [ ] **Step 5: Тест рендера «тоже видно»**

```python
# tests/test_coach_report.py (добавить)
from dota_coach.coach.brief import CoachBrief
from dota_coach.models import Leak
from dota_coach.report import render_coach_html


def test_render_shows_also_visible_and_coverage():
    brief = CoachBrief(focus_leak_key="feeding", headline="Много смертей",
                       diagnosis="d", why_it_costs="w")
    focus = Leak(key="feeding", title="Смерти", magnitude="20", family="deaths",
                 sample_size=8, considered=11)
    also = [Leak(key="low_obs", title="Мало обсов", magnitude="1 обс", family="vision",
                 sample_size=6, considered=11)]
    html = render_coach_html(brief, [focus, *also], also_visible=also)
    assert "тоже видно" in html.lower()
    assert "Мало обсов" in html
    assert "8 из 11" in html   # строка покрытия по лику-фокусу (правило деградации №5 спеки)
```

- [ ] **Step 6: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_coach_report.py -v`
Expected: FAIL.

- [ ] **Step 7: Обновить render_coach_html + строку покрытия в строке лика**

```python
# report.py — _coach_leak_row: добавить строку покрытия «N из M», когда данные есть:
def _coach_leak_row(leak: Leak) -> str:
    cov = (f" <span class='meta'>(данных: {leak.sample_size} из {leak.considered} матчей)</span>"
           if leak.considered else "")
    return f"<li><b>{_html.escape(leak.title)}</b>: {_html.escape(leak.magnitude)}{cov}</li>"

# render_coach_html — сигнатура + блок «тоже видно»:
def render_coach_html(brief: CoachBrief, leaks: list[Leak], progress: ProgressNote | None = None,
                      also_visible: list[Leak] | None = None) -> str:
    ...
    # внутри ветки с focus_leak_key, ПЕРЕД "Все системные лики":
        also = also_visible or []
        also_block = ("<h2>Тоже видно</h2><ul>"
                      + "\n".join(_coach_leak_row(l) for l in also) + "</ul>") if also else ""
    # вставить {also_block} в f-строку body после {progress_block}.
```

Строка покрытия закрывает правило деградации №5 спеки: «по лику X данных хватило на N из M матчей». `_coach_leak_row` рендерит и лики-фокус в блоке «Все системные лики», и «тоже видно».

- [ ] **Step 8: Пробросить also_visible из CLI (Task 13 использует)**

В `cli.py` `_cmd_coach` (не dry-run) заменить вычисление на разделение фокуса/остального:

```python
        from dota_coach.leaks.severity import rank
        brief = run_coach(matches, args.account_id, make_llm(args.provider))
        leaks = detect_leaks(matches, args.account_id)
        _focus, also = rank(list(leaks))
        html = render_coach_html(brief, leaks, also_visible=also)
```

- [ ] **Step 9: Прогнать всё**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/dota_coach/coach/principles.md src/dota_coach/report.py src/dota_coach/cli.py tests/test_principles_coverage.py tests/test_coach_report.py
git commit -m "feat(coach): 19 секций принципов + блок «тоже видно» в рендере"
```

---

### Task 13: CLI `--n 50`, инвариант анти-результатничества, живой прогон и приёмка

**Files:**
- Modify: `src/dota_coach/cli.py:120,126` (дефолт `--n` = 50 для `leaks` и `coach`)
- Test: `tests/test_anti_resultism.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: весь пакет.
- Produces: тест-сканер анти-результатничества по объектам `Leak` и сериализованному промпту.

- [ ] **Step 1: Инвариант — ни в Leak, ни в промпте нет исхода**

```python
# tests/test_anti_resultism.py
from dataclasses import asdict

from dota_coach.coach.prompt import build_coach_prompt
from dota_coach.leaks import detect_leaks
from dota_coach.models import Match, PlayerMatch

# radiant_* — сырые токены исхода, проверяем ВЕЗДЕ; русские слова — только в user-данных
# (системный промпт нарочно называет «Побед/поражений тебе не дают»).
_BANNED_TOKENS = ("radiant_win", "radiant_score", "dire_score")
_BANNED_WORDS = ("победа", "поражени", "выигр", "проигр")


def _me(**kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return PlayerMatch(**base)


def _series():
    return [Match(match_id=i, duration=1800, radiant_win=(i % 2 == 0),
                  players=[_me(position_est=4, deaths=18, obs_placed=1,
                               benchmarks={"gold_per_min": {"raw": 300, "pct": 0.19}})],
                  parsed=True) for i in range(8)]


def test_leaks_and_prompt_carry_no_outcome():
    leaks = detect_leaks(_series(), 7)
    assert leaks
    for leak in leaks:
        blob = str(asdict(leak)).lower()
        assert not any(t in blob for t in _BANNED_TOKENS)
        assert not any(w in blob for w in _BANNED_WORDS)
    msgs = build_coach_prompt(leaks, None, "p", None, leaks[0].key)
    whole = "".join(m["content"] for m in msgs).lower()
    assert not any(t in whole for t in _BANNED_TOKENS)
    user = msgs[1]["content"].lower()
    assert not any(w in user for w in _BANNED_WORDS)


def test_every_leak_has_complete_metadata():   # спека, инвариант #4 «целостность метаданных»
    leaks = detect_leaks(_series(), 7)
    assert leaks
    for leak in leaks:
        assert leak.key and leak.metric and leak.source
        assert leak.sample_size >= 5
        assert leak.role in (1, 2, 3, 4, 5)
```

- [ ] **Step 2: Тест дефолта CLI --n 50**

```python
# tests/test_cli.py (добавить)
from dota_coach.cli import build_parser


def test_coach_and_leaks_default_n_is_50():
    p = build_parser()
    assert p.parse_args(["coach", "--account-id", "1"]).n == 50
    assert p.parse_args(["leaks", "--account-id", "1"]).n == 50
```

- [ ] **Step 3: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_anti_resultism.py tests/test_cli.py -v`
Expected: FAIL (n=20; сканер может уже проходить).

- [ ] **Step 4: Поменять дефолты в cli.py**

```python
# cli.py — в build_parser: у парсера leaks и coach
    l.add_argument("--n", type=int, default=50)
    ...
    c.add_argument("--n", type=int, default=50)
```

- [ ] **Step 5: Прогнать весь пакет**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS (весь набор — ~110+ тестов).

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/cli.py tests/test_anti_resultism.py tests/test_cli.py
git commit -m "feat(cli): --n 50 + инвариант анти-результатничества"
```

- [ ] **Step 7: Живой прогон на реальных данных (ручная верификация, не unit-тест)**

Run:
```bash
cd /c/Users/user/PycharmProjects/dota-coach
PYTHONPATH=src PYTHONIOENCODING=utf-8 python -m dota_coach.cli coach --account-id 182097367 --n 50 --out coach.html
```

Свериться с критериями приёмки из спеки (`docs/superpowers/specs/2026-08-18-role-aware-leaks-design.md`, раздел «Приёмка»):
1. `low_obs` **не срабатывает** на pos3 (был ложный лик — обязан исчезнуть).
2. `farm_below_bracket` **срабатывает** на pos4 (перцентиль ~0.19 — сейчас прячется).
3. Лики семьи `deaths` срабатывают на всех трёх ролях (10–12 смертей/игра).
4. Роль с < 5 играми (pos5 ×3) **не разбирается** — «данных мало».
5. В «тоже видно» не больше одного лика семьи `deaths`.

- [ ] **Step 8: Калибровка ручных порогов (при необходимости)**

Если живой прогон даёт очевидно шумный результат (лик срабатывает на явно здоровой метрике или молчит на явно больной) — подправить константы в `leaks/thresholds.py::_MANUAL`, перегнать unit-тесты (`pytest -q`) и повторить Step 7. Зафиксировать финальные значения одним коммитом:

```bash
git add src/dota_coach/leaks/thresholds.py
git commit -m "tune(leaks): калибровка ручных порогов по живому прогону 50 матчей"
```

- [ ] **Step 9: Финальный отчёт**

Записать в конце этого файла короткий итог: сколько ликов реально сработало по ролям, какие пороги подкручены, подтверждены ли все 5 критериев приёмки, и что `early_deaths` осознанно отложен в T2 (итог v1 = 19 детекторов).

---

## Отклонения от спеки (осознанные)

1. **19 детекторов вместо 20.** `early_deaths` убран из v1: в объекте игрока OpenDota нет надёжного тайм-лайна собственных смертей (`kills_log` = мои убийства; `killed_by` = карта без времени). Переносится в T2 (кросс-референс `life_state`-таймсерии). Зафиксировать в отчёте приёмки.
2. **`personal`-источник порога** описан в спеке, но в v1 не срабатывает ни в одном детекторе (только `bench`/`manual`). `Thresholds` оставляет место, петля прогресса остаётся на `progress.py` как есть. Не блокер.
3. **История `leaks_snapshot`** добавлена как forward-compatible поле (schema_version=2), но `progress.py` в v1 продолжает сравнивать только фокус — как и требует спека («progress.py работает без изменений»).
4. **`farm_below_bracket` и `level_behind` расширены на pos4/pos5.** Каталог спеки (строка 177) даёт им роли `(1,2,3)`, но критерий приёмки №2 требует срабатывания `farm_below_bracket` на **pos4** (главная мотивация редизайна — скрытая дыра GPM pos4, перцентиль 0.19). GPM/XPM-перцентиль считается по герою → осмыслен для всех ролей. Внутреннее противоречие спеки решено в пользу приёмки; роли обоих = `(1,2,3,4,5)`.

## Self-Review + адверсариальное ревью (выполнено)

План прогнан через 4 параллельных критика (покрытие спеки / согласованность типов / корректность детекторов и полей OpenDota / целостность миграции). Найдено и **устранено** 3 блокера + 6 важных + минорные:

- **Блокеры (исправлены):** (1) `farm_below_bracket` не срабатывал на pos4 — роли расширены до `(1,2,3,4,5)`; (2) циклический импорт `roles.py`↔`rows.py` — `Row` вынесен под `TYPE_CHECKING`; (3) `test_cli.py::test_coach_dry_run` не мигрирован — добавлен ролевой сигнал в Task 11 Step 12.
- **Важные (исправлены):** развилка `make_leak`/`@detector` устранена — идентичность лика штампует обёртка декоратора (единый механизм, без `_SPEC`-констант); анти-результатничество больше не ловит `_SYSTEM` (скан русских слов только в user-сообщении); парс-зависимые счётчики (obs/sen/camps/neutral/observer_kills…) переведены в `int | None`, чтобы `requires` их исключал (инвариант «никогда не нолить»); строка покрытия «N из M» реализована (`Leak.considered` + рендер); `repeat_victim` считает только героев (`npc_dota_hero_*`).
- **Миноры (исправлены):** `low_dewarding` — убран мёртвый `sentry_uses` из requires; «чистая» фикстура в Task 11 (`denies=12`); сброс базлайна прогресса для переименованного `low_obs`; тест инварианта №4 «целостность метаданных» (Task 13); guard создания ветки в Task 0.

**Покрытие спеки:** ролевая сегментация (Task 3), гибридные пороги bench/manual (Task 4), 19/20 детекторов по 6 семьям (Tasks 5–9), severity+дедуп по семьям+детерминизм (Task 10), интеграция coach без слома контракта (Task 11), 19 секций принципов+«тоже видно»+строка покрытия (Task 12), CLI --n 50 + все 4 инварианта спеки (Tasks 10/12/13) + приёмка на реальных данных (Task 13). Деградация по requires — Task 4 (`filter_rows`) + порог ≥5 в фасаде (Task 10). Переименование low_warding→low_obs — Tasks 8/11.

**Согласованность типов:** `Row`, `Thresholds`, `DetectorSpec`, `detector`-обёртка, `make_leak` (спец-less, единый вызов во всех семьях), `detect_leaks`, `rank` — сигнатуры совпадают между задачами. `Leak`/`PlayerMatch` расширяются в Task 1 и используются везде ниже.

---

## Итог живого прогона на реальных данных (Task 13, Step 9)

Прогон `detect_leaks` по 24 закешированным матчам аккаунта 182097367 (2026-08-19). Роли: pos3×10, pos4×11, pos5×3 — **точно как предсказала спека**.

**Все 5 критериев приёмки — PASS:**

1. ✅ `low_obs` **НЕ срабатывает на pos3** — прежний ложный лик (0 обсов на оффлейне) исчез.
2. ✅ `farm_below_bracket` **срабатывает на pos4** (GPM-перцентиль 0.190 < 0.400) — скрытая системная дыра теперь видна (прежде её прятало смешивание ролей).
3. ✅ Семья `deaths` срабатывает на обеих разбираемых ролях (pos3: feeding 10.0, time_dead, repeat_victim; pos4: feeding 11.9, time_dead, repeat_victim). pos5 не разбирается — см. п.4.
4. ✅ pos5 (3 игры) **не разбирается** — ни одного лика с role=5.
5. ✅ В `also_visible` **0 ликов семьи deaths** (feeding — фокус, остальные deaths свёрнуты) — дедуп по семьям работает.

**Фокус:** pos4 `feeding` (11.9 смертей/игру, severity 0.427). **Тоже видно:** no_stacks (pos4), low_dewarding (pos4), low_fight_participation (pos3), low_denies (pos3) — диверсифицировано по семьям.

**Промпт (реальные данные):** несёт «Роль разбора: pos4», per-лик роль+source словами («ниже разумной планки для этой роли» / бенчмарк), блок подтверждающих деталей семьи; исход (win/lose/radiant_*) в user-часть НЕ протекает — анти-результатничество держится.

**Калибровка порогов:** не потребовалась — вывод связный, без явного шума. Наблюдение: `repeat_victim` на обеих ролях ~4.7–4.8 (порог 2.5) — на высокой стороне, но это подтверждающая деталь под семьёй deaths (не фокус), а не шум; при желании подкрутить порог до ~3.5 в `thresholds.py` в будущем.

**Итог:** 19 детекторов, 134 pytest зелёные, обе мотивирующие находки спеки подтверждены на живых данных. Фича закрыта.

### Отклонение v1, выявленное на приёмке (осознанное)

**Единый фокус по глобальной severity вместо отдельного разбора на каждую роль** (спека, принятое решение #2). Реализованный фасад отдаёт плоский список ликов всех ролей, а `coach` берёт ОДИН фокус — сильнейший по severity across roles (здесь pos4 feeding) — и делает один бриф; в блоке ликов промпта при этом видны и лики других ролей (pos3). Это упрощение v1: суть — «покажи одну самую большую системную проблему», что разумно. Отдельные пер-ролевые брифы (N фокусов, N записей истории) — кандидат в v2, если пер-ролевой разбор окажется нужен на практике.
