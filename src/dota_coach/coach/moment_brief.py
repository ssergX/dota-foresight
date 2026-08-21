from __future__ import annotations

import json
from dataclasses import dataclass, field

from dota_coach.coach.brief import _strip_code_fence


@dataclass
class MomentBrief:
    headline: str
    hypothesis: str
    process_question: str
    checklist: list[str] = field(default_factory=list)
    principle: str = ""
    # штампует КОД (не LLM):
    game_time: int = 0
    verdict: str = ""
    event_type: str = ""


def parse_moment_brief(raw: str | dict) -> MomentBrief:
    data = json.loads(_strip_code_fence(raw)) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("moment brief должен быть JSON-объектом")
    checklist_raw = data.get("checklist", [])
    if not isinstance(checklist_raw, list):
        raise ValueError("moment brief checklist должен быть списком")
    return MomentBrief(
        headline=str(data.get("headline") or ""),
        hypothesis=str(data.get("hypothesis") or ""),
        process_question=str(data.get("process_question") or ""),
        checklist=[str(c) for c in checklist_raw],
        principle=str(data.get("principle") or ""),
    )
