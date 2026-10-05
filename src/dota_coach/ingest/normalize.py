from __future__ import annotations

from dota_coach.models import Match, Objective, PlayerMatch, Teamfight


def _player(raw: dict) -> PlayerMatch:
    slot = raw["player_slot"]
    return PlayerMatch(
        account_id=raw.get("account_id"),
        player_slot=slot,
        hero_id=raw.get("hero_id", 0),
        is_radiant=slot < 128,
        kills=raw.get("kills", 0),
        deaths=raw.get("deaths", 0),
        assists=raw.get("assists", 0),
        gold_per_min=raw.get("gold_per_min", 0),
        xp_per_min=raw.get("xp_per_min", 0),
        last_hits=raw.get("last_hits", 0),
        gold_t=raw.get("gold_t") or [],
        xp_t=raw.get("xp_t") or [],
        lh_t=raw.get("lh_t") or [],
        kills_log=raw.get("kills_log") or [],
        purchase_log=raw.get("purchase_log") or [],
        obs_log=raw.get("obs_log") or [],
        sen_log=raw.get("sen_log") or [],
        benchmarks=raw.get("benchmarks") or {},
        position_est=raw.get("position_est"),
        lane_role=raw.get("lane_role"),
        is_roaming=bool(raw.get("is_roaming", False)),
        lane=raw.get("lane"),
        denies=raw.get("denies", 0),
        net_worth=raw.get("net_worth", 0),
        level=raw.get("level", 0),
        hero_damage=raw.get("hero_damage", 0),
        tower_damage=raw.get("tower_damage", 0),
        killed_by=raw.get("killed_by") or {},
        # парс-зависимые счётчики — БЕЗ дефолта 0: raw.get -> None, requires исключит матч
        observer_kills=raw.get("observer_kills"),
        sentry_uses=raw.get("sentry_uses"),
        obs_placed=raw.get("obs_placed"),
        sen_placed=raw.get("sen_placed"),
        camps_stacked=raw.get("camps_stacked"),
        neutral_kills=raw.get("neutral_kills"),
        rune_pickups=raw.get("rune_pickups"),
        towers_killed=raw.get("towers_killed"),
        roshans_killed=raw.get("roshans_killed"),
        lane_efficiency_pct=raw.get("lane_efficiency_pct"),
        life_state_dead=raw.get("life_state_dead"),
        teamfight_participation=raw.get("teamfight_participation"),
        stuns=raw.get("stuns"),
        dn_t=raw.get("dn_t") or [],
        obs_left_log=raw.get("obs_left_log") or [],
        buyback_log=raw.get("buyback_log") or [],
    )


def normalize(raw: dict) -> Match:
    teamfights = [
        Teamfight(start=t["start"], end=t["end"], deaths=t.get("deaths", 0),
                  players=t.get("players") or [])
        for t in (raw.get("teamfights") or [])
    ]
    objectives = [
        Objective(time=o["time"], type=o["type"], slot=o.get("slot"), key=o.get("key"),
                  team=o.get("team"), player_slot=o.get("player_slot"), unit=o.get("unit"))
        for o in (raw.get("objectives") or [])
    ]
    return Match(
        match_id=raw["match_id"],
        duration=raw.get("duration", 0),
        radiant_win=raw.get("radiant_win", False),
        players=[_player(p) for p in raw.get("players", [])],
        teamfights=teamfights,
        objectives=objectives,
        parsed=raw.get("version") is not None,
    )
