from copy import deepcopy
import json
import pytest

from dota_coach.decisions.resource_review import review_resource_prefix
from dota_coach.learning.resource_plan import compute_resource_plan,resource_plan_form
from tests.test_resource_review import state


def inputs():
    resource=review_resource_prefix(state(),item_id='item_black_king_bar')
    report={'match_id':123,'account_id':7,'resource_reviews':{'a':resource}}
    request={'decision_id':'a','resource_input_hash':resource['input_hash'],'reserve_action':'Следующее заклинание',
             'reserve_cost':300,'repetitions':2,'margin':10,'confirmed':True}
    return report,request


def test_real_resource_source_and_user_assumption_are_distinct_without_verdict():
    report,request=inputs()
    result=compute_resource_plan(report,request)
    assert result['required_mana']==610
    assert result['activate_slack']==26 and result['hold_slack']==76
    assert result['goal_origin']=='user_declared_what_if_not_prior_intent'
    assert result['reserve_cost_origin']=='user_declared_not_historical_mechanic'
    assert result['mana_source']['source_record_index']==7
    assert result['training_eligible'] is False
    assert result['verdict']=='insufficient_evidence' and result['feasibility']=='unknown'


def test_deficit_even_without_activation_does_not_accuse_or_make_hold_good():
    report,request=inputs();request['reserve_cost']=400
    result=compute_resource_plan(report,request)
    assert result['activate_slack']<0 and result['hold_slack']<0
    assert result['verdict']=='insufficient_evidence'


def test_unknown_and_conflicting_resources_are_not_zero_or_feasible():
    report,request=inputs();report['resource_reviews']['a']['own_mana_raw']=None
    result=compute_resource_plan(report,request)
    assert result['activate_slack'] is None and result['status']=='insufficient_resource_fields'
    report['resource_reviews']['a']['own_mana_raw']=0
    result=compute_resource_plan(report,request)
    assert result['status']=='conflicting_raw_resources' and result['hold_slack'] is None


@pytest.mark.parametrize('field,value',[('confirmed',False),('confirmed',1),('margin',True),('margin',-1),
    ('reserve_cost',float('nan')),('reserve_cost',10**1000),('repetitions',1.5),('repetitions',True),
    ('repetitions',21),('reserve_action',''),('resource_input_hash','changed'),('decision_id','foreign')])
def test_bad_or_stale_plan_is_rejected(field,value):
    report,request=inputs();request[field]=value
    with pytest.raises(ValueError): compute_resource_plan(report,request)


def test_multiplication_overflow_is_rejected():
    report,request=inputs();request.update(reserve_cost=1e308,repetitions=20)
    with pytest.raises(ValueError,match='Переполнение'): compute_resource_plan(report,request)


def test_unrelated_outcomes_and_future_positions_do_not_change_plan():
    report,request=inputs();before=compute_resource_plan(report,request)
    report.update(radiant_win=False,observed_outcomes={'future_death':True},enemy_positions=[1,2])
    after=compute_resource_plan(report,request)
    assert {k:v for k,v in before.items() if k!='created_at'}=={k:v for k,v in after.items() if k!='created_at'}


def test_detached_plan_preserves_dataset_origin_and_identity():
    report,request=inputs()
    unknown=compute_resource_plan(report,request)
    report['dataset_kind']='synthetic'
    synthetic=compute_resource_plan(report,request)
    assert unknown['dataset_kind']=='unknown' and synthetic['dataset_kind']=='synthetic'
    assert unknown['plan_id']!=synthetic['plan_id']


def test_form_starts_blank_and_unconfirmed_and_escapes_identifier():
    report,_=inputs();resource=deepcopy(report['resource_reviews']['a'])
    resource['action_id']="a'><script>alert(1)</script>"
    page=resource_plan_form(resource)
    assert '<script>' not in page and 'checked' not in page and "value='" not in page


def test_server_requires_completed_actual_report_and_keeps_plan_unreviewed(tmp_path):
    from dota_coach.server import Workbench
    from tests.test_live_report import sources
    _,raw=sources();source=tmp_path/'source.json';source.write_text(json.dumps(raw),encoding='utf-8')
    work=Workbench(source,tmp_path/'missing.json',tmp_path/'catalog.json',tmp_path/'jobs')
    report,request=inputs();ident='a'*24
    with pytest.raises(ValueError):work.resource_plan(ident,request)
    work.jobs[ident]={'state':'complete'}
    folder=work.out/ident;folder.mkdir(parents=True)
    (folder/'analysis.json').write_text(json.dumps(report),encoding='utf-8')
    saved=work.resource_plan(ident,request)
    assert json.loads((folder/'resource-plans.jsonl').read_text())['plan_id']==saved['plan_id']
    assert not (folder/'independent-review/annotations.jsonl').exists()
    work.worker.shutdown()
