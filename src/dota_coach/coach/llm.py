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
