"""Извлечение одного кадра из записи игры в заданный момент видео-времени (OpenCV)."""
from __future__ import annotations


def frame_png_at(video_path: str, t: float) -> bytes:
    """Кадр видео на секунде t -> PNG-байты. cv2 импортируется лениво (тяжёлая зависимость)."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"не удалось открыть видео: {video_path}")
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(f"не удалось прочитать кадр на {t:.1f}s")
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError("не удалось закодировать кадр в PNG")
        return buf.tobytes()
    finally:
        cap.release()
