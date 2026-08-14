from __future__ import annotations

from dota_coach.models import EventCandidate, EventType, Match, PlayerMatch

_NETWORTH_DROP = -500  # gold drop within one minute flagged as a swing


def _my_index(match: Match, me: PlayerMatch) -> int:
    return match.players.index(me)


def _teamfight_events(match: Match, me: PlayerMatch) -> list[EventCandidate]:
    idx = _my_index(match, me)
    out: list[EventCandidate] = []
    for tf in match.teamfights:
        mine = tf.players[idx] if idx < len(tf.players) else {}
        involves = bool(mine.get("deaths", 0)) or bool(mine.get("damage", 0))
        out.append(EventCandidate(
            type=EventType.TEAMFIGHT, game_time=tf.start, involves_me=involves,
            summary=f"тимфайт {tf.start // 60}:{tf.start % 60:02d}, погибло {tf.deaths}",
            data={
                "deaths": tf.deaths,
                "my_deaths": mine.get("deaths", 0),
                "my_gold_delta": mine.get("gold_delta", 0),
                "my_xp_delta": mine.get("xp_delta", 0),
                "my_damage": mine.get("damage", 0),
            },
        ))
    return out


def _objective_events(match: Match, me: PlayerMatch) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for o in match.objectives:
        out.append(EventCandidate(
            type=EventType.OBJECTIVE, game_time=o.time,
            involves_me=(o.slot is not None and o.slot == me.player_slot),
            summary=f"{o.type} на {o.time // 60}:{o.time % 60:02d}",
            data={"objective_type": o.type},
        ))
    return out


def _networth_swings(me: PlayerMatch) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for minute in range(1, len(me.gold_t)):
        delta = me.gold_t[minute] - me.gold_t[minute - 1]
        if delta <= _NETWORTH_DROP:
            t = minute * 60
            out.append(EventCandidate(
                type=EventType.NETWORTH_SWING, game_time=t, involves_me=True,
                summary=f"просадка нетворса {delta} на {minute}-й минуте",
                data={"delta": delta},
            ))
    return out


def _item_events(me: PlayerMatch) -> list[EventCandidate]:
    return [
        EventCandidate(
            type=EventType.ITEM_TIMING, game_time=p["time"], involves_me=True,
            summary=f"куплен {p['key']} на {p['time'] // 60}:{p['time'] % 60:02d}",
            data={"item": p["key"]},
        )
        for p in me.purchase_log
    ]


def _ward_events(me: PlayerMatch) -> list[EventCandidate]:
    out: list[EventCandidate] = []
    for w in me.obs_log:
        out.append(EventCandidate(
            type=EventType.WARD, game_time=w["time"], involves_me=True,
            summary=f"обс-вард на {w['time'] // 60}:{w['time'] % 60:02d}",
            data={"kind": "obs", "x": w.get("x"), "y": w.get("y")},
        ))
    return out


def extract_events(match: Match, account_id: int | None) -> list[EventCandidate]:
    me = match.player_by_account(account_id)
    if me is None:
        return []
    events = (
        _teamfight_events(match, me)
        + _objective_events(match, me)
        + _networth_swings(me)
        + _item_events(me)
        + _ward_events(me)
    )
    events.sort(key=lambda e: e.game_time)
    return events
