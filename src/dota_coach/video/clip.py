from __future__ import annotations

import subprocess


def clip_window(game_time: int, offset: float, before: int = 20,
                after: int = 10) -> tuple[float, float]:
    from dota_coach.video.align import video_time_for
    center = video_time_for(game_time, offset)
    return (max(0.0, center - before), center + after)


def build_clip_command(video_path: str, start_video: float, end_video: float,
                       out_path: str, ffmpeg: str = "ffmpeg") -> list[str]:
    dur = max(0.0, end_video - start_video)
    return [
        ffmpeg, "-y",
        "-ss", f"{start_video:.3f}",   # быстрый seek: -ss перед -i
        "-i", video_path,
        "-t", f"{dur:.3f}",            # длительность окна (надёжнее -to при input-seek)
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast",
        "-vf", "scale=-2:720",
        "-an",
        "-movflags", "+faststart",
        out_path,
    ]


def extract(video: str, game_time: int, offset: float, out_path: str,
            ffmpeg: str = "ffmpeg", runner=subprocess.run) -> None:
    t0, t1 = clip_window(game_time, offset)
    cmd = build_clip_command(video, t0, t1, out_path, ffmpeg=ffmpeg)
    runner(cmd, capture_output=True, text=True)
