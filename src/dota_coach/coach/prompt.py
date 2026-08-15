from __future__ import annotations

from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.progress import ProgressNote
from dota_coach.models import Leak

_SYSTEM = (
    "Ты — строгий, честный тренер по Dota 2. Разбираешь СЕРИЮ последних игр игрока.\n"
    "Жёсткие правила:\n"
    "1. Судишь процесс и решения по входным метрикам, НИКОГДА по исходу матча. "
    "Побед/поражений тебе не дают — не рассуждай о них.\n"
    "2. Не выдумывай числа. Используй только приведённые метрики. Каждый тезис и "
    "каждый дрилл привязывай к конкретной метрике (её ключ клади в metric_ref).\n"
    "3. Дай 1–2 конкретных, проверяемых дрилла на следующие игры. Без воды.\n"
    "4. Пиши по-русски.\n"
    "Верни СТРОГО JSON-объект такой формы (без markdown-обёртки):\n"
    '{"focus_leak_key": str, "headline": str, "diagnosis": str, '
    '"why_it_costs": str, "drills": [{"text": str, "metric_ref": str}]}'
)


def _leaks_block(leaks: list[Leak]) -> str:
    if not leaks:
        return "(ликов не обнаружено)"
    lines = [
        f"- key={leak.key} | {leak.title} | metric={leak.metric} | "
        f"value={leak.value:.3f} | threshold={leak.threshold:.3f} | "
        f"direction={leak.direction} | примеры_матчей={leak.example_matches}"
        for leak in leaks
    ]
    return "\n".join(lines)


def _progress_block(progress: ProgressNote | None, prior: CoachBrief | None) -> str:
    if prior is None or progress is None or progress.status == "no_history":
        return "Прошлого разбора нет — это базовая точка отсчёта."
    return f"Прошлый фокус: {prior.focus_leak_key}. Динамика метрики: {progress.text}"


def build_coach_prompt(leaks: list[Leak], progress: ProgressNote | None,
                       principles: str, prior: CoachBrief | None,
                       focus_key: str) -> list[dict]:
    user = (
        f"Лики по серии (детерминированный детектор):\n{_leaks_block(leaks)}\n\n"
        f"Главный лик-фокус: {focus_key}\n\n"
        f"Прогресс с прошлого разбора:\n{_progress_block(progress, prior)}\n\n"
        f"Тренерские принципы по этому лику:\n{principles}\n\n"
        "Сформулируй разбор строго по фокус-лику в заданном JSON-формате."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
