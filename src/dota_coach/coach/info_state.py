"""Информационное состояние в точке решения: что игрок МОГ ЗНАТЬ в момент T.

Вижн-модель — сознательное ПРИБЛИЖЕНИЕ (v1): круговые радиусы, без учёта рельефа,
деревьев, высот и цикла день/ночь. Враг «виден», если он в радиусе обзора живого
союзного героя ИЛИ активного союзного обсервер-варда. Сентри вижн героев не дают
(они для невидимости/девординга) — в модель не входят. Помечать вывод как оценку.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from dota_coach.models import ParsedReplay

DAY_VISION = 1800.0    # радиус обзора героя (дневной, приближение)
OBS_VISION = 1600.0    # радиус обзора обсервер-варда
NEARBY_RADIUS = 2500.0  # «рядом» — радиус боевого контакта (приближение)
SPLIT_DIST = 3000.0    # ближайший союзник дальше -> ты оторван/один
RIVER_BAND = 1500.0    # |x+y| меньше -> у реки/центр
LOW_HP = 0.35          # доля HP, ниже которой враг «на добивании»


@dataclass(frozen=True)
class EnemyInfo:
    slot: int
    hero: str
    x: float
    y: float
    alive: bool
    visible: bool
    missing_for: int   # секунд с момента, когда враг последний раз был виден (0 если виден сейчас)
    hp_frac: float = 1.0   # доля HP (для «низкий HP» у видимых)
    dist: float = 0.0      # расстояние до тебя (мировые ед.)


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
    # --- ситуативный расклад (заземление для тренерского разбора) ---
    allies_near: int = 0        # живых союзников рядом (радиус NEARBY_RADIUS), без тебя
    nearest_ally_dist: float = 0.0
    enemies_near: int = 0       # живых врагов рядом ФАКТИЧЕСКИ (ground truth, мог не знать)
    enemies_near_visible: int = 0  # из них ты видел
    zone: str = ""              # «на своей половине» | «у реки» | «на половине противника»


def _hero(name: str) -> str:
    n = name[len("CDOTA_Unit_Hero_"):] if name.startswith("CDOTA_Unit_Hero_") else name
    n = n.replace("_", " ")
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)   # StormSpirit -> Storm Spirit
    return n.strip()


def _zone(x: float, y: float, team: int) -> str:
    s = x + y
    own_sign = -1 if team == 2 else 1   # Radiant: своя половина при x+y<0
    if abs(s) < RIVER_BAND:
        return "у реки/центр"
    return "на своей половине" if s * own_sign > 0 else "на половине противника"


def render_knowable(info: "InfoState") -> str:
    """Заземление ТОЛЬКО из знаемого игроком в точке решения: вижн, свои союзники, своя
    позиция/ресурсы. Ground-truth о скрытых врагах (enemies_near — реально рядом, в т.ч.
    невидимые) сюда НЕ ПОПАДАЕТ: анти-хиндсайт гарантируется на уровне данных, а не просьбой
    в промпте. Это вход для ОЦЕНКИ РЕШЕНИЯ (решение судим по тому, что было видно).
    """
    pct = round(info.my_hp / info.my_max_hp * 100) if info.my_max_hp else 0
    alive = [e for e in info.enemies if e.alive]
    visible = [e for e in alive if e.visible]
    unseen = sorted((e for e in alive if not e.visible), key=lambda e: -e.missing_for)
    vis_names = ", ".join(_hero(e.hero) for e in visible) if visible else "никого"
    low = [_hero(e.hero) for e in visible if e.hp_frac <= LOW_HP]
    unseen_str = (", ".join(f"{_hero(e.hero)} ({e.missing_for}с)" for e in unseen)
                  if unseen else "нет")
    if info.allies_near:
        allies_line = f"рядом союзников: {info.allies_near}"
    elif info.nearest_ally_dist and info.nearest_ally_dist > SPLIT_DIST:
        allies_line = "рядом союзников нет — ты оторван от команды"
    else:
        allies_line = "рядом союзников нет"
    lines = [
        "Что было знаемо в точке решения (из реплея; вижн — оценка радиусами):",
        f"- Твоё состояние: HP {info.my_hp}/{info.my_max_hp} ({pct}%), уровень {info.my_level}"
        + ("" if info.my_alive else ", МЁРТВ") + ".",
        f"- Позиция: {info.zone}; {allies_line}.",
        f"- Видел врагов: {vis_names}" + (f" (низкий HP: {', '.join(low)})" if low else "")
        + f". Не видел: {unseen_str}. В тумане живых: {info.unseen_enemies}.",
    ]
    return "\n".join(lines)


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

    me = frame_t.units.get(my_slot)
    mx = me.x if me else 0.0
    my = me.y if me else 0.0

    enemies: list[EnemyInfo] = []
    unseen = 0
    max_missing = 0
    enemies_near = 0
    enemies_near_visible = 0
    for es in enemy_slots:
        u = frame_t.units.get(es)
        if u is None:
            continue
        seen = last_seen[es]
        visible = seen == t
        missing_for = 0 if visible else (t - seen if seen is not None else t)
        dist = _d2(mx, my, u.x, u.y) ** 0.5
        if u.alive and not visible:
            unseen += 1
            max_missing = max(max_missing, missing_for)
        if u.alive and dist <= NEARBY_RADIUS:
            enemies_near += 1
            if visible:
                enemies_near_visible += 1
        enemies.append(EnemyInfo(
            slot=es, hero=parsed.heroes.get(es, ""), x=u.x, y=u.y,
            alive=u.alive, visible=visible, missing_for=missing_for,
            hp_frac=(u.hp / u.max_hp if u.max_hp else 1.0), dist=dist,
        ))

    ally_dists = [_d2(mx, my, frame_t.units[s].x, frame_t.units[s].y) ** 0.5
                  for s in ally_slots
                  if s != my_slot and s in frame_t.units and frame_t.units[s].alive]
    allies_near = sum(1 for d in ally_dists if d <= NEARBY_RADIUS)
    nearest_ally = min(ally_dists) if ally_dists else 0.0

    return InfoState(
        time=t, my_slot=my_slot, my_x=mx, my_y=my,
        my_hp=me.hp if me else 0, my_max_hp=me.max_hp if me else 0,
        my_mana=me.mana if me else 0.0, my_level=me.level if me else 0,
        my_alive=me.alive if me else False,
        enemies=enemies, unseen_enemies=unseen, max_missing_for=max_missing,
        allies_near=allies_near, nearest_ally_dist=nearest_ally,
        enemies_near=enemies_near, enemies_near_visible=enemies_near_visible,
        zone=_zone(mx, my, my_team),
    )
