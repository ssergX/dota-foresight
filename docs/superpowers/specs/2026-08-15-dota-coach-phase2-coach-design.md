# Dota Coach — фаза 2: системный ЛЛМ-тренер (`coach`) — дизайн

> Дата: 2026-08-15. Продолжение MVP (фаза 1, влита в `master`, 33 pytest).
> Предыдущий дизайн: `docs/superpowers/specs/2026-08-14-dota-coach-mvp-design.md`.

## Цель

Превратить детерминированные **лики по серии матчей** (уже есть в `leaks.py`) в связный
тренерский бриф: для главного лика — **диагноз → почему тебя топит → 1-2 конкретных
дрилла** на следующие игры. Плюс **лёгкая петля подотчётности**: каждый бриф
сохраняется, следующий прогон детерминированно сравнивает, сдвинулась ли метрика
лика-фокуса, и тренер это проговаривает.

Область: **только системный разбор по серии** (не разбор одного матча — это отдельный
возможный кусок позже). Один вызов ЛЛМ на прогон.

## Принципы (наследуются из MVP, не нарушать)

1. **Анти-результатничество.** Тренер судит процесс/решения по входным данным,
   НИКОГДА по исходу матча. Гарантии:
   - в ЛЛМ передаются только процессные метрики (смерти/игру, GPM-перцентиль,
     варды/игру и т.п.) — **win/loss не передаётся вообще**;
   - явное правило в system-prompt;
   - в структурном выводе каждый тезис привязан к переданной метрике (`metric_ref`).
2. **Заземление / без выдуманных фактов.** ЛЛМ рассуждает только по нашим числам +
   курируемой базе принципов. «Как чинить» берётся из курируемого набора, а не из
   вольной памяти модели (снижает риск неверной меты). ЛЛМ не выдумывает числа.
3. **Провайдер-агностик.** Тонкий интерфейс `CoachLLM`; дефолт — GLM через
   OpenAI-совместимый эндпоинт. Смена модели — одной переменной окружения.
4. **Чистое ядро отдельно от сетевой склейки** (как `normalize` vs `opendota` в MVP):
   всё, что можно, — чистые функции с юнит-тестами; сетевой вызов ЛЛМ —
   тонкая непокрытая юнит-тестами склейка.

## Выбранный подход

**Детерминированное ядро + ЛЛМ как «писатель».** Код считает все факты (лики,
агрегаты, дельты прогресса); ЛЛМ только **формулирует** разбор и дриллы, привязанные к
этим числам, и возвращает **структурный JSON**, который мы рендерим детерминированно.

Отклонённые альтернативы:
- **ЛЛМ-аналитик** (ЛЛМ сам ищет лики по сырой стате): недетерминированный поиск
  ликов, тяжело тестировать, легко галлюцинирует и скатывается в результатничество,
  выкидывает уже валидированный детектор ликов.
- **ЛЛМ с tool-use**: оверкилл для «1 вызов на серию», лишняя агентная сложность.
  Отложено.

## Архитектура (юниты)

Один файл — одна ответственность. Новый пакет `src/dota_coach/coach/`.

### Правка существующего: `leaks.py` — обогатить `Leak` числами

`Leak` сейчас несёт только строку `magnitude` — для детерминированного сравнения
прогонов этого мало. Добавить поля (с дефолтами → обратно совместимо):

```python
@dataclass
class Leak:
    key: str
    title: str
    magnitude: str                       # человекочитаемо, для показа (как было)
    example_matches: list[int] = field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    # новое — для петли подотчётности и metric_ref:
    metric: str = ""                     # напр. "deaths_per_game" / "gpm_pct" / "obs_per_game"
    value: float = 0.0                   # измеренное значение по серии
    threshold: float = 0.0               # порог срабатывания
    direction: str = "lower_is_better"   # или "higher_is_better"
```

`detect_leaks` заполняет эти поля для всех трёх текущих ликов:
- `farm_below_bracket` → `metric="gpm_pct"`, `value=median(gpm_pct)`,
  `threshold=0.4`, `direction="higher_is_better"`;
- `feeding` → `metric="deaths_per_game"`, `value=avg_deaths`, `threshold=8.0`,
  `direction="lower_is_better"`;
- `low_warding` → `metric="obs_per_game"`, `value=avg_obs`, `threshold=4.0`,
  `direction="higher_is_better"`.

Значения совпадают с уже существующими порогами (`_FARM_PCT/_DEATHS_MAX/_OBS_MIN`).
Правка теста `test_leaks.py` — проверить наличие и корректность числовых полей.

### Новое: `coach/principles.md` + `coach/principles.py`

- `principles.md` — курируемые тренерские эвристики по типу лика (редактируемый текст,
  тюнится без правки кода).
- `principles.py`: `principles_for(leak_key: str) -> str` — читает секцию из `.md`
  (или встроенный дефолт, если секции нет). **Без RAG/векторов** (YAGNI). Интерфейс
  оставляет место под RAG в будущей фазе: сигнатура не меняется.

### Новое: `coach/progress.py` (чистый)

```python
compare_focus(prev_brief: CoachBrief | None,
              current_leaks: list[Leak]) -> ProgressNote
```
- Находит в `current_leaks` лик с `key == prev_brief.focus_leak_key`.
- Считает дельту `value` с учётом `direction`: улучшение / регресс / без сдвига /
  лик ушёл (не сработал в этом прогоне) / нет истории.
- Возвращает `ProgressNote(status, prev_value, curr_value, metric, text)`.
  `text` — короткая детерминированная строка на русском (напр.
  «смерти 11.1 → 8.3 за игру — прогресс»). Это **код, не ЛЛМ.**

### Новое: `coach/history.py` (простой IO)

- `load_history(account_id, cache_dir=Path("cache")) -> list[CoachBrief]`
- `save_brief(account_id, brief, cache_dir=Path("cache")) -> None`
- Файл `cache/coach_history_<account_id>.json` (список брифов; при сохранении —
  дозапись). Юнит-тест через `tmp_path` (round-trip).

### Новое: `coach/brief.py` (чистый)

```python
@dataclass
class Drill:
    text: str
    metric_ref: str            # ключ метрики, к которой привязан дрилл

@dataclass
class CoachBrief:
    focus_leak_key: str
    headline: str
    diagnosis: str
    why_it_costs: str
    drills: list[Drill]
    progress_note: str | None = None   # заполняется из ProgressNote (код), не ЛЛМ
    generated_for_matches: list[int] = field(default_factory=list)

def parse_brief(raw_json: str | dict) -> CoachBrief:
    ...  # валидирует форму; мягко предупреждает, если drills[].metric_ref пуст;
         # ValueError на битую форму (нет focus_leak_key / drills не список)
```

### Новое: `coach/llm.py` (склейка — без юнит-тестов, как `opendota.py`)

- Протокол `CoachLLM` с методом `complete(messages: list[dict]) -> str`.
- `OpenAICompatibleLLM`:
  - env: `DOTA_COACH_LLM_BASE_URL`, `DOTA_COACH_LLM_API_KEY`, `DOTA_COACH_LLM_MODEL`;
  - вызов `requests.post(f"{BASE_URL}/chat/completions", ...)`, просим JSON-ответ
    (`response_format={"type":"json_object"}` если бэкенд поддерживает; иначе
    инструкцией в промпте);
  - **дисковый кеш ответа** по SHA-256 от messages в `cache/coach_llm/<hash>.json`
    → повторные прогоны бесплатны и детерминированны (зеркалит кеш матч-JSON);
  - разумный таймаут + `raise_for_status`.
- `FakeLLM(canned: str)` — возвращает заранее заданный JSON; для тестов оркестратора.
- Зависимость — существующий `requests` (без SDK-локина, минимум зависимостей).

### Новое: `coach/prompt.py` (чистый)

```python
build_coach_prompt(leaks: list[Leak],
                   progress: ProgressNote | None,
                   principles: str,
                   prior: CoachBrief | None) -> list[dict]
```
- Возвращает `[{"role":"system",...}, {"role":"user",...}]`.
- System: роль тренера + правило анти-результатничества («судишь процесс по входным
  данным, НЕ по исходу; побед/поражений тебе не дают; не выдумывай числа; каждый тезис
  привязывай к метрике») + требование вернуть строго заданный JSON-контракт.
- User: список ликов с числами (`metric`, `value`, `threshold`, direction, примеры
  матчей), релевантные принципы, прошлый фокус и `ProgressNote` (если есть).
- Полностью юнит-тестируемо: проверяем, что промпт содержит числа, правило,
  прошлый фокус, принципы, и **не содержит** win/loss.

### Новое: `coach/coach.py` (оркестратор)

```python
run_coach(matches: list[Match], account_id: int | None,
          llm: CoachLLM, cache_dir=Path("cache")) -> CoachBrief
```
Шаги: `detect_leaks` → выбрать фокус → `load_history` → `compare_focus` →
`principles_for(focus.key)` → `build_coach_prompt` → `llm.complete` → `parse_brief` →
проставить `progress_note` из `ProgressNote` → `save_brief` → вернуть `CoachBrief`.

**Выбор фокуса (детерминированно, код):** лик с наибольшим нормированным отклонением
от порога `abs(value - threshold) / threshold` («худший нарушитель»); при равенстве —
фиксированный приоритет `["feeding", "farm_below_bracket", "low_warding"]`.

**Крайний случай «ликов нет»:** возвращаем «чистый» бриф `CoachBrief(focus_leak_key="",
headline="Системных ликов по этой серии не найдено", diagnosis="", why_it_costs="",
drills=[])` **без вызова ЛЛМ**; `progress_note` заполняется из `compare_focus` (если
прошлый фокус-лик исчез — это фиксируется как «лик ушёл»); бриф **сохраняется**, чтобы
история оставалась непрерывной.

### Правка: `report.py` — `render_coach_html`

```python
render_coach_html(brief: CoachBrief, leaks: list[Leak],
                  progress: ProgressNote | None) -> str
```
Отдельная тренерская страница (в стиле существующего тёмного отчёта): headline,
диагноз, почему топит, дриллы, блок прогресса, список ликов с числами. Русский,
HTML-escape. Чистая функция → юнит-тест.

### Правка: `cli.py` — подкоманда `coach`

```
dota-coach coach --account-id ID [--n 20] [--out coach.html] [--dry-run]
```
- Обычный режим: `fetch_recent` → `fetch_match`(кеш) → `normalize` →
  `OpenAICompatibleLLM` из env → `run_coach` → `render_coach_html` → запись.
- `--dry-run`: печатает промпт и НЕ вызывает ЛЛМ (дешёвая итерация над формулировками).

## Поток данных

```
fetch_recent + fetch_match (кеш) → [Match]
  → detect_leaks → [Leak + числа]
  → выбрать focus leak
  → load_history(account_id) → prior brief
  → compare_focus(prior, leaks) → ProgressNote            [чисто, код]
  → principles_for(focus.key) → principles text
  → build_coach_prompt(leaks, progress, principles, prior) → messages  [чисто]
  → CoachLLM.complete(messages) → raw json                [склейка, кеш]
  → parse_brief(raw) → CoachBrief                          [чисто]
  → brief.progress_note = progress.text
  → save_brief(account_id, brief)                          [IO]
  → render_coach_html(brief, leaks, progress) → HTML       [чисто]
```

## Контракт JSON от ЛЛМ

```json
{
  "focus_leak_key": "feeding",
  "headline": "одна фраза-суть",
  "diagnosis": "что именно не так, со ссылкой на метрику",
  "why_it_costs": "почему это топит ММР",
  "drills": [
    {"text": "конкретный дрилл на следующие игры", "metric_ref": "deaths_per_game"}
  ]
}
```
`progress_note` в JSON от ЛЛМ **не приходит** — его ставит код из `ProgressNote`,
чтобы прогресс нельзя было выдумать.

## Тесты (TDD, как в репо)

Чистые:
- `test_leaks.py` (правка) — числовые поля в `Leak`.
- `test_coach_prompt.py` — числа/анти-исход-правило/прошлый фокус/принципы в промпте;
  win/loss отсутствует.
- `test_coach_progress.py` — улучшение/регресс/флэт по обоим направлениям; лик ушёл;
  нет истории.
- `test_coach_brief.py` — `parse_brief` на хорошем/битом JSON.
- `test_coach_history.py` — round-trip save/load через `tmp_path`.
- `test_coach_report.py` — headline/дриллы/прогресс/русский/HTML-escape.
- `test_coach_orchestrator.py` — `run_coach` с `FakeLLM` (canned JSON) end-to-end,
  без сети; проверка, что `save_brief` вызван и `progress_note` проставлен кодом.
- `test_principles.py` — `principles_for` возвращает текст по ключу + дефолт.

Не юнит-тестируется: реальный `OpenAICompatibleLLM` (сеть) — ручной смок через CLI.

## Зависимости и стоимость

- ЛЛМ через существующий `requests` на OpenAI-совместимый `/chat/completions`
  (без нового SDK). Env: `DOTA_COACH_LLM_BASE_URL/_API_KEY/_MODEL`.
- 1 вызов на прогон; кеш по хешу входа → повторы бесплатны и детерминированны.
- MVP-часть остаётся $0; ЛЛМ-инференс — копейки на GLM.

## Вне области (следующие фазы)

- Разбор одного матча ЛЛМ (нарратив по топ-моментам).
- RAG/векторная база принципов (пока курируемый `.md`).
- Витрина хай-ммр (фаза 3).
- Продуктовизация/мультиюзер.
