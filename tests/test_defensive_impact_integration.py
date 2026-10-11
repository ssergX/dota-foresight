from dataclasses import replace
import json

import pytest

from dota_coach.cli import main
from dota_coach.live_report import render_live_report
from tests.test_contextual_builds import catalog
from tests.test_defensive_impact import portable
from tests.test_live_report import sources


def test_cli_computes_and_displays_conditional_alternatives_without_game_admission(tmp_path):
    source=tmp_path/'proposal.json';source.write_text(json.dumps(portable()),encoding='utf-8')
    out=tmp_path/'defensive-impact.json';page=tmp_path/'index.html'
    assert main(['defensive-impact-review','--input-json',str(source),'--out',str(out),'--html',str(page)])==0
    value=json.loads(out.read_text(encoding='utf-8'))
    assert value['verdict']=='unknown' and value['training_eligible'] is False
    assert value['candidate_arithmetic']['alternatives']['activate']['hp_after_impact']['minimum']==400
    text=page.read_text(encoding='utf-8')
    assert 'Синтетический сценарий' in text and 'не является общим обвинением' in text
    assert '400' in text and '100' in text and 'Баланс HP' in text
    assert 'Заявленные пороги:' in text and 'мана не ниже 50' in text
    assert 'one_committed_impact' not in text
    assert 'href="defensive-impact.json"' in text


@pytest.mark.parametrize('overlap',['json-input','html-input','same-outputs'])
def test_cli_protects_proposal_and_distinct_outputs_before_any_write(tmp_path,overlap):
    source=tmp_path/'proposal.json';source.write_text(json.dumps(portable()),encoding='utf-8')
    before=source.read_bytes();out=tmp_path/'result.json';page=tmp_path/'index.html'
    if overlap=='json-input':out=source
    if overlap=='html-input':page=source
    if overlap=='same-outputs':page=out
    assert main(['defensive-impact-review','--input-json',str(source),'--out',str(out),'--html',str(page)])==1
    assert source.read_bytes()==before
    assert not (tmp_path/'result.json').exists()


def report_proposal(r):
    data=portable()
    data['scope'].update(match_id=123,subject_ref='account:7',observer_ref='account:7',patch='opendota_patch_id:60',
        dataset_kind=r.replay.manifest.dataset_kind)
    data['scope']['item_entity']['replay_id']='match:123'
    data['model']['patch']='opendota_patch_id:60'
    for row in data['facts']:
        row['fact'].update(subject_ref='account:7',observer_ref='account:7')
    return data


def test_conditional_report_does_not_replace_notebook_cards_or_real_quality(tmp_path):
    r,raw=sources();r=replace(r,replay=replace(r.replay,manifest=replace(r.replay.manifest,dataset_kind='synthetic')))
    proposal=tmp_path/'proposal.json';proposal.write_text(json.dumps(report_proposal(r)),encoding='utf-8')
    base=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'base')
    value=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'linked',defensive_impact_path=proposal)
    assert value['cards']==base['cards'] and value['notebook']==base['notebook'] and value['quality']==base['quality']
    assert value['defensive_impact']['verdict']=='unknown'
    assert value['defensive_impact']['candidate_arithmetic'] is not None
    assert (tmp_path/'linked/defensive-impact.json').is_file()
    assert 'Условный сценарий' in (tmp_path/'linked/index.html').read_text(encoding='utf-8')


@pytest.mark.parametrize('mutation',[{'subject_ref':'account:99'},{'observer_ref':'account:99'},
                                    {'patch':'other.patch'},{'dataset_kind':'replay'}])
def test_foreign_or_synthetic_as_real_scenario_rejected_before_report_write(tmp_path,mutation):
    r,raw=sources();r=replace(r,replay=replace(r.replay,manifest=replace(r.replay.manifest,dataset_kind='synthetic')))
    data=report_proposal(r);data['scope'].update(mutation)
    if 'patch' in mutation:data['model']['patch']=mutation['patch']
    if 'subject_ref' in mutation:
        for row in data['facts']:row['fact']['subject_ref']=mutation['subject_ref']
    if 'observer_ref' in mutation:
        for row in data['facts']:row['fact']['observer_ref']=mutation['observer_ref']
    proposal=tmp_path/'proposal.json';proposal.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError,match='does not bind'):
        render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'out',defensive_impact_path=proposal)
    assert not (tmp_path/'out').exists()
