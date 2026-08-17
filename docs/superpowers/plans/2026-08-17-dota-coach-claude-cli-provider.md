# Claude Code CLI провайдер для ЛЛМ-тренера — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить провайдер `ClaudeCliLLM`, который дёргает `claude -p --output-format json` в счёт подписки Claude, и сделать его дефолтным (GLM/OpenAI — выбираемый запасной).

**Architecture:** Новый класс `ClaudeCliLLM` реализует тот же контракт `CoachLLM.complete(messages)->str`, что и существующий `OpenAICompatibleLLM`. Внутри — инъектируемый раннер `(argv, stdin, timeout)->(rc, out, err)` для тестируемости без запуска настоящего claude. Общий дисковый кеш выносится в free-функцию `_cached`. Фабрика `make_llm(provider)` выбирает провайдера; CLI зовёт её вместо хардкода.

**Tech Stack:** Python 3.12, `subprocess`, `pytest` (pythonpath=src), Claude Code CLI (`claude`).

## Global Constraints

- Контракт провайдера: `complete(messages: list[dict]) -> str`, где `messages` — список `{"role": str, "content": str}`, возврат — строка (обычно JSON-объект), которую дальше парсит `parse_brief`.
- Аутентификация claude — **только подписка (OAuth)**. Никакого `ANTHROPIC_API_KEY`, **никакого `--bare`** (он форсит API-ключ и ломает счёт-в-подписку).
- Точный вызов (сверено смоком 2026-08-17): `claude -p --output-format json --disallowed-tools "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Task"`, промпт — на **stdin**. Конверт ответа: `{"is_error": bool, "result": str, ...}`.
- Дефолтный провайдер — `claude`; `openai`/`glm` — запасной. Выбор: аргумент `make_llm(provider)` → env `DOTA_COACH_LLM_PROVIDER` → дефолт `claude`.
- Бинарь claude: `DOTA_COACH_CLAUDE_BIN` → дефолт `"claude"`.
- Кеш общий на оба провайдера (папка `cache/coach_llm`, ключ = `_messages_hash`).
- Тесты: реальный subprocess/сеть не гоняем (конвенция репо); чистые части — через инъекцию раннера/`produce`.
- Стиль: black line-length по проекту, комментарии по-русски как в окружающем коде.
- Команда тестов: `pytest` из корня репозитория `C:\Users\user\PycharmProjects\dota-coach`.

---

### Task 1: Общий кеш-хелпер `_cached` + перевод `OpenAICompatibleLLM` на него

**Files:**
- Modify: `src/dota_coach/coach/llm.py` (добавить `_cached`; переписать `OpenAICompatibleLLM.complete`, вынести `_post`)
- Test: `tests/test_coach_llm.py` (добавить тест `_cached`)

**Interfaces:**
- Consumes: `_messages_hash(messages) -> str` (уже есть в `llm.py`).
- Produces: `_cached(cache_dir: Path, messages: list[dict], produce: Callable[[], str]) -> str`.

- [ ] **Step 1: Написать падающий тест `_cached`**

В `tests/test_coach_llm.py` добавить в начало файла импорт `import json` и `import pytest` (если ещё нет), затем тест:

```python
def test_cached_produces_once_then_reads_from_disk(tmp_path):
    from dota_coach.coach.llm import _cached

    msgs = [{"role": "user", "content": "hi"}]
    calls = []

    def produce():
        calls.append(1)
        return "RESULT"

    first = _cached(tmp_path, msgs, produce)
    second = _cached(tmp_path, msgs, produce)
    assert first == "RESULT"
    assert second == "RESULT"
    assert len(calls) == 1  # второй вызов читает файл, produce не зовётся
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `pytest tests/test_coach_llm.py::test_cached_produces_once_then_reads_from_disk -v`
Expected: FAIL — `ImportError: cannot import name '_cached'`.

- [ ] **Step 3: Реализовать `_cached` и перевести `OpenAICompatibleLLM` на него**

В `src/dota_coach/coach/llm.py` после функции `_messages_hash` добавить:

```python
def _cached(cache_dir: Path, messages: list[dict], produce) -> str:
    """Дисковый кеш ответа ЛЛМ по хешу входных сообщений."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_messages_hash(messages)}.json"
    if path.exists():
        return path.read_text(encoding="utf-8")
    content = produce()
    path.write_text(content, encoding="utf-8")
    return content
```

Заменить тело `OpenAICompatibleLLM.complete` и вынести сетевой вызов в `_post`:

```python
    def complete(self, messages: list[dict]) -> str:
        return _cached(self.cache_dir, messages, lambda: self._post(messages))

    def _post(self, messages: list[dict]) -> str:
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
        return resp.json()["choices"][0]["message"]["content"]
```

- [ ] **Step 4: Запустить тесты — убедиться, что зелёные**

Run: `pytest tests/test_coach_llm.py -v`
Expected: PASS (новый тест + существующие `FakeLLM`/`_messages_hash`).

- [ ] **Step 5: Коммит**

```bash
git add src/dota_coach/coach/llm.py tests/test_coach_llm.py
git commit -m "refactor(coach): вынести дисковый кеш ЛЛМ в _cached"
```

---

### Task 2: `ClaudeCliLLM` — маппинг сообщений, вызов, извлечение result, кеш

**Files:**
- Modify: `src/dota_coach/coach/llm.py` (добавить `import os, subprocess`, если нет; `_CLAUDE_DISALLOWED_TOOLS`, `_default_runner`, класс `ClaudeCliLLM`)
- Test: `tests/test_coach_llm.py`

**Interfaces:**
- Consumes: `_cached` (Task 1).
- Produces:
  - `_default_runner(argv: list[str], stdin_text: str, timeout: float) -> tuple[int, str, str]`
  - `ClaudeCliLLM(claude_bin: str | None = None, cache_dir: Path = Path("cache")/"coach_llm", timeout: float = 120.0, runner=None)` с методом `complete(messages) -> str`. `runner` имеет сигнатуру `_default_runner`.

- [ ] **Step 1: Написать падающие тесты (маппинг+happy-path+кеш)**

В `tests/test_coach_llm.py` добавить вспомогательный фейк-раннер и тесты:

```python
class _FakeRunner:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.rc, self.stdout, self.stderr = rc, stdout, stderr
        self.calls = []

    def __call__(self, argv, stdin_text, timeout):
        self.calls.append((argv, stdin_text, timeout))
        return self.rc, self.stdout, self.stderr


def test_claude_cli_maps_messages_and_returns_result(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    envelope = json.dumps(
        {"type": "result", "is_error": False, "result": '{"focus_leak_key":"feeding"}'}
    )
    runner = _FakeRunner(rc=0, stdout=envelope)
    llm = ClaudeCliLLM(claude_bin="claude", cache_dir=tmp_path, runner=runner)

    out = llm.complete(
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USR"}]
    )
    assert out == '{"focus_leak_key":"feeding"}'

    argv, stdin_text, timeout = runner.calls[0]
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--disallowed-tools" in argv
    assert stdin_text == "SYS\n\nUSR"


def test_claude_cli_caches_second_call(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    runner = _FakeRunner(rc=0, stdout=json.dumps({"is_error": False, "result": "R"}))
    msgs = [{"role": "user", "content": "hi"}]
    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=runner)

    llm.complete(msgs)
    llm.complete(msgs)
    assert len(runner.calls) == 1  # второй раз — из кеша
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `pytest tests/test_coach_llm.py::test_claude_cli_maps_messages_and_returns_result -v`
Expected: FAIL — `ImportError: cannot import name 'ClaudeCliLLM'`.

- [ ] **Step 3: Реализовать `ClaudeCliLLM`, `_default_runner`, константу**

В шапке `src/dota_coach/coach/llm.py` убедиться, что есть `import os`, `import subprocess` (добавить `subprocess`, если отсутствует).

После `OpenAICompatibleLLM` добавить:

```python
_CLAUDE_DISALLOWED_TOOLS = "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Task"


def _default_runner(argv: list[str], stdin_text: str, timeout: float) -> tuple[int, str, str]:
    """Реальный запуск claude (без юнит-тестов, как сетевой путь)."""
    proc = subprocess.run(
        argv, input=stdin_text, capture_output=True, text=True,
        encoding="utf-8", timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


class ClaudeCliLLM:
    """Провайдер через Claude Code CLI (claude -p), в счёт подписки. Раннер инъектируется."""

    def __init__(self, claude_bin: str | None = None,
                 cache_dir: Path = Path("cache") / "coach_llm",
                 timeout: float = 120.0, runner=None):
        self.claude_bin = claude_bin or os.environ.get("DOTA_COACH_CLAUDE_BIN") or "claude"
        self.cache_dir = cache_dir
        self.timeout = timeout
        self._run = runner or _default_runner

    def complete(self, messages: list[dict]) -> str:
        return _cached(self.cache_dir, messages, lambda: self._invoke(messages))

    def _invoke(self, messages: list[dict]) -> str:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user = "\n".join(m["content"] for m in messages if m["role"] == "user")
        prompt = f"{system}\n\n{user}" if system else user

        argv = [
            self.claude_bin, "-p", "--output-format", "json",
            "--disallowed-tools", _CLAUDE_DISALLOWED_TOOLS,
        ]
        rc, out, err = self._run(argv, prompt, self.timeout)
        envelope = json.loads(out)
        result = envelope.get("result")
        return str(result)
```

Примечание: обработка ошибок (rc, is_error, пустой result, отсутствие бинаря, таймаут) добавляется в Task 3 — здесь минимальная реализация под happy-path тесты.

- [ ] **Step 4: Запустить тесты — зелёные**

Run: `pytest tests/test_coach_llm.py -v`
Expected: PASS (оба новых теста + предыдущие).

- [ ] **Step 5: Коммит**

```bash
git add src/dota_coach/coach/llm.py tests/test_coach_llm.py
git commit -m "feat(coach): ClaudeCliLLM — вызов claude -p, маппинг сообщений, кеш"
```

---

### Task 3: Обработка ошибок в `ClaudeCliLLM`

**Files:**
- Modify: `src/dota_coach/coach/llm.py` (`ClaudeCliLLM._invoke`)
- Test: `tests/test_coach_llm.py`

**Interfaces:**
- Consumes/Produces: тот же `ClaudeCliLLM._invoke`; поведение — кидает `RuntimeError` с понятным текстом.

- [ ] **Step 1: Написать падающие тесты ошибок**

В `tests/test_coach_llm.py` добавить:

```python
def test_claude_cli_raises_on_nonzero_rc(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    runner = _FakeRunner(rc=1, stdout="", stderr="boom")
    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=runner)
    with pytest.raises(RuntimeError, match="boom"):
        llm.complete([{"role": "user", "content": "x"}])


def test_claude_cli_raises_on_is_error(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    runner = _FakeRunner(rc=0, stdout=json.dumps({"is_error": True, "result": "denied"}))
    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=runner)
    with pytest.raises(RuntimeError, match="denied"):
        llm.complete([{"role": "user", "content": "x"}])


def test_claude_cli_raises_on_empty_result(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    runner = _FakeRunner(rc=0, stdout=json.dumps({"is_error": False, "result": "  "}))
    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=runner)
    with pytest.raises(RuntimeError):
        llm.complete([{"role": "user", "content": "x"}])


def test_claude_cli_raises_clear_error_when_binary_missing(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    def missing_runner(argv, stdin_text, timeout):
        raise FileNotFoundError(argv[0])

    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=missing_runner)
    with pytest.raises(RuntimeError, match="claude не найден"):
        llm.complete([{"role": "user", "content": "x"}])
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `pytest tests/test_coach_llm.py -k "raises" -v`
Expected: FAIL (текущий `_invoke` не проверяет rc/is_error/пустоту и не ловит FileNotFoundError).

- [ ] **Step 3: Добавить ветки ошибок в `_invoke`**

Заменить тело `ClaudeCliLLM._invoke` на полную версию:

```python
    def _invoke(self, messages: list[dict]) -> str:
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user = "\n".join(m["content"] for m in messages if m["role"] == "user")
        prompt = f"{system}\n\n{user}" if system else user

        argv = [
            self.claude_bin, "-p", "--output-format", "json",
            "--disallowed-tools", _CLAUDE_DISALLOWED_TOOLS,
        ]
        try:
            rc, out, err = self._run(argv, prompt, self.timeout)
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"claude не найден ({self.claude_bin!r}): поставь @anthropic-ai/claude-code "
                "и залогинься подпиской, либо используй --provider openai"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"claude -p не ответил за {self.timeout}s") from exc

        if rc != 0:
            raise RuntimeError(f"claude -p завершился с кодом {rc}: {err.strip()[:500]}")
        envelope = json.loads(out)
        if envelope.get("is_error"):
            raise RuntimeError(f"claude вернул ошибку: {str(envelope.get('result', ''))[:500]}")
        result = envelope.get("result")
        if not result or not str(result).strip():
            raise RuntimeError("claude -p вернул пустой result")
        return str(result)
```

- [ ] **Step 4: Запустить тесты — зелёные**

Run: `pytest tests/test_coach_llm.py -v`
Expected: PASS (все тесты llm, включая happy-path из Task 2).

- [ ] **Step 5: Коммит**

```bash
git add src/dota_coach/coach/llm.py tests/test_coach_llm.py
git commit -m "feat(coach): понятные ошибки ClaudeCliLLM (rc/is_error/пусто/нет бинаря/таймаут)"
```

---

### Task 4: Фабрика `make_llm`

**Files:**
- Modify: `src/dota_coach/coach/llm.py` (добавить `make_llm`)
- Test: `tests/test_coach_llm.py`

**Interfaces:**
- Consumes: `ClaudeCliLLM` (Task 2), `OpenAICompatibleLLM` (существует).
- Produces: `make_llm(provider: str | None = None) -> CoachLLM`.

- [ ] **Step 1: Написать падающие тесты фабрики**

```python
def test_make_llm_defaults_to_claude(monkeypatch):
    from dota_coach.coach.llm import make_llm, ClaudeCliLLM

    monkeypatch.delenv("DOTA_COACH_LLM_PROVIDER", raising=False)
    assert isinstance(make_llm(), ClaudeCliLLM)


def test_make_llm_openai_when_selected(monkeypatch):
    from dota_coach.coach.llm import make_llm, OpenAICompatibleLLM

    monkeypatch.setenv("DOTA_COACH_LLM_BASE_URL", "http://x")
    monkeypatch.setenv("DOTA_COACH_LLM_API_KEY", "k")
    monkeypatch.setenv("DOTA_COACH_LLM_MODEL", "m")
    assert isinstance(make_llm("openai"), OpenAICompatibleLLM)


def test_make_llm_reads_env_default(monkeypatch):
    from dota_coach.coach.llm import make_llm, OpenAICompatibleLLM

    monkeypatch.setenv("DOTA_COACH_LLM_PROVIDER", "openai")
    monkeypatch.setenv("DOTA_COACH_LLM_BASE_URL", "http://x")
    monkeypatch.setenv("DOTA_COACH_LLM_API_KEY", "k")
    monkeypatch.setenv("DOTA_COACH_LLM_MODEL", "m")
    assert isinstance(make_llm(), OpenAICompatibleLLM)


def test_make_llm_unknown_provider_raises(monkeypatch):
    from dota_coach.coach.llm import make_llm

    monkeypatch.delenv("DOTA_COACH_LLM_PROVIDER", raising=False)
    with pytest.raises(ValueError):
        make_llm("gemini")
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `pytest tests/test_coach_llm.py -k make_llm -v`
Expected: FAIL — `ImportError: cannot import name 'make_llm'`.

- [ ] **Step 3: Реализовать `make_llm`**

В конец `src/dota_coach/coach/llm.py` добавить:

```python
def make_llm(provider: str | None = None) -> CoachLLM:
    """Выбор провайдера ЛЛМ: аргумент → env DOTA_COACH_LLM_PROVIDER → дефолт claude."""
    provider = (provider or os.environ.get("DOTA_COACH_LLM_PROVIDER") or "claude").lower()
    if provider == "claude":
        return ClaudeCliLLM()
    if provider in ("openai", "glm"):
        return OpenAICompatibleLLM()
    raise ValueError(f"неизвестный провайдер ЛЛМ: {provider!r} (ожидалось claude|openai)")
```

- [ ] **Step 4: Запустить тесты — зелёные**

Run: `pytest tests/test_coach_llm.py -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add src/dota_coach/coach/llm.py tests/test_coach_llm.py
git commit -m "feat(coach): make_llm — выбор провайдера (дефолт claude)"
```

---

### Task 5: Подключить `make_llm` в CLI + флаг `--provider`

**Files:**
- Modify: `src/dota_coach/cli.py` (вынести `build_parser()`; `_cmd_coach` зовёт `make_llm`; добавить `--provider`)
- Test: `tests/test_cli_provider.py` (создать)

**Interfaces:**
- Consumes: `make_llm` (Task 4).
- Produces: `build_parser() -> argparse.ArgumentParser`; у подкоманды `coach` появляется `args.provider` (default `None`).

- [ ] **Step 1: Написать падающий тест парсера**

Создать `tests/test_cli_provider.py`:

```python
def test_coach_parser_accepts_provider():
    from dota_coach.cli import build_parser

    args = build_parser().parse_args(["coach", "--account-id", "1", "--provider", "openai"])
    assert args.provider == "openai"


def test_coach_parser_provider_defaults_none():
    from dota_coach.cli import build_parser

    args = build_parser().parse_args(["coach", "--account-id", "1"])
    assert args.provider is None
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `pytest tests/test_cli_provider.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_parser'`.

- [ ] **Step 3: Вынести `build_parser`, добавить `--provider`, перевести `_cmd_coach` на `make_llm`**

В `src/dota_coach/cli.py`:

а) В `_cmd_coach` заменить импорт и создание провайдера. Было:
```python
    try:
        from dota_coach.coach.coach import run_coach
        from dota_coach.coach.llm import OpenAICompatibleLLM

        brief = run_coach(matches, args.account_id, OpenAICompatibleLLM())
```
Стало:
```python
    try:
        from dota_coach.coach.coach import run_coach
        from dota_coach.coach.llm import make_llm

        brief = run_coach(matches, args.account_id, make_llm(args.provider))
```

б) Вынести построение парсера из `main` в `build_parser` и добавить `--provider` в подкоманду `coach`. Заменить функцию `main` на:
```python
def build_parser() -> argparse.ArgumentParser:
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

    c = sub.add_parser("coach", help="системный ЛЛМ-разбор по серии матчей")
    c.add_argument("--account-id", type=int, required=True, dest="account_id")
    c.add_argument("--n", type=int, default=20)
    c.add_argument("--out", default="coach.html")
    c.add_argument("--dry-run", action="store_true", dest="dry_run")
    c.add_argument(
        "--provider", default=None,
        help="claude|openai; по умолчанию claude (env DOTA_COACH_LLM_PROVIDER)",
    )
    c.set_defaults(func=_cmd_coach)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
```

- [ ] **Step 4: Запустить тесты — зелёные**

Run: `pytest tests/test_cli_provider.py -v`
Expected: PASS (оба теста).

- [ ] **Step 5: Коммит**

```bash
git add src/dota_coach/cli.py tests/test_cli_provider.py
git commit -m "feat(cli): coach --provider через make_llm (дефолт claude)"
```

---

### Task 6: Финальная проверка всего пакета + ручной смок

**Files:** нет изменений кода (проверочная задача).

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `pytest -q`
Expected: PASS, все тесты зелёные (не только coach_llm — убедиться, что рефактор ничего не сломал).

- [ ] **Step 2: Проверить, что `--provider` виден в справке**

Run: `python -m dota_coach.cli coach --help`
Expected: в выводе есть строка `--provider` с описанием `claude|openai`.

- [ ] **Step 3: Ручной смок реального провайдера (вне CI, требует залогиненного подпиской claude)**

Предусловие: `claude` залогинен подпиской (OAuth). При необходимости указать бинарь:
`export DOTA_COACH_CLAUDE_BIN="C:/Users/user/.local/bin/claude.exe"` (Windows).

Run: `python -m dota_coach.cli coach --account-id <ВАШ_ACCOUNT_ID> --out coach.html`
Expected: печатает `coach brief over N matches -> coach.html`; файл `coach.html` создан и содержит осмысленный бриф. Если ликов нет — «Системных ликов по этой серии не найдено» (это норма, ЛЛМ не зовётся).

- [ ] **Step 4: Коммит (если правились доки/заметки по итогам смока)**

```bash
git add -A
git commit -m "chore(coach): заметки по смоку claude-провайдера" || echo "нечего коммитить"
```

---

## Заметки по реализации

- Кеш общий: если во время смока `claude` вернул мусор и он закешировался — удалить `cache/coach_llm/<hash>.json` перед повтором.
- Стоимость: смок-вызов из тяжёлого проектного контекста создаёт ~22k cache-токенов; для дешевизны звать из dota-coach (лёгкий контекст). `--bare` НЕ добавлять (форсит API-ключ).
- Модель claude по умолчанию берётся из настроек CLI; при желании пин модели — отдельная задача (вне скоупа).
