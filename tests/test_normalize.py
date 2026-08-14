import json
from pathlib import Path

from dota_coach.ingest.normalize import normalize
from dota_coach.models import Match

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def _raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_normalize_builds_match_with_players_and_events():
    m = normalize(_raw())
    assert isinstance(m, Match)
    assert m.match_id == 8001
    assert m.parsed is True
    assert len(m.players) == 2
    me = m.player_by_account(111)
    assert me.is_radiant is True
    assert me.deaths == 9
    assert me.benchmarks["gold_per_min"]["pct"] == 0.32
    assert len(m.teamfights) == 1
    assert m.teamfights[0].players[0]["gold_delta"] == -400
    assert m.objectives[0].type == "CHAT_MESSAGE_TOWER_KILL"


def test_normalize_handles_unparsed_match():
    raw = _raw()
    raw.pop("version")
    raw["teamfights"] = None
    raw["objectives"] = None
    m = normalize(raw)
    assert m.parsed is False
    assert m.teamfights == []
    assert m.objectives == []
