from dataclasses import replace

import pytest

from dota_coach.decisions.contracts import (
    ActionObservation, Assessment, DecisionBoundary, DecisionInput,
)
from dota_coach.evidence.contracts import Fact, SourceRef, TimeRef, canonical_json
from dota_coach.evidence.knowledge import KnowledgeSnapshot, project_knowledge
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState, WardEvent


def unit(slot=0, x=0., hp=100):
    return UnitState(slot, x, 0., hp, 100, 50., 1, 0, True)


def replay(enemy=None, own=None, future=()):
    units = {5: enemy or unit(5, 9000.)}
    if own is not False:
        units[0] = own or unit()
    return ParsedReplay(1, 0., {0: "Own", 5: "Enemy"},
                        [ReplayFrame(10., units), *future], teams={0: 2, 5: 3})


def test_hidden_world_and_future_do_not_change_canonical_knowledge():
    first = replay()
    second = replay(enemy=replace(unit(5, 100.), hp=1, alive=False),
                    future=[ReplayFrame(20., {0: unit(hp=1)})])
    second = replace(second, wards=[WardEvent(7, 30, "obs", 2, 100, 0, "placed")])
    a, b = project_knowledge(first, 10., 0), project_knowledge(second, 10., 0)
    assert canonical_json(a) == canonical_json(b)
    assert a.input_hash == b.input_hash
    assert not any(f.predicate in ("enemy.x", "enemy.hp", "enemy.alive") for f in a.facts)


def test_known_zero_and_missing_are_different():
    missing = project_knowledge(replay(own=replace(unit(), hp=None)), 10., 0)
    zero = project_knowledge(replay(own=replace(unit(), hp=0)), 10., 0)
    a = next(f for f in missing.facts if f.predicate == "self.hp")
    b = next(f for f in zero.facts if f.predicate == "self.hp")
    assert a.status == "unknown" and a.value is None and a.unknown_reason
    assert b.status == "observed" and b.value == 0


def test_missing_self_and_stale_sample_do_not_invent_death_or_position():
    for parsed, t in ((replay(own=False), 10.), (replay(), 99.)):
        snapshot = project_knowledge(parsed, t, 0)
        own = [f for f in snapshot.facts if f.predicate.startswith("self.")]
        assert len(own) == 8 and all(f.value is None for f in own)
        assert all(f.status == "unknown" and f.unknown_reason for f in own)


def test_snapshot_rejects_world_and_future_fact():
    source = SourceRef("a", "hash", "test", "v1", "tick:1")
    fact = Fact("f", "self", "self.hp", 10, "observed", TimeRef(100),
                TimeRef(100), "world", (source,))
    with pytest.raises(ValueError, match="world"):
        KnowledgeSnapshot("s", "self", TimeRef(100), (fact,))
    with pytest.raises(ValueError, match="future"):
        KnowledgeSnapshot("s", "self", TimeRef(50), (replace(fact, perspective="team"),))


def test_time_uncertainty_straddling_cutoff_is_rejected():
    source = SourceRef("a", "hash", "test", "v1", "tick:1")
    fact = Fact("f", "self", "self.hp", 10, "observed", TimeRef(100),
                TimeRef(100, uncertainty_ms=10), "team", (source,))
    with pytest.raises(ValueError, match="future"):
        KnowledgeSnapshot("s", "self", TimeRef(100), (fact,))


def test_unresolved_incident_cannot_become_decision_input():
    knowledge = project_knowledge(replay(), 10, 0)
    action = ActionObservation("activation_commit", "bkb", "complete", ("event:1",))
    with pytest.raises(ValueError, match="unresolved"):
        DecisionInput("d", knowledge, DecisionBoundary("b", None), action, "c", "v1")
    with pytest.raises(ValueError, match="absence"):
        ActionObservation("observed_no_activation", "bkb", "unknown", ())
    with pytest.raises(ValueError, match="no validated"):
        Assessment("a", "mistake", ("ready",))


def test_resolved_input_hash_is_independent_of_hidden_positions():
    boundary = DecisionBoundary("b", TimeRef(10000), "resolved", "expert_annotation", ("e1",))
    action = ActionObservation("activation_commit", "bkb", "complete", ("event:1",))
    a = DecisionInput("d", project_knowledge(replay(), 10, 0), boundary, action, "c", "v1")
    b = replace(a, knowledge=project_knowledge(replay(enemy=unit(5, 100)), 10, 0))
    assert a.input_hash == b.input_hash


def test_mistagging_enemy_world_fact_as_team_does_not_bypass_allowlist():
    source = SourceRef("a", "hash", "test", "v1", "tick:1")
    fact = Fact("f", "enemy", "enemy.x", 9000, "observed", TimeRef(100),
                TimeRef(100), "team", (source,))
    with pytest.raises(ValueError, match="predicate"):
        KnowledgeSnapshot("s", "self", TimeRef(100), (fact,))


def test_nested_world_payload_cannot_hide_in_scalar_fact():
    source = SourceRef("a", "hash", "test", "v1", "tick:1")
    with pytest.raises(ValueError, match="scalar"):
        Fact("f", "self", "self.x", {"enemy_positions": [9000]}, "observed",
             TimeRef(100), TimeRef(100), "team", (source,))


def test_time_interval_comparison_does_not_round_future_uncertainty_to_boundary():
    from dota_coach.evidence.contracts import TimeRef
    cutoff=TimeRef(1000,10,5,0,'clock.v1','verified')
    assert not TimeRef(1000,9,1,1e-14,'clock.v1','verified').definitely_available_before(cutoff)
    assert TimeRef(1000,9,1,0,'clock.v1','verified').definitely_available_before(cutoff)
    assert not TimeRef(1000,9,1,0,'clock.v1','verified').definitely_available_before(
        TimeRef(1000,10,5,1e-14,'clock.v1','verified'))
