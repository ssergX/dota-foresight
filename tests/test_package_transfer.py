from pathlib import Path
import tomllib
import zipfile

import pytest

from scripts.check_package import audit_archive, inspect_entry

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", [".runtime/pkg.py", "out/replay.json", "cache/a.json", "../secret.py",
                                    "/absolute.py", "dota_coach/replay.dem", "dota_coach/tool.exe"])
def test_archive_audit_blocks_runtime_private_and_unsafe_paths(name):
    with pytest.raises(ValueError):
        inspect_entry(name, b"", wheel=True)


def test_package_audit_does_not_publish_personal_absolute_paths():
    with pytest.raises(ValueError, match="personal absolute path"):
        private = b"path = 'C:" + bytes([92]) + b"Users" + bytes([92]) + b"actual-person" + bytes([92]) + b"data.json'"
        inspect_entry("scripts/example.py", private, wheel=False)
    inspect_entry("scripts/example.py", b"path = 'out/data.json'", wheel=False)


def test_package_audit_rejects_large_replay_disguised_as_json():
    with pytest.raises(ValueError, match="oversized"):
        inspect_entry("tests/fixtures/a.json", b"", wheel=False, size=16_000_000)


def test_missing_installed_resources_blocks_wheel_transfer(tmp_path):
    wheel = tmp_path / "fixture.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("dota_coach/cli.py", "pass")
    with pytest.raises(ValueError, match="resources missing"):
        audit_archive(wheel)


def test_build_manifest_is_explicit_and_contains_no_local_corpus_or_git_assumption():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build = config["tool"]["hatch"]["build"]["targets"]
    assert build["wheel"]["packages"] == ["src/dota_coach"]
    assert "/src" in build["sdist"]["include"]
    assert "/tests" in build["sdist"]["include"]
    assert not any("out" in name or ".runtime" in name or ".git/" in name for name in build["sdist"]["include"])
    dependencies = config["project"]["dependencies"]
    assert any(dep.startswith("opencv-python-headless") for dep in dependencies)
    assert not any(dep.startswith("opencv-python>") for dep in dependencies)
