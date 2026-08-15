import json

import pytest

from dota_coach.coach.brief import CoachBrief, Drill, brief_to_dict, parse_brief


def test_parse_brief_good_json():
    raw = json.dumps({
        "focus_leak_key": "feeding",
        "headline": "Слишком часто умираешь",
        "diagnosis": "11 смертей за игру",
        "why_it_costs": "отдаёшь темп",
        "drills": [{"text": "перед движением проверь миникарту", "metric_ref": "deaths_per_game"}],
    })
    b = parse_brief(raw)
    assert isinstance(b, CoachBrief)
    assert b.focus_leak_key == "feeding"
    assert b.drills[0].metric_ref == "deaths_per_game"


def test_parse_brief_missing_focus_raises():
    with pytest.raises(ValueError):
        parse_brief(json.dumps({"headline": "x", "drills": []}))


def test_parse_brief_drills_not_list_raises():
    with pytest.raises(ValueError):
        parse_brief({"focus_leak_key": "feeding", "drills": "nope"})


def test_brief_dict_round_trip_preserves_focus_snapshot():
    b = CoachBrief(
        focus_leak_key="low_warding", headline="h", diagnosis="d", why_it_costs="w",
        drills=[Drill(text="ставь обс на руну", metric_ref="obs_per_game")],
        progress_note="варды p1 → p3 — прогресс", generated_for_matches=[1, 2],
        focus_metric="obs_per_game", focus_value=1.0, focus_direction="higher_is_better",
    )
    again = parse_brief(brief_to_dict(b))
    assert again.focus_leak_key == "low_warding"
    assert again.focus_value == 1.0
    assert again.focus_direction == "higher_is_better"
    assert again.progress_note == "варды p1 → p3 — прогресс"
    assert again.drills[0].text == "ставь обс на руну"


def test_parse_brief_null_focus_raises():
    with pytest.raises(ValueError):
        parse_brief({"focus_leak_key": None, "drills": []})


def test_parse_brief_strips_markdown_fence():
    raw = '```json\n{"focus_leak_key": "feeding", "drills": []}\n```'
    b = parse_brief(raw)
    assert b.focus_leak_key == "feeding"
