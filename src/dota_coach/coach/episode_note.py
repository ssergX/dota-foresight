"""Короткий тренерский комментарий на ОДИН эпизод (ситуация + вывод/совет).

Пишет LLM по-эпизодно (отдельный вызов на эпизод — модель не видит дугу матча,
исход не течёт). Заземлён на богатый info_state (вижн, расклад сил, позиция).
Клип показывает картинку — текст даёт СМЫСЛ (что за ситуация, где вероятно ошибка).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from dota_coach.coach.info_state import InfoState, render_knowable
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import _strip_code_fence
from dota_coach.episodes import Episode

_TYPE_RU = {
    "teamfight": "тимфайт",
    "death": "твоя смерть",
    "networth_swing": "просадка золота",
}

_SYSTEM = (
    "Ты — сильный честный тренер по Dota 2. По ОДНОМУ моменту матча дай КОРОТКИЙ разбор: "
    "опиши ситуацию своими словами и главный вывод/совет. Клип игрок уже видит — не "
    "пересказывай картинку, дай СМЫСЛ.\n"
    "Правила:\n"
    "1. Судишь по тому, что игрок МОГ ЗНАТЬ (вижн, свои союзники, своя позиция/ресурсы), "
    "НИКОГДА по исходу матча. Побед/поражений тебе не дают — не рассуждай о них. Размены "
    "описывай нейтрально (зашёл с информацией/вслепую, в большинстве/меньшинстве).\n"
    "2. Тебе дают ТОЛЬКО то, что игрок мог знать в точке решения (вижн, свои союзники, "
    "позиция, ресурсы). Чего он не видел — ты тоже не знаешь: не выдумывай, где стояли "
    "скрытые враги; если это важно, скажи, что стоило заподозрить/проверить.\n"
    "3. Геймплей ты не видел — вывод это ГИПОТЕЗА («вероятно…»). Дай КОНКРЕТНЫЙ совет под "
    "эту ситуацию. Общие фразы («играй аккуратнее», «улучшай позиционку», «фарми лучше») "
    "ЗАПРЕЩЕНЫ — совет должен цепляться за факты момента (позицию, вижн, расклад).\n"
    "4. Коротко: situation — 1–2 предложения; takeaway — одно предложение конкретного "
    "действия. По-русски.\n"
    'Верни СТРОГО JSON (без markdown): {"situation": str, "takeaway": str}'
)


@dataclass
class EpisodeNote:
    situation: str
    takeaway: str


def build_note_prompt(episode: Episode, grounding: str) -> list[dict]:
    ev = episode.moment.event
    kind = _TYPE_RU.get(ev.type.value, ev.type.value)
    ts = f"{ev.game_time // 60}:{ev.game_time % 60:02d}"
    user = (
        f"Момент: {kind} на {ts}. {ev.summary}\n\n"
        f"{grounding}\n\n"
        "Разбери строго в заданном JSON-формате."
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def parse_note(raw: str | dict) -> EpisodeNote:
    data = json.loads(_strip_code_fence(raw)) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("episode note должен быть JSON-объектом")
    return EpisodeNote(situation=str(data.get("situation", "")).strip(),
                       takeaway=str(data.get("takeaway", "")).strip())


def explain_note(episode: Episode, info: InfoState | None, llm: CoachLLM) -> EpisodeNote:
    grounding = render_knowable(info) if info is not None else episode.moment.event.summary
    messages = build_note_prompt(episode, grounding)
    return parse_note(llm.complete(messages))
