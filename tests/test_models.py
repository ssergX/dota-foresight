from dota_coach.models import Match, PlayerMatch, EventType, EventCandidate, Confidence, Verdict, Leak


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


def test_playermatch_new_fields_have_safe_defaults():
    p = PlayerMatch(account_id=1, player_slot=0, hero_id=1, is_radiant=True,
                    kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0)
    # парс-зависимые (в т.ч. счётчики вижна/леса) отсутствуют -> None (не 0),
    # чтобы requires исключил непропарсенный матч (инвариант «никогда не нолить»)
    assert p.position_est is None
    assert p.lane_efficiency_pct is None
    assert p.life_state_dead is None
    assert p.teamfight_participation is None
    assert p.obs_placed is None
    assert p.sen_placed is None
    assert p.camps_stacked is None
    assert p.neutral_kills is None
    assert p.observer_kills is None
    # всегда-присутствующие базовые числа -> 0 / пустые
    assert p.denies == 0
    assert p.hero_damage == 0
    assert p.killed_by == {}
    assert p.obs_left_log == []


def test_leak_new_fields_defaults():
    l = Leak(key="k", title="t", magnitude="m")
    assert l.role is None
    assert l.source == "manual"
    assert l.sample_size == 0
    assert l.considered == 0
    assert l.severity == 0.0
    assert l.phase == ""
    assert l.family == ""
