"""How long `knos decide` takes, measured here, and the table of it in docs/BENCH.md ("Decision time").

    python scripts/decide_bench.py            # measure and print
    python scripts/decide_bench.py --write    # and rewrite the block in docs/BENCH.md and the decision clock of docs/LOAD.md

What is timed is `knos.decide.token` (the relay's own reads, `knos.settle.v2.relay.precheck`) followed by
`knos.decide.provisional`, from the moment the token is in hand to the provisional receipt. The chain is LiteSVM with
the committed test builds of the programs (tests/_pay2.py), so a read costs no network: this is the time Knos's own
code takes, on this machine. On a cluster every read of the chain adds a round trip to an RPC endpoint, and that is
NOT in these numbers and has not been measured.

    fresh       a token never seen: the issuer's signature is checked and the chain is read
    cached      the same question again through `knos.decide.Cached`: answered from what the chain said before
    no chain    `ledger=None`: the token alone (it can be rejected, never accepted)
    free check  `knos.decide.checks`: the conclusions of the named checks, no token and no chain

Each row has its own n. p95 is by nearest rank. tests/test_decide.py runs the same measurement with fewer samples and
holds the two targets: a cached decision under 200 ms and evidence to decision under 2 s, both at p95.
"""
from __future__ import annotations

import argparse
import math
import os
import platform
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

DOC = ROOT / "docs" / "BENCH.md"
OPEN, CLOSE = "<!-- decide:time -->", "<!-- /decide:time -->"
TARGETS = {"cached": 200.0, "fresh": 2000.0}        # milliseconds at p95
ROWS = (("fresh, accepted", "fresh", "a fund token never seen: signature checked, chain read"),
        ("fresh, rejected", "fresh", "a pay token for an issue with nothing in escrow: signature checked, chain read"),
        ("cached, accepted", "cached", "the same fund token again, the chain's answers kept (`knos.decide.Cached`)"),
        ("no chain", "cached", "the token alone, `ledger=None`: insufficient evidence, or rejected"),
        ("free check", "cached", "the conclusions of three named checks, no token"))


def spread(ms: list[float]) -> dict:
    took = sorted(ms)
    return {"n": len(took), "p50": statistics.median(took), "p95": took[max(0, math.ceil(0.95 * len(took)) - 1)], "max": took[-1]}


def machine() -> str:
    cpu = ""
    try:
        cpu = next((ln.split(":", 1)[1].strip() for ln in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines() if ln.startswith("model name")), "")
    except OSError:
        pass
    return f"{cpu or platform.processor() or platform.machine()}, {os.cpu_count()} CPUs, {platform.system()} {platform.machine()}, Python {platform.python_version()}"


def measure(n: int = 40) -> dict:
    """{row: {n, p50, p95, max} in milliseconds, "decisions": {row: the decision every sample gave}}."""
    import test_relay2 as t2
    from _pay2 import Chain

    from knos import decide
    c, net = t2._setup(Chain())
    out: dict[str, list[float]] = {name: [] for name, _target, _what in ROWS}
    said: dict[str, set[str]] = {name: set() for name in out}

    def timed(name: str, fn) -> dict:
        began = time.perf_counter()
        doc = fn()
        out[name].append((time.perf_counter() - began) * 1000)
        said[name].add(doc["decision"])
        return doc

    for _ in range(n):
        org, repo, issue = t2.user(), t2.user(), t2.issue()
        fund = t2.faucet_jwt(c, issue, org, repo)
        now = c.now()
        timed("fresh, accepted", lambda: decide.provisional(decide.token(fund, t2.TERMS, ledger=net, payer=c.payer, jwks=t2.JWKS, now=now),
                                                            at=now, jwt=fund, terms=t2.TERMS))
        nothing = t2.pay_jwt(c, repo, issue, t2.user())
        timed("fresh, rejected", lambda: decide.provisional(decide.token(nothing, None, ledger=net, payer=c.payer, jwks=t2.JWKS, now=now), at=now, jwt=nothing))
        kept = decide.Cached(net)
        decide.token(fund, t2.TERMS, ledger=kept, payer=c.payer, jwks=t2.JWKS, now=now)       # the first read fills it; not timed in this row
        timed("cached, accepted", lambda: decide.provisional(decide.token(fund, t2.TERMS, ledger=kept, payer=c.payer, jwks=t2.JWKS, now=now),
                                                             at=now, jwt=fund, terms=t2.TERMS))
        timed("no chain", lambda: decide.provisional(decide.token(fund, t2.TERMS, jwks=t2.JWKS, now=now), at=now, jwt=fund, terms=t2.TERMS))
        timed("free check", lambda: decide.provisional(decide.checks([{"name": "build", "conclusion": "passed"}, {"name": "lint", "conclusion": "passed"},
                                                                      {"name": "test", "conclusion": "passed"}]), at=now,
                                                       subject={"repository": "octo/widgets", "commit": "a" * 40, "pull_request": 7}))
    return {"rows": {name: spread(ms) for name, ms in out.items()}, "decisions": {name: sorted(v) for name, v in said.items()}, "machine": machine()}


def table(r: dict, day: str) -> list[str]:
    """The block of docs/BENCH.md."""
    ms = lambda v: "under 0.1 ms" if v < 0.05 else f"{v:.1f} ms" if v < 100 else f"{v:.0f} ms"  # noqa: E731
    out = [f"Measured on {day} by `python scripts/decide_bench.py --write` on this machine: {r['machine']}. The chain is LiteSVM with the "
           "committed test builds, in the same process: no network. A cluster adds a round trip to its RPC endpoint for every read of the chain; "
           "that has not been measured, on devnet or anywhere.", "",
           "| decision | what is timed | n | p50 | p95 | slowest | every sample said | target at p95 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, target, what in ROWS:
        s = r["rows"][name]
        out.append(f"| {name} | {what} | {s['n']} | {ms(s['p50'])} | {ms(s['p95'])} | {ms(s['max'])} | {', '.join(w.replace('_', ' ') for w in r['decisions'][name])} | "
                   f"under {TARGETS[target]:.0f} ms |")
    return out


def render(doc: str, lines: list[str]) -> str:
    block = "\n".join([OPEN, *lines, CLOSE])
    if OPEN in doc:
        return re.sub(re.escape(OPEN) + r".*?" + re.escape(CLOSE), lambda _m: block, doc, flags=re.S)
    head = ("\n## Decision time\n\n"
            "`knos decide` answers accepted, rejected or insufficient evidence the moment the forge's signed token is in hand, by the reads a relay makes "
            "before it spends a fee (`knos.settle.v2.relay.precheck`), and writes a provisional receipt. A provisional receipt never authorises payment; "
            "the final receipt names it and replaces it ([LOAD.md](LOAD.md), \"The five clocks\").\n\n")
    return doc.rstrip("\n") + "\n" + head + block + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--n", type=int, default=40, help="samples for each row (default 40)")
    ap.add_argument("--write", action="store_true", help="rewrite the block in docs/BENCH.md")
    a = ap.parse_args(argv)
    r = measure(max(1, a.n))
    day = time.strftime("%Y-%m-%d", time.gmtime())
    lines = table(r, day)
    print("\n".join(lines))
    if a.write:
        DOC.write_text(render(DOC.read_text(encoding="utf-8"), lines), encoding="utf-8")
        # the same sample for the five clocks of docs/LOAD.md (docs/load.json `relay.decision`; scripts/load.py renders it)
        sys.path.insert(0, str(ROOT / "scripts"))
        import load
        doc = load.load()
        doc.setdefault("relay", {})["decision"] = {
            "source": f"`python scripts/decide_bench.py --write`, run on {day}: {a.n} decisions for each row, the chain simulated in the same process (LiteSVM, no network)",
            "machine": r["machine"], "rows": {name: {k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()} for name, row in r["rows"].items()}}
        load.write(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
