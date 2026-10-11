"""Retrospective radius estimate, NOT a validated KnowledgeSnapshot.

The strict evaluator projection lives in evidence.knowledge and never reads
enemy world coordinates. This legacy estimate is retained for inspection.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from dota_coach.models import ParsedReplay

DAY_VISION = 1800.0
OBS_VISION = 1600.0
NEARBY_RADIUS = 2500.0
SPLIT_DIST = 3000.0
RIVER_BAND = 1500.0
LOW_HP = 0.35


@dataclass(frozen=True)
class EnemyInfo:
    slot: int
    hero: str
    x: float | None
    y: float | None
    alive: bool | None
    visible: bool | None
    missing_for: float | None
    hp_frac: float | None = None
    dist: float | None = None


@dataclass(frozen=True)
class InfoState:
    time: float
    my_slot: int
    my_x: float | None
    my_y: float | None
    my_hp: int | None
    my_max_hp: int | None
    my_mana: float | None
    my_level: int | None
    my_alive: bool | None
    enemies: list[EnemyInfo]
    unseen_enemies: int
    max_missing_for: float | None
    allies_near: int = 0
    nearest_ally_dist: float | None = None
    enemies_near: int | None = None
    enemies_near_visible: int = 0
    zone: str = ""
    sample_time: float | None = None
    visibility_quality: str = "estimated"


def _hero(name: str) -> str:
    n = name.removeprefix("CDOTA_Unit_Hero_").replace("_", " ")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n).strip()


def _zone(x: float | None, y: float | None, team: int) -> str:
    if x is None or y is None:
        return "позиция неизвестна"
    s = x + y
    if abs(s) < RIVER_BAND:
        return "у реки/центр (приблизительно)"
    return "на своей половине" if s * (-1 if team == 2 else 1) > 0 else "на половине противника"


def render_info_state(info: InfoState) -> str:
    def show(value):
        return "неизвестно" if value is None else str(value)
    visible = [_hero(e.hero) for e in info.enemies if e.visible is True]
    missing = []
    for e in info.enemies:
        if e.visible is not True:
            duration = ("нет подтверждённой истории" if e.missing_for is None
                        else f"последнее приближённое наблюдение {e.missing_for:g}с назад")
            missing.append(f"{_hero(e.hero)} ({duration})")
    return (
        "Что было знаемо: точная наблюдаемость НЕ подтверждена.\n"
        "Ретроспективная оценка радиусами; не доказывает, что игрок видел или заметил угрозу.\n"
        f"- Собственное состояние в срезе: HP {show(info.my_hp)}/{show(info.my_max_hp)}, "
        f"мана {show(info.my_mana)}, ур. {show(info.my_level)}.\n"
        f"- По приближению видно: {', '.join(visible) or 'нет определённых наблюдений'}.\n"
        f"- Не видно или неизвестно: {'; '.join(missing) or 'нет записей'}."
    )


def render_grounding(info: InfoState) -> str:
    return render_info_state(info)


def _d2(ax: float, ay: float, bx: float, by: float) -> float:
    return (ax - bx) ** 2 + (ay - by) ** 2


def _obs_wards_active_at(parsed: ParsedReplay, team: int, t: float) -> list[tuple[float, float]]:
    active = {}
    for w in sorted(parsed.wards, key=lambda w: (w.time, w.sequence or 0)):
        if w.time > t:
            break
        if w.kind != "obs" or w.team != team:
            continue
        key = (w.id, w.generation)
        if w.op == "placed":
            active[key] = (w.x, w.y)
        elif w.op == "gone":
            active.pop(key, None)
    return [(x, y) for x, y in active.values() if x is not None and y is not None]


def _visible(ex: float, ey: float, ally_pos, obs) -> bool:
    return any(_d2(ex, ey, ax, ay) <= DAY_VISION ** 2 for ax, ay in ally_pos) or any(
        _d2(ex, ey, wx, wy) <= OBS_VISION ** 2 for wx, wy in obs)


def info_state_at(parsed: ParsedReplay, t: float, my_slot: int) -> InfoState | None:
    frame = parsed.frame_at(t)
    if frame is None or my_slot not in parsed.teams or my_slot not in frame.units:
        return None
    me = frame.units[my_slot]
    team = parsed.teams[my_slot]
    allies = [s for s, tm in parsed.teams.items() if tm == team]
    enemy_slots = sorted(s for s, tm in parsed.teams.items() if tm != team)
    last_seen = {}
    visibility = {}
    for f in parsed.frames:
        if f.time > frame.time:
            break
        positions = [(f.units[s].x, f.units[s].y) for s in allies if s in f.units
                     and f.units[s].alive is True and f.units[s].x is not None
                     and f.units[s].y is not None]
        obs = _obs_wards_active_at(parsed, team, f.time)
        for slot in enemy_slots:
            u = f.units.get(slot)
            seen = (None if u is None or u.x is None or u.y is None or u.alive is None
                    else _visible(u.x, u.y, positions, obs) if u.alive else False)
            if seen:
                last_seen[slot] = (f.time, u)
            if f is frame:
                visibility[slot] = seen
    enemies = []
    for slot in enemy_slots:
        visible = visibility.get(slot)
        history = last_seen.get(slot)
        current = frame.units.get(slot) if visible else None
        known = current or (history[1] if history else None)
        distance = (_d2(me.x, me.y, known.x, known.y) ** 0.5 if known and
                    me.x is not None and me.y is not None else None)
        enemies.append(EnemyInfo(
            slot, parsed.heroes.get(slot, "неизвестный герой"),
            known.x if known else None, known.y if known else None,
            current.alive if current else None, visible,
            0.0 if visible else t - history[0] if history else None,
            current.hp / current.max_hp if current and current.hp is not None
            and current.max_hp else None, distance))
    ally_dists = [_d2(me.x, me.y, frame.units[s].x, frame.units[s].y) ** 0.5
                  for s in allies if s != my_slot and s in frame.units
                  and frame.units[s].alive is True and me.x is not None and me.y is not None
                  and frame.units[s].x is not None and frame.units[s].y is not None]
    durations = [e.missing_for for e in enemies if e.visible is not True
                 and e.missing_for is not None]
    return InfoState(
        t, my_slot, me.x, me.y, me.hp, me.max_hp, me.mana, me.level, me.alive, enemies,
        sum(e.visible is not True for e in enemies), max(durations, default=None),
        allies_near=sum(d <= NEARBY_RADIUS for d in ally_dists),
        nearest_ally_dist=min(ally_dists, default=None),
        enemies_near_visible=sum(e.visible is True and e.dist is not None
                                 and e.dist <= NEARBY_RADIUS for e in enemies),
        zone=_zone(me.x, me.y, team), sample_time=frame.time)
