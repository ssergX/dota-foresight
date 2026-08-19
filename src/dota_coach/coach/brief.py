from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class Drill:
    text: str
    metric_ref: str = ""


@dataclass
class CoachBrief:
    focus_leak_key: str
    headline: str
    diagnosis: str
    why_it_costs: str
    drills: list[Drill] = field(default_factory=list)
    progress_note: str | None = None
    generated_for_matches: list[int] = field(default_factory=list)
    # снимок лика-фокуса для петли подотчётности (ставит код, не ЛЛМ):
    focus_metric: str = ""
    focus_value: float = 0.0
    focus_direction: str = "lower_is_better"
    schema_version: int = 2
    leaks_snapshot: list[dict] = field(default_factory=list)
    baseline_reset: bool = False   # рантайм-флаг (НЕ сериализуется): прошлый фокус переименован


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        # drop the opening fence line (``` or ```json) and a trailing ``` if present
        lines = s.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    return s


def parse_brief(raw: str | dict) -> CoachBrief:
    data = json.loads(_strip_code_fence(raw)) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise ValueError("coach brief должен быть JSON-объектом")
    if data.get("focus_leak_key") is None:
        raise ValueError("coach brief без focus_leak_key")
    drills_raw = data.get("drills", [])
    if not isinstance(drills_raw, list):
        raise ValueError("coach brief drills должен быть списком")

    drills: list[Drill] = []
    for d in drills_raw:
        if isinstance(d, dict):
            drills.append(Drill(text=str(d.get("text") or ""), metric_ref=str(d.get("metric_ref") or "")))
        else:
            drills.append(Drill(text=str(d), metric_ref=""))
    if drills and all(not d.metric_ref for d in drills):
        print("warning: ни один дрилл не привязан к метрике (metric_ref пуст)")

    return CoachBrief(
        focus_leak_key=str(data["focus_leak_key"]),
        headline=str(data.get("headline") or ""),
        diagnosis=str(data.get("diagnosis") or ""),
        why_it_costs=str(data.get("why_it_costs") or ""),
        drills=drills,
        progress_note=data.get("progress_note"),
        generated_for_matches=list(data.get("generated_for_matches", [])),
        focus_metric=str(data.get("focus_metric") or ""),
        focus_value=float(data.get("focus_value", 0.0)),
        focus_direction=str(data.get("focus_direction") or "lower_is_better"),
        schema_version=int(data.get("schema_version", 2)),
        leaks_snapshot=list(data.get("leaks_snapshot", [])),
    )


def brief_to_dict(b: CoachBrief) -> dict:
    return {
        "focus_leak_key": b.focus_leak_key,
        "headline": b.headline,
        "diagnosis": b.diagnosis,
        "why_it_costs": b.why_it_costs,
        "drills": [{"text": d.text, "metric_ref": d.metric_ref} for d in b.drills],
        "progress_note": b.progress_note,
        "generated_for_matches": b.generated_for_matches,
        "focus_metric": b.focus_metric,
        "focus_value": b.focus_value,
        "focus_direction": b.focus_direction,
        "schema_version": b.schema_version,
        "leaks_snapshot": b.leaks_snapshot,
    }
