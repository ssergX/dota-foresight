"""Planning contract tests use declared synthetic sources, never gaming verdicts."""
from copy import deepcopy
from dataclasses import replace

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.ingest.valve_catalog import (
    FetchReceipt, HeroDescriptor, MechanicDescriptor, ValveCatalogSnapshot,
)
from dota_coach.learning.build_planner import (
    REQUEST_SCHEMA, build_source_context, create_build_plan,
)


def catalog():
    receipt = FetchReceipt("https://www.dota2.com/datafeed/itemdata?language=english&item_id=1",
                           "2026-10-07T00:00:00+00:00", content_hash("synthetic fixture"), 100,
                           retrieval_method="manual_import")
    descriptions = (("item_spell_fixture", "Magic resistance; dispel", 3000),
                    ("item_mana_fixture", "Restore mana", 4000),
                    ("item_move_fixture", "Push an ally; move", 2000))
    items = tuple(MechanicDescriptor(index, name, name, receipt.source_url, receipt.receipt_hash,
                  text, (), price, (), (), (), (), "descriptor_available")
                  for index, (name, text, price) in enumerate(descriptions, 1))
    hero = HeroDescriptor(1, "npc_dota_hero_fixture", "Fixture hero", receipt.source_url, receipt.receipt_hash)
    return ValveCatalogSnapshot((receipt,), items, (hero,))


def source_purchase(item="spell_fixture", time=4, event="purchase/1"):
    return {"match_id": 1, "item_id": item, "game_time_seconds": time,
            "source_event_id": event, "source": {"match_id": 1, "url": "https://www.opendota.com/matches/1",
            "content_sha256": content_hash("full match changed after anchor"), "status": "unverified"}}


def report(snapshot=None):
    snapshot = snapshot or catalog()
    row = {"decision_id": "trace:1:record:100", "match_id": 1,
           "actor": "npc_dota_hero_fixture", "observation_time": 10,
           "source_record_index": 100, "source_trace_hash": content_hash("full trace"),
           "own_state": [["mana", 90], ["hp", 500], ["alive", True]],
           "own_state_time": 9, "own_state_source_record_index": 90,
           "resource_review": {"action_id": "trace:1:record:100",
             "mana_source": {"value": 80, "status": "raw_observed", "source_record_index": 95,
                             "net_tick": 3, "wire_type": "float32"},
             "cost_source": {"value": 30, "status": "raw_observed", "source_record_index": 80},
             "checks": [{"code": "control_allows_activation", "value": True,
                         "evidence_record_indices": [94], "status": "validated"}]}}
    return {"match_id": 1, "account_id": 7, "dataset_kind": "synthetic",
            "catalog_snapshot_id": snapshot.snapshot_id,
            "notebook": {"match_id": 1, "actor": row["actor"], "resource_slot": 0,
                         "dataset_kind": "synthetic", "entries": [row]},
            "extensions": {"portfolio": {"match_id": 1, "account_id": 7, "hero_id": 1,
              "patch": "fixture-provider-patch", "purchases": {"match_id": 1,
              "purchases": [source_purchase()]}}},
            "cards": [], "source_match_hash": content_hash("wholematch"),
            "observed_outcomes": {"death": True}, "enemy_world_state": {"hp": 1}}


def request(source=None, **updates):
    source = source or report()
    anchor = source["notebook"]["entries"][0]["decision_id"]
    value = {"schema_version": REQUEST_SCHEMA, "decision_id": anchor,
             "source_context_hash": build_source_context(source, anchor)["source_context_hash"],
             "goal_kind": "survive_spells", "goal_description": "Fixture planning goal", "confirmed": True}
    return value | updates


def test_declared_budget_math_preserves_unknown_feasibility_and_research_status():
    source, snapshot = report(), catalog()
    req = request(source, candidate_item_ids=["item_spell_fixture", "item_move_fixture"],
                  available_gold=1000, remaining_costs={"item_spell_fixture": 800, "item_move_fixture": 1300},
                  free_inventory_slot=True, purchase_available=True,
                  threat_kind="spell_damage", threat_description="Player message about spells")
    plan = create_build_plan(source, snapshot, req)
    first, second = plan["options"][:2]
    assert first["budget_after"] == 200 and second["budget_after"] == -300
    assert first["affordability"] == "affordable_by_declaration"
    assert second["affordability"] == "budget_shortfall_by_declaration"
    assert plan["comparisons"][0]["first_minus_second_declared_cost"] == -500
    assert plan["comparisons"][0]["ranking"] == "none"
    assert all(o["feasibility"] == "unknown" and o["purchase_observed"] is False for o in plan["options"])
    assert plan["training_eligible"] is False and plan["validation_status"] == "unverified"
    assert plan["source_binding"]["dataset_kind"] == "synthetic"
    assert plan["goal"]["prior_intent"] == "not_established"
    assert plan["threat"]["noticed_at_anchor"] == "not_established"
    assert plan["patch_applicability"] == "not_established"
    assert plan["payload_sha256"] == content_hash({k: v for k, v in plan.items() if k != "payload_sha256"})


def test_live_full_price_does_not_replace_component_aware_remaining_cost():
    source = report()
    plan = create_build_plan(source, catalog(), request(source, candidate_item_ids=["item_spell_fixture"], available_gold=1000))
    option = plan["options"][0]
    assert option["catalog_cost"] == 3000
    assert option["declared_remaining_cost"] is None and option["budget_after"] is None
    assert option["affordability"] == "unknown"
    declared = create_build_plan(source, catalog(), request(source,
        candidate_item_ids=["item_spell_fixture"], available_gold=1000, remaining_costs={"item_spell_fixture": 200}))
    assert declared["options"][0]["budget_after"] == 800
    assert declared["source_purchase_prefix"]["current_inventory"] == "not_established"


@pytest.mark.parametrize("legacy_value", [True, False])
def test_legacy_cooldown_truth_cannot_enter_source_bound_build_plan(legacy_value):
    source = report()
    source["notebook"]["entries"][0]["resource_review"]["checks"].append({
        "code": "raw_cooldown_end_not_after_clock", "value": legacy_value,
        "status": "validated", "evidence_record_indices": [80, 95],
    })
    context = build_source_context(source, "trace:1:record:100")
    plan = create_build_plan(source, catalog(), request(source))
    # Both a false grant and a false exclusion must remain unresolved.
    for result in (context, plan):
        checks = result["own_prefix"]["resource_operands"]["checks"]
        cooldown = next(c for c in checks if c["code"] == "raw_cooldown_end_not_after_clock")
        assert cooldown["value"] is None and cooldown["status"] == "unknown"
        assert cooldown["source_record_indices"] == [80, 95]
    assert plan["training_eligible"] is False


def test_selected_goal_changes_literal_catalog_retrieval_without_optimality():
    source = report()
    first = create_build_plan(source, catalog(), request(source))
    second = create_build_plan(source, catalog(), request(source, goal_kind="sustain_mana", goal_description="Restore resource"))
    assert first["options"][0]["item_id"] == "item_spell_fixture"
    assert second["options"][0]["item_id"] == "item_mana_fixture"
    assert first["plan_id"] != second["plan_id"]
    assert second["options"][0]["candidate_origin"] == "literal_goal_descriptor_retrieval"
    assert second["optimality"] == "not_established"


def test_future_and_enemy_and_whole_source_hash_changes_do_not_change_plan():
    source = report()
    req = request(source)
    first = create_build_plan(source, catalog(), req)
    changed = deepcopy(source)
    changed["observed_outcomes"] = {"death": False, "won": True}
    changed["enemy_world_state"] = {"all_items": ["hidden"]}
    changed["source_match_hash"] = content_hash("otherwholematch")
    row = changed["notebook"]["entries"][0]
    row["source_trace_hash"] = content_hash("futurechangedtrace")
    row["input_hash"] = content_hash("includesfuturemetadata")
    row["resource_review"]["mana_source"]["hidden_future_metadata"] = {"death": True}
    row["resource_review"]["checks"][0]["limitation"] = "arbitrary future metadata"
    purchases = changed["extensions"]["portfolio"]["purchases"]["purchases"]
    purchases[0]["source"]["content_sha256"] = content_hash("otherfullpurchasehistory")
    purchases.extend([source_purchase("mana_fixture", 11, "future/1"), source_purchase("move_fixture", None, "unknown/1"),
                      source_purchase("move_fixture", 10, "equal-boundary/1")])
    changed["notebook"]["entries"].append({"decision_id": "trace:1:record:999", "future_metadata": True})
    second = create_build_plan(changed, catalog(), req)
    assert first == second
    assert len(second["source_purchase_prefix"]["entries"]) == 1


def test_prefix_change_rejects_stale_browser_hash_and_changes_current_context():
    source = report()
    req = request(source)
    changed = deepcopy(source)
    changed["notebook"]["entries"][0]["own_state"][0][1] = 50
    with pytest.raises(ValueError, match="stale"):
        create_build_plan(changed, catalog(), req)
    fresh = create_build_plan(changed, catalog(), request(changed))
    assert fresh["source_context_hash"] != req["source_context_hash"]


def test_exact_prior_hash_and_goal_revision_chain():
    source = report()
    first = create_build_plan(source, catalog(), request(source))
    second = create_build_plan(source, catalog(), request(source, previous_plan_id=first["plan_id"],
                               goal_kind="reposition", goal_description="Different explicit goal"), previous=first)
    assert second["revision"] == 2 and second["previous_payload_sha256"] == first["payload_sha256"]
    assert second["plan_id"] != first["plan_id"]
    assert second["revision_reason"] == "context_or_goal_changed"
    assert second["comparison_scope"] == "scenario_planning_not_behavior_progress"
    with pytest.raises(ValueError, match="identity mismatch"):
        create_build_plan(source, catalog(), request(source, previous_plan_id=content_hash("foreign")), previous=first)
    corrupted = deepcopy(first)
    corrupted["goal"]["description"] = "Changed bytes"
    with pytest.raises(ValueError, match="integrity"):
        create_build_plan(source, catalog(), request(source, previous_plan_id=first["plan_id"]), previous=corrupted)
    with pytest.raises(ValueError, match="missing"):
        create_build_plan(source, catalog(), request(source, previous_plan_id=first["plan_id"]))


def test_revision_can_explicitly_move_anchor_but_not_account_or_stale_same_anchor():
    source = report()
    first = create_build_plan(source, catalog(), request(source))
    next_source = deepcopy(source)
    row = next_source["notebook"]["entries"][0]
    row.update(decision_id="trace:1:record:200", source_record_index=200, observation_time=20)
    row["resource_review"]["action_id"] = row["decision_id"]
    second = create_build_plan(next_source, catalog(), request(next_source, previous_plan_id=first["plan_id"]), previous=first)
    assert second["revision"] == 2
    assert second["source_binding"]["decision_id"] != first["source_binding"]["decision_id"]
    changed = deepcopy(source)
    changed["notebook"]["entries"][0]["own_state"][0][1] = 1
    with pytest.raises(ValueError, match="stale"):
        create_build_plan(changed, catalog(), request(changed, previous_plan_id=first["plan_id"]), previous=first)
    foreign = deepcopy(source)
    foreign["account_id"] = 8
    foreign["extensions"]["portfolio"]["account_id"] = 8
    with pytest.raises(ValueError, match="account"):
        create_build_plan(foreign, catalog(), request(foreign, previous_plan_id=first["plan_id"]), previous=first)


def test_foreign_catalog_and_missing_candidate_rejected():
    source, snapshot = report(), catalog()
    foreign = replace(snapshot, items=(replace(snapshot.items[0], description="changed"),) + snapshot.items[1:])
    with pytest.raises(ValueError, match="catalog differs"):
        create_build_plan(source, foreign, request(source))
    with pytest.raises(ValueError, match="absent"):
        create_build_plan(source, snapshot, request(source, candidate_item_ids=["item_missing"]))


@pytest.mark.parametrize("updates", [
    {"available_gold": True}, {"available_gold": float("nan")}, {"available_gold": float("inf")},
    {"available_gold": 10**1000}, {"available_gold": -1}, {"available_gold": {"value": 10}},
    {"candidate_item_ids": "item_spell_fixture"}, {"candidate_item_ids": [True]},
    {"candidate_item_ids": ["item_spell_fixture"] * 2},
    {"remaining_costs": {"item_spell_fixture": 10}}, {"remaining_costs": []},
    {"free_inventory_slot": 1}, {"purchase_available": "true"},
    {"goal_kind": []}, {"goal_description": {"fact": True}}, {"confirmed": 1},
    {"schema_version": "other"}, {"threat_kind": "control"},
    {"threat_kind": {"nested": True}}, {"threat_description": False},
    {"source_context_hash": None}, {"facts": []}, {"validation_status": "validated"},
    {"patch": "current"}, {"previous_plan_id": "not-a-hash"},
])
def test_malformed_or_self_promoted_requests_rejected(updates):
    source = report()
    with pytest.raises(ValueError):
        create_build_plan(source, catalog(), request(source, **updates))


def test_unknown_declarations_and_no_purchase_history_do_not_invent_facts():
    source = report()
    del source["extensions"]
    plan = create_build_plan(source, catalog(), request(source, goal_kind="unknown", threat_kind="unknown",
                             available_gold=None, free_inventory_slot=None, purchase_available=None))
    assert plan["source_purchase_prefix"]["status"] == "unavailable"
    assert plan["source_purchase_prefix"]["entries"] == []
    assert plan["threat"]["description"] is None
    assert plan["user_declarations"]["available_gold"] is None
    assert plan["own_prefix"]["feasibility"] == "unknown"
    assert plan["own_prefix"]["resource_operands"]["checks"][0]["status"] == "unverified_candidate"
    assert all(o["budget_after"] is None for o in plan["options"])
    assert any("следующего плана" in text for text in plan["research_questions"])
    assert not any(text.startswith("Какая цель была") for text in plan["research_questions"])


def test_native_tuple_purchase_sources_and_missing_previous_identity():
    source = report()
    sequence = source["extensions"]["portfolio"]["purchases"]
    sequence["purchases"] = tuple(sequence["purchases"])
    first = create_build_plan(source, catalog(), request(source))
    assert len(first["source_purchase_prefix"]["entries"]) == 1
    corrupt = deepcopy(first)
    del corrupt["declaration_receipt_hash"]
    corrupt["payload_sha256"] = content_hash({k: v for k, v in corrupt.items() if k != "payload_sha256"})
    with pytest.raises(ValueError, match="fields missing"):
        create_build_plan(source, catalog(), request(source, previous_plan_id=first["plan_id"]), previous=corrupt)


def test_equal_or_future_own_records_become_unknown():
    source = report()
    row = source["notebook"]["entries"][0]
    row["own_state_source_record_index"] = 100
    row["resource_review"]["mana_source"]["source_record_index"] = 101
    row["resource_review"]["checks"][0]["evidence_record_indices"] = [100]
    ctx = build_source_context(source, row["decision_id"])
    assert ctx["own_prefix"]["status"] == "unknown"
    assert all(value is None for value in ctx["own_prefix"]["own_state"].values())
    assert ctx["own_prefix"]["resource_operands"]["mana"]["value"] is None
    assert ctx["own_prefix"]["resource_operands"]["checks"][0]["value"] is None


@pytest.mark.parametrize("change", ["notebook_match", "row_match", "actor", "duplicate", "record", "time", "kind", "resource_action", "portfolio_account", "purchase_source"])
def test_corrupt_source_bindings_fail_closed(change):
    source = report()
    anchor = source["notebook"]["entries"][0]
    decision = anchor["decision_id"]
    if change == "notebook_match":
        source["notebook"]["match_id"] = 2
    elif change == "row_match":
        anchor["match_id"] = 2
    elif change == "actor":
        anchor["actor"] = "foreign"
    elif change == "duplicate":
        source["notebook"]["entries"].append(deepcopy(anchor))
    elif change == "record":
        anchor["source_record_index"] = 99
    elif change == "time":
        anchor["observation_time"] = True
    elif change == "kind":
        source["dataset_kind"] = "validated_real"
    elif change == "resource_action":
        anchor["resource_review"]["action_id"] = "foreign"
    elif change == "portfolio_account":
        source["extensions"]["portfolio"]["account_id"] = 8
    elif change == "purchase_source":
        source["extensions"]["portfolio"]["purchases"]["purchases"][0]["source"]["match_id"] = 2
    with pytest.raises(ValueError):
        build_source_context(source, decision)


def test_no_anchor_does_not_fabricate_current_decision():
    source = report()
    source["notebook"]["entries"] = []
    with pytest.raises(ValueError, match="absent"):
        build_source_context(source, "trace:1:record:100")
