from __future__ import annotations

from dataclasses import dataclass

from dota_coach.leaks.roles import role_of
from dota_coach.models import Match, PlayerMatch


@dataclass(frozen=True)
class Row:
    match_id: int
    duration: int
    parsed: bool
    role: int | None
    me: PlayerMatch


def build_rows(matches: list[Match], account_id: int | None) -> list[Row]:
    rows: list[Row] = []
    for m in matches:
        me = m.player_by_account(account_id)
        if me is None:
            continue
        rows.append(Row(match_id=m.match_id, duration=m.duration,
                        parsed=m.parsed, role=role_of(me), me=me))
    return rows
