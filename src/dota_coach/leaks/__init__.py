from __future__ import annotations

from dota_coach.leaks import detectors as _detectors  # noqa: F401  (регистрация)
from dota_coach.leaks.registry import applicable, filter_rows
from dota_coach.leaks.rows import build_rows
from dota_coach.leaks.roles import segment_by_role
from dota_coach.leaks.severity import rank
from dota_coach.leaks.thresholds import Thresholds
from dota_coach.models import Leak, Match

_MIN_GAMES_PER_ROLE = 5
_MIN_SAMPLE_PER_DETECTOR = 5


def detect_leaks(matches: list[Match], account_id: int | None) -> list[Leak]:
    rows = build_rows(matches, account_id)
    th = Thresholds()
    found: list[Leak] = []
    for role, role_rows in segment_by_role(rows).items():
        if len(role_rows) < _MIN_GAMES_PER_ROLE:
            continue
        for spec in applicable(role):
            usable = filter_rows(role_rows, spec.requires)
            if len(usable) < _MIN_SAMPLE_PER_DETECTOR:
                continue
            leak = spec.fn(usable, role, th)
            if leak is not None:
                leak.considered = len(role_rows)   # M: матчей в роли до requires (строка покрытия)
                found.append(leak)
    focus, also = rank(found)
    if focus is None:
        return []
    # порядок: фокус, затем «тоже видно», затем прочие члены семей (severity desc)
    ordered = [focus, *also]
    rest = sorted((l for l in found if l is not focus and l not in also),
                  key=lambda l: (-l.severity, l.key))
    return [*ordered, *rest]
