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


_SOURCE_RU = {
    "bench": "ниже, чем у ~60% игроков на этом герое (бенчмарк)",
    "manual": "ниже разумной планки для этой роли",
    "personal": "хуже твоего личного базлайна",
}


def _role_ru(role: int | None) -> str:
    return f"pos{role}" if role in (1, 2, 3, 4, 5) else "роль не определена"


def _leaks_block(leaks: list[Leak]) -> str:
    if not leaks:
        return "(ликов не обнаружено)"
    lines = []
    for leak in leaks:
        src = _SOURCE_RU.get(leak.source, leak.source)
        lines.append(
            f"- key={leak.key} | {leak.title} | {_role_ru(leak.role)} | metric={leak.metric} | "
            f"value={leak.value:.3f} | threshold={leak.threshold:.3f} | "
            f"direction={leak.direction} | оценка={src} | примеры={leak.example_matches}"
        )
    return "\n".join(lines)


def _progress_block(progress: ProgressNote | None, prior: CoachBrief | None) -> str:
    if prior is None or progress is None or progress.status == "no_history":
        return "Прошлого разбора нет — это базовая точка отсчёта."
    return f"Прошлый фокус: {prior.focus_leak_key}. Динамика метрики: {progress.text}"


def build_coach_prompt(leaks: list[Leak], progress: ProgressNote | None,
                       principles: str, prior: CoachBrief | None,
                       focus_key: str) -> list[dict]:
    focus = next((l for l in leaks if l.key == focus_key), None)
    family = focus.family if focus else ""
    confirming = [l for l in leaks if l.family == family and l.key != focus_key]
    conf_block = ("\n".join(f"- {l.title}: {l.metric}={l.value:.3f}" for l in confirming)
                  or "(нет)")
    role_line = _role_ru(focus.role) if focus else "роль не определена"
    user = (
        f"Роль разбора: {role_line}\n\n"
        f"Лики по серии (детерминированный детектор):\n{_leaks_block(leaks)}\n\n"
        f"Главный лик-фокус: {focus_key}\n"
        f"Подтверждающие детали той же семьи:\n{conf_block}\n\n"
        f"Прогресс с прошлого разбора:\n{_progress_block(progress, prior)}\n\n"
        f"Тренерские принципы по этому лику:\n{principles}\n\n"
        "Сформулируй разбор строго по фокус-лику в заданном JSON-формате."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
