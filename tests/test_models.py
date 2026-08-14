from dota_coach.models import Match, PlayerMatch, EventType, EventCandidate, Confidence, Verdict


def _player(account_id, slot):
    return PlayerMatch(
        account_id=account_id, player_slot=slot, hero_id=1, is_radiant=slot < 128,
        kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
        gold_t=[], xp_t=[], lh_t=[], kills_log=[], purchase_log=[], obs_log=[], sen_log=[],
        benchmarks={},
    )


def test_player_by_account_returns_matching_player():
    m = Match(match_id=1, duration=100, radiant_win=True,
              players=[_player(111, 0), _player(222, 128)],
              teamfights=[], objectives=[], parsed=True)
    assert m.player_by_account(222).player_slot == 128
    assert m.player_by_account(999) is None


def test_event_candidate_holds_signals():
    ev = EventCandidate(type=EventType.DEATH, game_time=842, involves_me=True,
                        summary="умер первым", data={"teamfight": True})
    assert ev.type == EventType.DEATH
    assert ev.data["teamfight"] is True
