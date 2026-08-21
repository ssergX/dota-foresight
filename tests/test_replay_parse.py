from pathlib import Path

import pytest

from dota_coach.ingest.replay import parse_replay_jsonl

_FIX = Path(__file__).parent / "fixtures" / "replay_sample.jsonl"


def _lines():
    return _FIX.read_text(encoding="utf-8").splitlines()


def test_parse_meta():
    r = parse_replay_jsonl(_lines(), match_id=42)
    assert r.match_id == 42
    assert r.game_start_time == 200.0
    assert r.heroes[0] == "CDOTA_Unit_Hero_Axe"
    assert r.heroes[5] == "CDOTA_Unit_Hero_Pudge"


def test_frames_sorted_by_time():
    r = parse_replay_jsonl(_lines(), match_id=42)
    assert [f.time for f in r.frames] == [0, 1, 2]   # фикстура нарочно вперемешку


def test_unit_fields_parsed():
    r = parse_replay_jsonl(_lines(), match_id=42)
    u = r.frame_at(2).units[5]
    assert u.slot == 5 and u.x == -30.0 and u.hp == 700 and u.alive is True
    dead = r.frame_at(1).units[0]
    assert dead.alive is False and dead.xp == 10


def test_missing_meta_raises():
    with pytest.raises(ValueError):
        parse_replay_jsonl(['{"t":"state","time":0,"units":[]}'], match_id=1)
