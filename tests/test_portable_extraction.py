from pathlib import Path
import subprocess

import pytest

from scripts.extract_trace import main, run_extractor


def test_extractor_stdout_is_written_without_text_reencoding(tmp_path, monkeypatch):
    tool = tmp_path / "tool.exe"
    dem = tmp_path / "input.dem"
    target = tmp_path / "trace.jsonl"
    payload = '{"name":"проверка"}\n'.encode("utf-8")
    def execute(command, *, stdout, check):
        assert command == [str(tool), "--trace", str(dem)] and check
        stdout.write(payload)
    monkeypatch.setattr(subprocess, "run", execute)
    run_extractor(tool, dem, target, "--trace")
    assert target.read_bytes() == payload
    assert not list(tmp_path.glob("trace-pending-*.part"))


def test_failed_extraction_preserves_existing_output_and_cleans_pending(tmp_path, monkeypatch):
    target = tmp_path / "trace.jsonl"
    target.write_bytes(b"previous complete artifact")
    def fail(command, *, stdout, check):
        stdout.write(b"partial")
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        run_extractor(tmp_path / "tool", tmp_path / "replay.dem", target, "--trace")
    assert target.read_bytes() == b"previous complete artifact"
    assert not list(tmp_path.glob("trace-pending-*.part"))


def test_source_and_binary_are_never_used_as_outputs(tmp_path):
    dem, tool = tmp_path / "source.dem", tmp_path / "tool.exe"
    dem.write_bytes(b"PBDEMS2\x00source")
    tool.write_bytes(b"synthetic tool marker")
    for target in (dem, tool):
        with pytest.raises(SystemExit):
            main(["--dem", str(dem), "--trace", str(target), "--tool", str(tool)])
    assert dem.read_bytes() == b"PBDEMS2\x00source"
    assert tool.read_bytes() == b"synthetic tool marker"


def test_invalid_replay_magic_fails_before_execution(tmp_path):
    dem, tool = tmp_path / "source.dem", tmp_path / "tool.exe"
    dem.write_bytes(b"compressed or invalid")
    tool.write_bytes(b"synthetic marker")
    with pytest.raises(SystemExit):
        main(["--dem", str(dem), "--trace", str(tmp_path / "trace.jsonl"), "--tool", str(tool)])
    assert not (tmp_path / "trace.jsonl").exists()
