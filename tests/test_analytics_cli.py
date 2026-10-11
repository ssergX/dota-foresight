from dataclasses import asdict
import json

import pytest

from dota_coach.cli import main


def test_typed_choice_cli_runs_computation_without_self_promoted_admission(tmp_path):
    from tests.test_choice_window import inputs
    scope,mechanics,sample,cue=inputs()
    payload={'schema_version':'foresight.choice-evidence.v1','scope':asdict(scope),
        'semantics':asdict(mechanics),'cues':[asdict(cue)],'samples':[asdict(sample)]}
    source=tmp_path/'source.json';source.write_text(json.dumps(payload),encoding='utf-8')
    out=tmp_path/'result.json'
    assert main(['choice-review','--input-json',str(source),'--out',str(out)])==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['feasibility_samples'][0]['candidate_feasibility']=='feasible'
    assert result['supported_choice_count']==0 and result['training_eligible'] is False
    original=source.read_bytes()
    assert main(['choice-review','--input-json',str(source),'--out',str(source)])==1
    assert source.read_bytes()==original


def test_raw_choice_cli_includes_samples_without_cast_and_checks_target_hash(tmp_path):
    from tests.test_opportunity_discovery import artifact, seal
    from dataclasses import replace
    from dota_coach.evidence.contracts import content_hash
    from dota_coach.ingest.trace import save_trace_result
    states,trace=artifact()
    trace=replace(trace,replay=replace(trace.replay,
        manifest=replace(trace.replay.manifest,dataset_kind='replay')),
        audit=trace.audit|{'match_id':trace.replay.match_id})
    states['source_extraction_hash']=content_hash(asdict(trace))
    seal(states)
    extraction=tmp_path/'extraction.json';save_trace_result(trace,extraction)
    source=tmp_path/'states.json';source.write_text(json.dumps(states),encoding='utf-8')
    out=tmp_path/'result.json'
    args=['choice-review','--extraction-json',str(extraction),'--action-states-json',str(source),'--out',str(out)]
    assert main(args)==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['sample_count']==3 and result['cue_count']==0 and result['unknown_count']==3
    assert main(args+['--replay-sha256','f'*64])==1


def test_ward_cli_computes_prefix_without_fabricating_goal(tmp_path):
    from tests.test_ward_plan import observations
    source=observations();ward=source['events'][1]['ward_id']
    path=tmp_path/'source.json';path.write_text(json.dumps(source),encoding='utf-8')
    out=tmp_path/'result.json'
    assert main(['ward-review','--source-json',str(path),'--ward-id',ward,'--out',str(out)])==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['task'] is None and result['callback_analysis']['callback_count']>0
    assert result['information_analysis']['status']=='attribution_not_established'


def test_temporal_cli_distinguishes_stale_and_last_known_not_visibility(tmp_path):
    from tests.test_temporal_knowledge import fact,time
    source={'schema_version':'foresight.temporal-input.v1','subject_player':'me','cutoff':asdict(time(2000)),
        'policy':{'version':'fixture.v1','predicate_max_age_ms':[['enemy.hp',500]]},
        'facts':[asdict(fact())],'dataset_kind':'synthetic'}
    path=tmp_path/'source.json';path.write_text(json.dumps(source),encoding='utf-8')
    out=tmp_path/'result.json'
    assert main(['knowledge-review','--input-json',str(path),'--out',str(out)])==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['states'][0]['status']=='stale' and result['states'][0]['value'] is None
    assert result['validation']=='unverified'


@pytest.mark.parametrize('name',['semantic-lifecycles.json','resource-opportunities.json','ward-observations.json',
    'objective-state.json','choice-windows.json','ward-analysis.json','mechanics.json','movement-support.json','defensive-impact.json','impact-prefix.json','case-assessment.json','terrain-support.json','verified-history.json'])
def test_generated_analytics_artifacts_cannot_overwrite_cli_inputs(tmp_path,name):
    source=tmp_path/name;source.write_text('{"match_id":1}',encoding='utf-8')
    before=source.read_bytes()
    assert main(['trace-review','--match-json',str(source),'--extraction-json',str(tmp_path/'unused'),
        '--account-id','9','--catalog-json',str(tmp_path/'unused-catalog'),'--out',str(tmp_path)])==1
    assert source.read_bytes()==before and not (tmp_path/'index.html').exists()


def test_monitor_cli_runs_without_promoting_portable_coverage(tmp_path):
    from tests.test_choice_monitor import portable
    file=tmp_path/'stream.json';file.write_text(json.dumps(portable()),encoding='utf-8')
    out=tmp_path/'result.json'
    assert main(['choice-monitor','--input-json',str(file),'--out',str(out)])==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['supported_span_count']==0 and result['training_eligible'] is False
    before=file.read_bytes()
    assert main(['choice-monitor','--input-json',str(file),'--out',str(file)])==1
    assert file.read_bytes()==before


def test_command_cli_keeps_missing_attempt_log_coverage_unknown(tmp_path):
    from tests.test_command_census import portable
    file=tmp_path/'commands.json';file.write_text(json.dumps(portable()),encoding='utf-8')
    out=tmp_path/'result.json'
    assert main(['command-review','--input-json',str(file),'--out',str(out)])==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['status']=='unknown' and result['unique_attempt_count']==0 and result['training_eligible'] is False


@pytest.mark.parametrize('command,kind',[('choice-monitor','monitor'),('command-review','commands')])
def test_stream_cli_exports_exact_manifest_without_overwriting_inputs(tmp_path,command,kind):
    if kind=='monitor':from tests.test_choice_monitor import portable
    else:from tests.test_command_census import portable
    file=tmp_path/'input.json';file.write_text(json.dumps(portable()),encoding='utf-8')
    out=tmp_path/'result.json';manifest=tmp_path/'dataset.jsonl'
    args=[command,'--input-json',str(file),'--out',str(out),'--replay-sha256','c'*64]
    assert main(args+['--manifest-json',str(manifest)])==0
    record=json.loads(manifest.read_text(encoding='utf-8'))
    assert record['replay_hash']=='c'*64 and len(record['input_hash'])==64
    original=file.read_bytes()
    assert main(args+['--manifest-json',str(file)])==1
    assert file.read_bytes()==original


def test_movement_cli_cannot_promote_unreviewed_route_or_overwrite_proposal(tmp_path):
    from tests.test_movement import context
    scope,graph,semantics,facts,_=context()
    proposal={'schema_version':'foresight.movement-input.v1','scope':asdict(scope),'graph':asdict(graph),
        'start_node':'a','destination_node':'c','facts':[asdict(f) for f in facts],'semantics':asdict(semantics)}
    source=tmp_path/'route.json';source.write_text(json.dumps(proposal),encoding='utf-8')
    out=tmp_path/'result.json'
    assert main(['movement-review','--input-json',str(source),'--out',str(out)])==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['status']=='unknown' and result['travel_duration_bounds'] is None
    before=source.read_bytes()
    assert main(['movement-review','--input-json',str(source),'--out',str(source)])==1
    assert source.read_bytes()==before
