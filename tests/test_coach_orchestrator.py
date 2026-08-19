import json

from dota_coach.coach.coach import run_coach
from dota_coach.coach.history import latest_brief
from dota_coach.coach.llm import FakeLLM
from dota_coach.models import Match, PlayerMatch

_CANNED = json.dumps({"focus_leak_key": "ignored", "headline": "h", "diagnosis": "d",
                      "why_it_costs": "w", "drills": [{"text": "t", "metric_ref": "obs_per_game"}]})


def _me(**kw):
    base = dict(account_id=7, player_slot=0, hero_id=1, is_radiant=True,
                kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    base.update(kw)
    return PlayerMatch(**base)


def _match(mid, me):
    return Match(match_id=mid, duration=1800, radiant_win=True, players=[me], parsed=True)


def test_focus_is_top_severity_leak(tmp_path):
    matches = [_match(i, _me(position_est=5, deaths=20, obs_placed=0,
                             benchmarks={"gold_per_min": {"raw": 500, "pct": 0.7}}))
               for i in range(8)]
    brief = run_coach(matches, 7, FakeLLM(_CANNED), cache_dir=tmp_path)
    assert brief.focus_leak_key in {"feeding", "low_obs"}   # оба лика pos5, фокус — сильнейший
    assert brief.focus_leak_key != ""
    assert brief.focus_metric != ""
    assert isinstance(brief.focus_value, float)
    saved = latest_brief(7, cache_dir=tmp_path)
    assert saved is not None and saved.focus_leak_key == brief.focus_leak_key


def test_run_coach_second_run_reports_progress(tmp_path):
    # pos5, obs_placed=1 -> low_obs фокус (avg 1 < порог 6); второй прогон obs=4 -> прогресс (higher_is_better)
    first = [_match(i, _me(position_est=5, deaths=3, obs_placed=1,
                           benchmarks={"gold_per_min": {"raw": 500, "pct": 0.7}})) for i in range(6)]
    run_coach(first, 7, FakeLLM(_CANNED), cache_dir=tmp_path)
    b1 = latest_brief(7, cache_dir=tmp_path)
    assert b1.focus_leak_key == "low_obs" and b1.focus_metric == "obs_per_game" and b1.focus_value == 1.0
    second = [_match(i, _me(position_est=5, deaths=3, obs_placed=4,
                            benchmarks={"gold_per_min": {"raw": 500, "pct": 0.7}})) for i in range(6)]
    brief2 = run_coach(second, 7, FakeLLM(_CANNED), cache_dir=tmp_path)
    assert brief2.progress_note is not None and "прогресс" in brief2.progress_note


def test_no_leaks_skips_llm(tmp_path):
    # «Чистая» серия: ручные метрики выше порогов (denies=12>8), бенчи здоровые,
    # парс-зависимые счётчики отсутствуют (None -> requires исключает) -> ни один детектор не сработал.
    matches = [_match(i, _me(position_est=1, deaths=2, last_hits=300, denies=12,
                             benchmarks={"gold_per_min": {"raw": 700, "pct": 0.8}}))
               for i in range(6)]
    llm = FakeLLM(_CANNED)
    brief = run_coach(matches, 7, llm, cache_dir=tmp_path)
    assert brief.focus_leak_key == "" and llm.calls == []
