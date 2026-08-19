from __future__ import annotations

from typing import TYPE_CHECKING

from dota_coach.models import PlayerMatch

if TYPE_CHECKING:  # НЕ импортировать Row в рантайме — иначе цикл rows<->roles
    from dota_coach.leaks.rows import Row


def role_of(me: PlayerMatch) -> int | None:
    if me.position_est in (1, 2, 3, 4, 5):
        return me.position_est
    lr = me.lane_role
    if lr == 2:
        return 2
    if lr == 1:
        return 5 if me.is_roaming else 1
    if lr == 3:
        return 4 if me.is_roaming else 3
    return None


def segment_by_role(rows: list["Row"]) -> dict[int, list["Row"]]:
    out: dict[int, list["Row"]] = {}
    for r in rows:
        if r.role is None:
            continue
        out.setdefault(r.role, []).append(r)
    return out
