"""Several agents reaching a repo none of them has read yet.

The claim tests cover two agents fighting over one topic in a store that
already exists. This covers the moment before that: the store does not exist,
and more than one agent opens it at once.

The first connection to a new store switches it to WAL, and that pragma wants
the database briefly to itself. `busy_timeout` does not cover it, so without a
retry one agent raises `database is locked` and dies while the other is still
creating the file. That is the first thing that happens when someone installs
knos and starts two agents, so it has to hold.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from knos import paths

AGENTS = 6


@pytest.mark.critical
def test_several_agents_can_open_a_store_that_does_not_exist_yet(
    knos_home, repo, tmp_path
):
    script = tmp_path / "open.py"
    script.write_text(
        "import sys\n"
        "from knos.memory import Memory\n"
        "with Memory(sys.argv[1]) as mem:\n"
        "    mem.claims()\n"
        "print('ok')\n",
        encoding="utf-8",
    )

    store = paths.store_for(Path(repo))
    if store.exists():
        store.unlink()
    assert not store.exists(), "the point is that nobody has read this repo yet"

    def start(_: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), str(repo)],
            capture_output=True, text=True, encoding="utf-8",
        )

    with ThreadPoolExecutor(max_workers=AGENTS) as pool:
        done = list(pool.map(start, range(AGENTS)))

    failed = [d.stderr for d in done if d.returncode != 0]
    assert not failed, (
        f"{len(failed)} of {AGENTS} agents could not open the store:\n"
        + "\n".join(failed[:2])
    )
    assert all(d.stdout.strip() == "ok" for d in done)
    assert store.exists()
