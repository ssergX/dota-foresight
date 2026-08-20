# Dota Coach — разбор одного матча (фокус-момент) — дизайн

> Дата: 2026-08-20. v2-фича поверх ролевых ликов (влиты в `master`, 134 pytest).
> Предыдущие дизайны: `2026-08-14-dota-coach-mvp-design.md`,
> `2026-08-15-dota-coach-phase2-coach-design.md`,
> `2026-08-18-role-aware-leaks-design.md`.

## Цель

Добавить **LLM-разбор ОДНОГО матча**: код находит и размечает ключевые моменты
(это уже делает MVP-команда `analyze`), затем LLM берёт **один фокус-момент** и
разбирает его вглубь — что вероятно произошло, какое решение спросить с себя, что
проверить (на видео, если есть), какой принцип.

Форма — **фокус-момент** (один, а не проход по всем): в духе серийного коуча
(«одна вещь, без шума»). Режим **данные-only + видео-бонус**: работает на любом
матче без записи; если передан `--video`, разбор даёт seek-ссылку на таймкод.

Область: только слой одиночного разбора. Детектор ликов, серийный коуч и их
контракты НЕ трогаются. Переиспользуем существующее: `extract_events`,
`score_events` (даёт `ScoredMoment` с вердиктами), LLM-инфру коуча
(`make_llm`/`claude -p`, дисковый кеш, строгий JSON, `FakeLLM`), рендер отчёта.

## Наследуемые принципы (не нарушать)

1. **Анти-результатничество.** Исход матча (`radiant_win`/`radiant_score`/
   `dire_score`, слова победа/поражение) НЕ передаётся в LLM ни в каком виде.
   Судим процесс/решение, не исход. Закрыто тестом-сканером.
2. **Детерминированное ядро.** Фокус-момент выбирает КОД, не LLM. Таймкод и
   вердикт на карточку ставит КОД. LLM только формулирует. Двойной прогон на
   одних входных данных → один и тот же фокус-момент.
3. **Заземление.** «Как надо» опирается на курируемый `moment_principles.md`, а не
   на вольную память модели.
4. **Уважение к тонкости данных.** Код видит только таймкод/дельту/вердикт, не сам
   геймплей. Поэтому разбор — это **гипотеза + вопрос-к-себе + чеклист проверки**,
   а НЕ авторитетный вердикт. Момент с `not_enough_info` разбирается явно в режиме
   «нужен ручной просмотр», без обвинений.
5. **Чистые функции отдельно от сетевой/LLM-склейки.**

## Принятые решения

| # | Решение |
|---|---|
| 1 | Форма — один фокус-момент вглубь (не проход по топ-N) |
| 2 | Фокус выбирает КОД детерминированно; предпочтение вердикта `mistake` над `not_enough_info` |
| 3 | Режим данные-only; видео (`--video`) — бонусная seek-ссылка |
| 4 | Команда — `analyze --coach` (флаг к существующей), не новая команда |
| 5 | Заземление — новый `moment_principles.md` по ТИПАМ моментов (не leak-принципы) |
| 6 | Переиспользуем LLM-инфру коуча (`make_llm`, `_cached`, `FakeLLM`, строгий JSON) |
| 7 | LLM не получает исход; структурная гарантия (передаём только `ScoredMoment` + принцип) |

## Архитектура

Новые модули — параллельно серийному коучу (`coach/`), один файл = одна
ответственность:

```
src/dota_coach/coach/
  moment_focus.py        — select_focus_moment(moments) -> ScoredMoment | None (детерминированно)
  moment_principles.py   — principle_for_moment(moment) -> str  (+ moment_principles.md)
  moment_principles.md   — секция на каждый тип момента
  moment_prompt.py       — build_moment_prompt(moment, principle) -> list[dict]
  moment_brief.py        — MomentBrief + parse_moment_brief(raw) -> MomentBrief
  moment_coach.py        — explain_moment(moments, llm, cache_dir) -> MomentBrief | None (оркестратор)
src/dota_coach/
  report.py              — MODIFY: секция «Разбор фокус-момента» + seek-кнопка
  cli.py                 — MODIFY: analyze --coach [--provider]
```

### Поток данных

```
match → extract_events → score_events → moments (top-N ScoredMoment)
                                            │
                        select_focus_moment(moments)  ← КОД (детерминизм + вердикт)
                                            │
                        principle_for_moment(focus)   ← moment_principles.md
                                            │
                        build_moment_prompt(focus, principle)  ← без исхода
                                            │
                        llm.complete(...) → parse_moment_brief  ← строгий JSON
                                            │
                        КОД штампует game_time / verdict / event_type
                                            │
                        render: секция разбора + ▶seek (если видео)
```

### Выбор фокус-момента (`moment_focus.py`)

```python
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

Детерминизм: тай-брейк по `game_time` (уникален в пределах матча-серии моментов на
практике; при равенстве — стабильная сортировка сохраняет входной порядок из
`score_events`, который сам детерминирован).

### `MomentBrief` и парсинг (`moment_brief.py`) — зеркало `brief.py`

```python
@dataclass
class MomentBrief:
    headline: str
    hypothesis: str          # «вероятно …» — гипотеза, НЕ факт
    process_question: str    # какое решение спросить с себя
    checklist: list[str]     # 2-3 что проверить (на видео если есть)
    principle: str
    # штампует КОД (не LLM):
    game_time: int = 0
    verdict: str = ""
    event_type: str = ""

def parse_moment_brief(raw: str | dict) -> MomentBrief: ...
    # strip code-fence (reuse pattern из brief.py), json.loads, валидация обязательных
    # строковых полей; checklist -> list[str]; понятная ошибка при кривом JSON.
```

### Промпт (`moment_prompt.py`)

`_SYSTEM` (строгий тренер): судишь ПРОЦЕСС/РЕШЕНИЕ по входным данным, НИКОГДА по
исходу (исход тебе не дают); данные о моменте тонкие — ты не видел геймплей,
поэтому формулируй ГИПОТЕЗУ, а не факт; **уважай вердикт** — если
`not_enough_info`, прямо скажи, что нужен ручной просмотр, и дай что проверить, без
обвинений; дай 2-3 пункта проверяемого чеклиста; пиши по-русски; верни СТРОГО JSON
формы `{headline, hypothesis, process_question, checklist:[...], principle}`.

`build_moment_prompt(moment, principle)` — user-сообщение: тип момента, таймкод
`mm:ss`, вердикт, причины (`moment.reasons`), числа из `moment.event.data`
(например `my_gold_delta`, `deaths` — но НЕ win/lose), затем принцип. Схема
структурного ответа фиксирована в `_SYSTEM`.

### Заземление (`moment_principles.py` + `moment_principles.md`)

Секция `## <event_type>` на каждый тип момента, который может выдать
`score_events`: `teamfight`, `objective`, `networth_swing`, `item_timing`, `ward`.
Каждая — 2-4 строки: что значит момент этого типа, почему важен, на что смотреть.
`principle_for_moment(moment)` = секция по `moment.event.type.value`, иначе
generic-фолбэк. Тест полноты: для каждого `EventType`, который реально производит
`extract_events`/`score_events`, есть секция (не фолбэк).

### Оркестратор (`moment_coach.py`) — зеркало `coach.py`

```python
def explain_moment(moments: list[ScoredMoment], llm: CoachLLM,
                   cache_dir: Path = Path("cache")) -> MomentBrief | None:
    focus = select_focus_moment(moments)
    if focus is None:
        return None
    principle = principle_for_moment(focus)
    messages = build_moment_prompt(focus, principle)
    brief = parse_moment_brief(llm.complete(messages))
    # идентичность момента ставит КОД, не LLM:
    brief.game_time = focus.event.game_time
    brief.verdict = focus.verdict.value
    brief.event_type = focus.event.type.value
    return brief
```

Никакого `radiant_win` в пути — `explain_moment` получает только `ScoredMoment`.

### Рендер (`report.py`)

`render_report(...)` получает новый необязательный аргумент
`moment_brief: MomentBrief | None = None`. Если задан — рендерит секцию «Разбор
фокус-момента» (headline → гипотеза → вопрос-к-себе → чеклист → принцип) с
`▶`-кнопкой seek на `moment_brief.game_time` (через существующий
`video_time_for(game_time, offset)`, как `_moment_row`), если есть `video_filename`.
Без видео — просто таймкод текстом.

### CLI (`cli.py`)

`analyze` получает флаги `--coach` (bool) и `--provider` (как у `coach`).
В `_cmd_analyze` (или `build_match_report`): после `score_events`, если `--coach`,
внутри error-boundary (try/except, как `_cmd_coach`): `explain_moment(moments,
make_llm(provider))` → передать `moment_brief` в `render_report`. Без `--coach`
поведение `analyze` не меняется.

## Анти-результатничество (инвариант, закрыт тестом)

Тест сканирует сериализованный `build_moment_prompt` (user-сообщение) и объект
`MomentBrief` на `radiant_win`/`radiant_score`/`dire_score` и русские слова исхода
(победа/поражени/выигр/проигр — в user-части) — их не должно быть. Системный промпт
может называть запрещённое (как в серийном коуче) → русские слова сканируем только
в user-сообщении.

## Тестирование

TDD. Чистые функции — без сети/LLM:
- `moment_focus`: детерминизм (двойной прогон), предпочтение `mistake` над
  `not_enough_info`, тай-брейк по `game_time`, пустой список → `None`.
- `moment_principles`: полнота (каждый производимый `EventType` имеет секцию),
  фолбэк на неизвестный тип.
- `moment_prompt`: нет исхода в user, есть принцип, режим уважения вердикта
  (для `not_enough_info` промпт это отражает).
- `moment_brief`: parse строгого JSON, strip fence, ошибка на кривом.
- `moment_coach`: `explain_moment` с `FakeLLM` — КОД ставит game_time/verdict/
  event_type (не LLM); пустые моменты → `None`; `len(llm.calls) == 1`.
- `report`: секция разбора рендерится; seek-кнопка при видео, таймкод-текст без.
- `anti_resultism`: сканер по промпту одиночного момента.
- `cli`: `analyze --coach` печатает/рендерит разбор (через `FakeLLM`/monkeypatch),
  без `--coach` — старое поведение.

## Вне области (отложено осознанно)

- Проход по нескольким моментам / полный таймлайн-нарратив (форма отвергнута в
  пользу фокус-момента).
- Компьютерное зрение по видео (авто-детект позиции/вижена) — данные о геймплее
  по-прежнему из API, видео только для ручного просмотра по seek-ссылке.
- Отдельный `moment_principles` под роль — момент этого не требует (тип момента
  универсальнее роли).
- Кросс-референс момента с ликами серии («этот момент — проявление системного
  лика X») — потенциальный v3, требует прогонять и серию, и матч вместе.
