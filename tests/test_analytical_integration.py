from dataclasses import replace
import json

import pytest

from dota_coach.live_report import render_live_report
from dota_coach.server import Workbench
from dota_coach.analytical_workflow import AnalyticsReviewContext, CaseReviewContext, evaluate_case_proposal
from tests.test_contextual_builds import catalog
from tests.test_defensive_impact_integration import report_proposal
from tests.test_live_report import sources
from tests.test_impact_pipeline import ready
from tests.test_terrain import fixture as terrain_fixture
from dataclasses import asdict


def test_default_report_all_new_paths_explicitly_unavailable_and_no_quality_promotion(tmp_path):
    r,raw=sources();out=tmp_path/'report'
    value=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=out)
    for key,name in [('impact_prefix','impact-prefix.json'),('case_assessment','case-assessment.json'),
                     ('terrain_support','terrain-support.json'),('verified_history','verified-history.json')]:
        assert value[key] is None and json.loads((out/name).read_text(encoding='utf-8')) is None
    text=(out/'index.html').read_text(encoding='utf-8')
    assert 'id="verified-case"' in text and 'id="terrain-support"' in text and 'id="verified-history"' in text
    assert value['quality']['decision']=='not_expert_validated'


def test_direct_impact_report_uses_actual_case_pipeline_without_promoting_snapshot(tmp_path):
    r,raw=sources();r=replace(r,replay=replace(r.replay,manifest=replace(r.replay.manifest,dataset_kind='synthetic')))
    path=tmp_path/'input.json';path.write_text(json.dumps(report_proposal(r)),encoding='utf-8')
    captured=[]
    value=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',
        defensive_impact_path=path,witness_sink=lambda case,history:captured.append((case,history)))
    assert value['case_assessment']['verdict']=='insufficient_evidence'
    assert value['case_assessment']['replay_hash']==r.replay.manifest.replay_hash
    assert value['case_assessment']['alternatives'][0]['hp_after_impact']['minimum']==400
    assert len(captured)==1 and captured[0][0].assessment.verdict=='insufficient_evidence'


@pytest.mark.parametrize('mutation',['foreign-observer','wrong-build','wrong-patch'])
def test_terrain_scope_fails_before_any_report_write(tmp_path,mutation):
    r,raw=sources();scope,model,_=terrain_fixture()
    scope=replace(scope,match_id=123,subject_ref='account:7',observer_ref='account:7',patch='opendota_patch_id:60')
    r=replace(r,replay=replace(r.replay,manifest=replace(r.replay.manifest,dataset_kind='synthetic',game_build='fixture.build')))
    if mutation=='foreign-observer':scope=replace(scope,observer_ref='account:99')
    if mutation=='wrong-build':scope=replace(scope,game_build='other')
    if mutation=='wrong-patch':scope=replace(scope,patch='other')
    value={'schema_version':'foresight.terrain-input.v1','scope':asdict(scope),'model':asdict(model),'blockers':[],'queries':[]}
    source=tmp_path/'input.json';source.write_text(json.dumps(value),encoding='utf-8')
    with pytest.raises(ValueError,match='does not bind'):
        render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',terrain_input_path=source)
    assert not (tmp_path/'report').exists()


def test_workbench_current_backend_status_revokes_cached_case_and_never_imports_json_authority(tmp_path):
    args=ready();case=args.pop('case');review=CaseReviewContext(**args)
    current=[AnalyticsReviewContext(case_review=review)]
    workflow=evaluate_case_proposal(case,review=review)
    _,raw=sources();path=tmp_path/'match.json';path.write_text(json.dumps(raw),encoding='utf-8')
    work=Workbench(path,tmp_path/'missing.json',tmp_path/'catalog.json',tmp_path/'jobs',
        analytical_review_provider=lambda account:current[0])
    ident='a'*24;work.jobs[ident]={'state':'complete'};work.analytical_witnesses[ident]=(7,workflow,None)
    try:
        first=work.analytical_status(ident)
        assert not first['case_admitted'] and first['case']['verdict']=='insufficient_evidence'
        assert first['case']['current_review']['testing_only']
        current[0]=replace(current[0],case_review=replace(review,registry=replace(review.registry,admissions=())))
        assert not work.analytical_status(ident)['case']['current_review']['active_case_witness']
        current[0]={'approved':True}
        with pytest.raises(TypeError,match='typed current'):
            work.analytical_status(ident)
    finally:work.worker.shutdown()


def test_foreign_history_account_rejected_before_report_output(tmp_path):
    r,raw=sources();source=tmp_path/'input.json'
    source.write_text(json.dumps({'schema_version':'foresight.verified-history-input.v1','account_id':99,
        'matches':[],'opportunities':[]}),encoding='utf-8')
    with pytest.raises(ValueError,match='history proposal'):
        render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',history_input_path=source)
    assert not (tmp_path/'report').exists()
