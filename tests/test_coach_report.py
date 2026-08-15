from dota_coach.coach.brief import CoachBrief, Drill
from dota_coach.models import Confidence, Leak
from dota_coach.report import render_coach_html


def _leak():
    return Leak(key="low_warding", title="Мало вардов",
                magnitude="в среднем 1.0 обс-вардов за игру (порог 4)",
                example_matches=[1, 2], confidence=Confidence.HIGH,
                metric="obs_per_game", value=1.0, threshold=4.0, direction="higher_is_better")


def _brief():
    return CoachBrief(
        focus_leak_key="low_warding", headline="Тебя топит вижн",
        diagnosis="варды в p1", why_it_costs="нет информации — лишние смерти",
        drills=[Drill(text="ставь обс на руну", metric_ref="obs_per_game")],
        progress_note="варды p1 → p3 — прогресс",
        focus_metric="obs_per_game", focus_value=1.0, focus_direction="higher_is_better",
    )


def test_coach_report_shows_headline_drills_and_progress():
    html = render_coach_html(_brief(), [_leak()])
    assert "Тебя топит вижн" in html
    assert "ставь обс на руну" in html
    assert "варды p1 → p3 — прогресс" in html
    assert "Мало вардов" in html


def test_coach_report_escapes_html():
    brief = _brief()
    brief.headline = "<script>alert(1)</script>"
    html = render_coach_html(brief, [_leak()])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_coach_report_no_leaks_message():
    empty = CoachBrief(focus_leak_key="", headline="Системных ликов по этой серии не найдено",
                       diagnosis="", why_it_costs="", drills=[])
    html = render_coach_html(empty, [])
    assert "не найдено" in html
    assert "<script>" not in html  # без инъекций
