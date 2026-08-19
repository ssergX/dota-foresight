from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.progress import compare_focus
from dota_coach.models import Confidence, Leak


def _leak(key, metric, value, threshold, direction):
    return Leak(key=key, title=key, magnitude="", example_matches=[],
                confidence=Confidence.HIGH, metric=metric, value=value,
                threshold=threshold, direction=direction)


def _prior(focus_key, metric, value, direction):
    return CoachBrief(focus_leak_key=focus_key, headline="", diagnosis="", why_it_costs="",
                      focus_metric=metric, focus_value=value, focus_direction=direction)


def test_no_history_when_no_prior():
    note = compare_focus(None, [_leak("feeding", "deaths_per_game", 11.0, 8.0, "lower_is_better")])
    assert note.status == "no_history"


def test_feeding_improved_lower_is_better():
    prior = _prior("feeding", "deaths_per_game", 11.0, "lower_is_better")
    curr = [_leak("feeding", "deaths_per_game", 8.5, 8.0, "lower_is_better")]
    note = compare_focus(prior, curr)
    assert note.status == "improved"
    assert "прогресс" in note.text


def test_feeding_regressed_lower_is_better():
    prior = _prior("feeding", "deaths_per_game", 8.5, "lower_is_better")
    curr = [_leak("feeding", "deaths_per_game", 12.0, 8.0, "lower_is_better")]
    note = compare_focus(prior, curr)
    assert note.status == "regressed"
    assert "регресс" in note.text


def test_gpm_improved_higher_is_better():
    prior = _prior("farm_below_bracket", "gpm_pct", 0.25, "higher_is_better")
    curr = [_leak("farm_below_bracket", "gpm_pct", 0.35, 0.4, "higher_is_better")]
    note = compare_focus(prior, curr)
    assert note.status == "improved"


def test_resolved_when_leak_absent():
    prior = _prior("low_obs", "obs_per_game", 1.0, "higher_is_better")
    note = compare_focus(prior, [_leak("feeding", "deaths_per_game", 9.0, 8.0, "lower_is_better")])
    assert note.status == "resolved"


def test_flat_when_same_value():
    prior = _prior("feeding", "deaths_per_game", 9.0, "lower_is_better")
    curr = [_leak("feeding", "deaths_per_game", 9.0, 8.0, "lower_is_better")]
    assert compare_focus(prior, curr).status == "flat"


def test_gpm_regressed_higher_is_better():
    prior = _prior("farm_below_bracket", "gpm_pct", 0.35, "higher_is_better")
    curr = [_leak("farm_below_bracket", "gpm_pct", 0.25, 0.4, "higher_is_better")]
    note = compare_focus(prior, curr)
    assert note.status == "regressed"
    assert "регресс" in note.text


def test_flat_higher_is_better():
    prior = _prior("farm_below_bracket", "gpm_pct", 0.30, "higher_is_better")
    curr = [_leak("farm_below_bracket", "gpm_pct", 0.30, 0.4, "higher_is_better")]
    assert compare_focus(prior, curr).status == "flat"


def test_no_history_when_focus_key_empty():
    prior = _prior("", "deaths_per_game", 11.0, "lower_is_better")
    note = compare_focus(prior, [_leak("feeding", "deaths_per_game", 9.0, 8.0, "lower_is_better")])
    assert note.status == "no_history"
