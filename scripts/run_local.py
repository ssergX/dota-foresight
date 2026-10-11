"""Run the project with an optional workspace-local dependency directory."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
local_packages = root / ".runtime" / "python-packages"
if local_packages.is_dir():
    sys.path.insert(0, str(local_packages))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dota_coach.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
