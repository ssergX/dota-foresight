from dataclasses import replace
import json

import pytest

from dota_coach.evidence.contracts import content_hash
from dota_coach.feedback import import_feedback
from dota_coach.live_report import render_live_report
from dota_coach.server import Workbench
from dota_coach.ingest.trace import save_trace_result
from dota_coach.ingest.valve_catalog import save_valve_snapshot
from dota_coach.cli import main
from tests.test_contextual_builds import catalog
from tests.test_trace_episode import result


def sources():
    r=result()
    r=replace(r,replay=replace(r.replay,heroes={0:'CDOTA_Unit_Hero_Fixture'}),
        actions=(replace(r.actions[0],actor='npc_dota_hero_fixture'),),
        audit=r.audit|{'resource_identities':{'0':{'m_iPlayerSteamID':str(76561197960265728+7),'m_nSelectedHeroID':1}}})
    raw={'match_id':123,'patch':60,'players':[{'account_id':7,'hero_id':1,'player_slot':0,
        'personaname':'<script>bad()</script>','purchase_log':[{'key':'black_king_bar','time':5},
        {'key':'manta','time':12}]}]}
    return r,raw


def test_live_report_integrates_prefix_build_questions_and_bound_feedback(tmp_path):
    r,raw=sources()
    payload=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path)
    assert payload['notebook']['activation_candidates']==1
    assert payload['quality']['decision']=='not_expert_validated'
    assert [p['item_id'] for p in payload['build_advice']['purchases']['purchases']]==['black_king_bar']
    page=(tmp_path/'index.html').read_text(encoding='utf-8')
    assert 'fixture' in page and 'Отложить выбор' in page
    assert '<script>bad()' not in page
    c=payload['cards'][0]
    row={'schema_version':'foresight.feedback.v1','match_id':123,'decision_id':c['episode_id'],
        'assessment_hash':content_hash(c['dossier']['assessment']),'context_hash':content_hash(c['dossier']),
        'kind':'different_goal','comment':'planned spell','created_at':'2026-10-06T00:00:00Z','status':'unreviewed'}
    assert len(import_feedback(payload,[row]))==1
    c['dossier']['observation']['item']='changed'
    with pytest.raises(ValueError,match='different decision'):
        import_feedback(payload,[row])


def test_identity_conflicts_fail_before_writing_report(tmp_path):
    r,raw=sources()
    with pytest.raises(ValueError,match='selected hero'):
        render_live_report(replace(r,replay=replace(r.replay,heroes={0:'Other'})),raw,
            account_id=7,catalog=catalog(),out_dir=tmp_path)
    assert not (tmp_path/'index.html').exists()


def test_order_receipts_integrate_without_changing_decision_notebook(tmp_path):
    from tests.test_order_source import fixture,write,CALLBACKS
    path,_,rows=fixture(tmp_path)
    write(path,rows)
    r,raw=sources()
    r=replace(r,audit=r.audit|{'replay_sha256':'a'*64})
    baseline=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'base')
    linked=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'linked',orders_path=path)
    assert linked['notebook']==baseline['notebook']
    assert linked['cards']==baseline['cards']
    assert linked['replay_sources']['orders']['callback_counts'][CALLBACKS[0]]==1
    assert linked['replay_sources']['orders']['attempt_count'] is None
    page=(tmp_path/'linked/index.html').read_text(encoding='utf-8')
    assert 'сообщений приказов spectator по всему матчу' in page
    assert (tmp_path/'linked/replay-sources.json').is_file()


def test_mismatched_order_source_refuses_report_before_write(tmp_path):
    from tests.test_order_source import fixture,write
    path,_,rows=fixture(tmp_path)
    rows[0]['replay_sha256']='b'*64
    write(path,rows)
    r,raw=sources();r=replace(r,audit=r.audit|{'replay_sha256':'a'*64})
    with pytest.raises(ValueError,match='binding'):
        render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',orders_path=path)
    assert not (tmp_path/'report/index.html').exists()


def test_same_hero_does_not_authorize_wrong_account_join(tmp_path):
    r,raw=sources()
    r=replace(r,audit=r.audit|{'resource_identities':{'0':{'m_iPlayerSteamID':'76561197960265999','m_nSelectedHeroID':1}}})
    with pytest.raises(ValueError,match='Steam account'):
        render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path)


def test_external_build_cannot_replace_target_plan(tmp_path):
    from dota_coach.learning.contextual import BuildQuestion,GoalHypothesis,analyze_build_question
    from dota_coach.evidence.contracts import TimeRef
    r,raw=sources()
    other=analyze_build_question(BuildQuestion('other',999,'player:88',TimeRef(0),GoalHypothesis('goal')),catalog())
    with pytest.raises(ValueError,match='bind'):
        render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path,build_advice=other)
    assert not (tmp_path/'index.html').exists()


def test_synthetic_or_unknown_origin_never_claimed_real(tmp_path):
    r,raw=sources()
    for kind,label in [('synthetic','Синтетический пример'),('unknown','Происхождение replay не установлено')]:
        changed=replace(r,replay=replace(r.replay,manifest=replace(r.replay.manifest,dataset_kind=kind)))
        render_live_report(changed,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/kind)
        page=(tmp_path/kind/'index.html').read_text(encoding='utf-8')
        assert label in page and 'Реальный публичный replay' not in page
        payload=json.loads((tmp_path/kind/'analysis.json').read_text(encoding='utf-8'))
        assert payload['dataset_kind']==kind


def test_workbench_shows_error_and_rejects_wrong_account(tmp_path):
    _,raw=sources()
    rawpath=tmp_path/'match.json';rawpath.write_text(json.dumps(raw),encoding='utf-8')
    work=Workbench(rawpath,tmp_path/'missing.json',tmp_path/'catalog.json',tmp_path/'jobs')
    assert '&lt;script&gt;' in work.page()
    with pytest.raises(ValueError,match='отсутствует'):
        work.submit(999)
    ident=work.submit(7)
    work.worker.shutdown(wait=True)
    assert work.jobs[ident]['state']=='error'
    assert 'report_url' not in work.jobs[ident]


def test_cached_cli_cannot_ignore_independent_replay_hash(tmp_path):
    r,raw=sources()
    match=tmp_path/'match.json';match.write_text(json.dumps(raw),encoding='utf-8')
    extraction=tmp_path/'extraction.json';save_trace_result(r,extraction)
    # Bind the synthetic test audit exactly as a captured extraction would.
    data=json.loads(extraction.read_text(encoding='utf-8'))
    data['audit'].update(match_id=123,replay_sha256='a'*64)
    data.pop('payload_sha256');data['payload_sha256']=content_hash(data)
    extraction.write_text(json.dumps(data),encoding='utf-8')
    cat=tmp_path/'catalog.json';save_valve_snapshot(catalog(),cat)
    out=tmp_path/'report'
    assert main(['trace-review','--match-json',str(match),'--extraction-json',str(extraction),
        '--catalog-json',str(cat),'--account-id','7','--replay-sha256','b'*64,'--out',str(out)])==1
    assert not (out/'index.html').exists()
