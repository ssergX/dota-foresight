from dota_coach.ingest.replay import parse_replay_jsonl
from dota_coach.models import WardEvent

_LINES = [
    '{"t":"meta","game_start_time":200.0,"tick_rate":30,"heroes":['
    '{"slot":0,"team":2,"hero":"CDOTA_Unit_Hero_Axe"},'
    '{"slot":5,"team":3,"hero":"CDOTA_Unit_Hero_Pudge"}]}',
    '{"t":"state","time":0,"units":[{"slot":0,"x":0.0,"y":0.0,"hp":600,"max_hp":600,"mana":100.0,"level":1,"xp":0,"alive":true}]}',
    '{"t":"ward","id":7,"time":10,"kind":"obs","team":2,"x":100.0,"y":200.0,"op":"placed"}',
    '{"t":"ward","id":7,"time":250,"kind":"obs","team":2,"x":100.0,"y":200.0,"op":"gone"}',
    '{"t":"ward","id":9,"time":30,"kind":"sentry","team":3,"x":-50.0,"y":-60.0,"op":"placed"}',
]


def test_teams_parsed_from_meta():
    r = parse_replay_jsonl(_LINES, match_id=1)
    assert r.teams == {0: 2, 5: 3}


def test_ward_events_parsed():
    r = parse_replay_jsonl(_LINES, match_id=1)
    assert len(r.wards) == 3
    w = r.wards[0]
    assert isinstance(w, WardEvent)
    assert w.id == 7 and w.time == 10 and w.kind == "obs" and w.team == 2
    assert w.x == 100.0 and w.op == "placed"


def test_replay_without_wards_has_empty_list():
    lines = [_LINES[0], _LINES[1]]
    r = parse_replay_jsonl(lines, match_id=1)
    assert r.wards == []
