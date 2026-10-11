"""Source-bound, revisable purchase planning without promoting declarations to facts.

The selected activation is a retrospective anchor, not a recovered purchase
decision. Current user input describes a plan to examine next; it cannot supply
prior intent, a noticed threat, historical mechanics or verified feasibility.
"""
from __future__ import annotations

from dataclasses import asdict
import math
import re

from dota_coach.evidence.contracts import TimeRef, content_hash
from dota_coach.ingest.valve_catalog import ValveCatalogSnapshot
from dota_coach.learning.contextual import (
    BuildQuestion, GOALS, GoalHypothesis, THREATS, analyze_build_question,
)

REQUEST_SCHEMA = "foresight.build-plan-request.v1"
PLAN_SCHEMA = "foresight.build-plan.v1"
PLANNER_VERSION = "contextual-build-planner.v1"
_REQUIRED = {"schema_version", "decision_id", "source_context_hash", "goal_kind",
             "goal_description", "confirmed"}
_OPTIONAL = {"threat_kind", "threat_description", "candidate_item_ids", "available_gold",
             "remaining_costs", "free_inventory_slot", "purchase_available", "previous_plan_id"}
_STATE_FIELDS = {"hp", "max_hp", "mana", "level", "alive"}
_CHECKS = {"exact_inventory_handle_resolves", "raw_mana_at_least_reported_cost",
           "raw_cooldown_end_not_after_clock", "control_allows_activation",
           "inventory_slot_allows_activation", "target_and_command_constraints_satisfied"}


def _text(value, name, *, maximum=2000):
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError(f"{name}: nonempty bounded text required")
    return value.strip()


def _hash(value, name):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name}: SHA-256 required")
    return value


def _positive_id(value, name):
    if type(value) is not int or not 0 < value <= 2**53 - 1:
        raise ValueError(f"{name}: bounded positive integer required")
    return value


def _number(value, name, *, nullable=True, nonnegative=True):
    if value is None and nullable:
        return None
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, TypeError):
        valid = False
    # JSON numbers beyond the exact integer range cannot travel through the UI
    # without changing their meaning. The limit also bounds all budget deltas.
    if not valid or abs(value) > 2**53 - 1 or (nonnegative and value < 0):
        raise ValueError(f"{name}: finite bounded numeric value required")
    return value


def _tri(value, name):
    if value is not None and type(value) is not bool:
        raise ValueError(f"{name}: boolean or null required")
    return value


def _record(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _raw_operand(value, cutoff_record):
    if not isinstance(value, dict):
        return {"value": None, "status": "unknown", "source_record_index": None}
    record = value.get("source_record_index")
    if not _record(record) or record >= cutoff_record:
        return {"value": None, "status": "unknown", "source_record_index": None}
    raw = _number(value.get("value"), "raw own resource")
    if raw is None or value.get("status") != "raw_observed":
        return {"value": None, "status": "unknown", "source_record_index": None}
    tick = value.get("net_tick")
    wire = value.get("wire_type")
    return {"value": raw, "status": "raw_observed_unverified", "source_record_index": record,
            "net_tick": tick if _record(tick) else None,
            "wire_type": wire if type(wire) is str and len(wire) <= 64 else None}


def _own_prefix(row, cutoff_time, cutoff_record):
    time = _number(row.get("own_state_time"), "own state time", nonnegative=False)
    record = row.get("own_state_source_record_index")
    preceding = (time is not None and time < cutoff_time and _record(record) and record < cutoff_record)
    values = row.get("own_state", [])
    if not isinstance(values, (list, tuple)):
        raise ValueError("own state must be a scalar pair sequence")
    state = {}
    for pair in values:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2 or type(pair[0]) is not str:
            raise ValueError("invalid own state pair")
        key, value = pair
        if key not in _STATE_FIELDS:
            continue
        if key in state:
            raise ValueError("duplicate own state field")
        state[key] = _tri(value, "alive") if key == "alive" else _number(value, key)
    result = {
        "status": "raw_preceding_observation_unverified" if preceding else "unknown",
        "own_state": {key: state.get(key) if preceding else None for key in sorted(_STATE_FIELDS)},
        "own_state_time": time if preceding else None,
        "source_record_index": record if preceding else None,
        "availability": "screen_and_choice_availability_not_established",
        "feasibility": "unknown",
    }
    resource = row.get("resource_review")
    if isinstance(resource, dict):
        if resource.get("action_id") != row["decision_id"]:
            raise ValueError("resource prefix action binding mismatch")
        checks = []
        rows = resource.get("checks", [])
        if not isinstance(rows, list):
            raise ValueError("resource checks must be an array")
        for check in rows:
            if not isinstance(check, dict):
                raise ValueError("invalid resource check object")
            if type(check.get("code")) is not str:
                raise ValueError("invalid resource check code")
            if check["code"] not in _CHECKS:
                continue
            refs = check.get("evidence_record_indices", [])
            if not isinstance(refs, list):
                raise ValueError("resource source records must be an array")
            available = bool(refs) and all(_record(r) and r < cutoff_record for r in refs)
            # Legacy reports treated this raw field as an absolute end time.
            # Prefix ordering cannot establish the meaning of the field.
            cooldown_unknown = check["code"] == "raw_cooldown_end_not_after_clock"
            checks.append({"code": check["code"],
                           "value": _tri(check.get("value"), "raw check") if available and not cooldown_unknown else None,
                           "source_record_indices": sorted(set(refs)) if available else [],
                           "status": "unverified_candidate" if available and not cooldown_unknown else "unknown"})
        if len({c["code"] for c in checks}) != len(checks):
            raise ValueError("duplicate own resource check")
        result["resource_operands"] = {
            "mana": _raw_operand(resource.get("mana_source"), cutoff_record),
            "activation_mana_cost": _raw_operand(resource.get("cost_source"), cutoff_record),
            "checks": sorted(checks, key=lambda c: c["code"]),
            "calculation_status": "arithmetic_on_unverified_raw_prefix",
            "control_and_item_usability": "unknown",
        }
    return result


def _purchase_prefix(report, match_id, account_id, cutoff_time):
    extensions = report.get("extensions")
    portfolio = extensions.get("portfolio") if isinstance(extensions, dict) else None
    if isinstance(portfolio, dict):
        if portfolio.get("match_id") != match_id or portfolio.get("account_id") != account_id:
            raise ValueError("purchase portfolio subject binding mismatch")
        sequence = portfolio.get("purchases")
    else:
        advice = report.get("build_advice")
        question_id = advice.get("question_id") if isinstance(advice, dict) else None
        sequence = advice.get("purchases") if (isinstance(question_id, str) and
                   question_id.startswith(f"build:{match_id}:{account_id}:")) else None
    if not isinstance(sequence, dict):
        return {"status": "unavailable", "entries": [], "current_inventory": "not_established",
                "availability": "player_screen_availability_unverified"}
    if sequence.get("match_id") not in (None, match_id):
        raise ValueError("purchase sequence match binding mismatch")
    rows = sequence.get("purchases", [])
    if not isinstance(rows, (list, tuple)):
        raise ValueError("source purchases must be an array")
    prefix = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid source purchase")
        time = _number(row.get("game_time_seconds"), "purchase time", nonnegative=False)
        # Equal-time receipt ordering is unresolved; unknown-time and later
        # events are excluded without importing their identities or values.
        if time is None or time >= cutoff_time:
            continue
        if row.get("match_id") != match_id:
            raise ValueError("prefix purchase match binding mismatch")
        item = _text(row.get("item_id"), "source purchase item", maximum=100)
        if re.fullmatch(r"(?:item_)?[a-z0-9_]+", item) is None:
            raise ValueError("invalid source purchase item identity")
        event = _text(row.get("source_event_id"), "source purchase event", maximum=300)
        source = row.get("source")
        if not isinstance(source, dict) or source.get("match_id") != match_id:
            raise ValueError("prefix purchase source match mismatch")
        prefix.append({"item_id": item if item.startswith("item_") else "item_" + item,
                       "game_time_seconds": time, "source_event_id": event,
                       "source_url": f"https://www.opendota.com/matches/{match_id}",
                       "status": "source_receipt_unverified"})
    if len({p["source_event_id"] for p in prefix}) != len(prefix):
        raise ValueError("duplicate source purchase receipt")
    return {"status": "observed_prefix_only", "entries": sorted(prefix, key=lambda p: (
        p["game_time_seconds"], p["source_event_id"])), "current_inventory": "not_established",
        "availability": "player_screen_availability_unverified"}


def build_source_context(report: dict, decision_id: str) -> dict:
    """Project only identity and strictly preceding own/purchase observations.

    Whole match/trace hashes, outcomes, enemy world state and all later rows are
    deliberately outside this hash. Their changing bytes cannot revise a plan.
    """
    if type(report) is not dict:
        raise ValueError("source report object required")
    decision_id = _text(decision_id, "decision id", maximum=200)
    match_id = _positive_id(report.get("match_id"), "match id")
    account_id = _positive_id(report.get("account_id"), "account id")
    catalog_id = _hash(report.get("catalog_snapshot_id"), "catalog snapshot")
    notebook = report.get("notebook")
    if not isinstance(notebook, dict) or notebook.get("match_id") != match_id:
        raise ValueError("notebook match binding mismatch")
    kind = report.get("dataset_kind")
    if kind not in ("replay", "synthetic", "unknown") or notebook.get("dataset_kind") != kind:
        raise ValueError("source dataset kind absent or inconsistent")
    entries = notebook.get("entries")
    if not isinstance(entries, list) or any(not isinstance(row, dict) for row in entries):
        raise ValueError("notebook entries required")
    selected = [row for row in entries if row.get("decision_id") == decision_id]
    if len(selected) != 1:
        raise ValueError("anchor decision absent or ambiguous")
    row = selected[0]
    if row.get("match_id") != match_id or row.get("actor") != notebook.get("actor"):
        raise ValueError("anchor subject binding mismatch")
    actor = _text(row.get("actor"), "own actor", maximum=200)
    cutoff_time = _number(row.get("observation_time"), "anchor time", nullable=False, nonnegative=False)
    cutoff_record = row.get("source_record_index")
    if not _record(cutoff_record):
        raise ValueError("anchor source record required")
    if decision_id != f"trace:{match_id}:record:{cutoff_record}":
        raise ValueError("anchor decision/source record mismatch")
    slot = notebook.get("resource_slot")
    if slot is not None and (type(slot) is not int or not 0 <= slot <= 9):
        raise ValueError("invalid subject resource slot")
    extensions = report.get("extensions")
    portfolio = extensions.get("portfolio") if isinstance(extensions, dict) else None
    provider_patch, hero_id = None, None
    if isinstance(portfolio, dict):
        provider_patch = portfolio.get("patch")
        if provider_patch is not None:
            provider_patch = _text(provider_patch, "provider patch identity", maximum=100)
        if portfolio.get("hero_id") is not None:
            hero_id = _positive_id(portfolio["hero_id"], "source hero id")
    source = {
        "schema_version": "foresight.build-source-context.v1",
        "source_binding": {"match_id": match_id, "account_id": account_id, "actor": actor,
                           "resource_slot": slot, "dataset_kind": kind,
                           "catalog_snapshot_id": catalog_id, "decision_id": decision_id,
                           "hero_id": hero_id, "provider_patch": provider_patch,
                           "historical_patch_applicability": "not_established",
                           "observation_time": cutoff_time, "source_record_index": cutoff_record,
                           "anchor_status": "activation_observation_choice_unresolved",
                           "temporal_order": "source_prefix_only_unverified"},
        "own_prefix": _own_prefix(row, cutoff_time, cutoff_record),
        "source_purchase_prefix": _purchase_prefix(report, match_id, account_id, cutoff_time),
    }
    source["source_context_hash"] = content_hash(source)
    return source


def _request(request):
    if type(request) is not dict or not _REQUIRED <= request.keys() or request.keys() - (_REQUIRED | _OPTIONAL):
        raise ValueError("build plan request keys invalid")
    if request["schema_version"] != REQUEST_SCHEMA or request["confirmed"] is not True:
        raise ValueError("explicit confirmed build goal required")
    goal = request["goal_kind"]
    threat = request.get("threat_kind", "unknown")
    if type(goal) is not str or goal not in GOALS or type(threat) is not str or threat not in THREATS:
        raise ValueError("invalid selected goal or declared threat kind")
    description = _text(request["goal_description"], "goal description")
    threat_text = request.get("threat_description")
    if threat_text is not None:
        threat_text = _text(threat_text, "threat description")
    if threat != "unknown" and threat_text is None:
        raise ValueError("declared threat category requires its player message")
    candidates = request.get("candidate_item_ids", [])
    if type(candidates) is not list or len(candidates) > 6 or any(
            type(item) is not str or re.fullmatch(r"item_[a-z0-9_]{1,95}", item) is None for item in candidates):
        raise ValueError("up to six canonical catalog item names required")
    if len(set(candidates)) != len(candidates):
        raise ValueError("duplicate build candidate")
    costs = request.get("remaining_costs", {})
    if type(costs) is not dict or any(type(key) is not str or key not in candidates for key in costs):
        raise ValueError("remaining costs must belong to explicitly selected candidates")
    costs = {key: _number(value, "remaining cost") for key, value in sorted(costs.items())}
    previous = request.get("previous_plan_id")
    if previous is not None:
        previous = _hash(previous, "previous plan id")
    return {
        "decision_id": _text(request["decision_id"], "decision id", maximum=200),
        "source_context_hash": _hash(request["source_context_hash"], "source context"),
        "goal_kind": goal, "goal_description": description, "threat_kind": threat,
        "threat_description": threat_text, "candidate_item_ids": list(candidates),
        "available_gold": _number(request.get("available_gold"), "available gold"),
        "remaining_costs": costs,
        "free_inventory_slot": _tri(request.get("free_inventory_slot"), "free slot"),
        "purchase_available": _tri(request.get("purchase_available"), "purchase availability"),
        "previous_plan_id": previous,
    }


def _plan_identity(plan):
    return content_hash({key: plan[key] for key in (
        "planner_version", "source_context_hash", "declaration_receipt_hash",
        "revision", "previous_plan_id", "previous_payload_sha256")})


def create_build_plan(report: dict, catalog: ValveCatalogSnapshot, request: dict,
                      previous: dict | None = None) -> dict:
    """Create a conditional plan; all imported declarations remain unverified."""
    declared = _request(request)
    if not isinstance(catalog, ValveCatalogSnapshot):
        raise ValueError("typed source catalog required")
    context = build_source_context(report, declared["decision_id"])
    if context["source_binding"]["catalog_snapshot_id"] != catalog.snapshot_id:
        raise ValueError("build catalog differs from the source report")
    if declared["source_context_hash"] != context["source_context_hash"]:
        raise ValueError("stale build source context: reload the report")
    for item_id in declared["candidate_item_ids"]:
        if catalog.item(item_id) is None:
            raise ValueError("selected candidate absent from source catalog")
    revision, previous_hash = 1, None
    revision_reason = "initial_planning_request"
    if previous is None:
        if declared["previous_plan_id"] is not None:
            raise ValueError("previous build plan missing")
    else:
        if type(previous) is not dict or previous.get("schema_version") != PLAN_SCHEMA:
            raise ValueError("typed previous build plan required")
        identity_keys = {"planner_version", "source_context_hash", "declaration_receipt_hash",
                         "revision", "previous_plan_id", "previous_payload_sha256", "plan_id", "payload_sha256"}
        if not identity_keys <= previous.keys():
            raise ValueError("previous build plan identity fields missing")
        if previous.get("planner_version") != PLANNER_VERSION or type(previous.get("revision")) is not int or not 1 <= previous["revision"] < 10000:
            raise ValueError("invalid previous build revision")
        prior_binding = previous.get("source_binding")
        binding_keys = ("match_id", "account_id", "actor", "resource_slot", "dataset_kind", "catalog_snapshot_id",
                        "hero_id", "provider_patch")
        if not isinstance(prior_binding, dict) or any(prior_binding.get(key) != context["source_binding"][key] for key in binding_keys):
            raise ValueError("previous plan account, match or catalog differs")
        if (prior_binding.get("decision_id") == context["source_binding"]["decision_id"] and
                previous.get("source_context_hash") != context["source_context_hash"]):
            raise ValueError("previous plan source context is stale")
        if previous.get("plan_id") != declared["previous_plan_id"]:
            raise ValueError("previous plan identity mismatch")
        previous_hash = content_hash({key: value for key, value in previous.items() if key != "payload_sha256"})
        if previous.get("payload_sha256") != previous_hash or previous.get("plan_id") != _plan_identity(previous):
            raise ValueError("previous build plan integrity mismatch")
        revision = previous["revision"] + 1
        revision_reason = "context_or_goal_changed"
    binding = context["source_binding"]
    receipt = {"schema_version": "foresight.build-declaration-receipt.v1",
               "origin": "explicit_player_input", "source_context_hash": context["source_context_hash"],
               "confirmation": "goal_confirmed_for_this_planning_request",
               "temporal_scope": "next_match_or_retrospective_plan",
               "prior_match_intent": "not_established",
               "declarations": {key: value for key, value in declared.items()
                                if key not in ("source_context_hash", "previous_plan_id", "decision_id")}}
    receipt_hash = content_hash(receipt)
    question = BuildQuestion(
        question_id="build-plan:" + receipt_hash, match_id=binding["match_id"],
        subject_ref=f"player:{binding['account_id']}",
        cutoff=TimeRef(binding["observation_time"] * 1000),
        goal=GoalHypothesis("planning-goal:" + receipt_hash, declared["goal_kind"],
                            declared["goal_description"], "user_hypothesis"),
        candidate_item_ids=tuple(declared["candidate_item_ids"]),
    )
    # No context Fact, ThreatEvidence or historical patch bundle is constructed
    # from player input or raw replay fields. Retrieval remains research only.
    analysis = analyze_build_question(question, catalog, limit=6)
    options = []
    for raw in analysis.options:
        item = catalog.item(raw.item_id) if raw.item_id else None
        if item is None:
            options.append(asdict(raw) | {"description": "", "catalog_cost": None,
                "catalog_cost_status": "not_applicable", "declared_remaining_cost": None,
                "budget_after": None, "affordability": "unknown", "purchase_observed": False,
                "feasibility": "unknown", "goal_condition": "Если неопределённость меняет выбранный план: " + declared["goal_description"]})
            continue
        cost = declared["remaining_costs"].get(item.internal_name)
        gold = declared["available_gold"]
        delta = gold - cost if gold is not None and cost is not None else None
        affinity = "affordable_by_declaration" if delta is not None and delta >= 0 else (
            "budget_shortfall_by_declaration" if delta is not None else "unknown")
        tradeoffs = list(raw.tradeoffs)
        if cost is not None:
            tradeoffs.append(f"Заявленный остаточный расход {cost} золота сокращает бюджет для других покупок на эту сумму; компоненты и доставка не проверены.")
        else:
            tradeoffs.append("Остаточная стоимость неизвестна: полная цена каталога не заменяет цену с уже имеющимися компонентами.")
        options.append(asdict(raw) | {"description": item.description,
            "catalog_cost": item.item_cost, "catalog_cost_status": "live_catalog_not_remaining_cost",
            "declared_remaining_cost": cost, "budget_after": delta, "affordability": affinity,
            "budget_calculation_status": "arithmetic_on_player_declarations" if delta is not None else "unknown",
            "purchase_observed": False, "feasibility": "unknown", "tradeoffs": tradeoffs,
            "goal_condition": "Если для следующего плана приоритетна цель: " + declared["goal_description"],
            "candidate_origin": "explicit_selection" if declared["candidate_item_ids"] else "literal_goal_descriptor_retrieval",
            "delivery_components_inventory": "not_established",
        })
    comparisons = []
    numeric = [o for o in options if o["item_id"] and o["declared_remaining_cost"] is not None]
    for index, first in enumerate(numeric):
        for second in numeric[index + 1:]:
            comparisons.append({"first_item_id": first["item_id"], "second_item_id": second["item_id"],
                "first_minus_second_declared_cost": first["declared_remaining_cost"] - second["declared_remaining_cost"],
                "scope": "declared_gold_cost_only", "benefit_comparison": "not_established",
                "ranking": "none"})
    # The historical analysis helper cannot interpret a goal entered now as
    # prior intent. Keep its mechanical research questions but replace its
    # historical-intent prompts with an explicit prospective planning prompt.
    historical_goal_prompts = (
        "Подтверди или измени цель;", "Какая цель была приоритетной до покупки:",
    )
    research = [text for text in analysis.research_questions
                if not text.startswith(historical_goal_prompts)]
    if declared["goal_kind"] == "unknown":
        research.insert(0, "Уточни цель следующего плана и действие, которое хочешь сохранить; прошлое намерение не установлено.")
    research.extend(("Сверь заявленную угрозу с записью собственного экрана и временем; сообщение не является доказательством замеченного сигнала.",
                     "Проверь остаточную стоимость, компоненты, доставку и слот отдельно от полной цены живого каталога.",
                     "Для каждого варианта назови проверяемый эффект относительно цели и условие пересмотра; дешевизна не доказывает полезность."))
    plan = {
        "schema_version": PLAN_SCHEMA, "planner_version": PLANNER_VERSION,
        "revision": revision, "previous_plan_id": declared["previous_plan_id"],
        "revision_reason": revision_reason, "comparison_scope": "scenario_planning_not_behavior_progress",
        "previous_payload_sha256": previous_hash,
        "source_context_hash": context["source_context_hash"], "source_binding": binding,
        "own_prefix": context["own_prefix"], "source_purchase_prefix": context["source_purchase_prefix"],
        "declaration_receipt": receipt, "declaration_receipt_hash": receipt_hash,
        "goal": {"kind": declared["goal_kind"], "description": declared["goal_description"],
                 "origin": "explicit_user_planning_goal", "temporal_scope": "next_match_or_retrospective_plan",
                 "prior_intent": "not_established"},
        "threat": {"kind": declared["threat_kind"], "description": declared["threat_description"],
                   "status": "user_declared_unverified", "noticed_at_anchor": "not_established"},
        "user_declarations": {"available_gold": declared["available_gold"],
                              "remaining_costs": declared["remaining_costs"],
                              "free_inventory_slot": declared["free_inventory_slot"],
                              "purchase_available": declared["purchase_available"],
                              "status": "unverified_player_message"},
        "options": options, "comparisons": comparisons,
        "research_questions": list(dict.fromkeys(research)),
        "status": "research_assistance", "review_state": "not_expert_validated",
        "validation_status": "unverified", "patch_applicability": "not_established",
        "feasibility": "unknown", "optimality": "not_established", "training_eligible": False,
        "limitations": list(analysis.limitations) + [
            "План задан сейчас; он не устанавливает цель прошлой покупки или правильность игрового решения.",
            "Предшествующий журнал покупок не устанавливает текущий инвентарь, продажи или доставку.",
            "Активация служит якорем просмотра; момент выбора покупки и доступность на экране не установлены.",
            "Разница заявленных расходов сравнивает бюджет; преимущества вариантов и вероятность победы не ранжируются.",
        ],
    }
    plan["plan_id"] = _plan_identity(plan)
    plan["payload_sha256"] = content_hash(plan)
    return plan
