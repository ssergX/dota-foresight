from dota_coach.coach.brief import CoachBrief
from dota_coach.coach.history import latest_brief, load_history, save_brief


def _brief(key, value):
    return CoachBrief(focus_leak_key=key, headline="h", diagnosis="d", why_it_costs="w",
                      focus_metric="deaths_per_game", focus_value=value,
                      focus_direction="lower_is_better")


def test_load_history_empty_when_no_file(tmp_path):
    assert load_history(111, cache_dir=tmp_path) == []
    assert latest_brief(111, cache_dir=tmp_path) is None


def test_save_then_load_round_trip(tmp_path):
    save_brief(111, _brief("feeding", 11.0), cache_dir=tmp_path)
    save_brief(111, _brief("feeding", 8.0), cache_dir=tmp_path)
    hist = load_history(111, cache_dir=tmp_path)
    assert len(hist) == 2
    assert hist[0].focus_value == 11.0
    assert latest_brief(111, cache_dir=tmp_path).focus_value == 8.0


def test_history_is_per_account(tmp_path):
    save_brief(111, _brief("feeding", 11.0), cache_dir=tmp_path)
    assert load_history(222, cache_dir=tmp_path) == []
