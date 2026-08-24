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


# --- read_clock (шаблоны цифр) + auto_offset (консенсус) ---

def _canon_templates():
    import numpy as np
    # 10 различимых глифов 20x14: верх/низ белые (bbox на всю высоту -> resize=identity),
    # цифра d кодируется высотой центрального блока
    t = {}
    for d in range(10):
        g = np.zeros((20, 14), dtype=np.uint8)
        g[0, :] = 255
        g[19, :] = 255
        g[2:3 + d, 3:11] = 255
        t[str(d)] = g
    return t


def _compose(digits):
    import numpy as np
    t = _canon_templates()
    gap = np.zeros((20, 2), dtype=np.uint8)
    parts = []
    for i, d in enumerate(digits):
        if i:
            parts.append(gap)
        parts.append(t[d])
    return np.concatenate(parts, axis=1)


_CLOCK_META = {"box": [0.0, 0.0, 1.0, 1.0], "thresh": 1, "canon": [14, 20]}


def test_read_clock_reads_mmss():
    from dota_coach.video.align import read_clock
    assert read_clock(_compose("1000"), _canon_templates(), _CLOCK_META) == 600   # 10:00


def test_read_clock_reads_mss():
    from dota_coach.video.align import read_clock
    assert read_clock(_compose("758"), _canon_templates(), _CLOCK_META) == 478    # 7:58


def test_read_clock_none_when_too_few_glyphs():
    from dota_coach.video.align import read_clock
    assert read_clock(_compose("55"), _canon_templates(), _CLOCK_META) is None    # 2 глифа


def test_auto_offset_solves_constant_offset_by_consensus():
    from dota_coach.video.align import auto_offset
    OFFSET = 183.0

    def read_at(t):
        g = int(t - OFFSET)
        return g if g >= 0 else None

    got = auto_offset(read_at, coarse_seed=120.0, span=300, step=20)
    assert abs(got - OFFSET) <= 1.0


def test_auto_offset_none_when_unreadable():
    from dota_coach.video.align import auto_offset
    assert auto_offset(lambda t: None, coarse_seed=0.0) is None
