from __future__ import annotations

import glob
import os
import re
import subprocess


def pick_session(sessions: list[dict], start_epoch: float, end_epoch: float) -> dict | None:
    """Выбрать сессию, чей ретейн-интервал покрывает окно [start_epoch, end_epoch]."""
    for s in sessions:
        lo = s["avail"] + s["rec_lo"]
        hi = s["avail"] + s["rec_hi"]
        if lo <= start_epoch and end_epoch <= hi:
            return s
    return None


def _avail_epoch(mpd_text: str) -> int | None:
    m = re.search(r'availabilityStartTime="([^"]+)"', mpd_text)
    if not m:
        return None
    import datetime
    dt = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%SZ")
    return int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())


def _scan_sessions(gamerecordings_dir: str) -> list[dict]:
    out: list[dict] = []
    video_dir = os.path.join(gamerecordings_dir, "video")
    for d in glob.glob(os.path.join(video_dir, "bg_570_*")):
        mpd = os.path.join(d, "session.mpd")
        chunks = glob.glob(os.path.join(d, "chunk-stream0-*.m4s"))
        if not os.path.exists(mpd) or not chunks:
            continue
        avail = _avail_epoch(open(mpd, encoding="utf-8", errors="replace").read())
        if avail is None:      # завершённая (type=static) сессия без availabilityStartTime
            continue
        nums = [int(re.search(r"-(\d+)\.m4s", c).group(1)) for c in chunks]
        out.append({"name": d, "avail": avail,
                    "rec_lo": (min(nums) - 1) * 3, "rec_hi": max(nums) * 3})
    return out


def find_session(start_time: int, duration: int,
                 gamerecordings_dir: str) -> tuple[str, int] | None:
    sessions = _scan_sessions(gamerecordings_dir)
    s = pick_session(sessions, start_epoch=start_time, end_epoch=start_time + duration)
    return (s["name"], s["avail"]) if s else None


def chunk_range(avail_epoch: float, rec_start_s: float, rec_end_s: float) -> tuple[int, int]:
    # чанк N покрывает rec-секунды [(N-1)*3, N*3): первый = содержащий rec_start,
    # последний = заканчивающийся <= rec_end (== rec_end//3).
    n0 = max(1, int(rec_start_s // 3) + 1)
    n1 = int(rec_end_s // 3)
    return (n0, n1)


def stitch_window(session_dir: str, avail_epoch: float, start_epoch: float,
                  end_epoch: float, out_mp4: str, ffmpeg: str,
                  runner=subprocess.run) -> None:
    rec_start = start_epoch - avail_epoch - 90   # запас 90с до гудка
    rec_end = end_epoch - avail_epoch + 60
    n0, n1 = chunk_range(avail_epoch, max(0, rec_start), rec_end)
    files = [os.path.join(session_dir, "init-stream0.m4s")]
    for n in range(n0, n1 + 1):
        p = os.path.join(session_dir, f"chunk-stream0-{n:05d}.m4s")
        if os.path.exists(p):
            files.append(p)
    concat = out_mp4 + ".concat"
    with open(concat, "wb") as out:
        for p in files:
            with open(p, "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""):
                    out.write(b)
    runner([ffmpeg, "-y", "-fflags", "+genpts", "-i", concat, "-c", "copy",
            "-movflags", "+faststart", out_mp4], capture_output=True, text=True)
    os.remove(concat)
