from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

import zstandard as zstd

from dota_coach.ingest.opendota import fetch_match
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState


class ReplayUnavailable(Exception):
    """Реплей нельзя достать/распарсить — разбор продолжается без реплей-слоя."""


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


def _default_downloader(url: str) -> bytes:
    import requests

    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


def _default_runner(argv: list[str]) -> str:
    proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(f"replay_tool rc={proc.returncode}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def _tool_default() -> str:
    exe = "replay_tool.exe" if os.name == "nt" else "replay_tool"
    return str(Path(__file__).resolve().parents[3] / "replay_tool" / exe)


def parse_replay(match_id: int, cache_dir: Path = Path("cache"), tool_path: str | None = None,
                 downloader=None, runner=None) -> ParsedReplay:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"replay_{match_id}.jsonl"
    if cached.exists():
        return parse_replay_jsonl(cached.read_text(encoding="utf-8").splitlines(), match_id)

    downloader = downloader or _default_downloader
    runner = runner or _default_runner
    tool_path = tool_path or _tool_default()

    try:
        url = (fetch_match(match_id) or {}).get("replay_url")
        if not url:
            raise ReplayUnavailable(f"нет replay_url для матча {match_id}")
        blob = downloader(url)
        dem = zstd.ZstdDecompressor().decompress(blob, max_output_size=1 << 30)
        with tempfile.NamedTemporaryFile(suffix=".dem", delete=False) as tf:
            tf.write(dem)
            dem_path = tf.name
        try:
            out = runner([tool_path, dem_path])
        finally:
            os.unlink(dem_path)
        cached.write_text(out, encoding="utf-8")
        return parse_replay_jsonl(out.splitlines(), match_id)
    except ReplayUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - граница реплей-слоя: любой сбой -> опциональная деградация
        raise ReplayUnavailable(f"реплей матча {match_id} недоступен: {exc}") from exc
