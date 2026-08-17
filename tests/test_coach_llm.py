import json

import pytest

from dota_coach.coach.llm import FakeLLM, _messages_hash


def test_fake_llm_returns_canned_and_records_calls():
    llm = FakeLLM('{"focus_leak_key": "feeding"}')
    msgs = [{"role": "user", "content": "hi"}]
    out = llm.complete(msgs)
    assert out == '{"focus_leak_key": "feeding"}'
    assert llm.calls == [msgs]


def test_messages_hash_is_stable_and_order_sensitive():
    a = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    b = [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
    c = [{"role": "system", "content": "x"}, {"role": "user", "content": "z"}]
    assert _messages_hash(a) == _messages_hash(b)
    assert _messages_hash(a) != _messages_hash(c)


def test_cached_produces_once_then_reads_from_disk(tmp_path):
    from dota_coach.coach.llm import _cached

    msgs = [{"role": "user", "content": "hi"}]
    calls = []

    def produce():
        calls.append(1)
        return "RESULT"

    first = _cached(tmp_path, msgs, produce)
    second = _cached(tmp_path, msgs, produce)
    assert first == "RESULT"
    assert second == "RESULT"
    assert len(calls) == 1  # второй вызов читает файл, produce не зовётся


class _FakeRunner:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.rc, self.stdout, self.stderr = rc, stdout, stderr
        self.calls = []

    def __call__(self, argv, stdin_text, timeout):
        self.calls.append((argv, stdin_text, timeout))
        return self.rc, self.stdout, self.stderr


def test_claude_cli_maps_messages_and_returns_result(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    envelope = json.dumps(
        {"type": "result", "is_error": False, "result": '{"focus_leak_key":"feeding"}'}
    )
    runner = _FakeRunner(rc=0, stdout=envelope)
    llm = ClaudeCliLLM(claude_bin="claude", cache_dir=tmp_path, runner=runner)

    out = llm.complete(
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USR"}]
    )
    assert out == '{"focus_leak_key":"feeding"}'

    argv, stdin_text, timeout = runner.calls[0]
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "--output-format" in argv and "json" in argv
    assert "--disallowed-tools" in argv
    assert stdin_text == "SYS\n\nUSR"


def test_claude_cli_caches_second_call(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    runner = _FakeRunner(rc=0, stdout=json.dumps({"is_error": False, "result": "R"}))
    msgs = [{"role": "user", "content": "hi"}]
    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=runner)

    llm.complete(msgs)
    llm.complete(msgs)
    assert len(runner.calls) == 1  # второй раз — из кеша


def test_claude_cli_raises_on_nonzero_rc(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    runner = _FakeRunner(rc=1, stdout="", stderr="boom")
    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=runner)
    with pytest.raises(RuntimeError, match="boom"):
        llm.complete([{"role": "user", "content": "x"}])


def test_claude_cli_raises_on_is_error(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    runner = _FakeRunner(rc=0, stdout=json.dumps({"is_error": True, "result": "denied"}))
    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=runner)
    with pytest.raises(RuntimeError, match="denied"):
        llm.complete([{"role": "user", "content": "x"}])


def test_claude_cli_raises_on_empty_result(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    runner = _FakeRunner(rc=0, stdout=json.dumps({"is_error": False, "result": "  "}))
    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=runner)
    with pytest.raises(RuntimeError):
        llm.complete([{"role": "user", "content": "x"}])


def test_claude_cli_raises_clear_error_when_binary_missing(tmp_path):
    from dota_coach.coach.llm import ClaudeCliLLM

    def missing_runner(argv, stdin_text, timeout):
        raise FileNotFoundError(argv[0])

    llm = ClaudeCliLLM(cache_dir=tmp_path, runner=missing_runner)
    with pytest.raises(RuntimeError, match="claude не найден"):
        llm.complete([{"role": "user", "content": "x"}])
