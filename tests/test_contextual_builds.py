from dataclasses import asdict, replace
import json

import pytest

from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, content_hash
from dota_coach.ingest.valve_catalog import (FetchReceipt, HeroDescriptor, MechanicDescriptor,
                                            ValveCatalogSnapshot)
from dota_coach.learning.builds import PurchaseObservation
from dota_coach.learning.contextual import (BuildQuestion, GoalFeedback, GoalHypothesis, MechanicMapping,
                                           PatchMechanicBundle, ThreatEvidence, analyze_build_question,
                                           check_patch_bundle, load_patch_bundle, revise_goal)
from dota_coach.learning.study import MatchSource


def catalog():
    receipt = FetchReceipt("https://www.dota2.com/datafeed/itemdata?language=english&item_id=116",
                           "2026-10-05T12:00:00+00:00", content_hash("synthetic payload"), 100,
                           retrieval_method="manual_import")
    item = MechanicDescriptor(116, "item_fixture", "Synthetic fixture item", receipt.source_url,
                              receipt.receipt_hash, "Fixture magic resistance effect; uses mana.",
                              ("Fixture contextual limitation.",), 2000, (20,), (25,), (), (), "descriptor_available")
    hero = HeroDescriptor(1, "npc_dota_hero_fixture", "Synthetic fixture hero", receipt.source_url, receipt.receipt_hash)
    return ValveCatalogSnapshot((receipt,), (item,), (hero,))


def bundle(s=None):
    s = s or catalog()
    item = s.items[0]
    mapping = MechanicMapping("fixture.mapping.v1", item.internal_name, item.descriptor_hash,
                               "Fixture magic resistance effect", ("survive_spells",), ("spell_damage",),
                               ("Fixture opportunity cost; compare with the other goal.",),
                               ("Fixture threat is replaced by a different observed threat.",))
    return PatchMechanicBundle("fixture.bundle", "v1", "fixture-patch", s.snapshot_id,
                               "fixture-reviewer", "2026-10-05T12:00:00+00:00",
                               "https://www.dota2.com/patches", (mapping,))


def fact(predicate, value=True, *, perspective="screen", subject="self", at=10000, flags=()):
    time = TimeRef(at, uncertainty_ms=0, clock_mapping_version="fixture-clock.v1", order_status="verified")
    source = SourceRef("subject-prefix", content_hash("synthetic prefix"), "synthetic fixture", "v1", "prefix/only")
    return Fact(predicate, subject, predicate, value, "observed", time, time, perspective,
                (source,), observer_ref="self", quality_flags=flags, method_version="fixture.v1")


def question(*, context=True, goal_confirmed=True):
    context_facts = tuple(fact(key, value) for key, value in (
        ("self.available_gold", 1000), ("self.remaining_cost:item_fixture", 900),
        ("self.purchase_available:item_fixture", True), ("self.free_inventory_slot", True))) if context else ()
    threat = ThreatEvidence("threat1", "spell_damage", fact("observed.threat.spell_damage", perspective="team", subject="enemy"))
    goal = GoalHypothesis("goal1", "survive_spells", "Fixture selected goal",
                          "user_confirmed" if goal_confirmed else "user_hypothesis")
    return BuildQuestion("q1", 1, "self", TimeRef(10000, uncertainty_ms=0,
                         clock_mapping_version="fixture-clock.v1", order_status="verified"), goal,
                         "fixture-patch", 1, "support", (threat,), context_facts, (), ("fixture",))


def purchase(t=5, key="fixture"):
    source = MatchSource(1, "https://www.opendota.com/matches/1", "", "", "unverified")
    return PurchaseObservation(1, key, t, source, "fixture-source-event")


def test_unknown_patch_has_source_backed_research_tradeoffs_and_actual_purchases():
    q = replace(question(), match_patch=None, purchases=(purchase(),))
    result = analyze_build_question(q, catalog())
    assert result.status == "research_assistance"
    item = result.options[0]
    assert item.purchase_observed is True and item.status == "research_question"
    assert item.source_urls[0].startswith("https://www.dota2.com/datafeed/")
    assert any("живом каталоге" in tradeoff and "2000" in tradeoff for tradeoff in item.tradeoffs)
    assert any("компонентами" in tradeoff for tradeoff in item.tradeoffs)
    assert result.purchases.purchases[0].item_id == "fixture"
    assert "historical_patch_compatibility_not_established" in result.reason_codes
    assert result.attention_rule is None and result.optimality == "not_established"
    assert result.options[-1].item_id is None


def test_declared_patch_context_produces_conditional_options_never_validated():
    s, q = catalog(), question()
    result = analyze_build_question(q, s, bundle(s))
    item = result.options[0]
    assert result.status == "conditional_analysis"
    assert item.status == "conditional_option" and item.feasibility == "feasible"
    assert "observed.threat.spell_damage" in item.evidence_ids
    assert "self.remaining_cost:item_fixture" in item.evidence_ids
    assert item.tradeoffs and item.revisit_conditions
    assert result.attention_rule.category == "planning_attention"
    assert result.attention_rule.training_eligible is False
    assert result.validation_status == "unverified"
    assert result.patch_applicability == "matching_declared_patch_review"


def test_full_item_price_is_not_remaining_purchase_cost():
    s, q = catalog(), question()
    # The full catalog price is 2000, but traced remaining cost with components
    # is 900; observed gold is 1000. Full price alone would give a false failure.
    result = analyze_build_question(q, s, bundle(s))
    assert result.options[0].feasibility == "feasible"
    changed = replace(q, context_facts=tuple(replace(f, value=1100) if f.predicate.startswith("self.remaining_cost:")
                                           else f for f in q.context_facts))
    assert analyze_build_question(changed, s, bundle(s)).options[0].feasibility == "infeasible"


def test_missing_context_does_not_create_feasible_purchase_or_attention_rule():
    s = catalog()
    result = analyze_build_question(question(context=False), s, bundle(s))
    assert result.options[0].status == "conditional_option"
    assert result.options[0].feasibility == "unknown"
    assert "context_unknown:self.available_gold" in result.options[0].feasibility_unknowns
    assert result.attention_rule is None
    assert any("выполнимость" in text for text in result.research_questions)


def test_unconfirmed_goal_can_compare_if_condition_but_never_gets_an_exercise():
    s = catalog()
    result = analyze_build_question(question(goal_confirmed=False), s, bundle(s))
    assert result.options[0].goal_condition.startswith("Если цель")
    assert "goal_is_hypothesis" in result.reason_codes
    assert result.attention_rule is None


def test_goal_is_editable_with_stable_feedback_chain_and_rechanges_analysis():
    q = question()
    feedback = GoalFeedback("feedback1", q.goal.goal_id, "reposition", "I intended to reposition")
    revised = revise_goal(q.goal, feedback)
    assert revised.kind == "reposition" and revised.origin == "user_confirmed"
    assert revised.previous_goal_id == q.goal.goal_id and revised.feedback_id == feedback.feedback_id
    assert revised.revision == 2 and revised.goal_id != q.goal.goal_id
    before = analyze_build_question(q, catalog(), bundle())
    after = analyze_build_question(replace(q, goal=revised), catalog(), bundle())
    assert before.input_hash != after.input_hash
    assert after.options[0].status == "research_question"
    assert after.attention_rule is None
    with pytest.raises(ValueError, match="identity mismatch"):
        revise_goal(q.goal, replace(feedback, goal_id="wrong"))


def test_world_enemy_state_and_future_fact_or_purchase_are_rejected():
    q = question()
    with pytest.raises(ValueError, match="not world"):
        ThreatEvidence("t", "spell_damage", fact("observed.threat.spell_damage", perspective="world", subject="enemy"))
    with pytest.raises(ValueError, match="relabeled"):
        ThreatEvidence("t", "spell_damage", fact("enemy.hp", 10, perspective="team", subject="enemy"))
    with pytest.raises(ValueError, match="own resource"):
        replace(q, context_facts=(fact("self.available_gold", 1000, subject="enemy"),))
    with pytest.raises(ValueError, match="future or missing"):
        replace(q, context_facts=(fact("self.available_gold", 1000, at=10001),))
    with pytest.raises(ValueError, match="future purchases"):
        replace(q, purchases=(purchase(11),))


def test_wrong_observation_recipient_unknown_order_or_stale_threat_does_not_activate_mapping():
    q, s = question(), catalog()
    with pytest.raises(ValueError, match="recipient"):
        replace(q, threats=(replace(q.threats[0], fact=replace(q.threats[0].fact, observer_ref="other")),))
    for fact_changes in ({"quality_flags": ("extraction_unverified",)},
                         {"available_at": replace(q.cutoff, uncertainty_ms=1)},
                         {"available_at": replace(q.cutoff, clock_mapping_version="different-clock")},
                         {"valid_at": replace(q.cutoff, game_time_ms=0), "available_at": replace(q.cutoff, game_time_ms=0)}):
        changed = replace(q, threats=(replace(q.threats[0], fact=replace(q.threats[0].fact, **fact_changes)),))
        result = analyze_build_question(changed, s, bundle(s))
        assert result.options[0].status == "research_question"
        assert result.attention_rule is None


def test_patch_mismatch_and_goal_or_threat_mismatch_are_research_only():
    q, s = question(), catalog()
    for changed in (replace(q, match_patch="different-patch"), replace(q, threats=()),
                    replace(q, goal=GoalHypothesis("other-goal", "accelerate_farm", "Fixture other goal", "user_confirmed"))):
        assert analyze_build_question(changed, s, bundle(s)).options[0].status == "research_question"


def test_patch_bundle_binds_exact_descriptor_and_excerpt_and_cannot_self_promote(tmp_path):
    s, b = catalog(), bundle()
    check_patch_bundle(b, s)
    for changed in (replace(b, snapshot_id=content_hash("other")),
                    replace(b, mappings=(replace(b.mappings[0], descriptor_hash=content_hash("other")),)),
                    replace(b, mappings=(replace(b.mappings[0], source_excerpt="A fictional guaranteed counter"),))):
        with pytest.raises(ValueError):
            check_patch_bundle(changed, s)
    with pytest.raises(ValueError, match="self-promote"):
        replace(b, validation_status="validated")
    with pytest.raises(ValueError, match="primary Valve"):
        replace(b, patch_source_url="https://example.com/untrusted-mechanics")
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(asdict(b)), encoding="utf-8")
    assert load_patch_bundle(path, s) == b


def test_unknown_goal_creates_editable_hypotheses_not_inferred_intent():
    q = replace(question(), goal=GoalHypothesis("unknown-goal"), threats=(), candidate_item_ids=())
    result = analyze_build_question(q)
    assert result.active_goal.kind == "unknown"
    assert len(result.goal_hypotheses) >= 3
    assert all(g.origin == "research_question" for g in result.goal_hypotheses)
    assert "goal_not_selected" in result.reason_codes
    assert result.research_questions and result.options[-1].item_id is None


def test_literal_source_retrieval_still_requires_patch_review_and_observed_context():
    q = replace(question(), candidate_item_ids=(), purchases=(), match_patch=None)
    result = analyze_build_question(q, catalog())
    assert result.options[0].label == "Synthetic fixture item"
    assert result.options[0].status == "research_question"
    assert result.options[0].feasibility == "unknown"


def test_unavailable_catalog_preserves_purchase_identity_and_targeted_questions():
    q = replace(question(), purchases=(purchase(),))
    result = analyze_build_question(q)
    assert result.purchases.purchases[0].item_id == "fixture"
    assert result.options[0].purchase_observed is True
    assert "mechanic_catalog_unavailable" in result.reason_codes
    assert any("стоимость" in text for text in result.research_questions)


@pytest.mark.parametrize("changes", (
    {"method_version": "legacy/unverified"},
    {"method_version": "unknown"},
    {"quality_flags": ("extraction_unverified",)},
    {"valid_at": TimeRef(10000, uncertainty_ms=0, clock_mapping_version="other-clock", order_status="verified")},
    {"valid_at": TimeRef(10000, uncertainty_ms=0, clock_mapping_version="fixture-clock.v1", order_status="unknown")},
    {"available_at": TimeRef(10000, uncertainty_ms=0, clock_mapping_version="fixture-clock.v1", order_status="partial")},
))
def test_unadmitted_resource_semantics_never_grant_purchase_feasibility(changes):
    q, s = question(), catalog()
    facts = (replace(q.context_facts[0], **changes),) + q.context_facts[1:]
    result = analyze_build_question(replace(q, context_facts=facts), s, bundle(s))
    assert result.options[0].feasibility == "unknown"
    assert "context_unknown:self.available_gold" in result.options[0].feasibility_unknowns
    assert result.attention_rule is None
    assert result.validation_status == "unverified"


@pytest.mark.parametrize("clock,order,uncertainty", (
    ("legacy/unverified", "verified", 0),
    ("fixture-clock.v1", "unknown", 0),
    ("fixture-clock.v1", "partial", 0),
    ("fixture-clock.v1", "verified", None),
))
def test_unadmitted_cutoff_cannot_activate_mechanic_or_attention(clock, order, uncertainty):
    q, s = question(), catalog()
    cutoff = replace(q.cutoff, clock_mapping_version=clock, order_status=order, uncertainty_ms=uncertainty)
    result = analyze_build_question(replace(q, cutoff=cutoff), s, bundle(s))
    assert result.options[0].status == "research_question"
    assert result.options[0].feasibility == "unknown"
    assert result.attention_rule is None


def test_resource_freshness_includes_full_uncertainty_interval():
    q, s = question(), catalog()
    oldest = replace(q.context_facts[0],
                     valid_at=replace(q.cutoff, game_time_ms=5000, uncertainty_ms=1),
                     available_at=replace(q.cutoff, game_time_ms=5001))
    result = analyze_build_question(replace(q, context_facts=(oldest,) + q.context_facts[1:]), s, bundle(s))
    assert result.options[0].feasibility == "unknown"
    assert result.attention_rule is None


def test_postmatch_receipt_change_does_not_change_build_prefix_identity():
    earlier_source = replace(purchase().source,
                             content_sha256=content_hash({"purchase_prefix": "same", "future_outcome": "win"}),
                             checked_at="2026-10-05T12:00:00Z")
    later_source = replace(earlier_source,
                           content_sha256=content_hash({"purchase_prefix": "same", "future_outcome": "loss"}),
                           checked_at="2026-10-06T12:00:00Z")
    before = replace(question(), purchases=(replace(purchase(), source=earlier_source),))
    after = replace(before, purchases=(replace(before.purchases[0], source=later_source),))
    left = analyze_build_question(before, catalog(), bundle())
    right = analyze_build_question(after, catalog(), bundle())
    assert before.input_hash == after.input_hash == left.input_hash == right.input_hash
    assert left.options == right.options and left.attention_rule == right.attention_rule
    # Exact immutable receipts remain available for artifact binding/auditing.
    assert asdict(left)["purchases"]["purchases"][0]["source"] == asdict(earlier_source)
    assert asdict(right)["purchases"]["purchases"][0]["source"] == asdict(later_source)
    assert left.purchases != right.purchases
    assert right.validation_status == "unverified"


def test_changed_purchase_prefix_or_source_scope_changes_analytical_identity():
    q = replace(question(), purchases=(purchase(),))
    for changed_purchase in (
        replace(purchase(), item_id="other_fixture"),
        replace(purchase(), game_time_seconds=6),
        replace(purchase(), source_event_id="another-prefix-event"),
        replace(purchase(), source=replace(purchase().source, url="https://api.opendota.com/api/matches/1")),
    ):
        assert replace(q, purchases=(changed_purchase,)).input_hash != q.input_hash


@pytest.mark.parametrize("purchase_time", (None, 10, 11))
def test_unresolved_purchase_time_is_not_admitted_as_prechoice_evidence(purchase_time):
    with pytest.raises(ValueError, match="purchase"):
        replace(question(), purchases=(purchase(purchase_time),))


def test_purchase_must_precede_entire_cutoff_uncertainty_interval():
    q = replace(question(), cutoff=replace(question().cutoff, uncertainty_ms=1000))
    assert replace(q, purchases=(purchase(8.9),)).purchases[0].game_time_seconds == 8.9
    with pytest.raises(ValueError, match="equal-time"):
        replace(q, purchases=(purchase(9),))


def test_unknown_purchase_clock_stays_research_only_after_receipt_projection():
    q = replace(question(), purchases=(purchase(),),
                cutoff=TimeRef(10000))
    result = analyze_build_question(q, catalog(), bundle())
    assert result.options[0].feasibility == "unknown"
    assert result.attention_rule is None
    assert result.validation_status == "unverified"
