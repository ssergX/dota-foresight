import json

from dota_coach.coach.coach import run_coach
from dota_coach.coach.history import latest_brief
from dota_coach.coach.llm import FakeLLM
from dota_coach.models import Match, PlayerMatch


def _p(account_id, gpm_pct, deaths, obs):
    return PlayerMatch(
        account_id=account_id, player_slot=0, hero_id=1, is_radiant=True,
        kills=0, deaths=deaths, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
        gold_t=[], xp_t=[], lh_t=[], kills_log=[], purchase_log=[],
        obs_log=[{"time": 60}] * obs, sen_log=[],
        benchmarks={"gold_per_min": {"raw": 400, "pct": gpm_pct}},
    )


def _m(mid, account_id, gpm_pct, deaths, obs):
    return Match(match_id=mid, duration=1800, radiant_win=True,
                 players=[_p(account_id, gpm_pct, deaths, obs)],
                 teamfights=[], objectives=[], parsed=True)


_CANNED = json.dumps({
    "focus_leak_key": "ignored-by-code",
    "headline": "Мало вардов",
    "diagnosis": "варды в p1",
    "why_it_costs": "нет информации — лишние смерти",
    "drills": [{"text": "ставь обс на руну перед фармом", "metric_ref": "obs_per_game"}],
})


def test_run_coach_builds_brief_and_saves(tmp_path):
    # obs=1 -> low_warding имеет наибольшее отклонение от порога -> фокус
    matches = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=1) for i in range(5)]
    llm = FakeLLM(_CANNED)
    brief = run_coach(matches, 111, llm, cache_dir=tmp_path)

    assert brief.focus_leak_key == "low_warding"      # фокус ставит код, не ЛЛМ
    assert brief.focus_metric == "obs_per_game"
    assert brief.focus_value == 1.0
    assert brief.drills[0].metric_ref == "obs_per_game"
    assert brief.progress_note is None                # первый прогон
    assert len(llm.calls) == 1
    # сохранён в историю
    assert latest_brief(111, cache_dir=tmp_path).focus_leak_key == "low_warding"


def test_run_coach_no_leaks_skips_llm(tmp_path):
    matches = [_m(i, 111, gpm_pct=0.7, deaths=3, obs=8) for i in range(5)]
    llm = FakeLLM(_CANNED)
    brief = run_coach(matches, 111, llm, cache_dir=tmp_path)
    assert brief.focus_leak_key == ""
    assert "не найдено" in brief.headline
    assert llm.calls == []                            # ЛЛМ не вызывался


def test_run_coach_second_run_reports_progress(tmp_path):
    first = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=1) for i in range(5)]
    run_coach(first, 111, FakeLLM(_CANNED), cache_dir=tmp_path)   # focus low_warding, obs=1
    second = [_m(i, 111, gpm_pct=0.25, deaths=11, obs=3) for i in range(5)]  # obs 1 -> 3
    brief2 = run_coach(second, 111, FakeLLM(_CANNED), cache_dir=tmp_path)
    assert brief2.progress_note is not None
    assert "прогресс" in brief2.progress_note         # higher_is_better, 1 -> 3
