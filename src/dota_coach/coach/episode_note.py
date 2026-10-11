"""Deterministic manual-review note for an unvalidated legacy incident."""
from __future__ import annotations
import json
from dataclasses import dataclass

from dota_coach.coach.info_state import InfoState
from dota_coach.coach.llm import CoachLLM
from dota_coach.coach.moment_brief import _strip_code_fence
from dota_coach.episodes import Episode

_TYPE_RU = {"teamfight": "драка", "death": "смерть", "networth_swing": "изменение нетворса"}
_SYSTEM = (
    "Опиши повод для ручного просмотра. Проверенного критерия решения нет. "
    "Не устанавливай ошибку, причины или лучший ход по исходу. "
    'Верни JSON: {"situation": str, "takeaway": str}.'
)


@dataclass
class EpisodeNote:
    situation: str
    takeaway: str


def build_note_prompt(episode: Episode, grounding: str) -> list[dict]:
    # The summary and arbitrary grounding may contain future/hidden truth.
    ev = episode.moment.event
    kind = _TYPE_RU.get(ev.type.value, ev.type.value)
    user = (f"Повод для просмотра: {kind} на {int(ev.game_time) // 60}:{int(ev.game_time) % 60:02d}.\n"
            "Недостаточно данных для оценки решения; нужен ручной просмотр.")
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


def parse_note(raw: str | dict) -> EpisodeNote:
    data = json.loads(_strip_code_fence(raw)) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("episode note должен быть JSON-объектом")
    return EpisodeNote(situation=str(data.get("situation", "")).strip(),
                       takeaway=str(data.get("takeaway", "")).strip())


def explain_note(episode: Episode, info: InfoState | None, llm: CoachLLM) -> EpisodeNote:
    ev = episode.moment.event
    kind = _TYPE_RU.get(ev.type.value, ev.type.value)
    return EpisodeNote(
        situation=f"{kind.capitalize()} на {int(ev.game_time) // 60}:{int(ev.game_time) % 60:02d} — повод для просмотра. "
                  "Недостаточно данных для оценки решения: проверенный критерий отсутствует.",
        takeaway="На записи проверь информацию до выбора, ресурсы, ограничения и доступные действия.",
    )
