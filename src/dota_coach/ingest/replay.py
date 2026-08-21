from __future__ import annotations

import json
from typing import Iterable

from dota_coach.models import ParsedReplay, ReplayFrame, UnitState


def parse_replay_jsonl(lines: Iterable[str], match_id: int) -> ParsedReplay:
    meta: dict | None = None
    frames: list[ReplayFrame] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        kind = obj.get("t")
        if kind == "meta":
            meta = obj
        elif kind == "state":
            units = {
                u["slot"]: UnitState(
                    slot=u["slot"], x=float(u["x"]), y=float(u["y"]),
                    hp=int(u["hp"]), max_hp=int(u["max_hp"]), mana=float(u["mana"]),
                    level=int(u["level"]), xp=int(u["xp"]), alive=bool(u["alive"]),
                )
                for u in obj["units"]
            }
            frames.append(ReplayFrame(time=int(obj["time"]), units=units))
    if meta is None:
        raise ValueError("в JSONL нет meta-строки — реплей не распарсен")
    frames.sort(key=lambda f: f.time)
    heroes = {h["slot"]: h["hero"] for h in meta["heroes"]}
    return ParsedReplay(match_id=match_id, game_start_time=float(meta["game_start_time"]),
                        heroes=heroes, frames=frames)
