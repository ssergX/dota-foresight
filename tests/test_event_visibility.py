from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json

import pytest

from dota_coach.evidence.contracts import ReplayManifest, content_hash
from dota_coach.ingest.event_visibility import extract_event_visibility, load_event_visibility_source
from dota_coach.ingest.trace import TraceResult
from dota_coach.models import ParsedReplay


def trace(count=1):
    replay = ParsedReplay(7, 10, {}, [], manifest=ReplayManifest("a" * 64, 7, dataset_kind="synthetic"))
    return TraceResult(replay, (), {"match_id": 7, "replay_sha256": "a" * 64,
        "trace_sha256": "b" * 64, "record_counts": {"combat_log": count}}, ())


def event(**flags):
    return {"t": "combat_log", "net_tick": 100, "sequence_in_tick": 1,
        "name_resolution": "CombatLogNames_at_callback/v1",
        "resolved_names": {"attacker_name": "hero_a", "target_name": "hero_b"},
        "data": {"type": "DOTA_COMBATLOG_DAMAGE", "timestamp": 12.5,
                 "attacker_name": 1, "target_name": 2, "health": 500, **flags}}


def source(path, events, mutate=None):
    rows = [{"t": "meta", "schema_version": "replay-combat-names.v1", "replay_sha256": "a" * 64}]
    rows.extend(events)
    rows.append({"t": "trace_end", "parser_completed": True})
    for index, row in enumerate(rows, 1):
        row["record_index"] = index
    rows[-1]["counts"] = dict(Counter(row["t"] for row in rows))
    if mutate:
        mutate(rows)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def extract(path, out, extraction=None, **kwargs):
    extraction = extraction or trace()
    args = {"expected_replay_sha256": "a" * 64,
            "expected_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "expected_extraction_sha256": content_hash(asdict(extraction))} | kwargs
    return extract_event_visibility(path, extraction, out, **args)


def test_explicit_false_is_preserved_absent_stays_unknown_and_roundtrip(tmp_path):
    p = source(tmp_path / "source", [event(is_visible_radiant=False), event(is_visible_dire=True), event()])
    t = trace(3)
    out = tmp_path / "result"
    result = extract(p, out, t)
    assert result == load_event_visibility_source(out, extraction=t)
    assert result["raw_flag_counts"] == {"radiant": {"true": 0, "false": 1, "unknown": 2},
        "dire": {"true": 1, "false": 0, "unknown": 2}}
    rows = [json.loads(line) for line in out.read_text().splitlines()][1:-1]
    assert rows[0]["raw_visibility"]["radiant"]["value"] is False
    assert rows[0]["source_domain"] == "combat_names"
    assert rows[0]["source_record_index"] == 2
    assert rows[0]["raw_target_health"] == 500
    assert rows[0]["resolved_names"]["target_name"] == "hero_b"
    assert all(row["screen_cue"] is None and row["entity_identity"] is None and row["game_time"] is None for row in rows)
    assert result["training_eligible"] is False
    assert result["continuous_visibility_coverage"] is None


@pytest.mark.parametrize("value", [None, 0, 1, "false", {}, []])
def test_visibility_flag_requires_explicit_boolean(tmp_path, value):
    p = source(tmp_path / "source", [event(is_visible_radiant=value)])
    with pytest.raises(ValueError, match="explicit boolean"):
        extract(p, tmp_path / "result")
    assert not (tmp_path / "result").exists()
    assert not list(tmp_path.glob("event-visibility-*.tmp"))


@pytest.mark.parametrize("mutation", [
    lambda rows: rows[-1].update(parser_completed=False),
    lambda rows: rows[-1].update(counts={"meta": 1, "combat_log": 9, "trace_end": 1}),
    lambda rows: rows[-1].update(counts={"meta": True, "combat_log": 1, "trace_end": 1}),
    lambda rows: rows[1].update(record_index=6),
    lambda rows: rows[0].update(replay_sha256="c" * 64),
    lambda rows: rows.append(dict(rows[1], record_index=4)),
    lambda rows: rows.pop(),
])
def test_invalid_source_never_replaces_prior_result(tmp_path, mutation):
    p = source(tmp_path / "source", [event()], mutate=mutation)
    out = tmp_path / "result"
    out.write_text("prior valid output")
    with pytest.raises(ValueError):
        extract(p, out)
    assert out.read_text() == "prior valid output"
    assert not list(tmp_path.glob("event-visibility-*.tmp"))


def test_source_and_extraction_receipts_are_mandatory_and_checked(tmp_path):
    p = source(tmp_path / "source", [event()])
    with pytest.raises(ValueError, match="source SHA256 mismatch"):
        extract(p, tmp_path / "out", expected_source_sha256="c" * 64)
    with pytest.raises(ValueError, match="binding mismatch"):
        extract(p, tmp_path / "out", expected_extraction_sha256="c" * 64)
    t = trace(2)
    with pytest.raises(ValueError, match="population"):
        extract(p, tmp_path / "out", t)
    assert not (tmp_path / "out").exists()


def test_no_overwrite_source_or_hardlink(tmp_path):
    p = source(tmp_path / "source", [event()])
    original = p.read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        extract(p, p)
    linked = tmp_path / "linked"
    linked.hardlink_to(p)
    with pytest.raises(ValueError, match="overwrite"):
        extract(p, linked)
    assert p.read_bytes() == original


def test_future_source_change_does_not_change_earlier_analytical_input(tmp_path):
    out1, out2 = tmp_path / "out1", tmp_path / "out2"
    p1 = source(tmp_path / "source1", [event(is_visible_radiant=True)])
    p2 = source(tmp_path / "source2", [event(is_visible_radiant=True), event(is_visible_dire=True)])
    extract(p1, out1)
    extract(p2, out2, trace(2))
    row1 = json.loads(out1.read_text().splitlines()[1])
    row2 = json.loads(out2.read_text().splitlines()[1])
    assert row1 == row2


def test_loaded_derivative_cannot_bind_different_extraction_or_forge_scope(tmp_path):
    p = source(tmp_path / "source", [event()])
    out = tmp_path / "result"
    extract(p, out)
    t = trace()
    changed = replace(t, audit=t.audit | {"trace_sha256": "c" * 64})
    with pytest.raises(ValueError, match="binding"):
        load_event_visibility_source(out, extraction=changed)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    rows[1]["screen_cue"] = True
    out.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="scope"):
        load_event_visibility_source(out, extraction=t)


def test_derivative_stream_seal_and_footer_counts_detect_edit(tmp_path):
    p = source(tmp_path / "source", [event()])
    out = tmp_path / "result"
    extract(p, out)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    rows[-1]["records_sha256"] = "c" * 64
    out.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="seal"):
        load_event_visibility_source(out, extraction=trace())


def test_empty_callback_population_has_unknown_coverage(tmp_path):
    p = source(tmp_path / "source", [])
    t = trace(0)
    out = tmp_path / "result"
    result = extract(p, out, t)
    assert result == load_event_visibility_source(out, extraction=t)
    assert result["observation_count"] == 0
    assert result["continuous_visibility_coverage"] is None


def test_duplicate_visibility_keys_and_oversized_lines_are_rejected(tmp_path, monkeypatch):
    p = source(tmp_path / "source", [event(is_visible_radiant=True)])
    text = p.read_text().replace('"is_visible_radiant": true',
                                '"is_visible_radiant": true, "is_visible_radiant": false')
    p.write_text(text)
    with pytest.raises(ValueError):
        extract(p, tmp_path / "result")
    from dota_coach.ingest import event_visibility
    monkeypatch.setattr(event_visibility, "MAX_RECORD_BYTES", 64)
    with pytest.raises(ValueError, match="size limit"):
        extract(p, tmp_path / "result")
    assert not (tmp_path / "result").exists()


def test_summary_event_type_cardinality_is_bounded(tmp_path):
    rows = [event() for _ in range(257)]
    for i, row in enumerate(rows):
        row["data"]["type"] = f"source_event_{i}"
    p = source(tmp_path / "source", rows)
    with pytest.raises(ValueError, match="cardinality"):
        extract(p, tmp_path / "result", trace(257))
    assert not (tmp_path / "result").exists()
