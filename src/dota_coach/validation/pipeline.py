"""Blinded packs, split audits and denominator-preserving quality reports.

The package records evidence for an independent review. It deliberately does
not award a validated capability or criterion from its own output.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from dota_coach.decisions.contracts import DecisionInput
from dota_coach.decisions.evaluator import ActivationInput
from dota_coach.evidence.contracts import content_hash
from .contracts import (ANNOTATION_SCHEMA, ERROR_VERDICTS, ActionCheck, Annotation,
                        DatasetRecord, FactCheck, Prediction, canonical_verdict, SPLITS)


def _unique(records, key, what):
    result = {}
    for record in records:
        identity = key(record)
        if identity in result:
            raise ValueError(f"duplicate {what}: {identity}")
        result[identity] = record
    return result


def audit_splits(records: tuple[DatasetRecord, ...] | list[DatasetRecord], *,
                 training_match_ids=(), retrieval_match_ids=(),
                 training_player_ids=(), retrieval_player_ids=(),
                 require_all_player_disjoint: bool = False) -> dict:
    """Audit declared partitions, including source copies and retrieval leakage.

    Development and calibration may share players, but each source match belongs
    to one split. Holdout/patch-transfer target players must be absent from every
    other split. Longitudinal periods may share players and must not share matches.
    """
    _unique(records, lambda r: r.decision_id, "decision id")
    issues = []
    by_match, by_replay, by_input = defaultdict(list), defaultdict(list), defaultdict(list)
    for record in records:
        by_match[record.match_id].append(record)
        by_replay[record.replay_hash].append(record)
        by_input[record.input_hash].append(record)
    for key, group in by_match.items():
        if len({r.split for r in group}) > 1:
            issues.append(f"match_crosses_splits:{key}")
        if len({r.replay_hash for r in group}) > 1:
            issues.append(f"conflicting_replay_hash_for_match:{key}")
        if len({r.patch for r in group}) > 1:
            issues.append(f"conflicting_patch_for_match:{key}")
        if len({r.dataset_kind for r in group}) > 1:
            issues.append(f"conflicting_dataset_kind_for_match:{key}")
    for key, group in by_replay.items():
        if len({r.match_id for r in group}) > 1:
            issues.append(f"source_hash_reused_for_different_matches:{key}")
        if len({r.split for r in group}) > 1:
            issues.append(f"source_copy_crosses_splits:{key}")
    for key, group in by_input.items():
        if len(group) > 1:
            issues.append(f"input_hash_reused_for_different_decisions:{key}")
    external_matches = set(training_match_ids) | set(retrieval_match_ids)
    external_players = set(training_player_ids) | set(retrieval_player_ids)
    locked = [r for r in records if r.split in ("holdout", "patch_transfer")]
    for record in locked:
        others = [r for r in records if r.split != record.split]
        if record.dataset_kind != "replay":
            issues.append(f"non_replay_in_locked_split:{record.decision_id}")
        if record.match_id in external_matches:
            issues.append(f"training_or_retrieval_match_leakage:{record.match_id}")
        if record.target_player in external_players:
            issues.append(f"training_or_retrieval_target_player_leakage:{record.target_player}")
        if record.target_player in {r.target_player for r in others}:
            issues.append(f"target_player_crosses_locked_split:{record.target_player}")
        if require_all_player_disjoint:
            if len(record.participants) != 10 or any(len(r.participants) != 10 for r in others):
                issues.append(f"all_player_disjoint_roster_incomplete:{record.decision_id}")
            shared = set(record.participants) & (
                {p for r in others for p in r.participants} | external_players)
            if shared:
                issues.append(f"participant_crosses_locked_split:{','.join(sorted(shared))}")
    return {
        "schema_version": "foresight.split-audit.v1",
        "valid": not issues,
        "independence_scope": "all_player_disjoint" if require_all_player_disjoint
                              else "target_player_disjoint",
        "issues": sorted(set(issues)),
        "decision_count": len(records), "match_count": len(by_match),
        "target_player_count": len({r.target_player for r in records}),
        "counts_by_split": dict(sorted(Counter(r.split for r in records).items())),
        "manifest_hash": content_hash([asdict(r) for r in sorted(records, key=lambda r: r.decision_id)]),
        "validation_status": "data_validation_pending",
        "limitations": ["declarations_require_independent_provenance_review",
                        "locked_holdout_access_history_not_verified",
                        "no_release_gate_is_automatically_granted"],
    }


def validate_annotations(annotations: tuple[Annotation, ...] | list[Annotation],
                         records: tuple[DatasetRecord, ...] | list[DatasetRecord],
                         inputs: tuple[DecisionInput, ...] | list[DecisionInput] = ()) -> dict:
    """Reject misbound labels, duplicate revisions and edits without an audit chain."""
    records_by_id = _unique(records, lambda r: r.decision_id, "decision id")
    inputs_by_id = _unique(inputs, lambda r: r.decision_id, "input decision id")
    indexed = _unique(annotations, lambda a: a.key, "annotation identity")
    for annotation in annotations:
        record = records_by_id.get(annotation.decision_id)
        if record is None:
            raise ValueError(f"annotation has unknown decision id: {annotation.decision_id}")
        for field in ("input_hash", "replay_hash", "patch", "dataset_kind"):
            if getattr(annotation, field) != getattr(record, field):
                raise ValueError(f"annotation {field} does not match manifest")
        if annotation.annotation_version > 1:
            previous = indexed.get((annotation.decision_id, annotation.annotator_id,
                                    annotation.review_pass, annotation.annotation_version - 1))
            if previous is None or previous.annotation_hash != annotation.previous_annotation_hash:
                raise ValueError("annotation revision chain missing or corrupted")
        decision = inputs_by_id.get(annotation.decision_id)
        if decision is not None:
            if decision.input_hash != annotation.input_hash:
                raise ValueError("annotation input hash does not match decision input")
            facts = (decision.knowledge.facts if isinstance(decision, DecisionInput)
                     else decision.conditions if annotation.review_pass == "decision_blinded"
                     else decision.conditions + decision.utility_bounds)
            fact_ids = {fact.fact_id for fact in facts}
            admissible = fact_ids | set(decision.action.event_refs) | set(
                decision.boundary.resolution_evidence_ids)
            if any(check.fact_id not in fact_ids for check in annotation.facts_checked):
                raise ValueError("annotation refers to an unknown fact")
            cited = set(annotation.decisive_evidence_ids)
            cited.update(ref for check in annotation.available_actions for ref in check.evidence_ids)
            if not cited <= admissible:
                raise ValueError("annotation cites evidence outside blinded input")
    return {"record_count": len(annotations),
            "human_blinded_count": sum(a.annotator_kind == "human_expert" and
                                        a.review_pass == "decision_blinded" for a in annotations),
            "validation_status": "data_validation_pending"}


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _rows(path: str | Path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line, object_pairs_hook=_no_duplicate_keys,
                                 parse_constant=lambda value: (_ for _ in ()).throw(
                                     ValueError(f"non-finite JSON value: {value}")))
                if not isinstance(row, dict):
                    raise ValueError("JSONL row must be an object")
                yield row
            except (ValueError, TypeError) as exc:
                raise ValueError(f"invalid JSONL line {line_number}: {exc}") from exc


def load_dataset(path: str | Path) -> tuple[DatasetRecord, ...]:
    records = []
    for row in _rows(path):
        row = dict(row)
        row["participants"] = _array(row, "participants")
        records.append(DatasetRecord(**row))
    _unique(records, lambda r: r.decision_id, "decision id")
    return tuple(records)


def load_annotations(path: str | Path) -> tuple[Annotation, ...]:
    annotations = []
    for row in _rows(path):
        row = dict(row)
        # The exported JSON uses "pass", matching the architecture specification.
        if "pass" in row:
            if "review_pass" in row:
                raise ValueError("duplicate review pass aliases")
            row["review_pass"] = row.pop("pass")
        for field in ("acceptable_verdicts", "decisive_evidence_ids", "unknowns"):
            row[field] = _array(row, field)
        row["facts_checked"] = tuple(FactCheck(**check) for check in _array(row, "facts_checked"))
        row["available_actions"] = tuple(ActionCheck(
            **{**check, "evidence_ids": _array(check, "evidence_ids")})
            for check in _array(row, "available_actions"))
        annotations.append(Annotation(**row))
    _unique(annotations, lambda a: a.key, "annotation identity")
    return tuple(annotations)


def _array(row, field):
    value = row.get(field, [])
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON array")
    return tuple(value)


def load_predictions(path: str | Path) -> tuple[Prediction, ...]:
    predictions = tuple(Prediction(**row) for row in _rows(path))
    _unique(predictions, lambda p: p.decision_id, "prediction decision id")
    return predictions


def _write_rows(path: str | Path, rows) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Write complete bytes in one call; caller must choose a distinct destination.
    target.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                                       allow_nan=False) + "\n" for row in rows), encoding="utf-8")


def write_annotations(path: str | Path, annotations) -> None:
    def row(annotation):
        result = asdict(annotation)
        result["pass"] = result.pop("review_pass")
        return result
    _write_rows(path, [row(a) for a in annotations])


def write_dataset(path: str | Path, records) -> None:
    _write_rows(path, [asdict(r) for r in records])


def blind_case(decision: DecisionInput | ActivationInput) -> dict:
    """Only pre-choice knowledge and the minimal observed action token.

    Raw artifact paths/locators are intentionally omitted. Experts receive cited
    fact IDs; any client-prefix media must be provisioned separately and reviewed
    for blinding. The full raw replay belongs to the later outcome pass.
    """
    if not isinstance(decision, (DecisionInput, ActivationInput)):
        raise TypeError("blind case requires a typed DecisionInput or ActivationInput")
    if isinstance(decision, ActivationInput):
        # Bounds are the criterion's proposed utility judgments. Showing them
        # would disclose the computed dominance verdict before expert labeling.
        source_facts = decision.conditions
    else:
        source_facts = decision.knowledge.facts
    facts = []
    for fact in source_facts:
        if fact.perspective == "world":
            raise ValueError("world evidence is not admissible in a blind pack")
        facts.append({key: getattr(fact, key) for key in (
            "fact_id", "subject_ref", "predicate", "value", "status", "perspective",
            "unknown_reason", "quality_flags", "derived_from")} | {
                "valid_at": asdict(fact.valid_at),
                "available_at": asdict(fact.available_at) if fact.available_at else None})
    result = {"schema_version": "foresight.blind-case.v1", "decision_id": decision.decision_id,
              "input_hash": decision.input_hash,
              "boundary": asdict(decision.boundary), "action": asdict(decision.action),
              "criterion_version": decision.criterion_version}
    if isinstance(decision, ActivationInput):
        result.update({"subject_ref": decision.subject_ref, "match_id": decision.match_id,
                       "patch": decision.patch, "dataset_kind": decision.dataset_kind,
                       "criterion_id": "defensive_activation.v1",
                       "conditions": facts,
                       "withheld_derived_assessment": True,
                       "review_limitations": ["proposed_utility_bounds_withheld_for_independence",
                                              "prechoice_source_context_or_media_required",
                                              "conditions_alone_do_not_establish_a_decision_grade"]})
    else:
        result.update({"criterion_id": decision.criterion_id,
                      "knowledge": {"subject_player": decision.knowledge.subject_player,
                          "cutoff": asdict(decision.knowledge.cutoff),
                          "policy_version": decision.knowledge.policy_version,
                           "limitations": decision.knowledge.limitations, "facts": facts}})
    return result


def export_blind_pack(inputs, records, out_dir: str | Path) -> dict:
    inputs_by_id = _unique(inputs, lambda d: d.decision_id, "input decision id")
    records_by_id = _unique(records, lambda r: r.decision_id, "decision id")
    if set(inputs_by_id) != set(records_by_id):
        raise ValueError("blind pack requires exactly one manifest record per decision input")
    cases, templates = [], []
    for key in sorted(inputs_by_id):
        decision, record = inputs_by_id[key], records_by_id[key]
        if decision.input_hash != record.input_hash:
            raise ValueError("blind pack input hash differs from manifest")
        if isinstance(decision, ActivationInput) and any(
                getattr(decision, field) != getattr(record, field)
                for field in ("match_id", "patch", "dataset_kind")):
            raise ValueError("blind pack scoped input differs from manifest")
        case = blind_case(decision)
        case.update({"match_id": record.match_id, "patch": record.patch,
                     "dataset_kind": record.dataset_kind})
        cases.append(case)
        templates.append({"schema_version": ANNOTATION_SCHEMA, "dataset_kind": "template_only",
                          "decision_id": key, "input_hash": decision.input_hash,
                          "replay_hash": record.replay_hash, "patch": record.patch,
                          "annotator_id": None, "annotation_version": 1,
                          "pass": "decision_blinded", "outcome_visible": False,
                          "system_verdict_visible": False, "acceptable_verdicts": [],
                          "eligibility": "unknown", "facts_checked": [],
                          "available_actions": [], "decisive_evidence_ids": [],
                          "unknowns": ["unfinished_annotation"], "rationale": None,
                          "adjudication_status": "unreviewed"})
    target = Path(out_dir)
    _write_rows(target / "blind-cases.jsonl", cases)
    _write_rows(target / "annotation-template.jsonl", templates)
    write_dataset(target / "dataset.jsonl", records)
    audit = audit_splits(records)
    (target / "split-audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    instructions = (
        "# Независимая слепая разметка\n\n"
        "Не открывайте полный replay, исход, оценку системы или подборку по смертям до фиксации "
        "decision_blinded. blind-cases.jsonl содержит разрешённые факты и token действия. "
        "Это пакет данных, а не доказательство истинности извлечения.\n\n"
        "Предложенные utility bounds скрыты: они являются суждениями рубрики и раскрывают "
        "её вердикт. Для независимой оценки отдельно подготовьте только контекст и запись "
        "до выбора. Без этого отмечайте недостаточность данных; не выводите label из границ "
        "полезности. Их проверяют отдельным проходом после фиксации слепых labels.\n\n"
        "Сохраните отдельный annotation JSONL для каждого эксперта. Замените template_only на "
        "вид данных из кейса и заполните каждый обязательный ответ. Два эксперта размечают "
        "независимо; расхождения обсуждают после фиксации и хеширования записей. "
        "Исправление требует следующей версии, previous_annotation_hash и revision_reason.\n\n"
        "Синтетические кейсы проверяют процедуру и не входят в статистику точности. "
        "Любая точность требует независимой проверки происхождения и закрытости holdout; "
        "этот пакет не включает критерий и не присваивает статус validated.\n")
    (target / "README.md").write_text(instructions, encoding="utf-8")
    return {"case_count": len(cases), "out_dir": str(target.resolve()),
            "manifest_hash": audit["manifest_hash"], "split_valid": audit["valid"],
            "validation_status": "data_validation_pending"}


def _latest(annotations):
    latest = {}
    for annotation in annotations:
        key = annotation.decision_id, annotation.annotator_id, annotation.review_pass
        if key not in latest or annotation.annotation_version > latest[key].annotation_version:
            latest[key] = annotation
    return list(latest.values())


def interrater_report(annotations, records) -> dict:
    validate_annotations(annotations, records)
    groups = defaultdict(list)
    for annotation in _latest(annotations):
        if annotation.annotator_kind == "human_expert" and annotation.review_pass == "decision_blinded":
            groups[annotation.decision_id].append(annotation)
    pairs = incompatible = different_sets = eligibility_disagreements = 0
    no_common_verdict = 0
    affected = set()
    for decision_id, group in groups.items():
        if len(group) >= 2 and not set.intersection(*(
                {canonical_verdict(v) for v in annotation.acceptable_verdicts}
                for annotation in group)):
            no_common_verdict += 1
            affected.add(decision_id)
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                pairs += 1
                a_set = {canonical_verdict(v) for v in a.acceptable_verdicts}
                b_set = {canonical_verdict(v) for v in b.acceptable_verdicts}
                if a_set != b_set:
                    different_sets += 1
                if not a_set & b_set:
                    incompatible += 1
                    affected.add(decision_id)
                if a.eligibility != b.eligibility:
                    eligibility_disagreements += 1
                    affected.add(decision_id)
    return {"pair_count": pairs, "incompatible_verdict_pairs": incompatible,
            "different_acceptable_set_pairs": different_sets,
            "eligibility_disagreement_pairs": eligibility_disagreements,
            "multi_rater_no_common_verdict_decisions": no_common_verdict,
            "disputed_decision_ids": sorted(affected),
            "single_rater_decision_count": sum(len(group) == 1 for group in groups.values()),
            "real_replay_pair_count": sum(len(group) * (len(group) - 1) // 2
                                          for group in groups.values() if group[0].dataset_kind == "replay"),
            "limitations": ["rater_identity_and_independence_are_declared_not_verified",
                            "pair_comparisons_within_decision_are_correlated"]}


def _metric(numerator, denominator, *, unknown=0):
    return {"numerator": numerator, "denominator": denominator,
            "rate": numerator / denominator if denominator else None,
            "unknown_count": unknown, "confidence_interval": None,
            "uncertainty_reason": "clustered_match_player_interval_not_estimated"}


def evaluate_predictions(predictions, annotations, records, *, split="holdout",
                         min_raters: int = 2) -> dict:
    """Quality evidence only, never an automatic release/validation decision.

    Consensus is the intersection of independently submitted acceptable sets.
    Missing predictions remain in eligible denominators. Unknown reference
    labels, disputed eligibility and incomplete rater coverage remain explicit.
    """
    if split not in SPLITS:
        raise ValueError("unknown evaluation partition")
    if type(min_raters) is not int or min_raters < 2:
        raise ValueError("independent quality statistics require at least two raters")
    validate_annotations(annotations, records)
    dataset = _unique(records, lambda r: r.decision_id, "decision id")
    predicted = _unique(predictions, lambda p: p.decision_id, "prediction decision id")
    versions = {p.evaluator_version for p in predictions}
    if len(versions) > 1:
        raise ValueError("cannot pool different evaluator versions")
    for prediction in predictions:
        record = dataset.get(prediction.decision_id)
        if record is None or record.input_hash != prediction.input_hash:
            raise ValueError("prediction is not bound to this manifest input")
    groups = defaultdict(list)
    excluded_annotations = Counter()
    for annotation in _latest(annotations):
        if annotation.dataset_kind != "replay":
            excluded_annotations["non_replay"] += 1
        elif annotation.annotator_kind != "human_expert":
            excluded_annotations["non_human"] += 1
        elif annotation.review_pass != "decision_blinded":
            excluded_annotations["not_decision_blinded"] += 1
        else:
            groups[annotation.decision_id].append(annotation)
    cohort = [r for r in records if r.split == split and r.dataset_kind == "replay"]
    counts = Counter()
    confusion = Counter()
    reviewed = []
    for record in cohort:
        group = groups.get(record.decision_id, [])
        if len(group) < min_raters:
            counts["insufficient_raters"] += 1
            continue
        accepted = set.intersection(*({canonical_verdict(v) for v in a.acceptable_verdicts}
                                      for a in group))
        if not accepted or any(a.adjudication_status == "disputed" for a in group):
            counts["disputed_reference"] += 1
            continue
        eligibility_votes = {a.eligibility for a in group}
        eligibility = next(iter(eligibility_votes)) if len(eligibility_votes) == 1 else "unknown"
        counts[f"eligibility_{eligibility}"] += 1
        prediction = predicted.get(record.decision_id)
        verdict = canonical_verdict(prediction.verdict) if prediction else "missing_prediction"
        reviewed.append(record)
        counts["expert_reviewed"] += 1
        if prediction is None:
            counts["missing_predictions"] += 1
        if eligibility == "eligible":
            counts["eligible"] += 1
            if verdict not in ("missing_prediction", "insufficient_evidence", "not_actionable"):
                counts["assessed"] += 1
            if verdict in accepted:
                counts["agreed"] += 1
            if "insufficient_evidence" not in accepted:
                counts["expert_assessable"] += 1
                if verdict in ("insufficient_evidence", "missing_prediction", "not_actionable"):
                    counts["missed_assessable"] += 1
        if verdict == "insufficient_evidence":
            counts["abstentions"] += 1
            if verdict in accepted:
                counts["warranted_abstentions"] += 1
        reference_error = accepted <= ERROR_VERDICTS
        reference_not_error = not bool(accepted & ERROR_VERDICTS)
        reference_nonerror = not bool(accepted & ERROR_VERDICTS) and "insufficient_evidence" not in accepted
        if reference_nonerror:
            counts["expert_nonerror"] += 1
        if verdict in ERROR_VERDICTS:
            counts["reviewed_accusations"] += 1
            if reference_error or reference_not_error:
                counts["unambiguous_accusations"] += 1
                if reference_not_error:
                    counts["false_accusations"] += 1
                if reference_nonerror:
                    counts["false_positive_accusations"] += 1
            else:
                counts["ambiguous_accusations"] += 1
        confusion[("|".join(sorted(accepted)), verdict)] += 1
    all_accusations = sum(p.verdict in ERROR_VERDICTS for p in predictions
                          if dataset[p.decision_id].split == split and
                          dataset[p.decision_id].dataset_kind == "replay")
    unknown_accusations = all_accusations - counts["unambiguous_accusations"]
    audit = audit_splits(records)
    from dota_coach.validation.fact_quality import fact_quality_report
    return {
        "schema_version": "foresight.quality-report.v1", "split": split,
        "evaluator_version": next(iter(versions)) if versions else None,
        "validation_status": "data_validation_pending", "release_gate": "not_evaluated",
        "quality_interpretation": "descriptive_review_summary" if audit["valid"]
                                  else "invalid_split_no_independent_quality_claim",
        "split_audit": audit,
        "cohort": {"decision_count": len(cohort), "match_count": len({r.match_id for r in cohort}),
                   "target_player_count": len({r.target_player for r in cohort}),
                   "decision_counts_by_patch": dict(sorted(Counter(r.patch for r in cohort).items())),
                   "expert_reviewed_decision_count": counts["expert_reviewed"],
                   "expert_reviewed_match_count": len({r.match_id for r in reviewed}),
                   "excluded_non_replay_decisions": sum(r.split == split and r.dataset_kind != "replay"
                                                          for r in records)},
        "counts": dict(sorted(counts.items())),
        "metrics": {
            "agreement_with_acceptable_sets": _metric(counts["agreed"], counts["eligible"],
                                                      unknown=len(cohort) - counts["eligible"]),
            "assessment_coverage": _metric(counts["assessed"], counts["eligible"],
                                            unknown=len(cohort) - counts["eligibility_eligible"] -
                                                    counts["eligibility_ineligible"]),
            "false_discovery_among_accusations": _metric(counts["false_accusations"],
                                                         counts["unambiguous_accusations"],
                                                         unknown=unknown_accusations),
            "false_positive_rate": _metric(counts["false_positive_accusations"], counts["expert_nonerror"]),
            "warranted_abstention": _metric(counts["warranted_abstentions"], counts["abstentions"]),
            "missed_assessable_cases": _metric(counts["missed_assessable"], counts["expert_assessable"]),
        },
        "all_issued_accusations": all_accusations, "unknown_reference_accusations": unknown_accusations,
        "confusion": [{"expert_acceptable_set": accepted.split("|"), "predicted": verdict, "count": count}
                      for (accepted, verdict), count in sorted(confusion.items())],
        "excluded_annotations": dict(sorted(excluded_annotations.items())),
        "interrater": interrater_report(annotations, records),
        "fact_review": fact_quality_report(annotations, records, split=split, min_raters=min_raters),
        "limitations": ["synthetic_and_self_evaluation_excluded_from_real_quality_statistics",
                        "independence_and_closed_holdout_require_external_review",
                        "confidence_intervals_require_clustered_match_player_design",
                        "pooled_descriptive_metrics_do_not_validate_patch_transfer",
                        "opportunity_recall_not_estimable_without_independent_interval_census",
                        "no_accuracy_or_release_threshold_is_claimed"],
    }
