"""Информационное состояние в точке решения: что игрок МОГ ЗНАТЬ в момент T.

Вижн-модель — сознательное ПРИБЛИЖЕНИЕ (v1): круговые радиусы, без учёта рельефа,
деревьев, высот и цикла день/ночь. Враг «виден», если он в радиусе обзора живого
союзного героя ИЛИ активного союзного обсервер-варда. Сентри вижн героев не дают
(они для невидимости/девординга) — в модель не входят. Помечать вывод как оценку.
"""
from __future__ import annotations

from dataclasses import dataclass

from dota_coach.models import ParsedReplay

DAY_VISION = 1800.0   # радиус обзора героя (дневной, приближение)
OBS_VISION = 1600.0   # радиус обзора обсервер-варда


@dataclass(frozen=True)
class EnemyInfo:
    slot: int
    hero: str
    x: float
    y: float
    alive: bool
    visible: bool
    missing_for: int   # секунд с момента, когда враг последний раз был виден (0 если виден сейчас)


@dataclass(frozen=True)
class InfoState:
    time: int
    my_slot: int
    my_x: float
    my_y: float
    my_hp: int
    my_max_hp: int
    my_mana: float
    my_level: int
    my_alive: bool
    enemies: list[EnemyInfo]
    unseen_enemies: int    # сколько ЖИВЫХ врагов не видно сейчас
    max_missing_for: int   # самая долгая пропажа среди живых врагов


def _hero(name: str) -> str:
    return name[len("CDOTA_Unit_Hero_"):] if name.startswith("CDOTA_Unit_Hero_") else name


def render_info_state(info: "InfoState") -> str:
    """Текстовый блок «что было знаемо» для промпта. Только факты, без исхода матча."""
    me = f"HP {info.my_hp}/{info.my_max_hp}, мана {info.my_mana:.0f}, ур. {info.my_level}"
    if not info.my_alive:
        me += ", МЁРТВ"
    alive = [e for e in info.enemies if e.alive]
    visible = [_hero(e.hero) for e in alive if e.visible]
    unseen = sorted((e for e in alive if not e.visible), key=lambda e: -e.missing_for)
    vis_line = ", ".join(visible) if visible else "никого"
    unseen_line = (", ".join(f"{_hero(e.hero)} (пропал {e.missing_for}с)" for e in unseen)
                   if unseen else "все живые враги видны")
    tail = f", дольше всех — {info.max_missing_for}с." if info.unseen_enemies else "."
    return (
        "Что было знаемо в этот момент (из реплея; вижн — оценка):\n"
        f"- Ты: {me}.\n"
        f"- Видно врагов: {vis_line}.\n"
        f"- Не видно: {unseen_line}. Всего непросвечено: {info.unseen_enemies}{tail}"
    )


def _d2(ax: float, ay: float, bx: float, by: float) -> float:
    return (ax - bx) ** 2 + (ay - by) ** 2


def _obs_wards_active_at(parsed: ParsedReplay, team: int, t: int) -> list[tuple[float, float]]:
    placed: dict[int, tuple[int, float, float]] = {}
    gone: dict[int, int] = {}
    for w in parsed.wards:
        if w.kind != "obs" or w.team != team:
            continue
        if w.op == "placed":
            placed[w.id] = (w.time, w.x, w.y)
        else:
            gone[w.id] = w.time
    out: list[tuple[float, float]] = []
    for wid, (pt, x, y) in placed.items():
        g = gone.get(wid)
        if pt <= t and (g is None or t < g):
            out.append((x, y))
    return out


def _visible(ex: float, ey: float, ally_pos: list[tuple[float, float]],
             obs: list[tuple[float, float]]) -> bool:
    if any(_d2(ex, ey, ax, ay) <= DAY_VISION ** 2 for ax, ay in ally_pos):
        return True
    if any(_d2(ex, ey, wx, wy) <= OBS_VISION ** 2 for wx, wy in obs):
        return True
    return False


def info_state_at(parsed: ParsedReplay, t: int, my_slot: int) -> InfoState | None:
    frame_t = parsed.frame_at(t)
    if frame_t is None or my_slot not in parsed.teams:
        return None
    my_team = parsed.teams[my_slot]
    ally_slots = [s for s, tm in parsed.teams.items() if tm == my_team]
    enemy_slots = sorted(s for s, tm in parsed.teams.items() if tm != my_team)

    # timeline видимости: последняя секунда <= t, когда каждый враг был виден и жив
    last_seen: dict[int, int | None] = {s: None for s in enemy_slots}
    for f in parsed.frames:
        if f.time > t:
            break
        obs = _obs_wards_active_at(parsed, my_team, f.time)
        ally_pos = [(f.units[s].x, f.units[s].y) for s in ally_slots
                    if s in f.units and f.units[s].alive]
        for es in enemy_slots:
            u = f.units.get(es)
            if u is None or not u.alive:
                continue
            if _visible(u.x, u.y, ally_pos, obs):
                last_seen[es] = f.time

    enemies: list[EnemyInfo] = []
    unseen = 0
    max_missing = 0
    for es in enemy_slots:
        u = frame_t.units.get(es)
        if u is None:
            continue
        seen = last_seen[es]
        visible = seen == t
        missing_for = 0 if visible else (t - seen if seen is not None else t)
        if u.alive and not visible:
            unseen += 1
            max_missing = max(max_missing, missing_for)
        enemies.append(EnemyInfo(
            slot=es, hero=parsed.heroes.get(es, ""), x=u.x, y=u.y,
            alive=u.alive, visible=visible, missing_for=missing_for,
        ))

    me = frame_t.units.get(my_slot)
    return InfoState(
        time=t, my_slot=my_slot,
        my_x=me.x if me else 0.0, my_y=me.y if me else 0.0,
        my_hp=me.hp if me else 0, my_max_hp=me.max_hp if me else 0,
        my_mana=me.mana if me else 0.0, my_level=me.level if me else 0,
        my_alive=me.alive if me else False,
        enemies=enemies, unseen_enemies=unseen, max_missing_for=max_missing,
    )
