"""Контекст матча в точке решения: экономика, свои ключевые предметы, карта, день/ночь.

Всё ЗНАЕМО игроком в моменте (нетворс-бар, собственный инвентарь, павшие вышки, цикл
день/ночь, глобальный анонс Рошана/свой аегис) — значит укладывается в принцип «судим
по тому, что игрок мог знать». Источники: OpenDota (gold_t, purchase_log, objectives) +
реплей (уровни посекундно). Ничего про исход матча здесь нет.
"""
from __future__ import annotations

from dataclasses import dataclass

from dota_coach.models import Match, ParsedReplay, PlayerMatch

DAY_NIGHT_CYCLE = 300   # день и ночь по 5 минут, игра начинается днём (приближение)
AEGIS_DURATION = 300    # аегис живёт 5 минут (верхняя граница окна «вероятно держит»)

# Ключевые для коучинга предметы: purchase_log-ключ -> читаемое имя. Остальное (расходники,
# компоненты) отфильтровывается как шум.
KEY_ITEMS: dict[str, str] = {
    "black_king_bar": "BKB", "blink": "Blink", "force_staff": "Force Staff",
    "travel_boots": "Boots of Travel", "travel_boots_2": "Boots of Travel",
    "glimmer_cape": "Glimmer Cape", "pipe": "Pipe", "guardian_greaves": "Greaves",
    "lotus_orb": "Lotus Orb", "ghost": "Ghost Scepter", "cyclone": "Eul's",
    "aeon_disk": "Aeon Disk", "sphere": "Linken's", "manta": "Manta",
    "aghanims_shard": "Aghanim's Shard", "ultimate_scepter": "Aghanim's Scepter",
    "shivas_guard": "Shiva's Guard", "crimson_guard": "Crimson Guard",
    "solar_crest": "Solar Crest", "spirit_vessel": "Spirit Vessel", "radiance": "Radiance",
    "heart": "Heart", "octarine_core": "Octarine", "assault": "Assault",
    "butterfly": "Butterfly", "refresher": "Refresher", "orchid": "Orchid",
    "bloodthorn": "Bloodthorn", "nullifier": "Nullifier", "diffusal_blade": "Diffusal",
    "skadi": "Skadi", "satanic": "Satanic", "abyssal_blade": "Abyssal",
    "silver_edge": "Silver Edge", "hurricane_pike": "Hurricane Pike", "desolator": "Desolator",
    "rapier": "Rapier", "mjollnir": "Mjollnir", "overwhelming_blink": "Overwhelming Blink",
    "swift_blink": "Swift Blink", "wind_waker": "Wind Waker", "harpoon": "Harpoon",
}


@dataclass(frozen=True)
class MomentContext:
    nw_lead: int                 # нетворс-лид твоей команды (+ впереди / − позади)
    my_level: int
    enemy_avg_level: float
    my_key_items: list[str]      # читаемые имена ключевых предметов, купленных к T
    is_night: bool
    radiant_towers_lost: int
    dire_towers_lost: int
    aegis_side: str | None       # «твоя» | «вражеская» | None — кто вероятно держит аегис
    my_is_radiant: bool


def _slot_index(player_slot: int) -> int:
    return player_slot if player_slot < 128 else player_slot - 123


def _gold_at(gold_t: list[int], t: int) -> int:
    if not gold_t:
        return 0
    minute = max(0, t // 60)
    return gold_t[min(minute, len(gold_t) - 1)]


def _networth_lead(match: Match, me: PlayerMatch, t: int) -> int:
    mine = sum(_gold_at(p.gold_t, t) for p in match.players if p.is_radiant == me.is_radiant)
    enemy = sum(_gold_at(p.gold_t, t) for p in match.players if p.is_radiant != me.is_radiant)
    return mine - enemy


def _levels(parsed: ParsedReplay | None, me: PlayerMatch, t: int) -> tuple[int, float]:
    if parsed is None:
        return me.level, 0.0
    frame = parsed.frame_at(t)
    if frame is None:
        return me.level, 0.0
    my_slot = _slot_index(me.player_slot)
    my_team = parsed.teams.get(my_slot)
    my_level = frame.units[my_slot].level if my_slot in frame.units else me.level
    enemy_levels = [u.level for s, u in frame.units.items()
                    if parsed.teams.get(s) not in (None, my_team)]
    enemy_avg = sum(enemy_levels) / len(enemy_levels) if enemy_levels else 0.0
    return my_level, enemy_avg


def _key_items_by(me: PlayerMatch, t: int) -> list[str]:
    seen: list[str] = []
    for e in me.purchase_log:
        if e.get("time", 0) <= t and e.get("key") in KEY_ITEMS:
            name = KEY_ITEMS[e["key"]]
            if name not in seen:
                seen.append(name)
    return seen


def _towers_lost(match: Match, t: int) -> tuple[int, int]:
    radiant = dire = 0
    for o in match.objectives:
        if o.type != "building_kill" or o.time > t or "tower" not in (o.key or ""):
            continue
        if "goodguys" in o.key:     # goodguys == Radiant
            radiant += 1
        elif "badguys" in o.key:    # badguys == Dire
            dire += 1
    return radiant, dire


def _aegis_side(match: Match, me: PlayerMatch, t: int) -> str | None:
    holder_radiant: bool | None = None
    for o in match.objectives:
        if o.type != "CHAT_MESSAGE_AEGIS" or not (0 <= t - o.time <= AEGIS_DURATION):
            continue
        if o.slot is not None:
            holder_radiant = o.slot < 5
        elif o.player_slot is not None:
            holder_radiant = o.player_slot < 128
    if holder_radiant is None:
        return None
    return "твоя" if holder_radiant == me.is_radiant else "вражеская"


def match_context_at(match: Match, me: PlayerMatch, parsed: ParsedReplay | None,
                     t: int) -> MomentContext:
    my_level, enemy_avg = _levels(parsed, me, t)
    radiant_lost, dire_lost = _towers_lost(match, t)
    return MomentContext(
        nw_lead=_networth_lead(match, me, t),
        my_level=my_level,
        enemy_avg_level=enemy_avg,
        my_key_items=_key_items_by(me, t),
        is_night=(max(0, t) // DAY_NIGHT_CYCLE) % 2 == 1,
        radiant_towers_lost=radiant_lost,
        dire_towers_lost=dire_lost,
        aegis_side=_aegis_side(match, me, t),
        my_is_radiant=me.is_radiant,
    )


def render_match_context(ctx: MomentContext) -> str:
    """Компактная факт-строка контекста матча для промпта/карточки. Без исхода матча."""
    sign = "+" if ctx.nw_lead >= 0 else ""
    econ = f"команда {sign}{ctx.nw_lead} по нетворсу ({'впереди' if ctx.nw_lead >= 0 else 'позади'})"
    lvl = f"ты ур.{ctx.my_level}" + (f" vs ~{ctx.enemy_avg_level:.0f} у врагов"
                                     if ctx.enemy_avg_level else "")
    items = ", ".join(ctx.my_key_items) if ctx.my_key_items else "нет ключевых"
    own_lost = ctx.radiant_towers_lost if ctx.my_is_radiant else ctx.dire_towers_lost
    enemy_lost = ctx.dire_towers_lost if ctx.my_is_radiant else ctx.radiant_towers_lost
    map_line = (f"{'ночь' if ctx.is_night else 'день'} (прибл.), вышек пало — "
                f"твоих {own_lost}, вражеских {enemy_lost}")
    aegis = f", аегис держит {ctx.aegis_side} сторона" if ctx.aegis_side else ""
    return (
        "Контекст матча (знаемо в моменте):\n"
        f"- Экономика: {econ}; {lvl}.\n"
        f"- Твои ключевые предметы: {items}.\n"
        f"- Карта: {map_line}{aegis}."
    )
