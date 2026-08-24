from dota_coach.coach.episode_card import EpisodeCard
from dota_coach.coach.moment_brief import MomentBrief
from dota_coach.models import Verdict
from dota_coach.report import render_match_report


def _card(game_time, facts="HP 100/100"):
    return EpisodeCard(game_time=game_time, verdict=Verdict.NEUTRAL, facts=facts,
                       numbers={"my_deaths": 1}, info=None)


def _brief(game_time):
    return MomentBrief(headline="Заголовок", hypothesis="гипотеза",
                       process_question="вопрос?", checklist=["пункт"], principle="принцип",
                       game_time=game_time, verdict="neutral", event_type="death")


def test_render_match_report_writes_index_with_cards_and_deep(tmp_path):
    cards = [_card(600), _card(1200)]
    render_match_report(1, cards, deep_briefs={600: _brief(600)}, clips={}, out_dir=str(tmp_path))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "10:00" in html and "20:00" in html      # оба эпизода
    assert "Заголовок" in html                       # блок брифа на deep-эпизоде
    assert "<video" not in html                      # клипов нет


def test_render_match_report_embeds_video_when_clip_present(tmp_path):
    render_match_report(1, [_card(600)], deep_briefs={}, clips={600: "clips/00.mp4"},
                        out_dir=str(tmp_path))
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "clips/00.mp4" in html and "<video" in html
