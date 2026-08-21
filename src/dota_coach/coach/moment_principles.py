from __future__ import annotations

from pathlib import Path

from dota_coach.coach.principles import _load_sections
from dota_coach.models import ScoredMoment

_PRINCIPLES_PATH = Path(__file__).with_name("moment_principles.md")
_DEFAULT = "Разбирай процесс и решение по данным, не по исходу. Дай проверяемое действие."


def principle_for_moment(moment: ScoredMoment, path: Path = _PRINCIPLES_PATH) -> str:
    section = _load_sections(path).get(moment.event.type.value)
    return section if section else _DEFAULT
