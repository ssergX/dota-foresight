import dota_coach.cli as cli
from dota_coach.episodes import Episode
from dota_coach.coach.match_review import MatchReview
from dota_coach.models import Confidence, EventCandidate, EventType, ScoredMoment, Verdict


class _Args:
    def __init__(self, out, video="game.mp4", video_offset=183.0):
        self.video = video
        self.video_offset = video_offset
        self.gamerecordings = None
        self.out = out


def _episode(gt):
    ev = EventCandidate(type=EventType.DEATH, game_time=gt, involves_me=True, summary="", data={})
    m = ScoredMoment(event=ev, score=5.0, confidence=Confidence.LOW, verdict=Verdict.NEUTRAL)
    return Episode(moment=m, severity=5.0)


def test_build_clips_extracts_per_episode(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "clip_extract",
                        lambda video, gt, off, out, ffmpeg: calls.append((gt, out)))
    review = MatchReview(episodes=[_episode(600), _episode(1200)], cards=[], deep_briefs={})
    clips = cli._build_clips(_Args(str(tmp_path)), review, start_time=None, duration=1800)
    assert clips == {600: "clips/00.mp4", 1200: "clips/01.mp4"}
    assert [c[0] for c in calls] == [600, 1200]


def test_build_clips_empty_when_offset_unresolved(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_resolve_offset", lambda args, video: None)
    review = MatchReview(episodes=[_episode(600)], cards=[], deep_briefs={})
    args = _Args(str(tmp_path), video_offset=None)
    assert cli._build_clips(args, review, start_time=None, duration=1800) == {}


def test_build_clips_empty_without_video(tmp_path):
    review = MatchReview(episodes=[_episode(600)], cards=[], deep_briefs={})
    args = _Args(str(tmp_path), video=None)
    assert cli._build_clips(args, review, start_time=None, duration=1800) == {}
