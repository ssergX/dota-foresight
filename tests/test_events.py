import json
from pathlib import Path

from dota_coach.events import extract_events
from dota_coach.ingest.normalize import normalize
from dota_coach.models import EventType

FIXTURE = Path(__file__).parent / "fixtures" / "opendota_match_sample.json"


def _match():
    return normalize(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_extract_events_finds_teamfight_objective_item_ward():
    events = extract_events(_match(), account_id=111)
    types = {e.type for e in events}
    assert EventType.TEAMFIGHT in types
    assert EventType.OBJECTIVE in types
    assert EventType.ITEM_TIMING in types
    assert EventType.WARD in types


def test_teamfight_event_marks_my_involvement_and_time():
    events = extract_events(_match(), account_id=111)
    tf = next(e for e in events if e.type == EventType.TEAMFIGHT)
    assert tf.game_time == 820           # teamfight start
    assert tf.involves_me is True        # my slot index 0 had deaths=1
    assert tf.data["my_gold_delta"] == -400


def test_networth_swing_emitted_for_sharp_drop():
    # my gold_t = [0,300,900,1500]; deltas per min = [300,600,600] -> no drop.
    # Force a drop to assert the rule triggers.
    m = _match()
    me = m.player_by_account(111)
    object.__setattr__(me, "gold_t", [0, 1000, 400, 900])  # min2->min3 drop of 600
    events = extract_events(m, account_id=111)
    swings = [e for e in events if e.type == EventType.NETWORTH_SWING]
    assert any(e.data["delta"] <= -500 for e in swings)


def test_extract_events_empty_when_account_absent():
    assert extract_events(_match(), account_id=999) == []


def test_objective_not_involving_me_when_slot_none():
    events = extract_events(_match(), account_id=111)
    roshan = next(
        e for e in events
        if e.type == EventType.OBJECTIVE and e.data["objective_type"] == "CHAT_MESSAGE_ROSHAN_KILL"
    )
    assert roshan.involves_me is False
