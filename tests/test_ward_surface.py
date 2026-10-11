from dataclasses import replace
from dota_coach.models import ParsedReplay, WardEvent
from dota_coach.wards import active_wards, ward_instances, render_ward_map


def replay(events):
    return ParsedReplay(1, 0, {}, [], wards=events)


def test_prefix_generation_and_pregame():
    events = [WardEvent(7, -10, "obs", 2, 0, 0, "placed", 0),
              WardEvent(7, 20, "obs", 2, None, None, "gone", 0)]
    parsed = replay(events)
    before = ward_instances(parsed, 10)
    future = replace(parsed, wards=events + [WardEvent(7, 30, "sentry", 3, 9000, 9000, "placed", 1)])
    assert ward_instances(future, 10) == before
    assert before[0].observed_lifetime is None
    assert active_wards(parsed, 10)[0].placed_at == -10
    assert not active_wards(parsed, 20)
    assert ward_instances(parsed, 20)[0].observed_lifetime == 30
    assert active_wards(future, 31)[0].generation == 1


def test_removal_without_placement_never_origin():
    w = ward_instances(replay([WardEvent(4, 10, "obs", None, 0, 0, "gone")]), 10)[0]
    assert w.placed_at is None and w.x is None and w.y is None
    assert w.observed_lifetime is None


def test_conflicting_lifecycle_not_active_and_html_safe():
    p = replay([WardEvent(4, 0, "</script><img>", 2, 0, 0, "placed"),
                WardEvent(4, 1, "obs", 2, 0, 0, "placed")])
    assert not active_wards(p, 2)
    rendered = render_ward_map(p)
    assert "</script><img>" not in rendered
    assert "\\u003c/script>" in rendered
    assert "ward-time" in rendered and "полезность не подтверждены" in rendered
    p = replace(p, wards=p.wards + [WardEvent(4, 2, "obs", 2, None, None, "gone")])
    w = ward_instances(p, 2)[0]
    assert w.status == "conflicting_lifecycle" and w.observed_lifetime is None
