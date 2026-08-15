import json
from pathlib import Path

from dota_coach.cli import build_match_report
from dota_coach.ingest.normalize import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def test_build_match_report_end_to_end():
    match = normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))
    html = build_match_report(match, account_id=111, video_filename=None,
                              offset=0.0, top_n=5)
    assert "Разбор матча 8001" in html
    assert "Ключевые моменты" in html


def test_coach_dry_run_prints_prompt_without_llm(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    from dota_coach.cli import main
    from dota_coach.models import Match, PlayerMatch

    def _p(deaths, obs, gpm):
        return PlayerMatch(
            account_id=111, player_slot=0, hero_id=1, is_radiant=True,
            kills=0, deaths=deaths, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
            gold_t=[], xp_t=[], lh_t=[], kills_log=[], purchase_log=[],
            obs_log=[{"time": 60}] * obs, sen_log=[],
            benchmarks={"gold_per_min": {"raw": 400, "pct": gpm}},
        )

    def _match(mid):
        return Match(match_id=mid, duration=1800, radiant_win=True,
                     players=[_p(11, 1, 0.25)], teamfights=[], objectives=[], parsed=True)

    monkeypatch.setattr("dota_coach.cli.fetch_recent", lambda acc, n: list(range(5)))
    monkeypatch.setattr("dota_coach.cli.fetch_match", lambda mid: {"id": mid})
    monkeypatch.setattr("dota_coach.cli.normalize", lambda raw: _match(raw["id"]))

    rc = main(["coach", "--account-id", "111", "--n", "5", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "system" in out
    assert "Главный лик-фокус" in out   # промпт напечатан, ЛЛМ не вызывался
