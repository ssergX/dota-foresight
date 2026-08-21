"""Рендер миникарты фокус-момента из данных реплея (PIL).

Показывает то, что текстом не заходит: где кто стоял, кого ты ВИДЕЛ, а кто был
в тумане и сколько. Не игровой скрин — схема из данных: точки героев, круги вижна,
невидимые враги полым контуром с секундами пропажи, активные варды.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from dota_coach.coach.info_state import OBS_VISION, DAY_VISION, _hero, info_state_at
from dota_coach.models import ParsedReplay

# playable-диапазон мира Доты (с запасом); координаты вне — клампим
MAP_MIN = -8200.0
MAP_MAX = 8200.0
SIZE = 720          # сторона игрового поля, px
MARGIN = 16
TOPBAR = 46

_BG = (24, 26, 30)
_RAD = (40, 74, 48)     # тинт Radiant (ЮЗ)
_DIRE = (86, 46, 44)    # тинт Dire (СВ)
_ALLY = (86, 152, 240)
_ME = (255, 205, 60)
_ENEMY = (232, 86, 76)
_UNSEEN = (150, 120, 120)
_WARD = (240, 214, 90)
_TEXT = (232, 232, 236)
_MUTED = (150, 156, 164)


def _font(size: int, bold: bool = False):
    for name in (("arialbd.ttf",) if bold else ("arial.ttf",)):
        for base in ("C:/Windows/Fonts/", ""):
            try:
                return ImageFont.truetype(base + name, size)
            except OSError:
                continue
    return ImageFont.load_default()


def world_to_px(x: float, y: float) -> tuple[int, int]:
    span = MAP_MAX - MAP_MIN
    fx = min(1.0, max(0.0, (x - MAP_MIN) / span))
    fy = min(1.0, max(0.0, (MAP_MAX - y) / span))   # север сверху
    return MARGIN + int(fx * SIZE), TOPBAR + int(fy * SIZE)


def _r_px(world_r: float) -> int:
    return int(world_r / (MAP_MAX - MAP_MIN) * SIZE)


def _obs_wards_active(parsed: ParsedReplay, team: int, t: int) -> list[tuple[float, float]]:
    placed: dict[int, tuple[int, float, float]] = {}
    gone: dict[int, int] = {}
    for w in parsed.wards:
        if w.kind != "obs" or w.team != team:
            continue
        (placed if w.op == "placed" else gone).__setitem__(
            w.id, (w.time, w.x, w.y) if w.op == "placed" else w.time)
    out = []
    for wid, (pt, x, y) in placed.items():
        g = gone.get(wid)
        if pt <= t and (g is None or t < g):
            out.append((x, y))
    return out


def render_moment(parsed: ParsedReplay, t: int, my_slot: int, out_path: str,
                  title: str = "") -> str:
    info = info_state_at(parsed, t, my_slot)
    frame = parsed.frame_at(t)
    if info is None or frame is None:
        raise ValueError("нет кадра реплея для этого времени")
    my_team = parsed.teams[my_slot]

    W = SIZE + 2 * MARGIN
    H = SIZE + TOPBAR + MARGIN
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)

    # поле + тинты сторон (Radiant ЮЗ / Dire СВ) + река по диагонали
    x0, y0 = MARGIN, TOPBAR
    x1, y1 = MARGIN + SIZE, TOPBAR + SIZE
    d.rectangle([x0, y0, x1, y1], fill=(30, 33, 38), outline=(60, 64, 70))
    d.polygon([(x0, y0), (x0, y1), (x1, y1)], fill=_RAD)     # ЮЗ-треугольник
    d.polygon([(x0, y0), (x1, y0), (x1, y1)], fill=_DIRE)    # СВ-треугольник
    d.line([(x0, y0), (x1, y1)], fill=(70, 96, 120), width=3)
    d.text((x0 + 6, y1 - 20), "Radiant", font=_font(13), fill=(120, 180, 130))
    d.text((x1 - 52, y0 + 6), "Dire", font=_font(13), fill=(200, 130, 120))

    # круги вижна (что ты мог видеть): живые союзники + активные обс-варды
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    ally_slots = [s for s, tm in parsed.teams.items() if tm == my_team]
    for s in ally_slots:
        u = frame.units.get(s)
        if u and u.alive:
            cx, cy = world_to_px(u.x, u.y)
            rr = _r_px(DAY_VISION)
            od.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(90, 150, 230, 26))
    wards = _obs_wards_active(parsed, my_team, t)
    for wx, wy in wards:
        cx, cy = world_to_px(wx, wy)
        rr = _r_px(OBS_VISION)
        od.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(230, 210, 90, 30))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)

    # варды (маркеры)
    for wx, wy in wards:
        cx, cy = world_to_px(wx, wy)
        d.polygon([(cx, cy - 5), (cx + 5, cy), (cx, cy + 5), (cx - 5, cy)],
                  fill=_WARD, outline=(40, 40, 40))

    fnt = _font(12)
    fnt_b = _font(13, bold=True)

    # союзники
    for s in ally_slots:
        u = frame.units.get(s)
        if u is None:
            continue
        cx, cy = world_to_px(u.x, u.y)
        is_me = s == my_slot
        col = _ME if is_me else _ALLY
        rad = 9 if is_me else 6
        if not u.alive:
            d.line([(cx - 6, cy - 6), (cx + 6, cy + 6)], fill=_MUTED, width=2)
            d.line([(cx - 6, cy + 6), (cx + 6, cy - 6)], fill=_MUTED, width=2)
        else:
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=col, outline=(20, 20, 20), width=2)
            if is_me:
                d.ellipse([cx - rad - 4, cy - rad - 4, cx + rad + 4, cy + rad + 4], outline=_ME, width=2)
        label = ("ТЫ " if is_me else "") + _hero(parsed.heroes.get(s, ""))
        d.text((cx + rad + 3, cy - 7), label, font=(fnt_b if is_me else fnt),
               fill=(_ME if is_me else _TEXT))

    # враги
    for e in info.enemies:
        cx, cy = world_to_px(e.x, e.y)
        name = _hero(e.hero)
        if not e.alive:
            d.line([(cx - 6, cy - 6), (cx + 6, cy + 6)], fill=_MUTED, width=2)
            d.line([(cx - 6, cy + 6), (cx + 6, cy - 6)], fill=_MUTED, width=2)
            d.text((cx + 9, cy - 7), name, font=fnt, fill=_MUTED)
        elif e.visible:
            d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=_ENEMY, outline=(20, 20, 20), width=2)
            d.text((cx + 10, cy - 7), name, font=fnt, fill=(245, 200, 195))
        else:
            # НЕВИДИМ: полый контур + «?» + секунды пропажи (ключевой сигнал)
            d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=_ENEMY, width=2)
            d.text((cx - 3, cy - 7), "?", font=fnt_b, fill=_ENEMY)
            d.text((cx + 11, cy - 12), name, font=fnt, fill=_UNSEEN)
            d.text((cx + 11, cy + 1), f"нет {e.missing_for}с", font=fnt, fill=_ENEMY)

    # верхняя плашка
    d.rectangle([0, 0, W, TOPBAR - 2], fill=(18, 20, 24))
    d.text((MARGIN, 6), title or f"матч {parsed.match_id}", font=_font(15, bold=True), fill=_TEXT)
    vis = sum(1 for e in info.enemies if e.alive and e.visible)
    alive_en = sum(1 for e in info.enemies if e.alive)
    sub = (f"{t // 60}:{t % 60:02d}  ·  видно врагов {vis}/{alive_en}  ·  "
           f"не видно {info.unseen_enemies}"
           + (f" (дольше всех {info.max_missing_for}с)" if info.unseen_enemies else "")
           + f"  ·  ты: HP {info.my_hp}/{info.my_max_hp} ур.{info.my_level}")
    d.text((MARGIN, 26), sub, font=_font(12), fill=_MUTED)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
