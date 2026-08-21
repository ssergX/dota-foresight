from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Protocol

import requests


class CoachLLM(Protocol):
    def complete(self, messages: list[dict]) -> str: ...


def _messages_hash(messages: list[dict]) -> str:
    blob = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cached(cache_dir: Path, messages: list[dict], produce) -> str:
    """Дисковый кеш ответа ЛЛМ по хешу входных сообщений."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_messages_hash(messages)}.json"
    if path.exists():
        return path.read_text(encoding="utf-8")
    content = produce()
    path.write_text(content, encoding="utf-8")
    return content


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
        self.base_url = (base_url or os.environ.get("DOTA_COACH_LLM_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or os.environ.get("DOTA_COACH_LLM_API_KEY")
        self.model = model or os.environ.get("DOTA_COACH_LLM_MODEL")
        if not self.base_url or not self.api_key or not self.model:
            raise ValueError(
                "нужны переменные окружения DOTA_COACH_LLM_BASE_URL, "
                "DOTA_COACH_LLM_API_KEY, DOTA_COACH_LLM_MODEL"
            )
        self.cache_dir = cache_dir
        self.timeout = timeout

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
                 timeout: float = 180.0, runner=None):
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


def make_llm(provider: str | None = None) -> CoachLLM:
    """Выбор провайдера ЛЛМ: аргумент → env DOTA_COACH_LLM_PROVIDER → дефолт claude."""
    provider = (provider or os.environ.get("DOTA_COACH_LLM_PROVIDER") or "claude").lower()
    if provider == "claude":
        return ClaudeCliLLM()
    if provider in ("openai", "glm"):
        return OpenAICompatibleLLM()
    raise ValueError(f"неизвестный провайдер ЛЛМ: {provider!r} (ожидалось claude|openai)")
