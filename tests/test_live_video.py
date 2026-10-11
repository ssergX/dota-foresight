from dataclasses import replace
import http.client
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from dota_coach.cli import main
from dota_coach.live_report import render_live_report
from dota_coach.ingest.trace import save_trace_result
from dota_coach.ingest.valve_catalog import save_valve_snapshot
import dota_coach.server as server
import dota_coach.video.trace_clips as clips
from tests.test_live_report import sources
from tests.test_contextual_builds import catalog


def fake_extract(command, **kwargs):
    if command[-1]=='pipe:1':
        # Explicit media decoder protocol fixture, not actual video material.
        png=b'\x89PNG\r\n\x1a\n'+(13).to_bytes(4,'big')+b'IHDR'+(1).to_bytes(4,'big')+(1).to_bytes(4,'big')
        return SimpleNamespace(returncode=0,stdout=png)
    Path(command[-1]).write_bytes(b'test-trimmed-material')
    return SimpleNamespace(returncode=0)


def configured(tmp_path):
    trace, raw=sources()
    # A hypothetical serialized replay protocol fixture, not a real gameplay
    # or video evidence claim. Cached trace loading requires replay origin.
    trace=replace(trace,replay=replace(trace.replay,manifest=replace(trace.replay.manifest,dataset_kind='replay')),
        audit=trace.audit|{'match_id':123,'replay_sha256':'a'*64})
    match=tmp_path/'match.json';match.write_text(json.dumps(raw),encoding='utf-8')
    extraction=tmp_path/'extraction.json';save_trace_result(trace,extraction)
    snapshot=tmp_path/'catalog.json';save_valve_snapshot(catalog(),snapshot)
    video=tmp_path/'private-source.mp4';video.write_bytes(b'supplied-test-source')
    return trace,raw,match,extraction,snapshot,video


def test_supplied_recording_adds_navigation_without_altering_analytical_features(tmp_path,monkeypatch):
    trace,raw,_,_,_,video=configured(tmp_path)
    baseline=render_live_report(trace,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'base')
    monkeypatch.setattr(clips.subprocess,'run',fake_extract)
    provided=render_live_report(trace,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'provided',video_path=video,video_offset=0)
    for name in ('notebook','cards','quality','case_assessment','choice_windows','observed_outcomes'):
        assert provided[name]==baseline[name]
    assert provided['clip_navigation']['dataset_kind']==trace.replay.manifest.dataset_kind
    assert baseline['clip_navigation']['status']=='not_supplied'
    page=(tmp_path/'provided/index.html').read_text(encoding='utf-8')
    assert "<video controls" in page and "src='clips/0000.mp4'" in page
    assert 'не доказательство момента выбора' in page
    assert str(video) not in page and 'private-source.mp4' not in page
    assert 'Запись не предоставлена' in (tmp_path/'base/index.html').read_text(encoding='utf-8')


def test_missing_ffmpeg_preserves_report_and_exposes_failure_state(tmp_path,monkeypatch):
    trace,raw,_,_,_,video=configured(tmp_path)
    def failed(*args,**kwargs):raise FileNotFoundError('private path must not leak')
    monkeypatch.setattr(clips.subprocess,'run',failed)
    value=render_live_report(trace,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',video_path=video,video_offset=0)
    assert value['clip_navigation']['entries'][0]['status']=='unavailable'
    page=(tmp_path/'report/index.html').read_text(encoding='utf-8')
    assert 'Клип не создан' in page and '<video' not in page
    assert 'private path' not in page


def test_render_rejects_implicit_alignment_before_writing(tmp_path):
    trace,raw,_,_,_,video=configured(tmp_path)
    with pytest.raises(ValueError,match='explicit finite'):
        render_live_report(trace,raw,account_id=7,catalog=catalog(),out_dir=tmp_path/'report',video_path=video)
    assert not (tmp_path/'report').exists()


@pytest.mark.parametrize('command',['trace-review','serve'])
def test_cli_requires_declared_video_offset(command,tmp_path):
    args=[command,'--match-json','missing','--extraction-json','missing','--catalog-json','missing',
          '--video','missing.mp4','--out',str(tmp_path/'report')]
    if command=='trace-review':args+=['--account-id','7']
    assert main(args)==1
    assert not (tmp_path/'report').exists()


def test_trace_review_cli_supplied_clip_is_source_bound_and_portable(tmp_path,monkeypatch):
    _,_,match,extraction,snapshot,video=configured(tmp_path)
    monkeypatch.setattr(clips.subprocess,'run',fake_extract)
    out=tmp_path/'report'
    assert main(['trace-review','--match-json',str(match),'--extraction-json',str(extraction),
        '--catalog-json',str(snapshot),'--account-id','7','--out',str(out),
        '--video',str(video),'--video-offset','11','--ffmpeg','explicit-helper'])==0
    value=json.loads((out/'analysis.json').read_text(encoding='utf-8'))
    assert value['clip_navigation']['video_offset_seconds']==11
    assert (out/'clips/0000.mp4').read_bytes()==b'test-trimmed-material'


def test_http_serves_only_current_trimmed_clip_and_never_original_video(tmp_path,monkeypatch):
    _,_,match,extraction,snapshot,video=configured(tmp_path)
    monkeypatch.setattr(clips.subprocess,'run',fake_extract)
    work=server.Workbench(match,extraction,snapshot,tmp_path/'jobs',video_path=video,video_offset=0)
    ident='b'*24;work.jobs[ident]={'job_id':ident,'state':'queued'};work._run(ident,7)
    assert work.jobs[ident]['state']=='complete',work.jobs[ident]
    factory=server.ThreadingHTTPServer;bound=[];ready=threading.Event()
    def capture(address,handler):
        instance=factory(address,handler);bound.append(instance);ready.set();return instance
    monkeypatch.setattr(server,'ThreadingHTTPServer',capture)
    thread=threading.Thread(target=server.serve_workbench,args=(work,0),daemon=True);thread.start()
    assert ready.wait(3)
    client=http.client.HTTPConnection('127.0.0.1',bound[0].server_port,timeout=3)
    try:
        def get(path):
            client.request('GET',path);response=client.getresponse()
            return response.status,response.getheader('Content-Type'),response.read()
        status,mime,data=get(f'/reports/{ident}/clips/0000.mp4')
        assert status==200 and mime=='video/mp4' and data==b'test-trimmed-material'
        clip_url=f'/reports/{ident}/clips/0000.mp4'
        for header,expected,start,end in [('bytes=0-3',data[:4],0,3),
                ('bytes=5-',data[5:],5,len(data)-1),
                ('bytes=-4',data[-4:],len(data)-4,len(data)-1),
                ('bytes=2-999',data[2:],2,len(data)-1),
                ('bytes=-999',data,0,len(data)-1)]:
            client.request('GET',clip_url,headers={'Range':header})
            response=client.getresponse()
            assert response.status==206 and response.read()==expected
            assert response.getheader('Accept-Ranges')=='bytes'
            assert response.getheader('Content-Range')==f'bytes {start}-{end}/{len(data)}'
            assert response.getheader('Content-Length')==str(len(expected))
        for header in ('bytes=999-','bytes=4-3','bytes=-0','bytes=0-1,3-4','bytes=-','garbage',
                       'bytes='+'9'*5000+'-'):
            client.request('GET',clip_url,headers={'Range':header})
            response=client.getresponse()
            assert response.status==416;response.read()
            assert response.getheader('Content-Range')==f'bytes */{len(data)}'
        for path in ('private-source.mp4','../private-source.mp4','clips/0000.pending.mp4','clips/9999.mp4'):
            assert get(f'/reports/{ident}/{path}')[0]==404
        assert get(f'/reports/{ident}/clip-navigation.json')[0]==200
        (work.out/ident/'clips/0000.mp4').write_bytes(b'mutated-clip')
        assert get(f'/reports/{ident}/clips/0000.mp4')[0]==404
        client.request('POST','/api/jobs',body=json.dumps({'account_id':7,'video_path':'any-source'}),
            headers={'Content-Type':'application/json','X-Foresight-Token':work.token})
        response=client.getresponse();assert response.status==400;response.read()
        # A rejected or running report cannot expose pre-existing aliases.
        # Completed reports also cannot expose the original via a hardlink
        # disguised under an otherwise allowed JSON artifact filename.
        manifest=work.out/ident/'clip-navigation.json'
        manifest.unlink();manifest.hardlink_to(video)
        original=video.read_bytes()
        for state in ('error','queued','running','complete'):
            work.jobs[ident]['state']=state
            assert get(f'/reports/{ident}/clip-navigation.json')[0]==404
        assert video.read_bytes()==original
    finally:
        client.close();bound[0].shutdown();thread.join(3);work.worker.shutdown()


@pytest.mark.parametrize('relative',['analysis.json','index.html','independent-review/dataset.jsonl'])
def test_report_output_hardlink_cannot_truncate_supplied_video(tmp_path,relative):
    trace,raw,_,_,_,video=configured(tmp_path)
    original=video.read_bytes();report=tmp_path/'report'
    target=report/relative;target.parent.mkdir(parents=True)
    target.hardlink_to(video)
    with pytest.raises(ValueError,match='overwrite'):
        render_live_report(trace,raw,account_id=7,catalog=catalog(),out_dir=report,video_path=video,video_offset=0)
    assert video.read_bytes()==original
    assert not (report/'clip-navigation.json').exists()
    assert not (report/'clips').exists()


def test_cli_output_guard_recognizes_input_hardlink(tmp_path):
    from dota_coach.cli import _guard_outputs
    source=tmp_path/'source.json';source.write_text('original',encoding='utf-8')
    root=tmp_path/'report';root.mkdir();(root/'analysis.json').hardlink_to(source)
    with pytest.raises(ValueError,match='overwrite'):
        _guard_outputs(root,['analysis.json'],[source])
    assert source.read_text(encoding='utf-8')=='original'


def test_cli_output_guard_resolves_output_alias(tmp_path,monkeypatch):
    from dota_coach.cli import _guard_outputs
    source=tmp_path/'source.json';source.write_text('original',encoding='utf-8')
    root=tmp_path/'report';target=root/'analysis.json'
    # Exact filesystem resolution fixture for an output symlink, independent
    # of Windows account privilege to create symlinks.
    resolve=Path.resolve
    def alias(path,*args,**kwargs):
        return resolve(source) if path==target else resolve(path,*args,**kwargs)
    monkeypatch.setattr(Path,'resolve',alias)
    with pytest.raises(ValueError,match='overwrite'):
        _guard_outputs(root,['analysis.json'],[source])
    assert source.read_text(encoding='utf-8')=='original'
