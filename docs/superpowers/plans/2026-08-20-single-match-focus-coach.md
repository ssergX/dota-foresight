# Single-Match Focus-Moment Coach — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить LLM-разбор одного матча: код выбирает один фокус-момент из уже размеченных `ScoredMoment`, LLM разбирает его вглубь (гипотеза → вопрос-к-себе → чеклист → принцип), рендерится секцией в HTML-отчёт `analyze` с seek-ссылкой на таймкод при наличии видео.

**Architecture:** Новые модули в `coach/` параллельно серийному коучу, каждый — одна ответственность. Переиспользуем `extract_events`/`score_events` (уже дают моменты с вердиктами), LLM-инфру коуча (`make_llm`/`_cached`/`FakeLLM`, строгий JSON). Фокус выбирает КОД детерминированно; LLM только формулирует и НЕ видит исход матча.

**Tech Stack:** Python 3.12, dataclasses, pytest. Без новых зависимостей.

## Global Constraints

- **Анти-результатничество:** `radiant_win`/`radiant_score`/`dire_score` и русские слова исхода (победа/поражени/выигр/проигр) НЕ попадают в user-часть промпта и в `MomentBrief`. LLM получает только `ScoredMoment` + принцип. Закрыто тестом-сканером.
- **Детерминизм:** фокус-момент выбирает КОД; `game_time`/`verdict`/`event_type` на `MomentBrief` ставит КОД, не LLM. Двойной прогон `select_focus_moment` на одних данных → тот же момент.
- **Заземление:** «как надо» — из курируемого `moment_principles.md`; секция на каждый производимый тип момента.
- **Уважение к тонкости данных:** момент с `not_enough_info` разбирается в режиме «гипотеза + что проверить», без обвинений (правило в `_SYSTEM`).
- **Не ломать существующее:** серийный `coach/`, детектор ликов, и `analyze` БЕЗ `--coach` — без изменений. Только добавления.
- Реюз LLM-инфры: `make_llm(provider)` (дефолт claude), `CoachLLM.complete(messages)`, `FakeLLM`. Строгий JSON парсится как в `coach/brief.py`.
- Линтеры: black line-length 120, isort профиль black. Русский интерфейс.

---

## File Structure

```
src/dota_coach/
  coach/
    moment_focus.py        NEW — select_focus_moment(moments) -> ScoredMoment | None
    moment_brief.py        NEW — MomentBrief + parse_moment_brief(raw)
    moment_principles.py   NEW — principle_for_moment(moment) (+ .md)
    moment_principles.md   NEW — секция на тип момента
    moment_prompt.py       NEW — build_moment_prompt(moment, principle) + _SYSTEM
    moment_coach.py        NEW — explain_moment(moments, llm) -> MomentBrief | None
  report.py                MODIFY — render_report(..., moment_brief=None) + секция разбора
  cli.py                   MODIFY — score_moments() helper + analyze --coach/--provider
tests/
  test_moment_focus.py       NEW
  test_moment_brief.py       NEW
  test_moment_principles.py  NEW
  test_moment_prompt.py      NEW
  test_moment_coach.py       NEW
  test_report.py             MODIFY — секция разбора
  test_cli.py                MODIFY — analyze --coach
```

Модели (для справки, `models.py`): `Verdict` = MISTAKE `"mistake"` / FINE_VARIANCE `"fine_variance"` / NOT_ENOUGH_INFO `"not_enough_info"` / NEUTRAL `"neutral"`. `EventType` = TEAMFIGHT `"teamfight"` / OBJECTIVE `"objective"` / NETWORTH_SWING `"networth_swing"` / ITEM_TIMING `"item_timing"` / WARD `"ward"` / DEATH `"death"`. `ScoredMoment(event, score, confidence, verdict, reasons)`; `EventCandidate(type, game_time, involves_me, summary, data)`.

---

### Task 1: `moment_focus.py` — детерминированный выбор фокус-момента

**Files:**
- Create: `src/dota_coach/coach/moment_focus.py`
- Test: `tests/test_moment_focus.py`

**Interfaces:**
- Produces: `select_focus_moment(moments: list[ScoredMoment]) -> ScoredMoment | None` — ранжирует по `(verdict_rank, -score, game_time)`; `mistake` первым, `not_enough_info` последним; пустой → `None`.

- [ ] **Step 1: Тест**

```python
# tests/test_moment_focus.py
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def _m(score, verdict, t, etype=EventType.TEAMFIGHT):
    ev = EventCandidate(type=etype, game_time=t, involves_me=True, summary="", data={})
    return ScoredMoment(event=ev, score=score, confidence=Confidence.LOW, verdict=verdict, reasons=[])


def test_empty_returns_none():
    assert select_focus_moment([]) is None


def test_mistake_preferred_over_higher_score_not_enough_info():
    nei = _m(score=99.0, verdict=Verdict.NOT_ENOUGH_INFO, t=100)   # выше score, но not_enough_info
    mistake = _m(score=5.0, verdict=Verdict.MISTAKE, t=200)
    assert select_focus_moment([nei, mistake]) is mistake


def test_among_same_verdict_higher_score_wins():
    a = _m(score=3.0, verdict=Verdict.MISTAKE, t=100)
    b = _m(score=8.0, verdict=Verdict.MISTAKE, t=200)
    assert select_focus_moment([a, b]) is b


def test_deterministic_tiebreak_by_game_time():
    a = _m(score=5.0, verdict=Verdict.MISTAKE, t=100)
    b = _m(score=5.0, verdict=Verdict.MISTAKE, t=300)
    assert select_focus_moment([a, b]) is a
    assert select_focus_moment([b, a]) is a   # порядок входа не влияет
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_focus.py -v`
Expected: FAIL (модуля нет).

- [ ] **Step 3: Реализовать**

```python
from __future__ import annotations

from dota_coach.models import ScoredMoment, Verdict

# mistake первым (есть измеримая ошибка); not_enough_info последним (данные не докажут)
_VERDICT_RANK = {
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
        key=lambda m: (_VERDICT_RANK.get(m.verdict, 9), -m.score, m.event.game_time),
    )[0]
```

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_focus.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/moment_focus.py tests/test_moment_focus.py
git commit -m "feat(match-coach): детерминированный выбор фокус-момента (mistake > not_enough_info)"
```

---

### Task 2: `moment_brief.py` — MomentBrief + строгий парсинг

**Files:**
- Create: `src/dota_coach/coach/moment_brief.py`
- Test: `tests/test_moment_brief.py`

**Interfaces:**
- Consumes: `_strip_code_fence` из `coach/brief.py` (реюз, DRY).
- Produces:
  - `MomentBrief(headline, hypothesis, process_question, checklist: list[str], principle, game_time=0, verdict="", event_type="")`
  - `parse_moment_brief(raw: str | dict) -> MomentBrief`

- [ ] **Step 1: Тест**

```python
# tests/test_moment_brief.py
import json

import pytest

from dota_coach.coach.moment_brief import MomentBrief, parse_moment_brief


def test_parse_valid_json():
    raw = json.dumps({"headline": "h", "hypothesis": "вероятно X", "process_question": "q",
                      "checklist": ["a", "b"], "principle": "p"})
    b = parse_moment_brief(raw)
    assert b.headline == "h" and b.hypothesis == "вероятно X"
    assert b.checklist == ["a", "b"] and b.principle == "p"
    assert b.game_time == 0 and b.verdict == "" and b.event_type == ""   # код проставит позже


def test_parse_strips_code_fence():
    raw = '```json\n{"headline":"h","hypothesis":"g","process_question":"q","checklist":[],"principle":"p"}\n```'
    assert parse_moment_brief(raw).headline == "h"


def test_parse_rejects_non_object():
    with pytest.raises(ValueError):
        parse_moment_brief("[1, 2, 3]")


def test_parse_rejects_non_list_checklist():
    with pytest.raises(ValueError):
        parse_moment_brief(json.dumps({"headline": "h", "checklist": "nope"}))
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_brief.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать**

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field

from dota_coach.coach.brief import _strip_code_fence


@dataclass
class MomentBrief:
    headline: str
    hypothesis: str
    process_question: str
    checklist: list[str] = field(default_factory=list)
    principle: str = ""
    # штампует КОД (не LLM):
    game_time: int = 0
    verdict: str = ""
    event_type: str = ""


def parse_moment_brief(raw: str | dict) -> MomentBrief:
    data = json.loads(_strip_code_fence(raw)) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("moment brief должен быть JSON-объектом")
    checklist_raw = data.get("checklist", [])
    if not isinstance(checklist_raw, list):
        raise ValueError("moment brief checklist должен быть списком")
    return MomentBrief(
        headline=str(data.get("headline") or ""),
        hypothesis=str(data.get("hypothesis") or ""),
        process_question=str(data.get("process_question") or ""),
        checklist=[str(c) for c in checklist_raw],
        principle=str(data.get("principle") or ""),
    )
```

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_brief.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/moment_brief.py tests/test_moment_brief.py
git commit -m "feat(match-coach): MomentBrief + строгий парсинг (реюз _strip_code_fence)"
```

---

### Task 3: `moment_principles.py` + `moment_principles.md` — заземление по типу момента

**Files:**
- Create: `src/dota_coach/coach/moment_principles.py`
- Create: `src/dota_coach/coach/moment_principles.md`
- Test: `tests/test_moment_principles.py`

**Interfaces:**
- Consumes: `_load_sections` из `coach/principles.py` (реюз парсера `## key`).
- Produces: `principle_for_moment(moment: ScoredMoment, path=_PRINCIPLES_PATH) -> str` — секция по `moment.event.type.value`, иначе generic-дефолт.

- [ ] **Step 1: Тест**

```python
# tests/test_moment_principles.py
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict

# типы, которые реально производит extract_events/score_events:
_PRODUCED = ["teamfight", "objective", "networth_swing", "item_timing", "ward"]
_DEFAULT = "Разбирай процесс и решение по данным, не по исходу. Дай проверяемое действие."


def _m(etype):
    ev = EventCandidate(type=etype, game_time=600, involves_me=True, summary="", data={})
    return ScoredMoment(event=ev, score=1.0, confidence=Confidence.LOW, verdict=Verdict.NEUTRAL, reasons=[])


def test_every_produced_type_has_section():
    missing = [t for t in _PRODUCED
               if principle_for_moment(_m(EventType(t))) == _DEFAULT]
    assert missing == [], f"нет секции принципа для типов момента: {missing}"


def test_unknown_type_falls_back_to_default():
    # DEATH события extract_events не производит -> секции нет -> дефолт
    assert principle_for_moment(_m(EventType.DEATH)) == _DEFAULT
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_principles.py -v`
Expected: FAIL (модуля/секций нет).

- [ ] **Step 3: Реализовать `moment_principles.py`**

```python
from __future__ import annotations

from pathlib import Path

from dota_coach.coach.principles import _load_sections
from dota_coach.models import ScoredMoment

_PRINCIPLES_PATH = Path(__file__).with_name("moment_principles.md")
_DEFAULT = "Разбирай процесс и решение по данным, не по исходу. Дай проверяемое действие."


def principle_for_moment(moment: ScoredMoment, path: Path = _PRINCIPLES_PATH) -> str:
    section = _load_sections(path).get(moment.event.type.value)
    return section if section else _DEFAULT
```

- [ ] **Step 4: Написать `moment_principles.md` (5 секций)**

Ключи секций = `EventType.value`, производимые `extract_events`. Каждая 2–4 строки: что значит момент, почему важен, на что смотреть.

```markdown
# База принципов по моментам матча

Разбирай решение по данным, а не по исходу. Момент — это повод задать себе вопрос,
а не приговор.

## teamfight
Драка — точка, где сходятся вижн, позиция и тайминги. Неудачный размен по золоту
сам по себе не ошибка: важно, зашёл ли ты с информацией и был ли путь к отступлению.
Смотри: где были варды, где враги на миникарте, был ли у тебя эскейп/CD до захода.

## networth_swing
Резкая просадка золота — потеря темпа: обычно смерть или неудачный размен. Каждая
такая просадка отодвигает твой предметный тайминг. Смотри: что предшествовало —
жадность до фарма без вижна, переоценка окна, или вынужденный размен.

## objective
Объекты (башни, Рошан, тормоза) двигают карту сильнее килов. Вопрос не «был ли ты
рядом», а «конвертировал ли команду в объект после успешного окна». Смотри: было ли
свободное окно до/после этого объекта, которое не использовали.

## item_timing
Ключевой предмет — это включение новой фазы силы. Поздний тайминг = меньше окон для
драк на своём пике. Смотри: не было ли «пустых» минут без ластхитов/леса до этой
покупки, которые сдвинули тайминг.

## ward
Вижн — это информация, которая предотвращает смерти и открывает объекты. Один вард в
нужном месте перед заходом стоит дешевле одной предотвращённой смерти. Смотри: ставил
ли ты вижн ПЕРЕД входом в опасную зону, а не после.
```

- [ ] **Step 5: Прогнать + sanity анти-результатничества**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_principles.py -v`
Expected: PASS.

**ВАЖНО:** ни одна секция принципа не должна содержать подстрок исхода (`победа`/`поражени`/`выигр`/`проигр`) — принцип вшивается в user-часть промпта, которую сканер анти-результатничества (Task 7) проверяет. Проверь:
```bash
PYTHONPATH=src python -c "
from pathlib import Path
t = Path('src/dota_coach/coach/moment_principles.md').read_text(encoding='utf-8').lower()
bad = [w for w in ('победа','поражени','выигр','проигр') if w in t]
print('BANNED SUBSTRINGS:', bad or 'none — clean')
assert not bad"
```
Expected: `none — clean`. (Формулировки: «неудачный размен», «успешное окно» — НЕ «проигранный»/«выигранного».)

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/coach/moment_principles.py src/dota_coach/coach/moment_principles.md tests/test_moment_principles.py
git commit -m "feat(match-coach): moment_principles по типам моментов + тест полноты"
```

---

### Task 4: `moment_prompt.py` — промпт + анти-результатничество

**Files:**
- Create: `src/dota_coach/coach/moment_prompt.py`
- Test: `tests/test_moment_prompt.py`

**Interfaces:**
- Produces: `build_moment_prompt(moment: ScoredMoment, principle: str) -> list[dict]` — `[{system}, {user}]`; user несёт тип/время/вердикт/причины/числа + принцип, БЕЗ исхода. `_SYSTEM` фиксирует JSON-схему и правила.

- [ ] **Step 1: Тест**

```python
# tests/test_moment_prompt.py
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


def _moment():
    ev = EventCandidate(type=EventType.NETWORTH_SWING, game_time=845, involves_me=True,
                        summary="просадка", data={"delta": -650})
    return ScoredMoment(event=ev, score=6.5, confidence=Confidence.HIGH,
                        verdict=Verdict.MISTAKE, reasons=["измеримая просадка нетворса"])


def test_prompt_shape_and_content():
    msgs = build_moment_prompt(_moment(), "принцип про нетворс")
    assert [m["role"] for m in msgs] == ["system", "user"]
    user = msgs[1]["content"]
    assert "14:05" in user            # 845s -> 14:05
    assert "networth_swing" in user
    assert "mistake" in user
    assert "принцип про нетворс" in user


def test_system_fixes_json_schema_and_hypothesis_rule():
    system = build_moment_prompt(_moment(), "p")[0]["content"]
    for key in ("headline", "hypothesis", "process_question", "checklist", "principle"):
        assert key in system
    assert "гипотез" in system.lower()   # правило «формулируй гипотезу, не факт»


def test_prompt_never_leaks_outcome():
    msgs = build_moment_prompt(_moment(), "p")
    user = msgs[1]["content"].lower()
    for banned in ("победа", "поражени", "выигр", "проигр"):
        assert banned not in user
    whole = "".join(m["content"] for m in msgs).lower()
    for banned in ("radiant_win", "radiant_score", "dire_score"):
        assert banned not in whole
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_prompt.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать**

```python
from __future__ import annotations

from dota_coach.models import ScoredMoment

_SYSTEM = (
    "Ты — строгий, честный тренер по Dota 2. Разбираешь ОДИН ключевой момент матча.\n"
    "Жёсткие правила:\n"
    "1. Судишь процесс и решение по входным данным, НИКОГДА по исходу матча. "
    "Побед/поражений тебе не дают — не рассуждай о них.\n"
    "2. Данные о моменте тонкие — ты НЕ видел геймплей. Формулируй ГИПОТЕЗУ («вероятно…»), "
    "а не факт. Уважай вердикт детектора: если not_enough_info — прямо скажи, что нужен "
    "ручной просмотр, и дай что проверить, без обвинений.\n"
    "3. Дай 2–3 пункта конкретного проверяемого чеклиста (что посмотреть, в т.ч. на записи).\n"
    "4. Пиши по-русски.\n"
    "Верни СТРОГО JSON-объект такой формы (без markdown-обёртки):\n"
    '{"headline": str, "hypothesis": str, "process_question": str, '
    '"checklist": [str], "principle": str}'
)


def _fmt_time(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


def build_moment_prompt(moment: ScoredMoment, principle: str) -> list[dict]:
    ev = moment.event
    reasons = "; ".join(moment.reasons) or "(нет)"
    numbers = ", ".join(f"{k}={v}" for k, v in ev.data.items()) or "(нет)"
    user = (
        "Фокус-момент матча:\n"
        f"- тип: {ev.type.value}\n"
        f"- время: {_fmt_time(ev.game_time)}\n"
        f"- вердикт детектора: {moment.verdict.value}\n"
        f"- причины разметки: {reasons}\n"
        f"- числа: {numbers}\n\n"
        f"Тренерский принцип для момента этого типа:\n{principle}\n\n"
        "Разбери этот момент строго в заданном JSON-формате."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
```

Note: `ev.data` для всех производимых типов не содержит ключей исхода (teamfight: my_gold_delta/my_xp_delta/my_damage/deaths/my_deaths; networth_swing: delta; objective: objective_type; item_timing: item; ward: kind/x/y). Дамп `data` безопасен для анти-результатничества.

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/moment_prompt.py tests/test_moment_prompt.py
git commit -m "feat(match-coach): промпт разбора момента (гипотеза, JSON-схема, без исхода)"
```

---

### Task 5: `moment_coach.py` — оркестратор `explain_moment`

**Files:**
- Create: `src/dota_coach/coach/moment_coach.py`
- Test: `tests/test_moment_coach.py`

**Interfaces:**
- Consumes: `select_focus_moment`, `principle_for_moment`, `build_moment_prompt`, `parse_moment_brief`, `CoachLLM`/`FakeLLM`.
- Produces: `explain_moment(moments: list[ScoredMoment], llm: CoachLLM) -> MomentBrief | None` — выбирает фокус, зовёт LLM, парсит, КОД штампует `game_time`/`verdict`/`event_type`; пустые моменты → `None`.

> Отклонение от спеки: `cache_dir` в `explain_moment` НЕ нужен — истории/подотчётности у одиночного разбора нет, а кеш ответа держит сам LLM (`_cached`). Сигнатура без `cache_dir`.

- [ ] **Step 1: Тест**

```python
# tests/test_moment_coach.py
import json

from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.moment_coach import explain_moment
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict

_CANNED = json.dumps({
    "headline": "заголовок-от-ллм", "hypothesis": "вероятно зашёл без вижна",
    "process_question": "был ли эскейп?", "checklist": ["проверь варды", "проверь CD"],
    "principle": "вижн перед заходом",
})


def _m(score, verdict, t, etype=EventType.NETWORTH_SWING):
    ev = EventCandidate(type=etype, game_time=t, involves_me=True, summary="", data={"delta": -600})
    return ScoredMoment(event=ev, score=score, confidence=Confidence.HIGH, verdict=verdict, reasons=["r"])


def test_explain_builds_brief_and_stamps_identity_by_code():
    moments = [_m(3.0, Verdict.NOT_ENOUGH_INFO, 100), _m(6.0, Verdict.MISTAKE, 845)]
    llm = FakeLLM(_CANNED)
    brief = explain_moment(moments, llm)
    assert brief.headline == "заголовок-от-ллм"          # текст от ЛЛМ
    assert brief.checklist == ["проверь варды", "проверь CD"]
    # идентичность ставит КОД по выбранному фокусу (mistake @ 845), не ЛЛМ:
    assert brief.game_time == 845
    assert brief.verdict == "mistake"
    assert brief.event_type == "networth_swing"
    assert len(llm.calls) == 1


def test_explain_no_moments_returns_none_and_skips_llm():
    llm = FakeLLM(_CANNED)
    assert explain_moment([], llm) is None
    assert llm.calls == []
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_coach.py -v`
Expected: FAIL.

- [ ] **Step 3: Реализовать**

```python
from __future__ import annotations

from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import MomentBrief, parse_moment_brief
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.models import ScoredMoment


def explain_moment(moments: list[ScoredMoment], llm: CoachLLM) -> MomentBrief | None:
    focus = select_focus_moment(moments)
    if focus is None:
        return None
    principle = principle_for_moment(focus)
    messages = build_moment_prompt(focus, principle)
    brief = parse_moment_brief(llm.complete(messages))
    # идентичность момента ставит КОД (не ЛЛМ) — детерминизм и анти-результатничество:
    brief.game_time = focus.event.game_time
    brief.verdict = focus.verdict.value
    brief.event_type = focus.event.type.value
    return brief
```

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_moment_coach.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/coach/moment_coach.py tests/test_moment_coach.py
git commit -m "feat(match-coach): explain_moment — фокус+LLM+парс, идентичность ставит код"
```

---

### Task 6: `report.py` — секция «Разбор фокус-момента» + seek

**Files:**
- Modify: `src/dota_coach/report.py` (`render_report` ~39-68, добавить хелпер)
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `MomentBrief`, существующие `video_time_for`, `_VERDICT_RU`.
- Produces: `render_report(match_id, moments, leaks, video_filename, offset, moment_brief: MomentBrief | None = None) -> str` — если `moment_brief`, рендерит секцию разбора + `▶`-кнопку seek (при видео) / таймкод-текст (без).

- [ ] **Step 1: Тест**

```python
# tests/test_report.py (добавить)
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.report import render_report


def _brief():
    return MomentBrief(headline="Слепой заход", hypothesis="вероятно без вижна",
                       process_question="был ли эскейп?", checklist=["проверь варды"],
                       principle="вижн перед заходом", game_time=845, verdict="mistake",
                       event_type="networth_swing")


def test_report_renders_moment_brief_section_no_video():
    html = render_report(1, [], leaks=[], video_filename=None, offset=0.0, moment_brief=_brief())
    assert "Разбор фокус-момента" in html
    assert "Слепой заход" in html and "проверь варды" in html
    assert "14:05" in html                       # таймкод текстом без видео


def test_report_moment_brief_has_seek_button_with_video():
    html = render_report(1, [], leaks=[], video_filename="v.mp4", offset=2.0, moment_brief=_brief())
    assert "seek(" in html and "▶" in html       # кнопка seek при видео


def test_report_without_moment_brief_unchanged():
    html = render_report(1, [], leaks=[], video_filename=None, offset=0.0)
    assert "Разбор фокус-момента" not in html
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_report.py -v`
Expected: FAIL (аргумента/секции нет).

- [ ] **Step 3: Реализовать**

```python
# report.py — добавить импорт вверху:
from dota_coach.coach.moment_brief import MomentBrief

# добавить хелперы:
def _fmt_time(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


def _moment_brief_section(brief: MomentBrief, video_filename: str | None, offset: float) -> str:
    ts = _fmt_time(brief.game_time)
    if video_filename:
        t = video_time_for(brief.game_time, offset)
        anchor = f"<button onclick=\"seek({t:.3f})\">▶ {ts}</button>"
    else:
        anchor = f"<b>{ts}</b>"
    verdict = _VERDICT_RU.get(brief.verdict, brief.verdict)
    checklist = "\n".join(f"<li>{_html.escape(c)}</li>" for c in brief.checklist)
    return (
        f"<h2>Разбор фокус-момента {anchor} <span class='meta'>[{verdict}]</span></h2>"
        f"<h3>{_html.escape(brief.headline)}</h3>"
        f"<p><b>Вероятно:</b> {_html.escape(brief.hypothesis)}</p>"
        f"<p><b>Спроси себя:</b> {_html.escape(brief.process_question)}</p>"
        f"<p><b>Проверь:</b></p><ul>{checklist}</ul>"
        f"<p class='reasons'>{_html.escape(brief.principle)}</p>"
    )
```

Затем в сигнатуре `render_report` добавить `moment_brief: MomentBrief | None = None`, вычислить `brief_section = _moment_brief_section(moment_brief, video_filename, offset) if moment_brief else ""` и вставить `{brief_section}` в f-строку body СРАЗУ ПОСЛЕ `{video_block}` и ПЕРЕД `<h2>Ключевые моменты</h2>`.

Note про циклический импорт: `report.py` будет импортировать из `coach/moment_brief.py`, а `cli.py` импортирует `report` и `coach`. `moment_brief.py` импортирует только из `coach/brief.py` (не из report) — цикла нет. Проверить: `PYTHONPATH=src python -c "import dota_coach.report"`.

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dota_coach/report.py tests/test_report.py
git commit -m "feat(match-coach): секция разбора фокус-момента в отчёте + seek-кнопка"
```

---

### Task 7: `cli.py` — `analyze --coach` + инвариант анти-результатничества

**Files:**
- Modify: `src/dota_coach/cli.py` (`build_match_report` ~19-25, `_cmd_analyze` ~44-54, parser ~110-116)
- Test: `tests/test_cli.py` (MODIFY), `tests/test_anti_resultism_moment.py` (NEW)

**Interfaces:**
- Produces: `score_moments(match, account_id, top_n) -> list[ScoredMoment]` (общий хелпер); `analyze --coach [--provider]` — при `--coach` внутри error-boundary зовёт `explain_moment` и передаёт `moment_brief` в рендер; без `--coach` поведение прежнее.

- [ ] **Step 1: Тесты**

```python
# tests/test_cli.py (добавить)
def test_analyze_coach_flag_defaults_off():
    from dota_coach.cli import build_parser
    args = build_parser().parse_args(["analyze", "--match-id", "1", "--account-id", "2"])
    assert args.coach is False


def test_analyze_coach_renders_moment_brief(tmp_path, monkeypatch, capsys):
    import json
    from dota_coach.cli import main
    from dota_coach.models import Match, PlayerMatch

    def _match(mid):
        # gold_t=[0,1000,200]: на 2-й минуте просадка -800 (<= -500) -> networth_swing (verdict MISTAKE)
        me = PlayerMatch(account_id=111, player_slot=0, hero_id=1, is_radiant=True,
                         kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
                         gold_t=[0, 1000, 200])
        return Match(match_id=mid, duration=1800, radiant_win=True, players=[me],
                     teamfights=[], objectives=[], parsed=True)

    canned = json.dumps({"headline": "H", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})

    monkeypatch.setattr("dota_coach.cli.fetch_match", lambda mid: {"id": mid})
    monkeypatch.setattr("dota_coach.cli.normalize", lambda raw: _match(raw["id"]))
    monkeypatch.setattr("dota_coach.cli.make_llm", lambda provider: __import__(
        "dota_coach.coach.llm", fromlist=["FakeLLM"]).FakeLLM(canned))

    out = tmp_path / "r.html"
    rc = main(["analyze", "--match-id", "5", "--account-id", "111", "--coach", "--out", str(out)])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "Разбор фокус-момента" in html and "H" in html
```

```python
# tests/test_anti_resultism_moment.py (NEW)
from dataclasses import asdict

from dota_coach.coach.moment_coach import explain_moment
from dota_coach.coach.llm import FakeLLM
from dota_coach.coach.moment_prompt import build_moment_prompt
from dota_coach.coach.moment_focus import select_focus_moment
from dota_coach.coach.moment_principles import principle_for_moment
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict
import json

_BANNED_TOKENS = ("radiant_win", "radiant_score", "dire_score")
_BANNED_WORDS = ("победа", "поражени", "выигр", "проигр")


def _moment():
    ev = EventCandidate(type=EventType.TEAMFIGHT, game_time=845, involves_me=True, summary="",
                        data={"deaths": 3, "my_deaths": 1, "my_gold_delta": -700})
    return ScoredMoment(event=ev, score=6.0, confidence=Confidence.LOW,
                        verdict=Verdict.NOT_ENOUGH_INFO, reasons=["слитая драка — нужен ручной разбор"])


def test_moment_prompt_and_brief_carry_no_outcome():
    focus = _moment()
    msgs = build_moment_prompt(focus, principle_for_moment(focus))
    whole = "".join(m["content"] for m in msgs).lower()
    assert not any(t in whole for t in _BANNED_TOKENS)
    user = msgs[1]["content"].lower()
    assert not any(w in user for w in _BANNED_WORDS)

    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})
    brief = explain_moment([focus], FakeLLM(canned))
    blob = str(asdict(brief)).lower()
    assert not any(t in blob for t in _BANNED_TOKENS)
    assert not any(w in blob for w in _BANNED_WORDS)
```

- [ ] **Step 2: Запустить — упадёт**

Run: `PYTHONPATH=src python -m pytest tests/test_cli.py tests/test_anti_resultism_moment.py -v`
Expected: FAIL (нет флага/хелпера).

- [ ] **Step 3: Реализовать в `cli.py`**

Добавить импорты вверху:
```python
from dota_coach.coach.llm import make_llm
from dota_coach.coach.moment_coach import explain_moment
```

Ввести общий хелпер и прокинуть `moment_brief`:
```python
def score_moments(match: Match, account_id: int | None, top_n: int):
    events = extract_events(match, account_id)
    benches = player_benchmarks(match, account_id)
    return score_events(events, benches, match, account_id, top_n=top_n)


def build_match_report(match: Match, account_id: int | None, video_filename: str | None,
                       offset: float, top_n: int = 10, moment_brief=None) -> str:
    moments = score_moments(match, account_id, top_n)
    return render_report(match.match_id, moments, leaks=[],
                         video_filename=video_filename, offset=offset, moment_brief=moment_brief)
```

В `_cmd_analyze` — посчитать разбор при `--coach` (error-boundary: LLM-сбой НЕ валит отчёт):
```python
def _cmd_analyze(args: argparse.Namespace) -> int:
    match = normalize(fetch_match(args.match_id))
    offset = 0.0
    video_filename = None
    if args.video:
        video_filename = Path(args.video).name
        offset = _video_offset(args.video, match.duration)

    moment_brief = None
    if args.coach:
        try:
            moments = score_moments(match, args.account_id, args.top_n)
            moment_brief = explain_moment(moments, make_llm(args.provider))
        except Exception as exc:  # noqa: BLE001 - LLM-разбор опционален, отчёт по данным всё равно рендерим
            print(f"LLM-разбор момента пропущен: {exc}")

    html = build_match_report(match, args.account_id, video_filename, offset, args.top_n,
                              moment_brief=moment_brief)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"report -> {args.out}")
    return 0
```

В `build_parser`, парсер `analyze` — добавить флаги:
```python
    a.add_argument("--coach", action="store_true", help="LLM-разбор фокус-момента")
    a.add_argument("--provider", default=None, help="claude|openai; по умолчанию claude")
```

Note про двойной скоринг: при `--coach` `score_moments` вызывается дважды (для explain и внутри `build_match_report`) — это чистые функции над одним матчем, стоимость пренебрежима; сознательно ради простоты (никакого протаскивания состояния).

- [ ] **Step 4: Прогнать**

Run: `PYTHONPATH=src python -m pytest tests/test_cli.py tests/test_anti_resultism_moment.py -v`
Expected: PASS.

- [ ] **Step 5: Полный набор**

Run: `PYTHONPATH=src python -m pytest -q`
Expected: PASS (весь набор + новые тесты; ничего старого не сломано).

- [ ] **Step 6: Commit**

```bash
git add src/dota_coach/cli.py tests/test_cli.py tests/test_anti_resultism_moment.py
git commit -m "feat(match-coach): analyze --coach + инвариант анти-результатничества момента"
```

- [ ] **Step 7: Живой смок (контроллер, не unit)**

```bash
PYTHONPATH=src PYTHONIOENCODING=utf-8 python -m dota_coach.cli analyze --match-id <ID> --account-id 182097367 --coach --out match.html
```
Проверить: выбран осмысленный фокус-момент, разбор в режиме гипотезы, при `not_enough_info` — явно «нужен ручной просмотр», исход нигде не упомянут.

---

## Self-Review (выполнено при написании)

- **Покрытие спеки:** фокус-выбор кодом+детерминизм (Task 1), MomentBrief+парс (Task 2), заземление по типу+полнота (Task 3), промпт без исхода+гипотеза-правило (Task 4), explain_moment со штампом идентичности кодом (Task 5), рендер+seek (Task 6), CLI `analyze --coach`+error-boundary+анти-результат-инвариант (Task 7). Реюз `_strip_code_fence`/`_load_sections`/`make_llm`/`FakeLLM` — без дублей.
- **Отклонение от спеки:** `explain_moment` без `cache_dir` (истории у одиночного разбора нет; кеш держит LLM) — зафиксировано в Task 5.
- **Плейсхолдеры:** нет; код полный в каждом шаге.
- **Согласованность типов:** `select_focus_moment`→`ScoredMoment|None`; `MomentBrief` поля ↔ схема промпта ↔ штамп в `explain_moment` ↔ рендер; `render_report` новый необязательный `moment_brief`. Импорт-цепочка `report→moment_brief→brief` без цикла (проверка в Task 6).
