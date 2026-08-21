import json
from pathlib import Path

from dota_coach.cli import build_match_report, build_parser
from dota_coach.ingest.normalize import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def test_coach_and_leaks_default_n_is_50():
    p = build_parser()
    assert p.parse_args(["coach", "--account-id", "1"]).n == 50
    assert p.parse_args(["leaks", "--account-id", "1"]).n == 50


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
            account_id=111, player_slot=0, hero_id=1, is_radiant=True, position_est=4,
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


def test_analyze_coach_flag_defaults_off():
    from dota_coach.cli import build_parser
    args = build_parser().parse_args(["analyze", "--match-id", "1", "--account-id", "2"])
    assert args.coach is False


def test_analyze_coach_renders_moment_brief(tmp_path, monkeypatch, capsys):
    import json
    from dota_coach.cli import main
    from dota_coach.models import Match, PlayerMatch

    def _match(mid):
        # gold_t=[0,1000,200]: на 2-й минуте просадка -800 (<= -500) -> networth_swing (verdict MISTAKE)
        me = PlayerMatch(account_id=111, player_slot=0, hero_id=1, is_radiant=True,
                         kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
                         gold_t=[0, 1000, 200])
        return Match(match_id=mid, duration=1800, radiant_win=True, players=[me],
                     teamfights=[], objectives=[], parsed=True)

    canned = json.dumps({"headline": "H", "hypothesis": "g", "process_question": "q",
                         "checklist": ["c"], "principle": "p"})

    monkeypatch.setattr("dota_coach.cli.fetch_match", lambda mid: {"id": mid})
    monkeypatch.setattr("dota_coach.cli.normalize", lambda raw: _match(raw["id"]))
    monkeypatch.setattr("dota_coach.cli.make_llm", lambda provider: __import__(
        "dota_coach.coach.llm", fromlist=["FakeLLM"]).FakeLLM(canned))

    def _no_replay(mid):
        from dota_coach.ingest.replay import ReplayUnavailable
        raise ReplayUnavailable("нет реплея в тесте")

    monkeypatch.setattr("dota_coach.cli.parse_replay", _no_replay)  # реплей-слой опционален -> деградация

    out = tmp_path / "r.html"
    rc = main(["analyze", "--match-id", "5", "--account-id", "111", "--coach", "--out", str(out)])
    assert rc == 0
    html = out.read_text(encoding="utf-8")
    assert "Разбор фокус-момента" in html and "H" in html


def test_analyze_video_offset_flag_parses():
    from dota_coach.cli import build_parser
    args = build_parser().parse_args(
        ["analyze", "--match-id", "1", "--account-id", "2", "--video", "g.mp4", "--video-offset", "5.5"])
    assert args.video_offset == 5.5
    args2 = build_parser().parse_args(["analyze", "--match-id", "1", "--account-id", "2"])
    assert args2.video_offset is None


def test_grab_moment_frame_bad_video_degrades_to_none():
    from dota_coach.cli import _grab_moment_frame
    assert _grab_moment_frame("does_not_exist.mp4", game_time=100, offset=0.0) is None
