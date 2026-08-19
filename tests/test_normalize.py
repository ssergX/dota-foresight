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


def test_normalize_pulls_role_and_parse_fields():
    raw = {"match_id": 1, "duration": 1800, "radiant_win": True, "version": 22,
           "players": [{"account_id": 7, "player_slot": 0, "position_est": 4,
                        "lane_role": 3, "is_roaming": False, "denies": 12,
                        "obs_placed": 7, "life_state_dead": 523,
                        "teamfight_participation": 0.52, "lane_efficiency_pct": 38}]}
    m = normalize(raw)
    me = m.players[0]
    assert me.position_est == 4 and me.denies == 12 and me.obs_placed == 7
    assert me.life_state_dead == 523 and me.teamfight_participation == 0.52


def test_normalize_absent_parse_fields_stay_none():
    raw = {"match_id": 2, "duration": 1800, "radiant_win": True,  # без version -> unparsed
           "players": [{"account_id": 7, "player_slot": 0}]}
    me = normalize(raw).players[0]
    assert me.position_est is None and me.life_state_dead is None
    assert me.teamfight_participation is None and me.denies == 0  # число -> 0
