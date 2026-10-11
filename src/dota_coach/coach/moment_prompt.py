"""Legacy incident prompt. Unstructured data has no verified knowledge boundary."""
from __future__ import annotations
from dota_coach.models import ScoredMoment

_SYSTEM = (
    "Ты редактируешь описание повода для ручного просмотра Dota 2. "
    "Проверенного критерия решения нет. Не устанавливай ошибку, причину или лучший ход; "
    "не формулируй гипотезу о поведении игрока по исходу. "
    'Верни JSON: {"headline": str, "hypothesis": str, "process_question": str, '
    '"checklist": [str], "principle": str}. Укажи недостаток данных.'
)


def build_moment_prompt(moment: ScoredMoment, principle: str, info_block: str = "") -> list[dict]:
    # Summaries, reasons, event.data and arbitrary strings can carry future/hidden truth.
    ev = moment.event
    user = (
        f"Повод для просмотра: {ev.type.value}, {int(ev.game_time) // 60}:{int(ev.game_time) % 60:02d}.\n"
        "Статус: not_enough_info. Проверенный критерий отсутствует.\n"
        "Проверь на записи доступную до выбора информацию, ресурсы и возможные действия."
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
