from __future__ import annotations

from pathlib import Path

_PRINCIPLES_PATH = Path(__file__).with_name("principles.md")
_DEFAULT = "Разбирай процесс и решения, а не исход. Дай конкретное проверяемое действие."


def _load_sections(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    sections: dict[str, str] = {}
    key: str | None = None
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if key is not None:
                sections[key] = "\n".join(buf).strip()
            key = line[3:].strip()
            buf = []
        elif key is not None:
            buf.append(line)
    if key is not None:
        sections[key] = "\n".join(buf).strip()
    return sections


def principles_for(leak_key: str, path: Path = _PRINCIPLES_PATH) -> str:
    section = _load_sections(path).get(leak_key)
    return section if section else _DEFAULT
