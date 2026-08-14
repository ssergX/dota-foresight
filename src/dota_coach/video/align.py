from __future__ import annotations

from statistics import median
from typing import Callable

from dota_coach.models import ClockRead


def compute_offset(reads: list[ClockRead]) -> float:
    if not reads:
        raise ValueError("need at least one ClockRead to compute offset")
    return median(r.t_video - r.t_game for r in reads)


def video_time_for(game_time: int, offset: float) -> float:
    return max(0.0, game_time + offset)


def sample_clock_reads(
    sample_times: list[float],
    frame_at: Callable[[float], object],
    ocr: Callable[[object], int | None],
    crop: Callable[[object], object],
) -> list[ClockRead]:
    reads: list[ClockRead] = []
    for t in sample_times:
        game = ocr(crop(frame_at(t)))
        if game is not None:
            reads.append(ClockRead(t_video=t, t_game=game))
    return reads


def opencv_frame_at(video_path: str) -> Callable[[float], object]:
    """Return frame_at(t) that grabs a BGR frame at second t via OpenCV."""
    import cv2

    cap = cv2.VideoCapture(video_path)

    def frame_at(t: float):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"cannot read frame at {t}s from {video_path}")
        return frame

    return frame_at


def crop_hud_clock(frame, box=(0.46, 0.0, 0.54, 0.04)):
    """Crop the top-center HUD clock. box = (x0,y0,x1,y1) as fractions of w/h."""
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    return frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def tesseract_clock_ocr(frame) -> int | None:
    """OCR a 'MM:SS' clock crop -> seconds, or None if unreadable."""
    import pytesseract

    text = pytesseract.image_to_string(
        frame, config="--psm 7 -c tessedit_char_whitelist=0123456789:"
    ).strip()
    if ":" not in text:
        return None
    mm, _, ss = text.partition(":")
    if not (mm.isdigit() and ss.isdigit()):
        return None
    return int(mm) * 60 + int(ss)
