import json

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


def test_brief_roundtrip_keeps_snapshot_and_version(tmp_path):
    b = CoachBrief(focus_leak_key="low_obs", headline="h", diagnosis="d", why_it_costs="w",
                   leaks_snapshot=[{"key": "low_obs", "metric": "obs_per_game", "value": 1.0,
                                    "direction": "higher_is_better", "role": 5}])
    save_brief(7, b, cache_dir=tmp_path)
    got = latest_brief(7, cache_dir=tmp_path)
    assert got.schema_version == 2
    assert got.leaks_snapshot[0]["key"] == "low_obs"


def test_history_maps_legacy_low_warding_key(tmp_path):
    path = tmp_path / "coach_history_7.json"
    path.write_text(json.dumps([{"focus_leak_key": "low_warding", "headline": "h",
                                 "diagnosis": "", "why_it_costs": "", "drills": []}]),
                    encoding="utf-8")
    got = latest_brief(7, cache_dir=tmp_path)
    assert got.focus_leak_key == "low_obs"
    assert got.baseline_reset is True   # переименованный ключ -> сравнение прогресса с нуля
