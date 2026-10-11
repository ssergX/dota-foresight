from dataclasses import replace

from dota_coach.decisions.trace_episode import activation_notebook
from dota_coach.evidence.contracts import ReplayManifest
from dota_coach.ingest.trace import LoggedAction, TraceResult
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState


def result(hp=100, future_hp=0, opponent_hp=999):
    own = UnitState(0, 1, 2, hp, 1000, 20, 10, 300, True)
    enemy = UnitState(1, 99, 99, opponent_hp, 1000, 200, 10, 400, True)
    replay = ParsedReplay(123, 0, {0:"CDOTA_Unit_Hero_Kez"},
        [ReplayFrame(9.5,{0:own,1:enemy}), ReplayFrame(10.1,{0:replace(own,hp=future_hp)})],
        manifest=ReplayManifest("a"*64,123))
    actions = (LoggedAction("a1",10,"item","npc_dota_hero_kez",None,"item_black_king_bar",10,"source"),
        LoggedAction("a2",11,"death","npc_dota_hero_kez",None,None,11,"source"),
        LoggedAction("a3",12,"item",None,None,"item_black_king_bar",12,"source"))
    return TraceResult(replay,actions,{'timing_provenance':[{'frame_time':9.5,'prefix_record_index':9},{'frame_time':10.1,'prefix_record_index':11}]},())


def test_no_future_opponent_or_outcome_dependency():
    a=activation_notebook(result(), actor="npc_dota_hero_kez",resource_slot=0)
    b=activation_notebook(result(future_hp=900,opponent_hp=1),actor="npc_dota_hero_kez",resource_slot=0)
    assert a==b
    assert a["activation_candidates"]==1 and a["unknown_actor_actions"]==1
    assert a["assessed_decisions"]==0 and a["non_activation_opportunities"] is None
    assert dict(a["entries"][0]["own_state"])["hp"]==100
    assert "x" not in dict(a["entries"][0]["own_state"])


def test_future_nearest_state_never_backfills():
    r=result()
    r=replace(r,replay=replace(r.replay,frames=[r.replay.frames[1]]))
    entry=activation_notebook(r,actor="npc_dota_hero_kez",resource_slot=0)["entries"][0]
    assert entry["own_state_time"] is None
    assert all(v is None for k,v in entry["own_state"])


def test_non_defensive_actions_do_not_become_choices():
    r=result()
    r=replace(r,actions=(replace(r.actions[0],ability_or_item="item_tpscroll"),))
    assert activation_notebook(r,actor="npc_dota_hero_kez",resource_slot=0)["activation_candidates"]==0


def test_notebook_preserves_source_dataset_kind_instead_of_promoting_it():
    for kind in ("synthetic", "unknown", "replay"):
        r = result()
        r = replace(r, replay=replace(r.replay, manifest=replace(r.replay.manifest, dataset_kind=kind)))
        notebook = activation_notebook(r, actor="npc_dota_hero_kez", resource_slot=0)
        assert notebook["dataset_kind"] == kind


def test_late_delivered_prefix_and_missing_provenance_abstain_on_state():
    for audit in ({}, {'timing_provenance':[{'frame_time':9.5,'prefix_record_index':12}]}):
        r=replace(result(),audit=audit)
        entry=activation_notebook(r,actor='npc_dota_hero_kez',resource_slot=0)['entries'][0]
        assert entry['own_state_time'] is None
        assert entry['own_state_source_record_index'] is None
