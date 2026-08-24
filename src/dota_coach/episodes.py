from __future__ import annotations

from dota_coach.models import ParsedReplay


def my_death_times(parsed: ParsedReplay, my_slot: int) -> list[int]:
    """Игровые секунды, где мой слот перешёл alive->dead (респавн игнор). Соло-смерти тоже."""
    times: list[int] = []
    prev_alive: bool | None = None
    for f in parsed.frames:
        u = f.units.get(my_slot)
        if u is None:
            continue
        if prev_alive is True and not u.alive:
            times.append(f.time)
        prev_alive = u.alive
    return times
