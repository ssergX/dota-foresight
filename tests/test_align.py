import pytest

from dota_coach.models import ClockRead
from dota_coach.video.align import compute_offset, sample_clock_reads, video_time_for


def test_compute_offset_is_median_of_video_minus_game():
    reads = [ClockRead(t_video=100.0, t_game=40),
             ClockRead(t_video=160.0, t_game=100),
             ClockRead(t_video=600.0, t_game=540)]
    # offsets: 60, 60, 60
    assert compute_offset(reads) == 60.0


def test_compute_offset_robust_to_one_bad_read():
    reads = [ClockRead(t_video=100.0, t_game=40),
             ClockRead(t_video=160.0, t_game=100),
             ClockRead(t_video=999.0, t_game=100)]  # outlier
    # offsets: 60, 60, 899 -> median 60
    assert compute_offset(reads) == 60.0


def test_compute_offset_empty_raises():
    with pytest.raises(ValueError):
        compute_offset([])


def test_video_time_for_clamps_to_zero():
    assert video_time_for(game_time=100, offset=60.0) == 160.0
    assert video_time_for(game_time=10, offset=-50.0) == 0.0


def test_sample_clock_reads_skips_none_ocr():
    frames = {0.0: "f0", 30.0: "f30", 60.0: "f60"}
    ocr_map = {"f0": 0, "f30": None, "f60": 60}
    reads = sample_clock_reads(
        sample_times=[0.0, 30.0, 60.0],
        frame_at=lambda t: frames[t],
        ocr=lambda f: ocr_map[f],
        crop=lambda f: f,
    )
    assert [r.t_game for r in reads] == [0, 60]
    assert [r.t_video for r in reads] == [0.0, 60.0]
