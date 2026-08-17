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
