import bz2
import json
from pathlib import Path

import pytest

from dota_coach.ingest.replay import ReplayUnavailable, _decompress, parse_replay, parse_replay_jsonl


def _meta(**changes):
    return dict(t="meta", schema_version="replay-jsonl.v2", game_start_time=200.0,
                tick_rate=30, heroes=[dict(slot=0, team=2, hero="CDOTA_Unit_Hero_Axe")],
                extractor_name="manta", extractor_version="foresight-replay/2",
                timebase_version="tick30-minus-start/unverified", completeness="partial",
                parse_warnings=[], capabilities=[dict(capability_id="primary_hero_identity",
                                                       implementation="implemented",
                                                       validation="unverified")], **changes)


def _lines(*records):
    return [json.dumps(record) for record in records]


def _state(**changes):
    state = dict(t="state", time=0.5, tick=6015, sequence=1,
                 units=[dict(slot=0, x=None, y=0.0, hp=0, alive=None)])
    state.update(changes)
    return state


def _ward(time, generation=1, op="placed", sequence=2):
    return dict(t="ward", id=17, generation=generation, time=time,
                tick=round((time + 200) * 30), sequence=sequence,
                kind="obs", team=2, x=0.0, y=0.0, op=op)


def test_nullable_missing_is_distinct_from_known_zero_and_fractional_time():
    replay = parse_replay_jsonl(_lines(_meta(), _state()), 1)
    unit = replay.frames[0].units[0]
    assert replay.frames[0].time == 0.5
    assert unit.x is None and unit.y == 0 and unit.hp == 0
    assert unit.mana is None and unit.alive is None
    assert "missing_unit_properties" in replay.manifest.parse_warnings
    assert replay.frames[0].tick == 6015


def test_legacy_is_explicitly_unverified():
    fixture = Path(__file__).parent / "fixtures" / "replay_sample.jsonl"
    replay = parse_replay_jsonl(fixture.read_text(encoding="utf-8").splitlines(), 1)
    assert replay.manifest.schema_version == "legacy-jsonl"
    assert not replay.manifest.supports("primary_hero_identity")
    assert "legacy_schema" in replay.manifest.parse_warnings


def test_parser_cannot_self_attest_validation():
    meta = _meta()
    meta["capabilities"][0].update(validation="validated", patch="fake", validation_refs=["fake"])
    replay = parse_replay_jsonl(_lines(meta, _state()), 1)
    assert replay.manifest.capabilities[0].validation == "unverified"
    assert not replay.manifest.supports("primary_hero_identity")
    assert any(w.startswith("ignored_untrusted_validation_claim") for w in replay.manifest.parse_warnings)


def test_pregame_ward_and_entity_reuse_keep_separate_instances():
    replay = parse_replay_jsonl(_lines(_meta(), _state(), _ward(-1.5),
                                      _ward(1.5, op="gone"), _ward(2, generation=2)), 1)
    assert [ward.time for ward in replay.wards] == [-1.5, 1.5, 2.0]
    assert [ward.generation for ward in replay.wards] == [1, 1, 2]


def test_future_ward_reuse_does_not_change_past_record():
    prefix = _lines(_meta(), _state(), _ward(-1.5))
    past = parse_replay_jsonl(prefix, 1).wards[0]
    full = parse_replay_jsonl(prefix + _lines(_ward(1.5, op="gone"), _ward(2, generation=2)), 1)
    assert full.wards[0] == past


@pytest.mark.parametrize("field,value", [
    ("hp", False), ("hp", "0"), ("hp", -1), ("hp", 1.5),
    ("alive", "false"), ("alive", 0), ("x", float("nan")),
    ("mana", float("inf")), ("slot", True), ("slot", 10),
])
def test_malformed_unit_properties_rejected(field, value):
    state = _state()
    state["units"][0][field] = value
    with pytest.raises(ValueError):
        parse_replay_jsonl(_lines(_meta(), state), 1)


@pytest.mark.parametrize("record", [
    dict(t="unexpected"),
    _state(time=float("nan")),
    _state(time=1.0),
    _state(tick=None),
    _state(units=[dict(slot=0), dict(slot=0)]),
    _ward(1, generation=0),
    {**_ward(1), "team": 4},
    {**_ward(1), "op": "maybe"},
])
def test_invalid_record_rejected(record):
    with pytest.raises(ValueError):
        parse_replay_jsonl(_lines(_meta(), record), 1)


def test_duplicate_meta_frame_and_json_key_rejected():
    for records in ((_meta(), _meta()), (_meta(), _state(), _state())):
        with pytest.raises(ValueError):
            parse_replay_jsonl(_lines(*records), 1)
    with pytest.raises(ValueError, match="duplicate JSON key"):
        parse_replay_jsonl(['{"t":"meta","t":"state"}'], 1)


def test_unsupported_schema_rejected():
    meta = _meta()
    meta["schema_version"] = "replay-jsonl.v99"
    with pytest.raises(ValueError, match="unsupported replay schema"):
        parse_replay_jsonl(_lines(meta), 1)


def test_malformed_cached_output_is_optional_unavailable(tmp_path):
    (tmp_path / "replay_42.v2.jsonl").write_text("not json", encoding="utf-8")
    with pytest.raises(ReplayUnavailable):
        parse_replay(42, tmp_path)


def _run_download(tmp_path, monkeypatch, output):
    monkeypatch.setattr("dota_coach.ingest.replay.fetch_match", lambda _: {"replay_url": "https://fixture.invalid/x.zst"})
    return parse_replay(42, tmp_path, downloader=lambda _: bz2.compress(b"PBDEMS2\x00fixture"),
                        runner=lambda _: output)


def test_invalid_runner_output_never_poison_cache(tmp_path, monkeypatch):
    with pytest.raises(ReplayUnavailable):
        _run_download(tmp_path, monkeypatch, "{broken}")
    assert list(tmp_path.glob("*.jsonl")) == []
    assert list(tmp_path.glob("*.tmp")) == []


def test_valid_output_atomically_publishes_versioned_cache(tmp_path, monkeypatch):
    output = "\n".join(_lines(_meta(), _state()))
    first = _run_download(tmp_path, monkeypatch, output)
    cached = next(tmp_path.glob("replay_42.v2.*.jsonl"))
    assert cached.read_text(encoding="utf-8") == output
    assert list(tmp_path.glob("*.tmp")) == []
    second = parse_replay(42, tmp_path, runner=lambda _: pytest.fail("cache must bypass runner"))
    assert first == second


def test_compression_magic_not_suffix_and_unknown_header_rejected():
    raw = b"PBDEMS2\x00fixture"
    assert _decompress(raw) == raw
    assert _decompress(bz2.compress(raw)) == raw
    with pytest.raises(ValueError, match="unknown replay"):
        _decompress(b"not replay")


def test_changed_parser_binary_changes_cache_namespace(tmp_path):
    from dota_coach.ingest.replay import _cache_path
    tool = tmp_path / "parser.exe"
    tool.write_bytes(b"parser-version-1")
    first = _cache_path(tmp_path, 42, str(tool))
    tool.write_bytes(b"parser-version-2")
    second = _cache_path(tmp_path, 42, str(tool))
    assert first != second
