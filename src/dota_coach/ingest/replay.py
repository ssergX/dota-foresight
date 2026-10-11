from __future__ import annotations

import bz2
import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

import zstandard as zstd

from dota_coach.evidence.contracts import CapabilityStatus, ReplayManifest, legacy_manifest
from dota_coach.ingest.opendota import fetch_match
from dota_coach.models import ParsedReplay, ReplayFrame, UnitState, WardEvent

SCHEMA_VERSION = "replay-jsonl.v2"
CACHE_VERSION = "v2"


class ReplayUnavailable(Exception):
    """Реплей нельзя достать/распарсить — разбор продолжается без реплей-слоя."""


def _number(value, label: str, *, nullable=False, integer=False, minimum=None):
    if value is None and nullable:
        return None
    try:
        finite = isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        finite = False
    if isinstance(value, bool) or not finite:
        raise ValueError(f"{label}: expected finite number")
    if integer and (not isinstance(value, int)):
        raise ValueError(f"{label}: expected integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label}: below minimum {minimum}")
    return value if integer else float(value)


def _slot(value):
    slot = _number(value, "slot", integer=True, minimum=0)
    if slot > 9:
        raise ValueError("slot: outside canonical range 0..9")
    return slot


def _team(value):
    team = _number(value, "team", nullable=True, integer=True)
    if team is not None and team not in (2, 3):
        raise ValueError("team: expected 2 or 3")
    return team


def _object(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected object")
    return value


def _list(value, label):
    if not isinstance(value, list):
        raise ValueError(f"{label}: expected array")
    return value


def _text(value, label, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: expected nonempty string")
    return value


def _no_duplicate_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _manifest(meta, digest, match_id, warnings):
    if meta.get("schema_version", "legacy-jsonl") == "legacy-jsonl":
        old = legacy_manifest(digest, match_id)
        return ReplayManifest(**{**old.__dict__, "parse_warnings": old.parse_warnings + tuple(warnings)})
    caps = []
    seen = set()
    for raw_cap in _list(meta.get("capabilities"), "capabilities"):
        cap = _object(raw_cap, "capability")
        name = _text(cap.get("capability_id"), "capability_id")
        if name in seen:
            raise ValueError("duplicate capability_id")
        seen.add(name)
        implementation = cap.get("implementation")
        if implementation not in ("absent", "implemented"):
            raise ValueError("invalid capability implementation")
        if cap.get("validation") not in ("unverified", "validated", "regressed"):
            raise ValueError("invalid capability validation")
        # Parser output is not an independent validation registry. Never grant admission here.
        if cap["validation"] != "unverified":
            warnings.append(f"ignored_untrusted_validation_claim:{name}")
        caps.append(CapabilityStatus(name, implementation, "unverified",
                                     limitations=("real_replay_client_validation_required",)))
    for name in ("exact_team_visibility", "inventory_abilities", "cast_control_events",
                 "reaction_cue_available_to_subject"):
        if name not in seen:
            caps.append(CapabilityStatus(name))
    if meta.get("completeness") not in ("complete", "partial", "unknown"):
        raise ValueError("invalid completeness")
    if meta["completeness"] == "complete":
        warnings.append("unverified_completeness_claim")
    declared_warnings = _list(meta.get("parse_warnings"), "parse_warnings")
    for warning in declared_warnings:
        _text(warning, "parse_warning")
    dataset = meta.get("dataset_kind", "unknown")
    if dataset not in ("replay", "synthetic", "unknown"):
        raise ValueError("invalid dataset_kind")
    return ReplayManifest(
        replay_hash=digest, match_id=match_id, schema_version=SCHEMA_VERSION,
        extractor_name=_text(meta.get("extractor_name"), "extractor_name"),
        extractor_version=_text(meta.get("extractor_version"), "extractor_version"),
        timebase_version=_text(meta.get("timebase_version"), "timebase_version"),
        game_build=_text(meta.get("game_build"), "game_build", nullable=True),
        patch=_text(meta.get("patch"), "patch", nullable=True),
        completeness="partial" if meta["completeness"] == "complete" else meta["completeness"],
        parse_warnings=tuple(dict.fromkeys(declared_warnings + warnings)),
        capabilities=tuple(caps), dataset_kind=dataset,
    )


def parse_replay_jsonl(lines: Iterable[str], match_id: int) -> ParsedReplay:
    _number(match_id, "match_id", integer=True, minimum=1)
    raw_lines = list(lines)
    digest = hashlib.sha256("\n".join(raw_lines).encode("utf-8")).hexdigest()
    records = []
    for line_number, raw in enumerate(raw_lines, 1):
        if not raw.strip():
            continue
        try:
            records.append(_object(json.loads(raw, object_pairs_hook=_no_duplicate_keys), "JSONL record"))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"JSONL line {line_number}: {exc}") from exc
    if not records or records[0].get("t") != "meta":
        raise ValueError("в JSONL нет начальной meta-строки — реплей не распарсен")
    meta = records[0]
    schema = meta.get("schema_version", "legacy-jsonl")
    if schema not in ("legacy-jsonl", SCHEMA_VERSION):
        raise ValueError(f"unsupported replay schema: {schema}")
    v2 = schema == SCHEMA_VERSION
    if "match_id" in meta:
        meta_match_id = _number(meta["match_id"], "meta match_id", integer=True, minimum=1)
        if meta_match_id != match_id:
            raise ValueError("replay match_id does not match request")
    start = _number(meta.get("game_start_time"), "game_start_time", minimum=0)
    tick_rate = _number(meta.get("tick_rate"), "tick_rate", minimum=0)
    if tick_rate == 0:
        raise ValueError("tick_rate must be positive")
    heroes, teams = {}, {}
    for h in _list(meta.get("heroes"), "heroes"):
        h = _object(h, "hero")
        slot = _slot(h.get("slot"))
        if slot in heroes:
            raise ValueError("duplicate hero slot")
        heroes[slot] = _text(h.get("hero"), "hero")
        team = _team(h.get("team"))
        if team is not None:
            teams[slot] = team
    warnings = []
    frames, wards = [], []
    frame_times, ordering_keys = set(), set()
    def timestamp(obj):
        time = _number(obj.get("time"), "time")
        tick = _number(obj.get("tick"), "tick", nullable=not v2, integer=True, minimum=0)
        sequence = _number(obj.get("sequence"), "sequence", nullable=not v2, integer=True, minimum=0)
        if v2:
            key = (tick, sequence)
            if key in ordering_keys:
                raise ValueError("duplicate replay tick/sequence")
            ordering_keys.add(key)
            if not math.isclose(time, tick / tick_rate - start, abs_tol=1e-7):
                raise ValueError("inconsistent tick/game-time mapping")
        return time, tick, sequence
    for obj in records[1:]:
        kind = obj.get("t")
        if kind == "state":
            time, tick, sequence = timestamp(obj)
            if time in frame_times:
                raise ValueError("duplicate frame time")
            frame_times.add(time)
            units = {}
            for raw_unit in _list(obj.get("units"), "units"):
                u = _object(raw_unit, "unit")
                slot = _slot(u.get("slot"))
                if slot in units:
                    raise ValueError("duplicate unit slot")
                alive = u.get("alive")
                if alive is not None and not isinstance(alive, bool):
                    raise ValueError("alive: expected boolean or null")
                units[slot] = UnitState(
                    slot=slot, x=_number(u.get("x"), "x", nullable=True),
                    y=_number(u.get("y"), "y", nullable=True),
                    hp=_number(u.get("hp"), "hp", nullable=True, integer=True, minimum=0),
                    max_hp=_number(u.get("max_hp"), "max_hp", nullable=True, integer=True, minimum=0),
                    mana=_number(u.get("mana"), "mana", nullable=True, minimum=0),
                    level=_number(u.get("level"), "level", nullable=True, integer=True, minimum=0),
                    xp=_number(u.get("xp"), "xp", nullable=True, integer=True, minimum=0),
                    alive=alive,
                    entity_index=_number(u.get("entity_index"), "entity_index", nullable=True, integer=True, minimum=0),
                    generation=_number(u.get("generation", 0), "generation", integer=True, minimum=0),
                )
            if len(units) != 10:
                warnings.append("partial_hero_roster")
            if any(any(getattr(u, field) is None for field in ("x", "y", "hp", "max_hp", "mana", "level", "xp", "alive")) for u in units.values()):
                warnings.append("missing_unit_properties")
            frames.append(ReplayFrame(time=time, units=units, tick=tick, sequence=sequence))
        elif kind == "ward":
            time, tick, sequence = timestamp(obj)
            if obj.get("kind") not in ("obs", "sentry") or obj.get("op") not in ("placed", "gone"):
                raise ValueError("unsupported ward kind or operation")
            wards.append(WardEvent(
                id=_number(obj.get("id"), "ward id", integer=True, minimum=0),
                generation=_number(obj.get("generation", 0), "ward generation", integer=True, minimum=1 if v2 else 0),
                time=time, kind=obj["kind"], team=_team(obj.get("team")),
                x=_number(obj.get("x"), "ward x", nullable=True),
                y=_number(obj.get("y"), "ward y", nullable=True), op=obj["op"],
                tick=tick, sequence=sequence,
            ))
        else:
            raise ValueError(f"unsupported or duplicate record type: {kind}")
    frames.sort(key=lambda f: f.time)
    wards.sort(key=lambda w: (w.time, w.sequence if w.sequence is not None else -1))
    active_wards, observed_instances = {}, set()
    for ward in wards:
        instance = (ward.id, ward.generation)
        if ward.op == "placed":
            if v2 and instance in observed_instances:
                raise ValueError("duplicate ward instance placement")
            if ward.id in active_wards:
                warnings.append("ward_generation_reuse_without_observed_removal")
            observed_instances.add(instance)
            active_wards[ward.id] = instance
        elif active_wards.get(ward.id) == instance:
            del active_wards[ward.id]
        else:
            warnings.append("ward_removal_without_matching_placement")
    if active_wards:
        warnings.append("ward_lifetimes_right_censored_at_replay_end")
    if any(w.x is None or w.y is None or w.team is None for w in wards):
        warnings.append("missing_ward_properties")
    if not frames:
        warnings.append("no_state_frames")
    manifest = _manifest(meta, digest, match_id, warnings)
    return ParsedReplay(match_id=match_id, game_start_time=start, heroes=heroes,
                        frames=frames, teams=teams, wards=wards, manifest=manifest)


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


def _decompress(blob: bytes) -> bytes:
    # Format is determined by content, not URL extension.
    if blob.startswith(b"BZh"):
        return bz2.decompress(blob)
    if blob.startswith(b"\x28\xb5\x2f\xfd"):
        return zstd.ZstdDecompressor().decompress(blob, max_output_size=1 << 30)
    if blob.startswith((b"PBDEMS2\x00", b"HL2DEMO\x00")):
        return blob
    raise ValueError("unknown replay compression/header")


def _atomic_cache_write(path: Path, text: str):
    # The caller has validated the entire output before publishing it to readers.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as tf:
            temp_path = Path(tf.name)
            tf.write(text)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _cache_path(cache_dir: Path, match_id: int, tool_path: str) -> Path:
    # Binary and extractor sources/options are part of the namespace. A changed
    # parser cannot silently reuse output of a different extractor build.
    project = Path(__file__).resolve().parents[3]
    tool = Path(tool_path)
    components = {"schema": SCHEMA_VERSION, "cache_version": CACHE_VERSION,
                  "tool_path": str(tool.resolve()),
                  "binary": hashlib.sha256(tool.read_bytes()).hexdigest() if tool.is_file() else None}
    for name in ("main.go", "go.mod", "go.sum"):
        source = project / "replay_tool" / name
        components[name] = hashlib.sha256(source.read_bytes()).hexdigest() if source.exists() else None
    fingerprint = hashlib.sha256(json.dumps(components, sort_keys=True).encode()).hexdigest()[:16]
    return cache_dir / f"replay_{match_id}.{CACHE_VERSION}.{fingerprint}.jsonl"


def parse_replay(match_id: int, cache_dir: Path = Path("cache"), tool_path: str | None = None,
                 downloader=None, runner=None) -> ParsedReplay:
    try:
        _number(match_id, "match_id", integer=True, minimum=1)
        cache_dir.mkdir(parents=True, exist_ok=True)
        tool_path = tool_path or _tool_default()
        cached = _cache_path(cache_dir, match_id, tool_path)
        legacy_cached = cache_dir / f"replay_{match_id}.jsonl"
        unversioned_parser_cache = cache_dir / f"replay_{match_id}.{CACHE_VERSION}.jsonl"
        source = (cached if cached.exists() else unversioned_parser_cache
                  if unversioned_parser_cache.exists() else legacy_cached)
        if source.exists():
            replay = parse_replay_jsonl(source.read_text(encoding="utf-8").splitlines(), match_id)
            if source != cached:
                from dataclasses import replace
                replay = replace(replay, manifest=replace(replay.manifest,
                    parse_warnings=replay.manifest.parse_warnings + ("cache_parser_fingerprint_missing",)))
            return replay
        downloader = downloader or _default_downloader
        runner = runner or _default_runner
        url = (fetch_match(match_id) or {}).get("replay_url")
        if not url:
            raise ReplayUnavailable(f"нет replay_url для матча {match_id}")
        dem = _decompress(downloader(url))
        with tempfile.NamedTemporaryFile(suffix=".dem", delete=False) as tf:
            tf.write(dem)
            dem_path = tf.name
        try:
            out = runner([tool_path, dem_path])
        finally:
            os.unlink(dem_path)
        replay = parse_replay_jsonl(out.splitlines(), match_id)
        _atomic_cache_write(cached, out)
        return replay
    except ReplayUnavailable:
        raise
    except Exception as exc:  # optional replay boundary, including malformed cached output
        raise ReplayUnavailable(f"реплей матча {match_id} недоступен: {exc}") from exc
