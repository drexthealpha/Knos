"""Several agents reaching a repo none of them has read yet.

The claim tests cover agents fighting over one file in stores that already exist. This covers the moment before
that: neither the memory store nor the claim list exists, and more than one agent opens them at once.

The first connection to a new SQLite file switches it to WAL and creates its tables, and both want the database
briefly to itself. `busy_timeout` does not always cover that, so without a retry one agent raises `database is
locked` and dies while another is still creating the file. That is the first thing that happens when someone
installs knos and starts two agents, so it has to hold.

Rewritten for 0.2.0: claims moved out of the memory store into claims.db, so each agent now opens both, then claims
a file of its own. Nothing was dropped; the new assertion is that no agent's claim was lost in the scramble.
"""

from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from knos import paths
from knos.claims import Claims, claims_db

AGENTS = 6


@pytest.mark.critical
def test_several_agents_can_open_stores_that_do_not_exist_yet(knos_home, repo, tmp_path):
    script = tmp_path / "open.py"
    script.write_text(
        "import sys\n"
        "from knos.claims import Claims\n"
        "from knos.identity import Agent\n"
        "from knos.memory import Memory\n"
        "repo, n = sys.argv[1], sys.argv[2]\n"
        "with Memory(repo) as mem:\n"
        "    mem.journal()\n"
        "with Claims(repo) as c:\n"
        "    took, conflict, mine = c.take(Agent(host='agent-' + n, session=n), 'mine ' + n, ['src/own_' + n + '.py'])\n"
        "print('ok' if took else 'refused')\n",
        encoding="utf-8",
    )

    store = paths.store_for(Path(repo))
    claims = claims_db(Path(repo))
    for f in (store, claims):
        if f.exists():
            f.unlink()
    assert not store.exists() and not claims.exists(), "the point is that nobody has read this repo yet"

    def start(n: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), str(repo), str(n)],
            capture_output=True, text=True, encoding="utf-8",
        )

    with ThreadPoolExecutor(max_workers=AGENTS) as pool:
        done = list(pool.map(start, range(AGENTS)))

    failed = [d.stderr for d in done if d.returncode != 0]
    assert not failed, (
        f"{len(failed)} of {AGENTS} agents could not open the stores:\n"
        + "\n".join(failed[:2])
    )
    assert all(d.stdout.strip().splitlines()[-1] == "ok" for d in done), [d.stdout for d in done]
    assert store.exists() and claims.exists()

    with Claims(repo) as c:
        live = c.live()
    assert sorted(x.globs[0] for x in live) == sorted(f"src/own_{n}.py" for n in range(AGENTS)), (
        "an agent was told it had its file but the claim is not in the list"
    )
