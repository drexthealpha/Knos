"""`knos bench --chain URL`: the 0.3 bars that need a chain, run on a local validator with the devnet-deployed SAS and
Lighthouse (scripts/devchain.sh start). Every number here is re-runnable; the definitions are in docs/BENCH.md.

  security   3 machines x 3 vendor hooks (Claude Code, Codex, Cursor) race for 4 files, N rounds. Arms: none;
             advisory (Agent Mail-style reservations: each agent checks and respects them with probability 0.9, and
             the commit guard it offers is modelled: a commit touching a file someone else reserved is refused);
             knos (the real team guard, live.check, against the chain). Metric 1: conflicting writes to working
             trees (a write to a file another agent also wrote that round). Metric 2: conflicting commits.
  speed      the guard's hot path: an agent editing its own claimed file 20 times per claim. p50/p95 of the decision
             in ms, and the share of edits that waited on the chain (the first, which places the claim).
  cost       what a claim costs on chain: the fee (lamports) and the refundable rent while it is live.
  budget     overspend attempts signed directly with an agent's delegate key (no Knos code involved), on Solana:
             each must be rejected by the Token program.
"""

from __future__ import annotations

import random
import secrets
import statistics
import tempfile
import threading
import time
from pathlib import Path

from solders.keypair import Keypair

LAMPORTS = 1_000_000_000


def _funded(url: str, sol: float) -> Keypair:
    from .team import rpc
    k = Keypair()
    rpc.airdrop(url, k.pubkey(), int(sol * LAMPORTS))
    return k


def _team(url: str, machines: int):
    from .team import config, registry
    owner = _funded(url, 5)
    keys = [_funded(url, 3) for _ in range(machines)]
    made = registry.create(url, owner, [owner.pubkey(), *[k.pubkey() for k in keys]])
    tf = config.TeamFile("localnet", made.credential, made.name, owner.pubkey(), made.schemas, secrets.token_bytes(32),
                         url)
    return tf, secrets.token_bytes(32), keys


def security(url: str, rounds: int = 200, compliance: float = 0.9, seed: int = 3, read_s: float = 1.0) -> dict:
    import os

    from .team import live
    os.environ["KNOS_NO_MIRROR"] = "1"
    live.DIRECT_READ_S = read_s  # the guard's budget for a direct read when the mirror is stale (product: 1 s)
    rng = random.Random(seed)
    files = ["src/billing/tax.py", "src/billing/invoice.py", "src/auth/login.py", "src/api/routes.py"]
    hosts = ["claude", "codex", "cursor"]
    tf, salt, keys = _team(url, 3)
    work = Path(tempfile.mkdtemp(prefix="knos-bench-"))
    machines = []
    for i, k in enumerate(keys):
        cls = type(f"Runtime{i}", (live.Runtime,), {})
        rt = cls(work / f"m{i}", tf, k, salt, f"machine-{i}")
        d = work / f"m{i}" / "mirror"
        d.mkdir(parents=True, exist_ok=True)
        cls.dir = property(lambda self, d=d: d)
        machines.append(rt)
    agents = [(m, h) for m in machines for h in hosts]
    out = {arm: {"writes": 0, "conflicting_writes": 0, "commits": 0, "conflicting_commits": 0}
           for arm in ("none", "advisory", "knos")}
    for r in range(rounds):
        picks = [rng.choice(files) for _ in agents]
        # none: everyone writes
        _tally(out["none"], [(i, f) for i, f in enumerate(picks)], [(i, f) for i, f in enumerate(picks)])
        # advisory: reserve-then-write when compliant; the commit guard refuses commits of files reserved by others
        reserved: dict[str, int] = {}
        order = list(range(len(agents)))
        rng.shuffle(order)
        writes = []
        for i in order:
            f = picks[i]
            if rng.random() < compliance:
                if f in reserved and reserved[f] != i:
                    continue
                reserved.setdefault(f, i)
            writes.append((i, f))
        commits = [(i, f) for i, f in writes if reserved.get(f, i) == i]
        _tally(out["advisory"], writes, commits)
        # knos: all nine race through the real guard at once
        allowed: list[tuple[int, str]] = []
        lock = threading.Lock()

        def go(i: int) -> None:
            m, h = agents[i]
            d = live.check(m, picks[i], h, f"r{r}-a{i}", verdict_s=60)
            if d.allow:
                with lock:
                    allowed.append((i, picks[i]))
                    if d.warning:  # allowed without the chain's word (the RPC was too slow or down): fail-open
                        out["knos"]["fail_open"] = out["knos"].get("fail_open", 0) + 1
                        out["knos"].setdefault("fail_open_reasons", {})[d.warning[:60]] =                             out["knos"].get("fail_open_reasons", {}).get(d.warning[:60], 0) + 1

        ts = [threading.Thread(target=go, args=(i,)) for i in range(len(agents))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        _tally(out["knos"], allowed, allowed)
        for i, (m, h) in enumerate(agents):
            try:
                live.release_all(m, h, f"r{r}-a{i}")
            except Exception:  # noqa: BLE001 - lapses at its lease; the next round uses new sessions anyway
                pass
    out["rounds"], out["agents"], out["files"], out["compliance"] = rounds, len(agents), len(files), compliance
    out["direct_read_budget_s"] = read_s
    return out


def _tally(acc: dict, writes: list[tuple[int, str]], commits: list[tuple[int, str]]) -> None:
    for kind, rows in (("writes", writes), ("commits", commits)):
        by_file: dict[str, int] = {}
        for _, f in rows:
            by_file[f] = by_file.get(f, 0) + 1
        acc[kind] += len(rows)
        acc["conflicting_" + kind] += sum(n - 1 for n in by_file.values() if n > 1)


def speed(url: str, units_n: int = 5, edits_per_unit: int = 20) -> dict:
    import os

    from .team import live
    os.environ["KNOS_NO_MIRROR"] = "1"
    tf, salt, keys = _team(url, 1)
    work = Path(tempfile.mkdtemp(prefix="knos-bench-speed-"))
    cls = type("RuntimeS", (live.Runtime,), {})
    rt = cls(work, tf, keys[0], salt, "machine-s")
    d = work / "mirror"
    d.mkdir(parents=True, exist_ok=True)
    cls.dir = property(lambda self: d)
    times, delayed = [], 0
    for u in range(units_n):
        rel = f"src/mod{u}/file.py"
        for e in range(edits_per_unit):
            if e == 1:
                live.sync(rt)  # what the background mirror keeps doing every 3 s
            t = time.perf_counter()
            got = live.check(rt, rel, "claude", "speed-session", verdict_s=60)
            ms = (time.perf_counter() - t) * 1000
            assert got.allow
            if e == 0:
                delayed += 1
            else:
                times.append(ms)

    def pct(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]
    return {"edits": units_n * edits_per_unit, "p50_ms": round(pct(times, 50), 1), "p95_ms": round(pct(times, 95), 1),
            "median_added_ms": round(statistics.median(times), 1),
            "delayed_share": round(delayed / (units_n * edits_per_unit), 3)}


def cost(url: str) -> dict:
    from .team import rpc, schemas, units
    data = schemas.ClaimData(b"\0" * 32, b"\0" * 16, b"\0" * 32, 0, units.FILE).encode()
    size = 1 + 32 * 3 + 4 + len(data) + 32 + 8 + 32
    rent = rpc.call(url, "getMinimumBalanceForRentExemption", [size])
    return {"claim_account_bytes": size, "rent_lamports_refundable": rent, "fee_lamports": 5000,
            "rent_sol": rent / LAMPORTS, "fee_sol": 5000 / LAMPORTS}


def budget(url: str, attempts: int = 200) -> dict:
    from .pro import sol_budget as sb
    from .team import rpc
    from solders.system_program import CreateAccountParams, create_account
    owner, agent = _funded(url, 3), _funded(url, 2)
    mint = Keypair()
    lam = rpc.call(url, "getMinimumBalanceForRentExemption", [sb.MINT_SIZE])
    rpc.send(url, [create_account(CreateAccountParams(from_pubkey=owner.pubkey(), to_pubkey=mint.pubkey(),
                                                      lamports=lam, space=sb.MINT_SIZE, owner=sb.TOKEN_PROGRAM)),
                   sb.initialize_mint2(mint.pubkey(), 6, owner.pubkey())], owner, [mint])
    vault = Keypair()
    rpc.send(url, sb.new_vault_ixs(url, owner.pubkey(), owner.pubkey(), vault, mint.pubkey()), owner, [vault])
    rpc.send(url, [sb.mint_to_checked(mint.pubkey(), vault.pubkey(), owner.pubkey(), 1_000_000_000, 6),
                   sb.approve_checked(vault.pubkey(), mint.pubkey(), agent.pubkey(), owner.pubkey(), 5_000_000, 6)],
             owner)
    shop = Keypair().pubkey()
    rpc.send(url, [sb.create_ata_idempotent(owner.pubkey(), shop, mint.pubkey())], owner)
    dest = sb.ata(shop, mint.pubkey())
    rng = random.Random(9)
    rejected = moved_past = 0
    for _ in range(attempts):
        amount = rng.randint(5_000_001, 50_000_000)
        try:
            rpc.send(url, [sb.transfer_checked(vault.pubkey(), mint.pubkey(), dest, agent.pubkey(), amount, 6)], agent)
            moved_past += amount
        except rpc.RpcError:
            rejected += 1
    left = sb.status(url, vault.pubkey())
    return {"attempts": attempts, "rejected": rejected, "moved_past_limit_units": moved_past,
            "vault_units_after": left["amount"]}


def run(url: str, rounds: int = 200, quick: bool = False, say=print) -> dict:
    out = {}
    say("cost ...")
    out["cost"] = cost(url)
    say("budget (Solana delegate) ...")
    out["budget"] = budget(url, 20 if quick else 200)
    say("speed ...")
    out["speed"] = speed(url, 2 if quick else 5)
    say(f"security ({20 if quick else rounds} rounds) ...")
    out["security"] = security(url, 20 if quick else rounds)
    return out
