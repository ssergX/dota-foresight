from dataclasses import replace
import json

import pytest

from dota_coach.analytical_workflow import CaseReviewContext, evaluate_case_proposal, evaluate_prefix_workflow
from dota_coach.cli import main
from tests.test_defensive_impact import portable as impact_proposal
from tests.test_impact_prefix import context, portable as prefix_proposal, registry_for
from tests.test_impact_pipeline import ready


def test_default_prefix_workflow_never_invents_forecast_or_reviewed_case():
    value = evaluate_prefix_workflow(context()).document()
    assert value['prefix']['forecast'] is None and value['prefix']['status']=='unavailable'
    assert value['defensive_impact'] is None and value['case_assessment'] is None
    assert not value['portable_document_grants_validation']


def test_reviewed_testing_prefix_is_consumed_by_actual_alternative_algorithm_with_bound_replay():
    inputs=context()
    value=evaluate_prefix_workflow(inputs, prefix_registry=registry_for(inputs)).document()
    assert value['prefix']['forecast']['arrival_time_min_ms']==1100
    assert value['defensive_impact']['candidate_arithmetic']['alternatives']['activate']['hp_after_impact']['minimum']==340
    assert value['case_assessment']['replay_hash']==inputs['query'].replay_sha256
    assert value['case_assessment']['verdict']=='insufficient_evidence' and value['case_assessment']['snapshot_only']


def test_cached_testing_case_document_never_exports_admitted_game_verdict_or_authority():
    args=ready()
    case=args.pop('case')
    review=CaseReviewContext(**args)
    computed=evaluate_case_proposal(case, review=review)
    assert computed.assessment.verdict=='confirmed_error_within_criterion'
    value=computed.document(current_review=review)
    assert value['case_assessment']['verdict']=='insufficient_evidence'
    assert value['case_assessment']['current_review']['testing_only']
    assert all(c.startswith('conditional:') for c in value['case_assessment']['explanation_claims'])
    changed=replace(review, registry=replace(review.registry, admissions=()))
    assert not computed.document(current_review=changed)['case_assessment']['current_review']['active_case_witness']


@pytest.mark.parametrize('command,proposal', [('impact-prefix-review',prefix_proposal),('case-review',impact_proposal)])
def test_cli_defaults_and_preserves_input(command, proposal, tmp_path):
    source=tmp_path/'input.json';source.write_text(json.dumps(proposal()),encoding='utf-8')
    before=source.read_bytes();out=tmp_path/'result.json'
    assert main([command,'--input-json',str(source),'--out',str(out)])==0
    value=json.loads(out.read_text(encoding='utf-8'))
    assert not value['portable_document_grants_validation'] and not value['training_eligible']
    assert source.read_bytes()==before
    assert main([command,'--input-json',str(source),'--out',str(source)])==1
    assert source.read_bytes()==before


@pytest.mark.parametrize('command,proposal', [('impact-prefix-review',prefix_proposal),('case-review',impact_proposal)])
def test_cli_portable_grants_rejected_before_output_write(command,proposal,tmp_path):
    value=proposal();value['registry']={'release':True}
    source=tmp_path/'input.json';source.write_text(json.dumps(value),encoding='utf-8');out=tmp_path/'result.json'
    assert main([command,'--input-json',str(source),'--out',str(out)])==1
    assert not out.exists()


def test_case_cli_page_shows_goal_and_computed_alternatives_with_unknown_verdict(tmp_path):
    source=tmp_path/'input.json';source.write_text(json.dumps(impact_proposal()),encoding='utf-8')
    out=tmp_path/'case.json';page=tmp_path/'case.html'
    assert main(['case-review','--input-json',str(source),'--out',str(out),'--html',str(page)])==0
    text=page.read_text(encoding='utf-8')
    assert 'недостаточно данных' in text and '400' in text and '100' in text
    assert 'href="case.json"' in text and 'conditional:activate' not in text


def test_portable_history_cli_cannot_import_witness_or_assign_exercise(tmp_path):
    data={'schema_version':'foresight.verified-history-input.v1','account_id':11,'matches':[],'opportunities':[]}
    source=tmp_path/'input.json';source.write_text(json.dumps(data),encoding='utf-8')
    out=tmp_path/'history.json';page=tmp_path/'history.html'
    assert main(['verified-history-review','--input-json',str(source),'--out',str(out),'--html',str(page)])==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['status']=='insufficient_evidence' and not result['portable_authority']
    assert 'href="history.json"' in page.read_text(encoding='utf-8')
    data['admission']={'validated':True};source.write_text(json.dumps(data),encoding='utf-8')
    before=out.read_bytes()
    assert main(['verified-history-review','--input-json',str(source),'--out',str(out)])==1
    assert out.read_bytes()==before
