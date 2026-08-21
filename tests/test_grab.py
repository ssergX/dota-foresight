import numpy as np
import pytest

from dota_coach.video.grab import frame_png_at


def _make_video(path, fps=30, secs=3, w=160, h=90):
    import cv2

    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    if not vw.isOpened():
        pytest.skip("нет MJPG-кодека для синтетического видео")
    per_sec = [(0, 0, 255), (0, 255, 0), (255, 0, 0)]  # BGR: сек0 красный, сек1 зелёный, сек2 синий
    for i in range(fps * secs):
        frame = np.full((h, w, 3), per_sec[(i // fps) % 3], dtype=np.uint8)
        vw.write(frame)
    vw.release()


def test_frame_png_at_returns_valid_png(tmp_path):
    import cv2

    vid = tmp_path / "rec.avi"
    _make_video(vid)
    png = frame_png_at(str(vid), 1.5)
    assert isinstance(png, (bytes, bytearray)) and len(png) > 0
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape[0] == 90 and img.shape[1] == 160


def test_frame_png_at_bad_path_raises(tmp_path):
    with pytest.raises(Exception):
        frame_png_at(str(tmp_path / "nope.avi"), 1.0)
