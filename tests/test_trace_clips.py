from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import subprocess

import pytest

from dota_coach.video.trace_clips import build_activation_clips, verified_clip_path, validate_video_options


def notebook(time=40, count=1, dataset='replay'):
    return {'match_id':123,'dataset_kind':dataset,'entries':[
        {'decision_id':f'activation:{i}', 'observation_time':time, 'source_record_index':100+i,
         'source_trace_hash':'a'*64} for i in range(count)]}


def source(tmp_path):
    path=tmp_path/'provided.mp4';path.write_bytes(b'provided-video-source')
    return path


def successful(command, **kwargs):
    if command[-1]=='pipe:1':
        # Explicit media decoder protocol fixture, not actual video material.
        png=b'\x89PNG\r\n\x1a\n'+(13).to_bytes(4,'big')+b'IHDR'+(1).to_bytes(4,'big')+(1).to_bytes(4,'big')
        return SimpleNamespace(returncode=0,stdout=png)
    Path(command[-1]).write_bytes(b'trimmed-clip')
    return SimpleNamespace(returncode=0)


@pytest.mark.parametrize('video,offset',[(None,3),('x',None),('x',True),('x',float('nan')),('x',float('inf')),('x','3')])
def test_video_requires_explicit_finite_offset(video,offset):
    with pytest.raises(ValueError):
        validate_video_options(video,offset)


def test_source_navigation_receipt_binds_video_trace_and_declared_offset(tmp_path):
    video=source(tmp_path);commands=[]
    def run(command,**kwargs):
        commands.append((command,kwargs));return successful(command,**kwargs)
    value=build_activation_clips(notebook(),tmp_path/'report',replay_sha256='b'*64,
        video_path=video,video_offset=7,ffmpeg='explicit-ffmpeg',runner=run)
    assert value['source_video_sha256']==hashlib.sha256(video.read_bytes()).hexdigest()
    assert value['replay_sha256']=='b'*64 and value['dataset_kind']=='replay'
    assert value['alignment']=='user_declared_unverified'
    assert value['choice_boundary_proof'] is value['pov_proof'] is value['training_eligible'] is False
    receipt=value['entries'][0]
    assert receipt['requested_video_window_seconds']==[27,57]
    assert receipt['source_trace_sha256']=='a'*64 and receipt['source_record_index']==100
    assert commands[0][0][0]=='explicit-ffmpeg' and '-an' in commands[0][0]
    assert commands[0][1]['timeout']==60
    assert commands[1][0][commands[1][0].index('-ss')+1]=='20.000000'
    assert receipt['navigation_event_offset_seconds']==20
    assert verified_clip_path(tmp_path/'report',receipt['relative_path']).read_bytes()==b'trimmed-clip'
    assert str(video) not in json.dumps(value)


@pytest.mark.parametrize('time,offset,reason',[(None,0,'activation_time_unavailable'),(float('nan'),0,'activation_time_unavailable'),
    (float('inf'),0,'activation_time_unavailable'),(True,0,'activation_time_unavailable'),
    (3,-4,'activation_outside_declared_video_clock'),(1e308,1e308,'activation_outside_declared_video_clock'),
    (1e20,0,'video_window_not_representable')])
def test_unmapped_unrepresentable_windows_do_not_invoke_extractor(tmp_path,time,offset,reason):
    def forbidden(*args,**kwargs): raise AssertionError('must not extract')
    value=build_activation_clips(notebook(time),tmp_path/'report',video_path=source(tmp_path),video_offset=offset,runner=forbidden)
    assert value['entries'][0]['reason_code']==reason
    assert value['entries'][0]['relative_path'] is None


def test_start_window_is_trimmed_at_zero_without_fake_negative_seek(tmp_path):
    value=build_activation_clips(notebook(5),tmp_path/'report',video_path=source(tmp_path),video_offset=0,runner=successful)
    assert value['entries'][0]['requested_video_window_seconds']==[0,15]


def test_absent_and_missing_video_are_distinct(tmp_path):
    absent=build_activation_clips(notebook(),tmp_path/'absent')
    missing=build_activation_clips(notebook(),tmp_path/'missing',video_path=tmp_path/'none.mp4',video_offset=0)
    assert absent['status']=='not_supplied' and missing['status']=='unavailable'
    assert missing['entries'][0]['reason_code']=='source_video_unavailable'


@pytest.mark.parametrize('mode,reason', [('nonzero','clip_extraction_failed'),('empty','clip_output_empty'),
    ('timeout','clip_extraction_timeout'),('missing_executable','clip_extractor_or_output_unavailable')])
def test_failed_extraction_cannot_reuse_old_successful_clip(tmp_path,mode,reason):
    report=tmp_path/'report';(report/'clips').mkdir(parents=True)
    (report/'clips/0000.mp4').write_bytes(b'stale-success')
    (report/'clips/0000.pending.mp4').write_bytes(b'stale-pending')
    def run(command,**kwargs):
        if mode=='timeout': raise subprocess.TimeoutExpired(command,60)
        if mode=='missing_executable': raise FileNotFoundError()
        return SimpleNamespace(returncode=1 if mode=='nonzero' else 0)
    value=build_activation_clips(notebook(),report,video_path=source(tmp_path),video_offset=0,runner=run)
    assert value['entries'][0]['reason_code']==reason
    assert verified_clip_path(report,'clips/0000.mp4') is None


def test_source_mutation_revokes_all_generated_links(tmp_path):
    video=source(tmp_path)
    def run(command,**kwargs):
        successful(command,**kwargs);video.write_bytes(b'changed-source')
        return SimpleNamespace(returncode=0)
    value=build_activation_clips(notebook(),tmp_path/'report',video_path=video,video_offset=0,runner=run)
    assert value['status']=='source_changed'
    assert value['entries'][0]['relative_path'] is None
    assert verified_clip_path(tmp_path/'report','clips/0000.mp4') is None


def test_clip_byte_mutation_revokes_http_allowlist(tmp_path):
    report=tmp_path/'report'
    build_activation_clips(notebook(),report,video_path=source(tmp_path),video_offset=0,runner=successful)
    (report/'clips/0000.mp4').write_bytes(b'changed-clip')
    assert verified_clip_path(report,'clips/0000.mp4') is None


@pytest.mark.parametrize('relative',['provided.mp4','../provided.mp4','clips/../provided.mp4',
    'clips/0000.pending.mp4','clips/0000.mp4/extra','clips/9999.mp4','C:/provided.mp4'])
def test_only_success_receipts_and_exact_numeric_clip_names_are_served(tmp_path,relative):
    report=tmp_path/'report'
    build_activation_clips(notebook(),report,video_path=source(tmp_path),video_offset=0,runner=successful)
    assert verified_clip_path(report,relative) is None


def test_original_inside_report_directory_refused_before_any_overwrite(tmp_path):
    report=tmp_path/'report';report.mkdir()
    video=report/'index.html';video.write_bytes(b'original-source')
    with pytest.raises(ValueError,match='outside'):
        build_activation_clips(notebook(),report,video_path=video,video_offset=0,runner=successful)
    assert video.read_bytes()==b'original-source'
    assert not (report/'clip-navigation.json').exists()


def test_duplicate_clip_identity_refused(tmp_path):
    value=notebook(count=2);value['entries'][1]['decision_id']=value['entries'][0]['decision_id']
    with pytest.raises(ValueError,match='unique'):
        build_activation_clips(value,tmp_path/'report')


def test_all_observations_kept_when_clip_work_is_bounded(tmp_path):
    value=build_activation_clips(notebook(count=51),tmp_path/'report',video_path=source(tmp_path),video_offset=0,runner=successful)
    assert len(value['entries'])==51
    assert sum(row['status']=='available' for row in value['entries'])==50
    assert value['entries'][-1]['reason_code']=='navigation_clip_limit_reached'


@pytest.mark.parametrize('returncode,frame',[(0,b''),(1,b'frame'),(0,b'header-only')])
def test_nonempty_container_without_decodable_video_never_published(tmp_path,returncode,frame):
    def run(command,**kwargs):
        if command[-1]=='pipe:1':
            return SimpleNamespace(returncode=returncode,stdout=frame)
        return successful(command,**kwargs)
    report=tmp_path/'report'
    value=build_activation_clips(notebook(),report,video_path=source(tmp_path),video_offset=0,runner=run)
    assert value['entries'][0]['reason_code']=='clip_not_decodable'
    assert value['entries'][0]['relative_path'] is None
    assert verified_clip_path(report,'clips/0000.mp4') is None


def test_hardlink_manifest_alias_cannot_truncate_original_video(tmp_path):
    video=source(tmp_path);original=video.read_bytes()
    report=tmp_path/'report';report.mkdir()
    (report/'clip-navigation.json').hardlink_to(video)
    with pytest.raises(ValueError,match='overwrite'):
        build_activation_clips(notebook(),report,video_path=video,video_offset=0,runner=successful)
    assert video.read_bytes()==original


def test_validation_decodes_at_event_offset_not_first_frame(tmp_path):
    commands=[]
    def run(command,**kwargs):
        commands.append(command)
        if command[-1]=='pipe:1':
            assert command[command.index('-ss')+1]=='20.000000'
            return SimpleNamespace(returncode=0,stdout=b'')
        return successful(command,**kwargs)
    value=build_activation_clips(notebook(20),tmp_path/'report',video_path=source(tmp_path),video_offset=0,runner=run)
    assert value['entries'][0]['reason_code']=='clip_not_decodable'
    assert value['entries'][0]['requested_video_window_seconds']==[0,30]
