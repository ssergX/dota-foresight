"""Portable checks using the active Python environment and an explicit Go tool.

No package installation, corpus downloads or parent Git inspection occurs.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-only", action="store_true")
    parser.add_argument("--go", help="path to Go executable; defaults to PATH")
    args = parser.parse_args(argv)
    report = ROOT / "out/verification/python-tests.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    checks = [[sys.executable, "-m", "pytest", "-q", f"--junitxml={report}"]]
    if not args.python_only:
        go = args.go or shutil.which("go")
        if go is None:
            parser.error("Go is unavailable; install Go 1.24+ or explicitly select --python-only")
        go = str(Path(go).resolve())
    for command in checks:
        subprocess.run(command, cwd=ROOT, check=True)
    if not args.python_only:
        subprocess.run([go, "mod", "verify"], cwd=ROOT / "replay_tool", check=True)
        subprocess.run([go, "test", "-mod=readonly", "./..."], cwd=ROOT / "replay_tool", check=True)
        subprocess.run([go, "build", "-mod=readonly", "./..."], cwd=ROOT / "replay_tool", check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
