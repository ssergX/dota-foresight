from dota_coach.models import EventType, Match, Objective, PlayerMatch, Teamfight


def _me(kills_log=None, purchase_log=None, gold_t=None):
    return PlayerMatch(account_id=7, player_slot=1, hero_id=1, is_radiant=True,
                       kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
                       gold_t=gold_t or [0, 100], xp_t=[0] * len(gold_t or [0, 100]),
                       kills_log=kills_log or [], purchase_log=purchase_log or [])


def _match(me, objectives=None, teamfights=None):
    return Match(match_id=1, duration=3600, radiant_win=False, players=[me],
                 teamfights=teamfights or [], objectives=objectives or [])


def test_pickoff_events_exclude_teamfight_kills():
    from dota_coach.episodes import _pickoff_events
    me = _me(kills_log=[{"time": 278, "key": "npc_dota_hero_phantom_lancer"},
                        {"time": 1080, "key": "npc_dota_hero_windrunner"}])
    tfs = [Teamfight(start=1065, end=1104, deaths=3)]
    evs = _pickoff_events(me, tfs)
    assert [e.game_time for e in evs] == [278]            # 1080 внутри драки свёрнут
    assert evs[0].type == EventType.PICKOFF
    assert evs[0].involves_me is True


def test_build_episodes_includes_pickoff_and_my_objective():
    from dota_coach.episodes import build_episodes
    me = _me(kills_log=[{"time": 300, "key": "npc_dota_hero_pudge"}])
    objs = [Objective(time=700, type="building_kill", key="npc_dota_badguys_tower1_mid",
                      slot=1, player_slot=1, unit="npc_dota_hero_windrunner")]
    eps = build_episodes(_match(me, objectives=objs), None, account_id=7)
    kinds = {e.moment.event.type for e in eps}
    assert EventType.PICKOFF in kinds
    assert EventType.OBJECTIVE in kinds


def test_objective_building_kill_has_readable_summary():
    from dota_coach.events import extract_events
    me = _me()
    objs = [Objective(time=700, type="building_kill", key="npc_dota_badguys_tower2_mid",
                      slot=1, player_slot=1)]
    ev = next(e for e in extract_events(_match(me, objectives=objs), 7)
              if e.type == EventType.OBJECTIVE)
    assert "вышк" in ev.summary.lower()                   # не сырое "building_kill"


def test_enemy_objective_not_my_episode():
    from dota_coach.episodes import build_episodes
    # вражеский снос (slot не мой) не должен становиться моим эпизодом
    objs = [Objective(time=700, type="building_kill", key="npc_dota_goodguys_tower1_mid",
                      slot=9, player_slot=132)]
    eps = build_episodes(_match(_me(), objectives=objs), None, account_id=7)
    assert all(e.moment.event.type != EventType.OBJECTIVE for e in eps)


def test_build_episodes_caps_total_count():
    from dota_coach.episodes import build_episodes
    kl = [{"time": 100 + i * 30, "key": "npc_dota_hero_pudge"} for i in range(40)]
    eps = build_episodes(_match(_me(kills_log=kl)), None, account_id=7)
    assert len(eps) <= 25                                 # не заваливаем 40 эпизодами
