from __future__ import annotations


def build_clip_command(video_path: str, start_video: float, end_video: float,
                       out_path: str) -> list[str]:
    return [
        "ffmpeg", "-y",
        "-ss", f"{start_video:.3f}",
        "-to", f"{end_video:.3f}",
        "-i", video_path,
        "-c", "copy",
        out_path,
    ]
