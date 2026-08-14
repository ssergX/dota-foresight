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
