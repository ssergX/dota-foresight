"""Portable binary-output wrapper; PowerShell encoding cannot alter the JSONL."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run_extractor(tool: Path, dem: Path, target: Path, mode: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="trace-pending-", suffix=".part", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            subprocess.run([str(tool), mode, str(dem)], stdout=stream, check=True)
            stream.flush()
            os.fsync(stream.fileno())
        if Path(temporary).stat().st_size == 0:
            raise ValueError("extractor returned an empty artifact")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dem", required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--names", help="optional separate --combat-names output")
    parser.add_argument("--enriched", help="join raw trace and callback name pass; requires --names")
    parser.add_argument("--tool", default=str(ROOT / "replay_tool" / ("replay_tool.exe" if os.name == "nt" else "replay_tool")))
    args = parser.parse_args(argv)
    dem, tool, trace = map(lambda value: Path(value).resolve(), (args.dem, args.tool, args.trace))
    if not dem.is_file() or not tool.is_file():
        parser.error("replay and built Go extractor must be existing files")
    with dem.open("rb") as stream:
        if stream.read(8) != b"PBDEMS2\x00":
            parser.error("expected a decompressed Source 2 replay")
    targets = [trace] + [Path(value).resolve() for value in (args.names, args.enriched) if value]
    if len(set(targets)) != len(targets) or set(targets) & {dem, tool}:
        parser.error("distinct outputs must not overwrite replay or extractor")
    if args.enriched and not args.names:
        parser.error("--enriched requires --names")
    with dem.open("rb") as stream:
        replay_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    print(f"source .dem SHA-256: {replay_hash}", flush=True)
    run_extractor(tool, dem, trace, "--trace")
    if args.names:
        names = Path(args.names).resolve()
        run_extractor(tool, dem, names, "--combat-names")
        if args.enriched:
            sys.path.insert(0, str(ROOT / "src"))
            from dota_coach.ingest.trace import enrich_trace_names
            receipt = enrich_trace_names(trace, names, Path(args.enriched).resolve())
            print(f"name enrichment checked {receipt['matched_combat_records']} callback payloads")
    print("Trace artifacts complete; extraction and mechanics remain unverified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
