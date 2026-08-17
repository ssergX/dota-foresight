# Dota Coach — провайдер ЛЛМ через Claude Code CLI (`claude -p`)

**Дата:** 2026-08-17
**Статус:** дизайн утверждён, готов к плану реализации

## Задача

Сейчас ЛЛМ-тренер (`coach/`) ходит только в платный OpenAI-совместимый эндпоинт
(`OpenAICompatibleLLM`, дефолт GLM), требующий `DOTA_COACH_LLM_*` и списывающий деньги
за каждый вызов. Нужно добавить провайдер, который вместо HTTP дёргает **Claude Code CLI
в headless-режиме** (`claude -p`) — как это делает командный дайджест-бот Tablichki
(`scripts/team_digest/run_digest.sh`: `printf '%s' "$DATA" | claude -p "$(cat prompt.txt)"`).
Смысл: вызовы идут **в счёт подписки Claude (OAuth), а не за API-кредиты** — фактически
бесплатно для юзера №1.

## Решения (утверждены при брейнсторме)

1. **Дефолтный провайдер — `claude`.** GLM/OpenAI остаётся выбираемым запасным вариантом
   (когда claude не залогинен/недоступен), не удаляется.
2. **Чтение ответа — `--output-format json`**, достаём поле `result` из конверта claude;
   `result` дополнительно прогоняется через существующий `_strip_code_fence` в `parse_brief`
   (двойная страховка от ` ```json ` обёрток).
3. **Маппинг сообщений** — склейка `system` + `user` в один текст, подаётся на **stdin**
   (без argv-квотинга и лимитов длины на Windows). Роли CLI не принимает.

## Архитектура

Всё в `src/dota_coach/coach/llm.py`. Контракт `CoachLLM.complete(messages: list[dict]) -> str`
не меняется — новый провайдер взаимозаменяем со старым и с `FakeLLM`.

### Компоненты

**`ClaudeCliLLM` (новый класс)**
- Реализует `complete(messages) -> str`.
- Конструктор:
  - `claude_bin` — бинарь, дефолт `os.environ["DOTA_COACH_CLAUDE_BIN"]` или `"claude"`
    (на Windows юзер укажет `C:\Users\user\.local\bin\claude.exe`).
  - `cache_dir=Path("cache")/"coach_llm"`, `timeout=120.0`.
  - `runner` — **инъектируемый раннер** `(argv, stdin_text, timeout) -> (rc, stdout, stderr)`;
    по умолчанию `_default_runner` (обёртка над `subprocess.run`). Это тестовый шов:
    маппинг и парсинг проверяются без запуска настоящего claude.
- Аутентификация: **никакого API-ключа**. Полагается на залогиненный подпиской `claude`
  (OAuth-креды в `~/.claude` текущего пользователя).

**`_invoke(messages) -> str` (метод `ClaudeCliLLM`)**
```python
system = "\n".join(m["content"] for m in messages if m["role"] == "system")
user   = "\n".join(m["content"] for m in messages if m["role"] == "user")
prompt = f"{system}\n\n{user}" if system else user

argv = [self.claude_bin, "-p", "--output-format", "json", <флаг-глушения-тулов>]
rc, out, err = self._run(argv, prompt, self.timeout)
if rc != 0:
    raise RuntimeError(f"claude -p завершился с кодом {rc}: {err.strip()[:500]}")
envelope = json.loads(out)                 # {"type":"result","result":"...","is_error":false,...}
if envelope.get("is_error"):
    raise RuntimeError(f"claude вернул ошибку: {str(envelope.get('result',''))[:500]}")
result = envelope.get("result")
if not result or not str(result).strip():
    raise RuntimeError("claude -p вернул пустой result")
return str(result)                         # parse_brief снимет ```-обёртку сам
```
- **Глушение тулов**: в argv добавляется флаг, запрещающий Claude Code лезть в инструменты
  (Read/Bash и т.п.) — нам нужен только текст. Точное имя флага (`--disallowedTools "*"`
  или актуальный эквивалент) **сверяется смоком с установленной версией claude на этапе
  реализации** (см. «Открытые сверки»).
- **`_default_runner`**: `subprocess.run(argv, input=prompt, capture_output=True, text=True,
  encoding="utf-8", timeout=timeout)` → `(proc.returncode, proc.stdout, proc.stderr)`.

**`_cached(cache_dir, messages, produce) -> str` (новая free-функция)**
- Убирает дублирование дискового кеша: `mkdir` → если файл `<hash>.json` есть, вернуть его;
  иначе `content = produce()`, записать, вернуть. Ключ — существующий `_messages_hash`.
- `OpenAICompatibleLLM.complete` переписывается на `_cached(..., lambda: self._post(messages))`;
  сетевой POST выносится в приватный `_post`. **Поведение GLM-пути не меняется** (тот же
  кеш по хешу входа) — существующие тесты остаются зелёными.
- **Кеш общий на оба провайдера** (одна папка, ключ = хеш сообщений). Закешированный ответ
  одного провайдера отдаётся и другому на тех же сообщениях — это осознанно (меньше платных
  вызовов). При необходимости строгого разделения позже добавить префикс провайдера в имя
  файла; **по умолчанию — общий кеш.**

**`make_llm(provider=None) -> CoachLLM` (новая фабрика)**
```python
provider = (provider or os.environ.get("DOTA_COACH_LLM_PROVIDER") or "claude").lower()
if provider == "claude":            return ClaudeCliLLM()
if provider in ("openai", "glm"):   return OpenAICompatibleLLM()
raise ValueError(f"неизвестный провайдер ЛЛМ: {provider!r} (ожидалось claude|openai)")
```

### Поток данных

```
detect_leaks → build_coach_prompt (system+user) → make_llm(provider).complete(messages)
   → [ClaudeCliLLM] склейка → stdin → claude -p --output-format json → result
   → parse_brief (_strip_code_fence + json) → CoachBrief → render_coach_html
```

Код (не ЛЛМ) по-прежнему ставит фокус/снимок метрики/прогресс в `run_coach` — эта петля
подотчётности не затрагивается.

## Изменения в CLI (`cli.py`)

- `_cmd_coach`: `OpenAICompatibleLLM()` → `make_llm(args.provider)`; импорт `make_llm`
  вместо `OpenAICompatibleLLM`.
- Новый аргумент подкоманды `coach`:
  `--provider` (default `None`, help: «claude|openai; по умолч. claude / env DOTA_COACH_LLM_PROVIDER»).
- `--dry-run` не трогается (ЛЛМ не зовёт).
- Существующая CLI-граница (`except Exception → print + return 1`) уже ловит наши
  `RuntimeError`/`ValueError` и печатает чистое сообщение.

## Обработка ошибок

`ClaudeCliLLM` кидает `RuntimeError` с понятным текстом на:
- ненулевой код возврата (с хвостом stderr, обрезка 500 символов);
- `is_error: true` в конверте;
- пустой `result`;
- `subprocess.TimeoutExpired` (оборачивается в `RuntimeError`);
- `FileNotFoundError` — claude не найден: «поставь `@anthropic-ai/claude-code` и залогинься
  подпиской, либо `--provider openai`».

`make_llm` на неизвестном провайдере — `ValueError`. Всё всплывает в CLI-границе `_cmd_coach`.

## Тестирование

Сетевой/subprocess-слой реального запуска не юнит-тестируется (конвенция репо: как
`opendota.py` и сетевой путь `OpenAICompatibleLLM`). Тестируем чистые части через инъекцию
`runner`. Дописать в `tests/test_coach_llm.py`:

- **argv/stdin**: `ClaudeCliLLM(runner=fake).complete(msgs)` → в argv есть бинарь, `-p`,
  `--output-format`, `json`, флаг-глушения-тулов; stdin == склейка system+user (в правильном
  порядке, `\n\n` между блоками).
- **happy-path**: раннер отдаёт `(0, '{"result":"{...}","is_error":false}', "")` →
  `complete` возвращает содержимое `result`.
- **is_error** → `RuntimeError`.
- **пустой `result`** → `RuntimeError`.
- **rc ≠ 0** → `RuntimeError` (в тексте есть stderr).
- **кеш**: второй `complete` с теми же сообщениями не зовёт раннер (счётчик вызовов фейка == 1).
- **`make_llm`**: `"claude"` → `ClaudeCliLLM`; `"openai"` при выставленных `DOTA_COACH_LLM_*`
  → `OpenAICompatibleLLM`; дефолт берётся из `DOTA_COACH_LLM_PROVIDER`; мусор → `ValueError`.
- **`_cached`**: `produce` зовётся один раз, второй вызов читает файл.

Существующие тесты (`FakeLLM`, `_messages_hash`, GLM-путь) остаются зелёными.

**Ручной смок (не в CI):**
1. `claude -p --output-format json` на тестовом промпте — сверить структуру конверта
   (`result`, `is_error`) и рабочий флаг глушения тулов на установленной версии.
2. `dota-coach coach --account-id <ID>` с залогиненным подпиской `claude` — живой бриф.

## Открытые сверки (на этапе реализации, до/во время кода)

- Точная структура конверта `claude -p --output-format json` (имя поля результата, наличие
  `is_error`) — смоком.
- Точный флаг запрета инструментов (`--disallowedTools` vs эквивалент) — смоком.
- Читает ли `claude -p` промпт из stdin без позиционного аргумента, или нужен `-p -`
  / пустой позиционный — смоком; если нет, промпт уходит `-p <combined>` (тогда учесть
  Windows-квотинг — передать через временный механизм, не argv напрямую).

## Вне скоупа (YAGNI)

- Стриминг ответа, повторные попытки/бэкофф, учёт стоимости из конверта claude.
- Разделение кеша по провайдерам (общий по умолчанию).
- Правка `OpenAICompatibleLLM` сверх выноса `_post` и перевода на `_cached`.
