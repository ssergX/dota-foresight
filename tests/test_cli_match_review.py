import json

import dota_coach.cli as cli
from dota_coach.coach.llm import FakeLLM
from dota_coach.models import (
    Match, ParsedReplay, PlayerMatch, ReplayFrame, Teamfight, UnitState,
)


def _u(alive):
    return UnitState(slot=0, x=0, y=0, hp=100, max_hp=100, mana=0, level=1, xp=0, alive=alive)


def _match():
    me = PlayerMatch(account_id=7, player_slot=1, hero_id=25, is_radiant=True,
                     kills=1, deaths=1, assists=0, gold_per_min=500, xp_per_min=500,
                     last_hits=0, gold_t=[0, 100, 200], xp_t=[0, 0, 0])
    tf = Teamfight(start=120, end=140, deaths=3,
                   players=[{"deaths": 1, "gold_delta": -300, "damage": 100}])
    return Match(match_id=1, duration=1800, radiant_win=True, players=[me],
                 teamfights=[tf], objectives=[])


def _replay():
    frames = [ReplayFrame(time=t, units={1: _u(t != 600)}) for t in range(0, 700, 10)]
    return ParsedReplay(match_id=1, game_start_time=0, heroes={1: "Lina"},
                        frames=frames, teams={1: 2})


def test_analyze_coach_writes_folder_report(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "fetch_match", lambda mid: {"_": mid})
    monkeypatch.setattr(cli, "normalize", lambda raw: _match())
    monkeypatch.setattr(cli, "parse_replay", lambda mid: _replay())
    canned = json.dumps({"headline": "h", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p",
                         "situation": "с", "takeaway": "т"})
    monkeypatch.setattr(cli, "make_llm", lambda provider: FakeLLM(canned))
    out = tmp_path / "review"
    rc = cli.main(["analyze", "--match-id", "1", "--account-id", "7",
                   "--coach", "--out", str(out)])
    assert rc == 0
    assert (out / "index.html").exists()
    assert "эпизодов" in (out / "index.html").read_text(encoding="utf-8")
