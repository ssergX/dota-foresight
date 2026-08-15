from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.progress import compare_focus
from dota_coach.coach.prompt import build_coach_prompt
from dota_coach.models import Confidence, Leak


def _leak(key, metric, value, threshold, direction):
    return Leak(key=key, title=key, magnitude="", example_matches=[7, 8],
                confidence=Confidence.HIGH, metric=metric, value=value,
                threshold=threshold, direction=direction)


def _leaks():
    return [_leak("feeding", "deaths_per_game", 11.0, 8.0, "lower_is_better")]


def test_prompt_has_system_and_user_roles():
    msgs = build_coach_prompt(_leaks(), None, "принципы фидинга", None, "feeding")
    assert [m["role"] for m in msgs] == ["system", "user"]


def test_prompt_contains_numbers_focus_and_principles():
    msgs = build_coach_prompt(_leaks(), None, "принципы фидинга", None, "feeding")
    user = msgs[1]["content"]
    assert "11.0" in user            # value
    assert "8.0" in user             # threshold
    assert "feeding" in user         # focus key
    assert "принципы фидинга" in user


def test_system_enforces_anti_outcome_rule():
    msgs = build_coach_prompt(_leaks(), None, "p", None, "feeding")
    assert "исход" in msgs[0]["content"].lower()


def test_user_prompt_has_no_winloss_data():
    # анти-результатничество: сырых исходов матча в данные не подаём
    msgs = build_coach_prompt(_leaks(), None, "p", None, "feeding")
    user = msgs[1]["content"]
    assert "radiant_win" not in user
    assert "победа" not in user.lower()
    assert "поражение" not in user.lower()


def test_prompt_includes_prior_progress():
    prior = CoachBrief(focus_leak_key="feeding", headline="", diagnosis="", why_it_costs="",
                       focus_metric="deaths_per_game", focus_value=14.0,
                       focus_direction="lower_is_better")
    progress = compare_focus(prior, _leaks())   # 14.0 -> 11.0, lower_is_better -> improved
    msgs = build_coach_prompt(_leaks(), progress, "p", prior, "feeding")
    assert "прогресс" in msgs[1]["content"]
