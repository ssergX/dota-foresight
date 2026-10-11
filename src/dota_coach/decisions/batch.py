"""Strict offline import and full supplied-opportunity ledger for experiments."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import json
from pathlib import Path

from dota_coach.decisions.contracts import ActionObservation, DecisionBoundary
from dota_coach.decisions.evaluator import ActivationInput, CriterionScope, evaluate_activation, explain_evaluation
from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef


def strict_json(text: str):
    def pairs(items):
        d = {}
        for key, value in items:
            if key in d:
                raise ValueError("duplicate JSON key: " + key)
            d[key] = value
        return d
    return json.loads(text, object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("nonfinite JSON: " + x)))


def _keys(d, required, optional=()):
    if not isinstance(d, dict) or set(d) - set(required) - set(optional) or set(required) - set(d):
        raise ValueError("unexpected or missing fields in evidence contract")


def read_time(d):
    _keys(d, ("game_time_ms",), ("replay_tick", "sequence_in_tick", "uncertainty_ms",
                                 "clock_mapping_version", "order_status"))
    if type(d["game_time_ms"]) not in (int, float, type(None)):
        raise ValueError("invalid timestamp")
    return TimeRef(**d)


def read_fact(d):
    _keys(d, ("fact_id", "subject_ref", "predicate", "value", "status", "valid_at",
              "available_at", "perspective", "source_refs"),
             ("derived_from", "observer_ref", "method_version", "quality_flags", "unknown_reason"))
    values = dict(d)
    values["valid_at"] = read_time(d["valid_at"])
    values["available_at"] = read_time(d["available_at"]) if d["available_at"] is not None else None
    for s in d["source_refs"]:
        _keys(s, ("artifact_id", "content_hash", "provider", "schema_version", "locator"), ("extractor_version",))
    values["source_refs"] = tuple(SourceRef(**s) for s in d["source_refs"])
    for field in ("derived_from", "quality_flags"):
        if field in values:
            if not isinstance(values[field], list) or not all(isinstance(x, str) for x in values[field]):
                raise ValueError("immutable string references required")
            values[field] = tuple(values[field])
    return Fact(**values)


def read_activation(d):
    _keys(d, ("decision_id", "match_id", "subject_ref", "patch", "criterion_version",
              "boundary", "action", "conditions", "utility_bounds", "dataset_kind"))
    b, a = d["boundary"], d["action"]
    _keys(b, ("boundary_id", "anchor", "status", "method", "resolution_evidence_ids"))
    _keys(a, ("kind", "action_id", "log_completeness", "event_refs"))
    if not isinstance(a["event_refs"], list) or not all(isinstance(x, str) for x in a["event_refs"]):
        raise ValueError("action source refs must be strings")
    if not isinstance(b["resolution_evidence_ids"], list) or not all(
            isinstance(x, str) and x for x in b["resolution_evidence_ids"]):
        raise ValueError("boundary references must be nonempty strings")
    for obj, names in ((d, ("decision_id", "subject_ref", "patch", "criterion_version")),
                       (b, ("boundary_id", "status", "method")),
                       (a, ("kind", "action_id", "log_completeness"))):
        if not all(isinstance(obj[name], str) and obj[name] for name in names):
            raise ValueError("contract identities must be nonempty strings")
    boundary = DecisionBoundary(b["boundary_id"], read_time(b["anchor"]) if b["anchor"] else None,
                                b["status"], b["method"], tuple(b["resolution_evidence_ids"]))
    action = ActionObservation(a["kind"], a["action_id"], a["log_completeness"], tuple(a["event_refs"]))
    return ActivationInput(d["decision_id"], d["match_id"], d["subject_ref"], d["patch"],
                           d["criterion_version"], boundary, action,
                           tuple(read_fact(f) for f in d["conditions"]),
                           tuple(read_fact(f) for f in d["utility_bounds"]), d["dataset_kind"])


@dataclass(frozen=True)
class Batch:
    inputs: tuple[ActivationInput, ...]
    scope: CriterionScope
    discovery_status: str
    exclusions: tuple[dict, ...]


def read_batch(text: str, experimental: bool = False) -> Batch:
    d = strict_json(text)
    _keys(d, ("schema_version", "scope", "discovery_status", "decisions", "exclusions"))
    if d["schema_version"] != "foresight.activation-batch.v1":
        raise ValueError("unsupported batch schema")
    if d["discovery_status"] not in ("partial", "unknown"):
        raise ValueError("complete discovery is not independently validated")
    s = d["scope"]
    _keys(s, ("patch", "criterion_version", "capabilities", "rubric_source_ids"), ("acceptable_floor",))
    for key in ("capabilities", "rubric_source_ids"):
        if not isinstance(s[key], list) or not all(isinstance(x, str) for x in s[key]):
            raise ValueError("scope references must be strings")
    scope = CriterionScope(s["patch"], s["criterion_version"], tuple(s["capabilities"]),
                           tuple(s["rubric_source_ids"]), "experimental" if experimental else "disabled",
                           s.get("acceptable_floor"))
    inputs = tuple(read_activation(v) for v in d["decisions"])
    ids = [i.decision_id for i in inputs]
    for e in d["exclusions"]:
        _keys(e, ("opportunity_id", "match_id", "eligibility", "reason_codes"))
        if (not isinstance(e["opportunity_id"], str) or not e["opportunity_id"] or
                e["eligibility"] not in ("ineligible", "unknown") or
                not isinstance(e["reason_codes"], list) or not e["reason_codes"] or
                not all(isinstance(r, str) and r for r in e["reason_codes"])):
            raise ValueError("excluded opportunity requires eligibility and reasons")
        if type(e["match_id"]) is not int or e["match_id"] <= 0:
            raise ValueError("exclusion match identity required")
        ids.append(e["opportunity_id"])
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate opportunity identity")
    return Batch(inputs, scope, d["discovery_status"], tuple(d["exclusions"]))


def evaluate_batch(batch: Batch) -> dict:
    evaluations = [evaluate_activation(i, batch.scope) for i in batch.inputs]
    assessed = sum(e.verdict not in ("insufficient_evidence", "not_actionable") for e in evaluations)
    unknown = sum(e.verdict == "insufficient_evidence" for e in evaluations)
    ineligible = sum(e.verdict == "not_actionable" for e in evaluations)
    unknown += sum(e["eligibility"] == "unknown" for e in batch.exclusions)
    ineligible += sum(e["eligibility"] == "ineligible" for e in batch.exclusions)
    return {"schema_version": "foresight.evaluation-batch.v1", "mode": batch.scope.mode,
            "validation_status": "unverified", "discovery_status": batch.discovery_status,
            "supplied_opportunities": len(evaluations) + len(batch.exclusions),
            "experimental_assessed": assessed, "validated_assessed": 0,
            "unknown": unknown, "ineligible": ineligible, "population_coverage": None,
            "scope": asdict(batch.scope), "exclusions": list(batch.exclusions),
            "evaluations": [asdict(e) | {"assessment_hash": e.assessment_hash,
                "explanation": list(explain_evaluation(e))} for e in evaluations]}


def write_batch_report(batch: Batch, out_dir: str) -> dict:
    result = evaluate_batch(batch)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluations.json").write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                                   allow_nan=False), encoding="utf-8")
    (out / "decision-inputs.json").write_text(json.dumps([asdict(i) for i in batch.inputs],
                                ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    esc = html.escape
    cards = "".join(f"<article data-decision='{esc(e['decision_id'], quote=True)}'><h2>{esc(e['decision_id'])}</h2>"
        f"<p>Экспериментальная оценка: <b>{esc(e['verdict'])}</b>. Допуск к упражнениям: нет.</p>"
        f"<ul>{''.join('<li>'+esc(t)+'</li>' for t in e['explanation'])}</ul>"
        f"<details><summary>Причины, claims и хеши</summary><pre>{esc(json.dumps(e, ensure_ascii=False, indent=2))}</pre></details></article>"
        for e in result["evaluations"])
    ledger_rows = "".join(f"<tr><td>{esc(e['opportunity_id'])}</td><td>{esc(e['eligibility'])}</td>"
        f"<td>{esc(', '.join(e['reason_codes']))}</td></tr>" for e in result["exclusions"])
    page = f"""<!doctype html><html lang='ru'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'><title>Foresight — экспериментальная рубрика</title>
<style>body{{font:16px system-ui;margin:32px auto;max-width:1000px;padding:0 20px;background:#141c25;color:#e7eef5}}a{{color:#8dc9ff}}article{{padding:20px;border:1px solid #415161;border-radius:12px;margin:16px 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}td,th{{padding:8px;text-align:left}}.gate{{background:#332c1d;padding:18px;border-radius:12px}}</style></head><body>
<h1>Проверка экспериментальной рубрики</h1><div class='gate'>
<p>Достоверность игровой механики, диапазонов пользы и качества решения не подтверждена.
Этот отчёт проверяет алгоритм на переданных входах; он не является анализом ошибок реального игрока.</p>
<p>Передано возможностей: {result['supplied_opportunities']}; экспериментально оценено: {result['experimental_assessed']};
неизвестно: {result['unknown']}; исключено: {result['ineligible']}; подтверждённых оценок: 0.
Охват всех возможностей матча неизвестен.</p></div>
<p><a href='evaluations.json'>Результаты и ledger</a> · <a href='decision-inputs.json'>Входы для независимой разметки</a></p>
{cards}<h2>Исключённые и неизвестные возможности</h2><table><thead><tr><th>ID</th><th>Статус</th><th>Причина</th></tr></thead><tbody>{ledger_rows}</tbody></table></body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")
    return result
