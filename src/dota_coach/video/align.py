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


# --- авто-выравнивание 0:00 по HUD-часам: шаблоны цифр + консенсус ---

def _clock_binary(frame, box, thresh: int):
    import cv2
    if frame.ndim == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = box
    crop = frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    _, b = cv2.threshold(crop, thresh, 255, cv2.THRESH_BINARY)
    return b


def _segment_glyphs(binary, canon):
    import cv2
    import numpy as np
    on = (binary > 0).sum(axis=0) > 1        # столбцы с >1 белым пикселем (двоеточие отсеивается)
    groups = []
    s = None
    for i, v in enumerate(on):
        if v and s is None:
            s = i
        elif not v and s is not None:
            groups.append((s, i - 1))
            s = None
    if s is not None:
        groups.append((s, len(on) - 1))
    out = []
    for a, b in groups:
        sub = binary[:, a:b + 1]
        rows = np.where(sub.sum(axis=1) > 0)[0]
        if len(rows):
            sub = sub[rows[0]:rows[-1] + 1, :]
        out.append(cv2.resize(sub, tuple(canon), interpolation=cv2.INTER_NEAREST))
    return out


def load_clock_templates(assets_dir: str = "assets"):
    import json
    import os

    import cv2

    meta = json.load(open(os.path.join(assets_dir, "clock_box.json")))
    tmpls = {}
    for d in "0123456789":
        p = os.path.join(assets_dir, "clock_digits", f"{d}.png")
        if os.path.exists(p):
            tmpls[d] = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
    return tmpls, meta


def read_clock(frame, templates, meta) -> int | None:
    """HUD-часы 'MM:SS'/'M:SS' -> секунды. None, если глифов не 3..5 (ночной мусор)."""
    b = _clock_binary(frame, tuple(meta["box"]), int(meta["thresh"]))
    glyphs = _segment_glyphs(b, tuple(meta["canon"]))
    if not (3 <= len(glyphs) <= 5):
        return None
    ds = []
    for g in glyphs:
        best = max(templates, key=lambda d: (g == templates[d]).mean())
        ds.append(best)
    try:
        return int("".join(ds[:-2])) * 60 + int(ds[-2]) * 10 + int(ds[-1])
    except ValueError:
        return None


def auto_offset(read_at, coarse_seed: float, span: float = 900, step: float = 60,
                min_votes: int = 3) -> float | None:
    """offset (video-сек, где игровое 0:00) по консенсусу чтений часов. None, если нет кворума."""
    from collections import Counter
    votes: Counter = Counter()
    t = coarse_seed
    while t <= coarse_seed + span:
        g = read_at(t)
        if g is not None and g >= 0:
            votes[round(t - g)] += 1
        t += step
    if not votes:
        return None
    off, n = votes.most_common(1)[0]
    return float(off) if n >= min_votes else None
