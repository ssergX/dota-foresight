import json

import pytest

from dota_coach.coach.moment_brief import MomentBrief, parse_moment_brief


def test_parse_valid_json():
    raw = json.dumps({"headline": "h", "hypothesis": "вероятно X", "process_question": "q",
                      "checklist": ["a", "b"], "principle": "p"})
    b = parse_moment_brief(raw)
    assert b.headline == "h" and b.hypothesis == "вероятно X"
    assert b.checklist == ["a", "b"] and b.principle == "p"
    assert b.game_time == 0 and b.verdict == "" and b.event_type == ""   # код проставит позже


def test_parse_strips_code_fence():
    raw = '```json\n{"headline":"h","hypothesis":"g","process_question":"q","checklist":[],"principle":"p"}\n```'
    assert parse_moment_brief(raw).headline == "h"


def test_parse_rejects_non_object():
    with pytest.raises(ValueError):
        parse_moment_brief("[1, 2, 3]")


def test_parse_rejects_non_list_checklist():
    with pytest.raises(ValueError):
        parse_moment_brief(json.dumps({"headline": "h", "checklist": "nope"}))
