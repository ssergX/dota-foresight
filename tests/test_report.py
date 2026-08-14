from dota_coach.models import (
    Confidence, EventCandidate, EventType, Leak, ScoredMoment, Verdict,
)
from dota_coach.report import render_report


def _moment(t, summary, verdict=Verdict.NEUTRAL):
    ev = EventCandidate(type=EventType.TEAMFIGHT, game_time=t, involves_me=True,
                        summary=summary, data={})
    return ScoredMoment(event=ev, score=9.0, confidence=Confidence.LOW,
                        verdict=verdict, reasons=["ты вовлечён"])


def test_report_contains_moment_and_seek_time():
    moments = [_moment(100, "тимфайт 1:40")]
    html = render_report(8001, moments, leaks=[], video_filename="game.mp4", offset=60.0)
    assert "тимфайт 1:40" in html
    assert "game.mp4" in html
    assert "160" in html            # video_time_for(100, 60) = 160.0 seek target
    assert "8001" in html


def test_report_lists_leaks():
    leak = Leak(key="feeding", title="Слишком много смертей",
                magnitude="в среднем 11.0 смертей за игру", example_matches=[1, 2],
                confidence=Confidence.HIGH)
    html = render_report(8001, moments=[], leaks=[leak], video_filename=None, offset=0.0)
    assert "Слишком много смертей" in html
    assert "в среднем 11.0" in html


def test_report_without_video_has_no_video_tag():
    html = render_report(8001, moments=[_moment(50, "x")], leaks=[],
                         video_filename=None, offset=0.0)
    assert "<video" not in html


def test_report_escapes_html_special_chars():
    moments = [_moment(100, "<b>drama</b> & risk")]
    leak = Leak(key="x", title="<script>alert(1)</script>", magnitude="a & b",
                example_matches=[1], confidence=Confidence.HIGH)
    html = render_report(8001, moments, leaks=[leak], video_filename=None, offset=0.0)
    # raw HTML-special content must NOT appear unescaped
    assert "<b>drama</b>" not in html
    assert "<script>alert(1)</script>" not in html
    # escaped forms MUST appear
    assert "&lt;b&gt;drama&lt;/b&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_report_without_video_has_no_seek_button_or_script():
    html = render_report(8001, moments=[_moment(50, "x")], leaks=[],
                         video_filename=None, offset=0.0)
    assert "<button" not in html          # CSS rule is 'button{', not '<button'
    assert 'onclick="seek(' not in html
    assert "<script" not in html
