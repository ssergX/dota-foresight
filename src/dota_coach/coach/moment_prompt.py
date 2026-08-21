from __future__ import annotations

from dota_coach.models import ScoredMoment

_SYSTEM = (
    "Ты — строгий, честный тренер по Dota 2. Разбираешь ОДИН ключевой момент матча.\n"
    "Жёсткие правила:\n"
    "1. Судишь процесс и решение по входным данным, НИКОГДА по исходу матча. "
    "Побед/поражений тебе не дают — не рассуждай о них. Про сами драки/размены тоже "
    "пиши нейтрально (размен удался/не удался, зашёл с информацией/вслепую), а не в "
    "терминах итога.\n"
    "2. Данные о моменте тонкие — ты НЕ видел геймплей. Формулируй ГИПОТЕЗУ («вероятно…»), "
    "а не факт. Уважай вердикт детектора: если not_enough_info — прямо скажи, что нужен "
    "ручной просмотр, и дай что проверить, без обвинений.\n"
    "3. Дай 2–3 пункта конкретного проверяемого чеклиста (что посмотреть, в т.ч. на записи).\n"
    "4. Пиши по-русски.\n"
    "Верни СТРОГО JSON-объект такой формы (без markdown-обёртки):\n"
    '{"headline": str, "hypothesis": str, "process_question": str, '
    '"checklist": [str], "principle": str}'
)


def _fmt_time(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


def build_moment_prompt(moment: ScoredMoment, principle: str) -> list[dict]:
    ev = moment.event
    reasons = "; ".join(moment.reasons) or "(нет)"
    numbers = ", ".join(f"{k}={v}" for k, v in ev.data.items()) or "(нет)"
    user = (
        "Фокус-момент матча:\n"
        f"- тип: {ev.type.value}\n"
        f"- время: {_fmt_time(ev.game_time)}\n"
        f"- вердикт детектора: {moment.verdict.value}\n"
        f"- причины разметки: {reasons}\n"
        f"- числа: {numbers}\n\n"
        f"Тренерский принцип для момента этого типа:\n{principle}\n\n"
        "Разбери этот момент строго в заданном JSON-формате."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
