"""Trimmed local video navigation for observed activations, never decision evidence."""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import tempfile
from pathlib import Path
import re
import subprocess

from dota_coach.video.clip import build_clip_command, clip_window

MAX_CLIPS = 50
CLIP_NAME = re.compile(r"clips/[0-9]{4}\.mp4\Z")


def validate_video_options(video_path, video_offset):
    if video_path is None:
        if video_offset is not None:
            raise ValueError("video offset requires a supplied local video")
        return
    if type(video_offset) not in (int, float) or not math.isfinite(video_offset):
        raise ValueError("supplied video requires an explicit finite video offset")


def guard_video_source(video_path, out_dir):
    """A report write must not truncate a source through any existing alias.

    Path.resolve catches symlinks; samefile additionally catches NTFS/POSIX
    hardlinks, including assets later written by the surrounding renderer.
    Existing report descendants are inspected without following symlink dirs.
    """
    if video_path is None:
        return
    source = Path(video_path).resolve()
    root = Path(out_dir).resolve()
    if source.is_relative_to(root):
        raise ValueError('supplied video must be outside the generated report directory')
    if root.exists():
        for target in root.rglob('*'):
            if not target.resolve().is_relative_to(root):
                raise ValueError('report output alias escapes report directory')
            if source.exists() and target.is_file() and source.samefile(target):
                raise ValueError('report output must not overwrite supplied video through an alias')


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _executable(ffmpeg):
    if ffmpeg is not None:
        if not isinstance(ffmpeg, str) or not ffmpeg.strip():
            raise ValueError("ffmpeg executable must be a nonempty string")
        return ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError, OSError):
        return 'ffmpeg'


def build_activation_clips(notebook, out_dir, *, replay_sha256=None,
                           video_path=None, video_offset=None, ffmpeg=None,
                           runner=None):
    """Save bounded clips and receipts. Caller declares alignment; no POV proof.

    Source hashes bind material for navigation only. The video is never copied
    or exposed. Failed, absent and unknown-clock material remain distinct.
    """
    validate_video_options(video_path, video_offset)
    guard_video_source(video_path, out_dir)
    root = Path(out_dir).resolve()
    entries = notebook['entries']
    ids = [row['decision_id'] for row in entries]
    if len(ids) != len(set(ids)):
        raise ValueError('activation identities must be unique')
    output = {
        'schema_version': 'foresight.clip-navigation.v1',
        'match_id': notebook['match_id'], 'dataset_kind': notebook['dataset_kind'],
        'replay_sha256': replay_sha256, 'purpose': 'observed_activation_navigation_only',
        'alignment': 'not_supplied' if video_path is None else 'user_declared_unverified',
        'video_offset_seconds': video_offset,
        'source_video_sha256': None, 'source_video_bytes': None,
        'choice_boundary_proof': False, 'pov_proof': False, 'training_eligible': False,
        'status': 'not_supplied' if video_path is None else 'unavailable',
        'entries': [],
    }
    source = None
    initial_hash = None
    source_error = None
    if video_path is not None:
        source = Path(video_path).resolve()
        if source.is_relative_to(root):
            raise ValueError('supplied video must be outside the generated report directory')
        # Guard every possible generated target before creating any directory.
        targets = [root/'clip-navigation.json'] + [root/'clips'/f'{i:04d}.mp4'
                    for i in range(min(len(entries), MAX_CLIPS))]
        if any(source == target.resolve() or (source.exists() and target.exists() and source.samefile(target)) for target in targets):
            raise ValueError('output must not overwrite supplied video')
        try:
            if not source.is_file():
                raise OSError('source video unavailable')
            initial_hash = file_sha256(source)
            output['source_video_sha256'] = initial_hash
            output['source_video_bytes'] = source.stat().st_size
        except OSError:
            source_error = 'source_video_unavailable'
    executable = _executable(ffmpeg) if video_path is not None else None
    run = subprocess.run if runner is None else runner
    for index, row in enumerate(entries):
        time = row.get('observation_time')
        recorded_time = time if type(time) in (int, float) and math.isfinite(time) else None
        receipt = {
            'decision_id': row['decision_id'], 'source_record_index': row['source_record_index'],
            'source_trace_sha256': row['source_trace_hash'], 'observation_time_seconds': recorded_time,
            'status': 'not_supplied', 'reason_code': 'video_not_supplied',
            'relative_path': None, 'clip_sha256': None, 'clip_bytes': None,
            'requested_video_window_seconds': None, 'navigation_event_offset_seconds': None,
        }
        output['entries'].append(receipt)
        if video_path is None:
            continue
        receipt['status'] = 'unavailable'
        if source_error:
            receipt['reason_code'] = source_error
            continue
        if type(time) not in (int, float) or not math.isfinite(time):
            receipt.update(status='unknown_clock', reason_code='activation_time_unavailable')
            continue
        center = time + video_offset
        if not math.isfinite(center) or center < 0:
            receipt.update(status='unknown_alignment', reason_code='activation_outside_declared_video_clock')
            continue
        start, end = clip_window(time, video_offset)
        if not all(math.isfinite(v) for v in (start, end)) or not 0 < end-start <= 30.000001:
            receipt.update(status='unknown_alignment', reason_code='video_window_not_representable')
            continue
        receipt['requested_video_window_seconds'] = [start, end]
        receipt['navigation_event_offset_seconds'] = center-start
        if index >= MAX_CLIPS:
            receipt['reason_code'] = 'navigation_clip_limit_reached'
            continue
        relative = f'clips/{index:04d}.mp4'
        target = root/relative
        if not target.resolve().is_relative_to(root):
            raise ValueError('clip output escapes report directory')
        target.parent.mkdir(parents=True, exist_ok=True)
        # A stale output must never turn a failed extraction into availability.
        temporary = target.with_name(target.stem+'.pending.mp4')
        if not temporary.resolve().is_relative_to(root) or source == temporary.resolve():
            raise ValueError('temporary clip output escapes report directory or overwrites source')
        try:
            temporary.unlink(missing_ok=True)
            command = build_clip_command(str(source), start, end, str(temporary), ffmpeg=executable)
            completed = run(command, capture_output=True, text=True, timeout=60)
            if completed.returncode != 0:
                receipt['reason_code'] = 'clip_extraction_failed'
                continue
            if not temporary.is_file() or temporary.stat().st_size == 0:
                receipt['reason_code'] = 'clip_output_empty'
                continue
            # FFmpeg can return zero with a nonempty container but no frames
            # when the declared window lies beyond EOF. Decode one actual
            # frame at the declared activation offset before publishing a
            # navigation link. A valid earlier frame does not place an event
            # beyond the recording's end inside the recording.
            probe = run([executable, '-v', 'error', '-i', str(temporary),
                         '-ss', f'{center-start:.6f}', '-map', '0:v:0', '-frames:v', '1', '-f', 'image2pipe',
                         '-vcodec', 'png', 'pipe:1'], capture_output=True, timeout=20)
            frame = getattr(probe, 'stdout', None)
            if (probe.returncode != 0 or not isinstance(frame, bytes) or len(frame) < 24
                    or frame[:8] != b'\x89PNG\r\n\x1a\n' or frame[12:16] != b'IHDR'
                    or int.from_bytes(frame[16:20], 'big') == 0
                    or int.from_bytes(frame[20:24], 'big') == 0):
                receipt['reason_code'] = 'clip_not_decodable'
                continue
            temporary.replace(target)
            receipt.update(status='available', reason_code='user_declared_alignment_not_verified',
                relative_path=relative, clip_sha256=file_sha256(target), clip_bytes=target.stat().st_size)
        except subprocess.TimeoutExpired:
            receipt['reason_code'] = 'clip_extraction_timeout'
        except OSError:
            receipt['reason_code'] = 'clip_extractor_or_output_unavailable'
    if source is not None and initial_hash is not None:
        try:
            unchanged = file_sha256(source) == initial_hash
        except OSError:
            unchanged = False
        if not unchanged:
            output['status'] = 'source_changed'
            for receipt in output['entries']:
                receipt.update(status='unavailable', reason_code='source_video_changed_during_extraction',
                               relative_path=None, clip_sha256=None, clip_bytes=None)
        else:
            output['status'] = 'available' if any(row['status']=='available' for row in output['entries']) else 'unavailable'
    root.mkdir(parents=True, exist_ok=True)
    manifest = root/'clip-navigation.json'
    if not manifest.resolve().is_relative_to(root):
        raise ValueError('clip manifest escapes report directory')
    # Atomic replacement cannot truncate an existing hardlink to a source.
    descriptor, temporary_manifest = tempfile.mkstemp(prefix='clip-navigation-',suffix='.pending.json',dir=root)
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
        json.dump(output,stream,ensure_ascii=False,allow_nan=False,indent=2)
    Path(temporary_manifest).replace(manifest)
    return output


def clip_card_html(receipt):
    if receipt['status'] == 'available':
        path = html.escape(receipt['relative_path'], quote=True)
        return ("<details class='activation-clip'><summary>Посмотреть предоставленную запись</summary>"
                "<p>Приблизительное окно наблюдаемой активации по указанному вами смещению времени. "
                "Паузы и соответствие записи матчу не проверены. Это не доказательство момента выбора или того, что видел игрок.</p>"
                f"<video controls preload='none' style='width:100%;max-height:420px' src='{path}'></video>"
                f"<p><a href='{path}'>Открыть короткий клип</a> · <a href='clip-navigation.json'>Связь с источником</a></p></details>")
    messages = {'not_supplied':'Запись не предоставлена: клип недоступен.',
                'unknown_clock':'Время активации неизвестно: окно записи не установлено.',
                'unknown_alignment':'По указанному смещению окно записи не установлено.',
                'unavailable':'Клип не создан. Запись или инструмент извлечения недоступны либо извлечение завершилось ошибкой.'}
    return "<p class='clip-status'>"+messages.get(receipt['status'], messages['unavailable'])+" <a href='clip-navigation.json'>Состояние записи</a></p>"


def verified_clip_path(report_dir, relative):
    """HTTP allowlist: only exact successful, unchanged local clip receipts."""
    if not isinstance(relative, str) or CLIP_NAME.fullmatch(relative) is None:
        return None
    root = Path(report_dir).resolve()
    try:
        manifest = root/'clip-navigation.json'
        if not manifest.resolve().is_relative_to(root):
            return None
        payload = json.loads(manifest.read_text(encoding='utf-8'))
        if payload.get('schema_version') != 'foresight.clip-navigation.v1' or payload.get('status')!='available':
            return None
        rows = [row for row in payload.get('entries', ()) if row.get('relative_path')==relative and row.get('status')=='available']
        if len(rows)!=1:
            return None
        target = root/relative
        if not target.resolve().is_relative_to(root) or not target.is_file():
            return None
        if target.stat().st_size != rows[0]['clip_bytes'] or file_sha256(target)!=rows[0]['clip_sha256']:
            return None
        return target
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return None
