from dota_coach.video.steam_recording import chunk_range, pick_session


def _sess(avail_epoch, lo_chunk, hi_chunk, name):
    # ретейн-интервал = [avail+(lo-1)*3, avail+hi*3]
    return {"name": name, "avail": avail_epoch,
            "rec_lo": (lo_chunk - 1) * 3, "rec_hi": hi_chunk * 3}


def test_pick_session_covering_match_window():
    sessions = [
        _sess(avail_epoch=1000, lo_chunk=1, hi_chunk=100, name="early"),     # 1000..1300
        _sess(avail_epoch=1000, lo_chunk=3737, hi_chunk=6136, name="late"),  # 12208..19408
    ]
    # окно матча в rec-секундах late-сессии: 12838..14937
    got = pick_session(sessions, start_epoch=1000 + 12838, end_epoch=1000 + 14937)
    assert got["name"] == "late"


def test_pick_session_none_when_uncovered():
    sessions = [_sess(1000, 1, 100, "early")]
    assert pick_session(sessions, start_epoch=1000 + 5000, end_epoch=1000 + 6000) is None


def test_chunk_range_from_rec_seconds():
    # rec 12747..15300 -> chunk floor/3+1
    assert chunk_range(0, 12747, 15300) == (4250, 5100)
    assert chunk_range(0, 0, 9) == (1, 3)
