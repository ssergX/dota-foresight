from dataclasses import replace
import json
import pytest
from dota_coach.cli import main
from dota_coach.live_report import render_live_report
from dota_coach.ingest.trace import save_trace_result
from dota_coach.server import Workbench
from tests.test_projectile_source import fixture
from tests.test_order_source import write
from tests.test_live_report import sources
from tests.test_contextual_builds import catalog

def bound_source(tmp_path):
    path,_,rows=fixture(tmp_path);r,raw=sources()
    replay=r.replay.manifest.replay_hash
    rows[0]['replay_sha256']=rows[-1]['replay_sha256']=replay
    r=replace(r,audit=r.audit|{'replay_sha256':replay,'match_id':r.replay.match_id},replay=replace(r.replay,manifest=replace(r.replay.manifest,game_build='6943',dataset_kind='replay')))
    for row in rows:
        if row.get('entity_context'):
            for s in row['entity_context']['selected_heroes']:s['steam_id']=76561197960265728+7
    write(path,rows)
    return path,r,raw

def test_source_integrates_without_promoting_forecast_or_card(tmp_path):
    path,r,raw=bound_source(tmp_path);out=tmp_path/'report'
    p=render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=out,projectiles_path=path)
    assert p['replay_sources']['projectiles']['prefix']['selected_reference_association_counts']['target']==2
    assert p['impact_prefix'] is p['defensive_impact'] is p['case_assessment'] is None
    assert p['quality']['decision']=='not_expert_validated'
    assert 'id="projectile-sources"' in (out/'index.html').read_text(encoding='utf-8')

@pytest.mark.parametrize('mutation',['foreign-replay','foreign-build','truncated'])
def test_source_mismatch_refused_before_report_writes(tmp_path,mutation):
    path,r,raw=bound_source(tmp_path);rows=[json.loads(s) for s in path.read_text().splitlines()]
    if mutation=='foreign-replay':rows[0]['replay_sha256']=rows[-1]['replay_sha256']='b'*64
    if mutation=='foreign-build':rows[-1]['game_build']=12345
    if mutation=='truncated':rows.pop()
    write(path,rows)
    with pytest.raises(ValueError):render_live_report(r,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',projectiles_path=path)
    assert not (tmp_path/'report').exists()

def test_cli_prefix_and_no_input_overwrite(tmp_path):
    path,r,raw=bound_source(tmp_path);saved=tmp_path/'extraction.json';save_trace_result(r,saved)
    out=tmp_path/'prefix.json'
    args=['projectiles-source','--source-jsonl',str(path),'--extraction-json',str(saved),'--account-id','7','--cutoff-record-index','3']
    assert main(args+['--out',str(out)])==0
    p=json.loads(out.read_text());assert p['prefix']['open_message_bracket_count']==1
    original=path.read_bytes();assert main(args+['--out',str(path)])==1;assert path.read_bytes()==original

def test_workbench_preserves_caller_source_path(tmp_path):
    path,r,raw=bound_source(tmp_path);match=tmp_path/'match.json';match.write_text(json.dumps(raw))
    w=Workbench(match,tmp_path/'missing',tmp_path/'catalog',tmp_path/'jobs',projectiles_jsonl=path)
    try:assert w.projectiles_path==path
    finally:w.worker.shutdown()

def test_trace_cli_new_input_guard_prevents_generated_overwrite(tmp_path):
    path=tmp_path/'replay-sources.json';path.write_text('projectile source input')
    args=['trace-review','--match-json',str(tmp_path/'missing-match'),'--extraction-json',str(tmp_path/'missing-extraction'),
        '--account-id','7','--catalog-json',str(tmp_path/'missing-catalog'),'--projectiles-jsonl',str(path),'--out',str(tmp_path)]
    before=path.read_bytes();assert main(args)==1;assert path.read_bytes()==before
