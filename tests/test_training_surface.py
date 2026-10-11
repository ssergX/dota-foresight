from dataclasses import asdict,replace
import json

import pytest

from dota_coach.server import Workbench
from dota_coach.learning.training import BehaviorOpportunity,TrainingPeriod
from tests.test_live_report import sources


def workbench(tmp_path):
    _,raw=sources()
    path=tmp_path/'match.json';path.write_text(json.dumps(raw),encoding='utf-8')
    return Workbench(path,tmp_path/'missing',tmp_path/'missing-catalog',tmp_path/'reports')


def period(assignment,index,completed):
    return TrainingPeriod(f'p{index}',assignment.assignment_id,assignment.scope,
        f'2026-10-{index+1:02}T00:00:00Z',f'2026-10-{index+1:02}T12:00:00Z',(100+index,),
        (BehaviorOpportunity(f'o{index}',100+index,assignment.assignment_id,'eligible',completed,
            'user_journal',(f'user-note{index}',),note='QA note only'),),
        'user_journal_complete',(f'user-period{index}',),'same-eligibility.v1')


def test_ui_never_confirms_goal_without_explicit_choice(tmp_path):
    w=workbench(tmp_path)
    with pytest.raises(ValueError,match='подтверждение'):
        w.submit_training(7,'fight_entry','goal',False)
    assert not w.jobs and not w.assignments
    page=w.page()
    assert "id='confirm-goal'" in page and "id='confirm-goal' checked" not in page
    w.worker.shutdown()


def test_source_bound_user_exercise_has_journal_and_no_fake_progress(tmp_path):
    w=workbench(tmp_path)
    ident=w.submit_training(7,'fight_entry','Я хочу рассматривать альтернативы.',True)
    w.worker.shutdown(wait=True)
    assert w.jobs[ident]['state']=='complete'
    payload=json.loads((w.out/ident/'training.json').read_text(encoding='utf-8'))
    assert payload['assignment']['scope']['subject_ref']=='account:7'
    assert payload['progress'] is None and payload['baseline'] is None
    assert not payload['automatic_error_diagnosis']
    page=(w.out/ident/'index.html').read_text(encoding='utf-8')
    assert "id='journal'" in page and "data-period='baseline'" in page
    assert 'Нападение' not in page


def test_comparison_preserves_user_notes_and_selfreport_limits(tmp_path):
    w=workbench(tmp_path);ident=w.submit_training(7,'fight_entry','QA exercise',True)
    w.worker.shutdown(wait=True);a=w.assignments[ident]
    # The fixture role is unknown, so changing counts cannot establish progress.
    result=w.compare_training(ident,asdict(period(a,1,False)),asdict(period(a,2,True)))
    payload=json.loads((w.out/result['job_id']/'training.json').read_text(encoding='utf-8'))
    assert payload['baseline']['opportunities'][0]['note']=='QA note only'
    assert result['progress']['completion_rate_delta'] is None
    assert result['progress']['status']=='insufficient_evidence'
    assert 'не устанавливает' in result['progress']['conclusion']


def test_other_subject_or_overlapping_period_cannot_claim_improvement(tmp_path):
    w=workbench(tmp_path);ident=w.submit_training(7,'fight_entry','QA exercise',True)
    w.worker.shutdown(wait=True);a=w.assignments[ident]
    baseline=period(a,1,False)
    foreign=replace(period(a,2,True),scope=replace(a.scope,subject_ref='account:999'))
    with pytest.raises(ValueError,match='different assignment'):
        w.compare_training(ident,asdict(baseline),asdict(foreign))
    overlapping=replace(period(a,2,True),match_ids=baseline.match_ids,
        opportunities=(replace(period(a,2,True).opportunities[0],match_id=baseline.match_ids[0]),))
    result=w.compare_training(ident,asdict(baseline),asdict(overlapping))
    assert result['progress']['completion_rate_delta'] is None
    assert 'overlapping_matches' in result['progress']['reason_codes']


def test_missing_exercise_and_arbitrary_task_rejected(tmp_path):
    w=workbench(tmp_path)
    with pytest.raises(ValueError):
        w.compare_training('../escape',{}, {})
    with pytest.raises(ValueError):
        w.submit_training(7,'invented','goal',True)
    assert not w.jobs
    w.worker.shutdown()
