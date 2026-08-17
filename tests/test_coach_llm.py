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
