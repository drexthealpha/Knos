"""Where knos keeps its data. Never inside the repo it reads."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def home() -> Path:
    """The knos data directory. Override with KNOS_HOME."""
    override = os.environ.get("KNOS_HOME")
    root = Path(override) if override else Path.home() / ".knos"
    root.mkdir(parents=True, exist_ok=True)
    return root


def slug(repo: Path) -> str:
    """A stable short name for a repo path."""
    real = str(Path(repo).resolve()).lower()
    digest = hashlib.sha256(real.encode()).hexdigest()[:10]
    return f"{Path(real).name}-{digest}"


def store_for(repo: Path) -> Path:
    """The sqlite file holding memory for one repo."""
    d = home() / slug(repo)
    d.mkdir(parents=True, exist_ok=True)
    return d / "memory.db"


def pointer() -> Path:
    """File recording the repo most recently pointed at."""
    return home() / "pointed"


def remember_pointed(repo: Path) -> None:
    pointer().write_text(str(Path(repo).resolve()), encoding="utf-8")


def current_repo() -> Path | None:
    p = pointer()
    if not p.exists():
        return None
    raw = p.read_text(encoding="utf-8").strip()
    return Path(raw) if raw else None
