"""Where Knos keeps its own small files on this machine."""

from __future__ import annotations

import os
from pathlib import Path


def home() -> Path:
    """The Knos data directory (hook state, the relay's fee key). Override with KNOS_HOME."""
    override = os.environ.get("KNOS_HOME")
    root = Path(override) if override else Path.home() / ".knos"
    root.mkdir(parents=True, exist_ok=True)
    return root
