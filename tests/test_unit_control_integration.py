from dataclasses import replace
import json
import pytest
from dota_coach.cli import main
from dota_coach.ingest.trace import parse_trace, save_trace_result
from dota_coach.live_report import render_live_report
from dota_coach.server import Workbench
from tests.test_unit_control import rows, write
from tests.test_contextual_builds import catalog


def bound(tmp_path):
    values=rows()
    values[1]['fields']={'m_vecPlayerData.0000.m_iPlayerSteamID':str(76561197960265728+7),
        'm_vecPlayerTeamData.0000.m_hSelectedHero':str(1+(1<<14)),
        'm_vecPlayerData.0000.m_nSelectedHeroID':1}
    values[2]['class']='CDOTA_Unit_Hero_Fixture'
    values.insert(5,{'t':'player_mapping','resource_slot':0,'entity_index':1,'generation':1,'status':'resolved_handle'})
    values.insert(6,{'t':'combat_log','data':{'type':'DOTA_COMBATLOG_ITEM','timestamp':10},
        'resolved_names':{'attacker_name':'npc_dota_hero_fixture','inflictor_name':'item_black_king_bar'},
        'name_resolution':'CombatLogNames_at_callback/v1'})
    values[1:1]=[{'t':'server_info','data':{'tick_interval':1}},
        {'t':'clock','fields':{'m_pGameRules.m_flGameStartTime':1,'m_pGameRules.m_nTotalPausedTicks':0,'m_pGameRules.m_bGamePaused':False,'m_pGameRules.m_nPauseStartTick':0}}]
    path,r=write(tmp_path,values)
    raw={'match_id':7,'patch':60,'players':[{'account_id':7,'hero_id':1,'player_slot':0,'purchase_log':[]}]}
    return path,r,raw


def test_report_source_graph_cannot_promote_decision_or_forecast(tmp_path):
    path,r,raw=bound(tmp_path);out=tmp_path/'report'
    p=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=out,unit_control_trace_path=path)
    graph=p['unit_control']['snapshots'][0]
    assert graph['cutoff_record_index']==9 and graph['associated_unit_count']==2
    assert graph['training_eligible'] is False and p['defensive_impact'] is None
    assert p['quality']['decision']=='not_expert_validated'
    assert json.loads((out/'unit-control.json').read_text())==p['unit_control']
    assert 'id="unit-control"' in (out/'index.html').read_text(encoding='utf-8')


def test_changed_source_fails_before_report_writes(tmp_path):
    path,r,raw=bound(tmp_path);path.write_bytes(path.read_bytes()+b'\n')
    with pytest.raises(ValueError):render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',unit_control_trace_path=path)
    assert not (tmp_path/'report').exists()


def test_cli_cutoff_and_overwrite_protection(tmp_path):
    path,r,_=bound(tmp_path);saved=tmp_path/'extraction.json';save_trace_result(r,saved)
    args=['unit-control-source','--source-jsonl',str(path),'--extraction-json',str(saved),'--account-id','7','--cutoff-record-index','6']
    assert main(args+['--out',str(tmp_path/'units.json')])==0
    assert json.loads((tmp_path/'units.json').read_text())['snapshots'][0]['associated_unit_count']==1
    before=path.read_bytes();assert main(args+['--out',str(path)])==1;assert path.read_bytes()==before


def test_trace_guard_protects_new_generated_json_and_trace_input(tmp_path):
    path=tmp_path/'unit-control.json';path.write_text('source input')
    args=['trace-review','--match-json','missing','--extraction-json','missing','--catalog-json','missing',
        '--account-id','7','--unit-control-trace',str(path),'--out',str(tmp_path)]
    assert main(args)==1 and path.read_text()=='source input'


def test_workbench_passes_full_source_path(tmp_path):
    path,r,raw=bound(tmp_path);match=tmp_path/'match.json';match.write_text(json.dumps(raw))
    w=Workbench(match,'missing','missing',tmp_path/'jobs',unit_control_trace=path)
    try:assert w.unit_control_trace_path==path
    finally:w.worker.shutdown()


def test_missing_source_is_explicitly_unavailable(tmp_path):
    _,r,raw=bound(tmp_path)
    p=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report')
    assert p['unit_control'] is None
    assert json.loads((tmp_path/'report/unit-control.json').read_text()) is None
    assert 'не подключён' in (tmp_path/'report/index.html').read_text(encoding='utf-8')



def test_many_real_source_anchors_are_bounded_with_explicit_omissions(tmp_path):
    path,_,raw=bound(tmp_path)
    values=[json.loads(row) for row in path.read_text().splitlines()]
    observed=next(row for row in values if row['t']=='combat_log')
    import copy
    values[-2:-2]=[copy.deepcopy(observed) for _ in range(128)]
    path,r=write(tmp_path,values)
    assert len(r.actions)==129
    p=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',unit_control_trace_path=path)
    assert len(p['unit_control']['snapshots'])==128
    assert p['unit_control']['anchor_selection']['omitted_anchors']==1
    assert 'оставлено без проекции: 1' in (tmp_path/'report/index.html').read_text(encoding='utf-8')
