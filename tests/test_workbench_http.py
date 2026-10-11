import http.client
import json
import threading
from datetime import datetime
import pytest

import dota_coach.server as server
from tests.test_live_report import sources


@pytest.mark.parametrize('endpoint',['/api/resource-plan','/api/semantic-prefix','/api/build-plan','/api/ward-plan','/api/review/'+'a'*24])
def test_deep_json_gets_controlled_400_without_breaking_workbench(tmp_path,monkeypatch,endpoint):
    _,raw=sources();source=tmp_path/'match.json';source.write_text(json.dumps(raw),encoding='utf-8')
    work=server.Workbench(source,tmp_path/'missing.json',tmp_path/'catalog.json',tmp_path/'jobs')
    factory=server.ThreadingHTTPServer;bound=[];ready=threading.Event()
    def capture(address,handler):
        instance=factory(address,handler);bound.append(instance);ready.set();return instance
    monkeypatch.setattr(server,'ThreadingHTTPServer',capture)
    thread=threading.Thread(target=server.serve_workbench,args=(work,0),daemon=True);thread.start()
    assert ready.wait(3)
    client=http.client.HTTPConnection('127.0.0.1',bound[0].server_port,timeout=3)
    try:
        client.request('POST',endpoint,body=b'{"nested":'+b'['*30000+b'0'+b']'*30000+b'}',
                       headers={'Content-Type':'application/json','X-Foresight-Token':work.token})
        response=client.getresponse()
        assert response.status==400 and json.loads(response.read())['error']
        client.request('GET','/')
        response=client.getresponse()
        assert response.status==200 and b'Foresight' in response.read()
    finally:
        client.close();bound[0].shutdown();thread.join(3);work.worker.shutdown()


@pytest.fixture
def planning_server(tmp_path, monkeypatch):
    from tests.test_build_planner import catalog, report
    from dota_coach.ingest.valve_catalog import save_valve_snapshot
    raw={'match_id':1,'players':[{'account_id':7,'hero_id':1,'player_slot':0}]}
    source=tmp_path/'match.json';source.write_text(json.dumps(raw),encoding='utf-8')
    snapshot=catalog();catalog_path=tmp_path/'catalog.json'
    save_valve_snapshot(snapshot,catalog_path)
    work=server.Workbench(source,tmp_path/'missing.json',catalog_path,tmp_path/'jobs')
    ident='b'*24;directory=work.out/ident;directory.mkdir(parents=True)
    payload=report(snapshot);(directory/'analysis.json').write_text(json.dumps(payload),encoding='utf-8')
    work.jobs[ident]={'job_id':ident,'state':'complete'}
    factory=server.ThreadingHTTPServer;bound=[];ready=threading.Event()
    def capture(address,handler):
        instance=factory(address,handler);bound.append(instance);ready.set();return instance
    monkeypatch.setattr(server,'ThreadingHTTPServer',capture)
    thread=threading.Thread(target=server.serve_workbench,args=(work,0),daemon=True);thread.start()
    assert ready.wait(3)
    client=http.client.HTTPConnection('127.0.0.1',bound[0].server_port,timeout=3)
    def call(method,path,body=None,*,token=True):
        headers={'Content-Type':'application/json'}
        if token: headers['X-Foresight-Token']=work.token
        client.request(method,path,body=json.dumps(body) if body is not None else None,headers=headers)
        response=client.getresponse();data=response.read()
        return response.status,([json.loads(line) for line in data.splitlines()] if path.endswith('.jsonl') else json.loads(data))
    try:
        yield work,ident,payload,call
    finally:
        client.close();bound[0].shutdown();thread.join(3);work.worker.shutdown()


def test_build_plan_http_revision_chain_and_persisted_receipt(planning_server):
    from tests.test_build_planner import request
    from dota_coach.evidence.contracts import content_hash
    work,ident,payload,call=planning_server
    assert call('GET','/api/build-plan/'+ident)==(200,{'latest_plan':None})
    req=request(payload,candidate_item_ids=['item_spell_fixture'],available_gold=1000,
                remaining_costs={'item_spell_fixture':800})
    status,first=call('POST','/api/build-plan',{'job_id':ident,'request':req})
    assert status==200 and first['options'][0]['budget_after']==200
    assert datetime.fromisoformat(first['recorded_at']).utcoffset().total_seconds()==0
    assert first['payload_sha256']==content_hash({k:v for k,v in first.items() if k!='payload_sha256'})
    status,second=call('POST','/api/build-plan',{'job_id':ident,'request':req|{
        'previous_plan_id':first['plan_id'],'goal_description':'Another explicit QA scenario'}})
    assert status==200 and second['revision']==2
    assert second['previous_payload_sha256']==first['payload_sha256']
    assert second['training_eligible'] is False and second['feasibility']=='unknown'
    assert call('GET','/api/build-plan/'+ident)==(200,{'latest_plan':second})
    rows=[json.loads(line) for line in (work.out/ident/'build-plan-history.jsonl').read_text(encoding='utf-8').splitlines()]
    assert rows==[first,second]
    status,download=call('GET',f'/reports/{ident}/build-plan-history.jsonl')
    assert status==200 and download==rows


def test_build_plan_http_rejects_stale_duplicate_and_unconfirmed_requests(planning_server):
    from tests.test_build_planner import request
    work,ident,payload,call=planning_server
    req=request(payload,candidate_item_ids=['item_spell_fixture'])
    for invalid in (req|{'source_context_hash':'0'*64},req|{'confirmed':False},
                    req|{'remaining_costs':{'item_other':10}}):
        status,value=call('POST','/api/build-plan',{'job_id':ident,'request':invalid})
        assert status==400 and value['error']
    assert not (work.out/ident/'build-plan-history.jsonl').exists()
    status,first=call('POST','/api/build-plan',{'job_id':ident,'request':req})
    assert status==200
    status,value=call('POST','/api/build-plan',{'job_id':ident,'request':req})
    assert status==400 and value['error']
    assert call('GET','/api/build-plan/'+ident)[1]['latest_plan']==first
    assert len((work.out/ident/'build-plan-history.jsonl').read_text(encoding='utf-8').splitlines())==1


def test_build_plan_http_requires_session_token_and_typed_envelope(planning_server):
    from tests.test_build_planner import request
    work,ident,payload,call=planning_server
    envelope={'job_id':ident,'request':request(payload)}
    assert call('POST','/api/build-plan',envelope,token=False)[0]==403
    for row in (envelope|{'catalog':{}},envelope|{'job_id':'c'*24},envelope|{'request':[]}):
        assert call('POST','/api/build-plan',row)[0]==400
    assert call('GET','/api/build-plan/'+'c'*24)[0]==400
    assert not (work.out/ident/'build-plan-history.jsonl').exists()


def test_build_plan_http_catalog_drift_and_training_jobs_cannot_create_plan(planning_server):
    from dataclasses import replace
    from tests.test_build_planner import catalog, request
    from dota_coach.ingest.valve_catalog import save_valve_snapshot
    work,ident,payload,call=planning_server
    (work.out/ident/'analysis.json').unlink()
    assert call('GET','/api/build-plan/'+ident)[0]==400
    assert call('POST','/api/build-plan',{'job_id':ident,'request':request(payload)})[0]==400
    (work.out/ident/'analysis.json').write_text(json.dumps(payload),encoding='utf-8')
    snapshot=catalog();drift=replace(snapshot,items=(replace(snapshot.items[0],item_cost=999),)+snapshot.items[1:])
    work.catalog_path=work.catalog_path.with_name('different-catalog.json')
    save_valve_snapshot(drift,work.catalog_path)
    assert call('POST','/api/build-plan',{'job_id':ident,'request':request(payload)})[0]==400
    assert not (work.out/ident/'build-plan-history.jsonl').exists()


def ward_source_for_job(work, ident):
    from tests.test_ward_plan import observations, request
    from dataclasses import replace
    from tests.test_ward_plan import ward_trace
    trace=ward_trace()
    trace=replace(trace,replay=replace(trace.replay,match_id=1,
        manifest=replace(trace.replay.manifest,match_id=1)))
    source=observations(trace)
    (work.out/ident/'ward-observations.json').write_text(json.dumps(source),encoding='utf-8')
    return source,request(source)


def test_ward_plan_http_preserves_revision_goal_and_unknown_quality(planning_server):
    work,ident,_,call=planning_server
    source,req=ward_source_for_job(work,ident)
    assert call('GET','/api/ward-plan/'+ident)==(200,{'latest_plan':None})
    envelope={'job_id':ident,'request':req}
    assert call('POST','/api/ward-plan',envelope,token=False)[0]==403
    assert call('POST','/api/ward-plan',{'job_id':ident,'request':req|{'confirmed':False}})[0]==400
    status,first=call('POST','/api/ward-plan',envelope)
    assert status==200 and first['revision']==1 and first['training_eligible'] is False
    assert first['utility']=='not_established' and first['information_review']['status']=='insufficient_evidence'
    assert call('POST','/api/ward-plan',envelope)[0]==400
    status,second=call('POST','/api/ward-plan',{'job_id':ident,'request':req|{
        'goal_description':'Explicit QA revised team task','previous_plan_id':first['plan_id']}})
    assert status==200 and second['revision']==2
    assert second['previous_payload_sha256']==first['payload_sha256']
    assert call('GET','/api/ward-plan/'+ident)[1]['latest_plan']==second
    status,history=call('GET',f'/reports/{ident}/ward-plan-history.jsonl')
    assert status==200 and history==[first,second]


def test_ward_plan_http_rejects_foreign_source_and_unknown_envelope(planning_server):
    from tests.test_ward_plan import observations, rehash
    work,ident,_,call=planning_server
    source,req=ward_source_for_job(work,ident)
    assert call('POST','/api/ward-plan',{'job_id':ident,'request':req,'validation':'verified'})[0]==400
    assert call('POST','/api/ward-plan',{'job_id':ident,'request':req|{'source_context_hash':'0'*64}})[0]==400
    source['account_id']=8;rehash(source)
    (work.out/ident/'ward-observations.json').write_text(json.dumps(source),encoding='utf-8')
    assert call('POST','/api/ward-plan',{'job_id':ident,'request':req})[0]==400
    assert not (work.out/ident/'ward-plan-history.jsonl').exists()


def test_analytical_status_and_new_assets_are_readonly_closed_without_backend_authority(planning_server):
    work,ident,_,call=planning_server
    work.analytical_witnesses[ident]=(7,None,None)
    status,value=call('GET','/api/analytics-status/'+ident)
    assert status==200 and value['case'] is None and not value['case_admitted']
    assert value['snapshot_json_is_not_authority'] and not value['global_coaching_certified']
    assert value['prefix_admission_active'] is None
    for name in ('impact-prefix.json','case-assessment.json','terrain-support.json','verified-history.json'):
        (work.out/ident/name).write_text('null',encoding='utf-8')
        assert call('GET',f'/reports/{ident}/{name}')==(200,None)
    assert call('GET','/api/analytics-status/'+'c'*24)[0]==400
    work.analytical_review_provider=lambda account:{'approved':True}
    assert call('GET','/api/analytics-status/'+ident)[0]==400
