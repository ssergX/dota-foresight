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


from dota_coach.ingest.replay import ReplayUnavailable, parse_replay


def test_parse_replay_cache_hit(tmp_path):
    # положить готовый JSONL в кеш -> parse_replay читает его без сети
    (tmp_path / "replay_5.jsonl").write_text(_FIX.read_text(encoding="utf-8"), encoding="utf-8")
    r = parse_replay(5, cache_dir=tmp_path,
                     downloader=lambda url: (_ for _ in ()).throw(AssertionError("сети быть не должно")),
                     runner=lambda argv: (_ for _ in ()).throw(AssertionError("бинарь не звать")))
    assert r.match_id == 5 and len(r.heroes) == 2


def test_parse_replay_runner_failure_raises_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("dota_coach.ingest.replay.fetch_match",
                        lambda mid: {"replay_url": "http://x/y.dem.bz2"})

    def bad_runner(argv):
        raise RuntimeError("бинарь упал")

    with pytest.raises(ReplayUnavailable):
        parse_replay(7, cache_dir=tmp_path,
                     downloader=lambda url: b"\x28\xb5\x2f\xfd",
                     runner=bad_runner)


def test_parse_replay_no_replay_url_raises_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("dota_coach.ingest.replay.fetch_match", lambda mid: {})
    with pytest.raises(ReplayUnavailable):
        parse_replay(9, cache_dir=tmp_path)
