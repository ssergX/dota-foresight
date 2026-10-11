"""Audit wheel/sdist contents before transfer; never enumerate the parent Git tree."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import tarfile
import zipfile

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
FORBIDDEN_COMPONENTS = {".runtime", ".venv", "out", "cache", ".git", ".codex", ".agents",
                        ".aws", ".pytest_cache", "__pycache__", ".playwright-mcp", "spike_replay"}
FORBIDDEN_SUFFIXES = (".exe", ".dem", ".dem.bz2", ".dem.compressed", ".mp4", ".pyc", ".part")
SDIST_ROOT_FILES = {"README.md", "INSTALL.md", "pyproject.toml", "constraints-python312.txt",
                     ".gitignore", "PKG-INFO"}
SDIST_DIRECTORIES = {"src", "tests", "scripts", "replay_tool", "assets", ".github", "docs"}
PRIVATE_PATH = re.compile(rb"(?:[A-Za-z]:[\\/]+Users[\\/]+(?!<|user(?:[\\/]|$))[^\s\"']+|"
                          + rb"/ho" + rb"me/[^\s\"']+|/Us" + rb"ers/[^\s\"']+)", re.I)


def inspect_entry(name: str, data: bytes, *, wheel: bool, size: int | None = None) -> None:
    path = PurePosixPath(name)
    if "\\" in name or path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"unsafe archive path: {name}")
    if set(path.parts) & FORBIDDEN_COMPONENTS or name.endswith(FORBIDDEN_SUFFIXES):
        raise ValueError(f"runtime or private artifact in archive: {name}")
    if (size if size is not None else len(data)) > MAX_FILE_BYTES:
        raise ValueError(f"oversized artifact: {name}")
    if wheel:
        if path.parts[0] != "dota_coach" and not path.parts[0].endswith(".dist-info"):
            raise ValueError(f"unexpected wheel package: {name}")
    else:
        if path.parts[0] not in SDIST_DIRECTORIES and name not in SDIST_ROOT_FILES:
            raise ValueError(f"unexpected source distribution artifact: {name}")
        if path.parts[0] == "replay_tool" and path.suffix != ".go" and path.name not in ("go.mod", "go.sum"):
            raise ValueError(f"non-source extractor artifact: {name}")
        if path.parts[0]=='docs' and (path.suffix!='.md' or path.parts[1] not in ('architecture','implementation','data-spike')):
            raise ValueError(f'unexpected documentation artifact: {name}')
    if path.suffix in (".py", ".md", ".toml", ".json", ".jsonl", ".txt", ".yml", ".yaml"):
        if PRIVATE_PATH.search(data):
            raise ValueError(f"personal absolute path in distributable text: {name}")


def audit_archive(path: str | Path) -> dict:
    path = Path(path)
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError(f"archive exceeds source-transfer size budget: {path.name}")
    names = []
    total = 0
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                if entry.file_size > MAX_FILE_BYTES or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError(f"oversized or linked wheel artifact: {entry.filename}")
                data = archive.read(entry)
                inspect_entry(entry.filename, data, wheel=True, size=entry.file_size)
                names.append(entry.filename)
                total += entry.file_size
        required = {"dota_coach/coach/principles.md", "dota_coach/coach/moment_principles.md",
                    "dota_coach/cli.py", "dota_coach/server.py"}
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            roots = {PurePosixPath(entry.name).parts[0] for entry in archive.getmembers()}
            if len(roots) != 1:
                raise ValueError("source archive requires one top-level project directory")
            for entry in archive.getmembers():
                if entry.isdir():
                    continue
                if not entry.isfile() or entry.size > MAX_FILE_BYTES:
                    raise ValueError(f"linked, non-file or oversized source artifact: {entry.name}")
                source = archive.extractfile(entry)
                name = "/".join(PurePosixPath(entry.name).parts[1:])
                inspect_entry(name, source.read(), wheel=False, size=entry.size)
                names.append(name)
                total += entry.size
        required = {"pyproject.toml", "INSTALL.md", "replay_tool/go.mod", "replay_tool/go.sum",
                    "replay_tool/main.go", "tests/fixtures/opendota_match_sample.json",
                    ".github/workflows/tests.yml", "scripts/check_installed.py"}
    else:
        raise ValueError("expected wheel or tar.gz source distribution")
    if len(set(names)) != len(names):
        raise ValueError("duplicate archive entry")
    if total > MAX_ARCHIVE_BYTES:
        raise ValueError("unpacked archive exceeds source-transfer size budget")
    if not required <= set(names):
        raise ValueError(f"required distributable resources missing: {sorted(required - set(names))}")
    return {"archive": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "files": len(names), "unpacked_bytes": total}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", default="dist")
    args = parser.parse_args(argv)
    directory = Path(args.directory)
    wheels, sources = sorted(directory.glob("*.whl")), sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        parser.error("expected exactly one wheel and one source distribution; use a fresh build directory")
    for path in wheels + sources:
        print(audit_archive(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
