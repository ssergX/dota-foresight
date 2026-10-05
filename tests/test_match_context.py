from dota_coach.ingest.normalize import normalize
from dota_coach.models import Match, ParsedReplay, PlayerMatch, ReplayFrame, UnitState


def _players_with_gold(gold_by_slot: dict[int, list[int]]) -> list[PlayerMatch]:
    out = []
    for slot, gt in gold_by_slot.items():
        out.append(PlayerMatch(
            account_id=slot, player_slot=slot, hero_id=1, is_radiant=slot < 128,
            kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
            gold_t=gt, xp_t=[0] * len(gt),
            purchase_log=[]))
    return out


def _match(players, objectives=None):
    return Match(match_id=1, duration=1800, radiant_win=False, players=players,
                 teamfights=[], objectives=objectives or [])


# --- A1: Objective должен сохранять team (для стороны Рошана/аегиса) ---

def test_normalize_keeps_objective_team_and_unit():
    raw = {"match_id": 1, "players": [], "objectives": [
        {"time": 1852, "type": "CHAT_MESSAGE_ROSHAN_KILL", "team": 3},
        {"time": 693, "type": "building_kill", "key": "npc_dota_goodguys_tower1_top",
         "unit": "npc_dota_hero_grimstroke", "slot": 2, "player_slot": 2},
    ]}
    m = normalize(raw)
    rosh = m.objectives[0]
    assert rosh.team == 3
    tower = m.objectives[1]
    assert tower.unit == "npc_dota_hero_grimstroke" and tower.player_slot == 2


# --- A2: экономика ---

def test_networth_lead_is_my_team_minus_enemy_at_minute():
    from dota_coach.coach.match_context import match_context_at
    # minute 2 (T=120..): radiant slots 0-4, dire 128-132
    gold = {0: [0, 1000, 2000], 1: [0, 1000, 2000], 2: [0, 1000, 2000],
            3: [0, 1000, 2000], 4: [0, 1000, 2000],
            128: [0, 500, 1000], 129: [0, 500, 1000], 130: [0, 500, 1000],
            131: [0, 500, 1000], 132: [0, 500, 1000]}
    players = _players_with_gold(gold)
    me = players[1]   # radiant
    ctx = match_context_at(_match(players), me, None, t=120)
    assert ctx.nw_lead == 5 * 2000 - 5 * 1000   # +5000 впереди


# --- A2: ключевые предметы по purchase_log с whitelist ---

def test_key_items_owned_by_T_filters_noise():
    from dota_coach.coach.match_context import match_context_at
    me = PlayerMatch(account_id=1, player_slot=1, hero_id=1, is_radiant=True,
                     kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
                     gold_t=[0, 0, 0], xp_t=[0, 0, 0],
                     purchase_log=[{"time": -80, "key": "tango"}, {"time": 200, "key": "boots"},
                                   {"time": 1000, "key": "black_king_bar"},
                                   {"time": 1500, "key": "blink"}])
    ctx = match_context_at(_match([me]), me, None, t=1200)
    assert "BKB" in ctx.my_key_items          # bkb куплен к 1200
    assert "Blink" not in ctx.my_key_items    # blink ещё не куплен
    assert all("tango" != x.lower() for x in ctx.my_key_items)   # расходники отфильтрованы


# --- A2: день/ночь из времени ---

def test_day_night_from_clock():
    from dota_coach.coach.match_context import match_context_at
    me = PlayerMatch(account_id=1, player_slot=1, hero_id=1, is_radiant=True,
                     kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
                     gold_t=[0], xp_t=[0], purchase_log=[])
    assert match_context_at(_match([me]), me, None, t=100).is_night is False   # [0,300) день
    assert match_context_at(_match([me]), me, None, t=400).is_night is True    # [300,600) ночь


# --- A2: павшие вышки по сторонам из objectives ---

def test_towers_lost_by_side_from_objectives():
    from dota_coach.coach.match_context import match_context_at
    from dota_coach.models import Objective
    objs = [
        Objective(time=100, type="building_kill", key="npc_dota_goodguys_tower1_top"),
        Objective(time=200, type="building_kill", key="npc_dota_goodguys_tower1_mid"),
        Objective(time=300, type="building_kill", key="npc_dota_badguys_tower1_top"),
        Objective(time=9999, type="building_kill", key="npc_dota_goodguys_tower2_top"),
    ]
    me = PlayerMatch(account_id=1, player_slot=1, hero_id=1, is_radiant=True,
                     kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
                     gold_t=[0], xp_t=[0], purchase_log=[])
    ctx = match_context_at(_match([me], objs), me, None, t=500)
    assert ctx.radiant_towers_lost == 2    # два goodguys до T=500
    assert ctx.dire_towers_lost == 1       # один badguys


# --- A2: аегис в окне 300с, сторона относительно игрока ---

def test_aegis_side_within_window():
    from dota_coach.coach.match_context import match_context_at
    from dota_coach.models import Objective
    objs = [Objective(time=1850, type="CHAT_MESSAGE_AEGIS", slot=9, player_slot=132)]  # Dire
    me = PlayerMatch(account_id=1, player_slot=1, hero_id=1, is_radiant=True,   # Radiant
                     kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
                     gold_t=[0], xp_t=[0], purchase_log=[])
    assert match_context_at(_match([me], objs), me, None, t=2000).aegis_side == "вражеская"
    assert match_context_at(_match([me], objs), me, None, t=2200).aegis_side is None  # >300с протух


# --- A2: уровни из реплея ---

def test_levels_from_replay():
    from dota_coach.coach.match_context import match_context_at
    me = PlayerMatch(account_id=1, player_slot=1, hero_id=1, is_radiant=True,
                     kills=0, deaths=0, assists=0, gold_per_min=0, xp_per_min=0, last_hits=0,
                     gold_t=[0], xp_t=[0], purchase_log=[])

    def u(slot, lvl):
        return UnitState(slot=slot, x=0, y=0, hp=100, max_hp=100, mana=0, level=lvl, xp=0, alive=True)
    frame = ReplayFrame(time=600, units={1: u(1, 15), 6: u(6, 10), 7: u(7, 12), 8: u(8, 14)})
    parsed = ParsedReplay(match_id=1, game_start_time=0, heroes={}, frames=[frame],
                          teams={1: 2, 6: 3, 7: 3, 8: 3})
    ctx = match_context_at(_match([me]), me, parsed, t=600)
    assert ctx.my_level == 15
    assert ctx.enemy_avg_level == 12.0   # (10+12+14)/3


# --- A2: рендер факт-строки без утечки исхода ---

def test_render_match_context_no_outcome():
    from dota_coach.coach.match_context import match_context_at, render_match_context
    gold = {1: [0, 2000], 128: [0, 1000]}
    players = _players_with_gold(gold)
    txt = render_match_context(match_context_at(_match(players), players[0], None, t=60)).lower()
    assert "нетворс" in txt
    for banned in ("победа", "поражени", "выигр", "проигр", "radiant_win"):
        assert banned not in txt
