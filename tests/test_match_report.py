from dota_coach.coach.episode_card import EpisodeCard
from dota_coach.coach.episode_note import EpisodeNote
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.models import Verdict
from dota_coach.report import render_match_report


def _card(game_time):
    return EpisodeCard(game_time=game_time, verdict=Verdict.NEUTRAL, facts="",
                       numbers={}, info=None)


def _brief(game_time):
    return MomentBrief(headline="Заголовок", hypothesis="гипотеза",
                       process_question="вопрос?", checklist=["пункт"], principle="принцип",
                       game_time=game_time, verdict="neutral", event_type="death")


def _note():
    return EpisodeNote(situation="Ты был оторван от команды", takeaway="Держи ТП к союзникам")


def test_render_match_report_shows_note_and_deep_brief(tmp_path):
    cards = [_card(600), _card(1200)]
    render_match_report(1, cards, notes={600: _note()}, deep_briefs={1200: _brief(1200)},
                        clips={}, out_dir=str(tmp_path))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "10:00" in html and "20:00" in html          # оба эпизода
    assert "Ты был оторван от команды" in html          # комментарий на первом
    assert "Держи ТП к союзникам" in html
    assert "Заголовок" in html                           # полный бриф на втором
    assert "<video" not in html                          # клипов нет


def test_render_match_report_embeds_video_when_clip_present(tmp_path):
    render_match_report(1, [_card(600)], notes={600: _note()}, deep_briefs={},
                        clips={600: "clips/00.mp4"}, out_dir=str(tmp_path))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "clips/00.mp4" in html and "<video" in html
