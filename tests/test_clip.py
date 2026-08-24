from dota_coach.video.clip import build_clip_command


def test_build_clip_command_shape():
    cmd = build_clip_command("game.mp4", start_video=155.0, end_video=170.0,
                             out_path="out/clip.mp4")
    assert cmd[0] == "ffmpeg"
    assert "-i" in cmd and cmd[cmd.index("-i") + 1] == "game.mp4"
    assert "155.000" in cmd          # fast seek value
    assert cmd[-1] == "out/clip.mp4"
    # -ss must precede -i for fast seek
    assert cmd.index("-ss") < cmd.index("-i")


def test_clip_window_20_before_10_after_clamped():
    from dota_coach.video.clip import clip_window
    assert clip_window(600, offset=183) == (763.0, 793.0)   # 600+183-20 .. +10
    assert clip_window(5, offset=0, before=20, after=10) == (0.0, 15.0)  # кламп t0>=0


def test_build_clip_command_transcodes_h264_720p_no_audio():
    from dota_coach.video.clip import build_clip_command
    cmd = build_clip_command("game.mp4", 763.0, 793.0, "clips/00.mp4", ffmpeg="FF")
    assert cmd[0] == "FF"
    assert "libx264" in cmd
    assert any(a.startswith("scale=") and "720" in a for a in cmd)
    assert "-an" in cmd
    assert cmd.index("-ss") < cmd.index("-i")     # быстрый seek
