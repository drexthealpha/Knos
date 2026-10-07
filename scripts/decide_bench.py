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
    offline     `knos.decide.offline`: the signature against KEPT key lists, the claims and the terms; nothing read
    chain check `knos.decide.chain_check` and `after_chain`: one request to the (simulated) chain, then the answer
    free check  `knos.decide.checks`: the conclusions of the named checks, no token and no chain

Each row has its own n. p95 is by nearest rank. tests/test_decide.py runs the same measurement with fewer samples and
holds the two targets: a cached decision under 200 ms and evidence to decision under 2 s, both at p95. Both are
bounds on this machine with no network; neither is a claim about a cluster.

`cold(n)` times the whole command in a new process each time (`python -m knos.decide --token-file ... --no-chain`:
interpreter start, imports, the offline decision, the receipt written). `round_trips()` counts requests through an
endpoint that only counts: the relay's whole precheck (what `knos decide` asked of a cluster in 0.3.18) against the
one request of `chain_check`. The 250 ms figure in the table is a TARGET for the offline decision, not a measurement.
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
TARGETS = {"cached": 200.0, "fresh": 2000.0, "local": 250.0}        # milliseconds at p95: targets, on one machine with no network
DEVNET = ("On devnet, four runs of the 0.3.18 command (the relay's whole precheck, on real fund tokens over the shared public RPC) took 4.3 to 32.6 s: "
          "a first reading, not a sample. The 0.3.19 split was timed there on 24 real tokens: the tables after this block.")
ROWS = (("fresh, accepted", "fresh", "a fund token never seen: signature checked, chain read"),
        ("fresh, rejected", "fresh", "a pay token for an issue with nothing in escrow: signature checked, chain read"),
        ("cached, accepted", "cached", "the same fund token again, the chain's answers kept (`knos.decide.Cached`)"),
        ("no chain", "cached", "the token alone, `ledger=None`: insufficient evidence, or rejected"),
        ("free check", "cached", "the conclusions of three named checks, no token"),
        ("offline, accepted", "local", "the fund token against kept key lists: signature, claims, terms; nothing read (`knos.decide.offline`)"),
        ("chain check", "local", "one request to the simulated chain and the updated answer (`knos.decide.chain_check`, `after_chain`)"))


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
    from knos.settle.v2 import relay
    c, net = t2._setup(Chain())
    keys = {relay.oidc.ISSUERS[k]: v for k, v in t2.JWKS.items() if k in relay.oidc.ISSUERS}
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
        first = timed("offline, accepted", lambda: decide.provisional(decide.offline(fund, t2.TERMS, keys=keys, now=now), at=now, jwt=fund, terms=t2.TERMS))
        d = decide.offline(fund, t2.TERMS, keys=keys, now=now)
        timed("chain check", lambda: decide.provisional(decide.after_chain(d, decide.chain_check(fund, ledger=net), fund), at=now, jwt=fund, terms=t2.TERMS,
                                                        updates=decide.digest(first)))
    return {"rows": {name: spread(ms) for name, ms in out.items()}, "decisions": {name: sorted(v) for name, v in said.items()}, "machine": machine()}


class Counting:
    """An endpoint that only counts: every call of a method of the ledger is one request to an RPC endpoint."""

    def __init__(self, ledger) -> None:
        self.ledger, self.calls, self.url = ledger, [], "counting"

    def __getattr__(self, name: str):
        got = getattr(self.ledger, name)
        if not callable(got):
            return got

        def asked(*a, **k):
            self.calls.append(name)
            return got(*a, **k)
        return asked


def round_trips() -> dict:
    """{before: {calls, n}, after: {calls, n}} for one fund token in a process that has asked the chain nothing yet."""
    import test_relay2 as t2
    from _pay2 import Chain

    from knos import decide
    from knos.settle.v2 import relay
    c, net = t2._setup(Chain())
    fund = t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user())
    relay.forget()
    before, after = Counting(net), Counting(net)
    decide.token(fund, t2.TERMS, ledger=before, payer=c.payer, jwks=t2.JWKS)        # no `now`: the chain's clock is read too, as the command did
    decide.chain_check(fund, ledger=after)
    return {"before": {"n": len(before.calls), "calls": before.calls}, "after": {"n": len(after.calls), "calls": after.calls}}


def cold(n: int = 10) -> dict:
    """{n, p50, p95, max, inside: {...}, decisions}: the whole offline command, a new process each time, in
    milliseconds. `inside` is what the command itself reports (from its first line to the receipt)."""
    import subprocess
    import tempfile

    import test_relay2 as t2
    from _pay2 import Chain

    from knos import decide
    from knos.settle.v2 import relay
    c, _net = t2._setup(Chain())
    whole, inside, said = [], [], set()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "token.txt").write_text(t2.faucet_jwt(c, t2.issue(), t2.user(), t2.user()), encoding="utf-8")
        (d / "terms.json").write_bytes(t2.TERMS)
        decide.keep_keys({relay.oidc.ISSUERS[k]: v for k, v in t2.JWKS.items() if k in relay.oidc.ISSUERS}, 0, d / "keys.json")
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        for _ in range(n):
            began = time.perf_counter()
            got = subprocess.run([sys.executable, "-m", "knos.decide", "--token-file", str(d / "token.txt"), "--terms-file", str(d / "terms.json"),
                                  "--keys-file", str(d / "keys.json"), "--no-chain", "--out", str(d / "provisional.json")],
                                 capture_output=True, encoding="utf-8", env=env, check=False)
            whole.append((time.perf_counter() - began) * 1000)
            hit = re.search(r"decided in (\d+) ms", got.stderr)
            inside.append(float(hit.group(1)) if hit else float("nan"))
            said.add(got.stdout.strip().split(". Not paid")[0])
        (d / "checks.json").write_text('[{"name": "test", "conclusion": "passed"}]', encoding="utf-8")
        token = ["--token-file", str(d / "token.txt"), "--terms-file", str(d / "terms.json"), "--keys-file", str(d / "keys.json"), "--no-chain", "--out", str(d / "p.json")]
        imports = {"token": imported(token, env), "checks": imported(["--checks-file", str(d / "checks.json"), "--out", str(d / "c.json")], env)}
    return {**spread(whole), "inside": spread(inside), "decisions": sorted(said), "imports": imports}


def imported(args: list[str], env: dict, n: int = 5) -> dict:
    """What `python -X importtime -m knos.decide <args>` imports, over `n` new processes: {ms: the median of the sum of
    every module's own import time, modules, typer, relay}. `typer`: whether the command-line library (or click or
    rich under it) was loaded; `relay`: whether the relay's rules were."""
    import statistics
    import subprocess
    took, names = [], []
    for _ in range(n):
        got = subprocess.run([sys.executable, "-X", "importtime", "-m", "knos.decide", *args], capture_output=True, encoding="utf-8", env=env, check=False)
        rows = [line.split("|") for line in got.stderr.splitlines() if line.startswith("import time:") and "[us]" not in line]
        took.append(sum(int(r[0].split(":")[1]) for r in rows) / 1000)
        names = [r[2].strip() for r in rows]
    return {"ms": statistics.median(took), "modules": len(names), "typer": any(m.split(".")[0] in ("typer", "click", "rich") for m in names),
            "relay": "knos.settle.v2.relay" in names}


def split_lines(trips: dict, c: dict) -> list[str]:
    """What stands under the table: the requests before and after the split, and the cold command."""
    ms = lambda v: f"{v:.0f} ms"  # noqa: E731
    count = lambda calls: ", ".join(f"{calls.count(k)} {k}" for k in dict.fromkeys(calls))  # noqa: E731
    return ["", f"Requests to an RPC endpoint for one fund token, counted through an endpoint that only counts (`round_trips()`): before the split, the "
            f"relay's whole precheck made {trips['before']['n']} calls of the ledger ({count(trips['before']['calls'])}), each at least one request, one after another, and fetched the issuer's key list "
            f"besides; the chain check makes {trips['after']['n']} ({count(trips['after']['calls'])}: one getMultipleAccounts), with a timeout of 2 s, and the "
            "offline half makes none.", "",
            f"The whole offline command in a new process each time (`python -m knos.decide --token-file ... --no-chain`: interpreter start, imports, decision, "
            f"receipt written), n {c['n']}: p50 {ms(c['p50'])}, p95 {ms(c['p95'])}, slowest {ms(c['max'])}; of that, inside the command p50 {ms(c['inside']['p50'])}, "
            f"p95 {ms(c['inside']['p95'])}. Every run said: {'; '.join(c['decisions'])} (the simulator's clock is not this machine's, so its token is past its "
            "time for the command; the signature and the key lookup are the same work). The 250 ms target is for the warm offline decision; the cold command "
            + ("does not meet it here." if c["inside"]["p95"] > 250 else "meets it here inside the command, and not with the interpreter's own start counted."
               if c["p95"] > 250 else "meets it here."),
            *imports_lines(c.get("imports"))]


def imports_lines(i: dict | None) -> list[str]:
    """What the standalone command imports (`python -X importtime`), and what it does not."""
    if not i:
        return []
    yes = lambda b: "loaded" if b else "not loaded"  # noqa: E731
    t, k = i["token"], i["checks"]
    return ["", "What `python -m knos.decide` imports, by `python -X importtime` (the median of 5 new processes, each module's own time summed): deciding on a token offline, "
            f"{t['modules']} modules in {t['ms']:.0f} ms, typer {yes(t['typer'])}, the relay's rules {yes(t['relay'])} (they are the rules it decides by); "
            f"the free check, {k['modules']} modules in {k['ms']:.0f} ms, typer {yes(k['typer'])}, the relay's rules {yes(k['relay'])}. Before 0.3.19 the same "
            "command loaded typer for every answer: on this machine, idle, 151 modules in 94 ms for the free check and 268 in 165 ms for a token."]


def table(r: dict, day: str) -> list[str]:
    """The block of docs/BENCH.md."""
    ms = lambda v: "under 0.1 ms" if v < 0.05 else f"{v:.1f} ms" if v < 100 else f"{v:.0f} ms"  # noqa: E731
    out = [f"Measured on {day} by `python scripts/decide_bench.py --write` on this machine: {r['machine']}. The chain is LiteSVM with the "
           "committed test builds, in the same process: no network. " + DEVNET, "",
           "| decision | what is timed | n | p50 | p95 | slowest | every sample said | target at p95 (a target, not a measurement) |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, target, what in ROWS:
        s = r["rows"][name]
        out.append(f"| {name} | {what} | {s['n']} | {ms(s['p50'])} | {ms(s['p95'])} | {ms(s['max'])} | {', '.join(w.replace('_', ' ') for w in r['decisions'][name])} | "
                   f"under {TARGETS[target]:.0f} ms |")
    if r.get("trips") and r.get("cold"):
        out += split_lines(r["trips"], r["cold"])
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
    ap.add_argument("--cold", type=int, default=10, help="new processes for the cold command (default 10)")
    ap.add_argument("--write", action="store_true", help="rewrite the block in docs/BENCH.md")
    a = ap.parse_args(argv)
    r = measure(max(1, a.n))
    r["trips"], r["cold"] = round_trips(), cold(a.cold)
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
            "machine": r["machine"], "round_trips": {k: v["n"] for k, v in r["trips"].items()},
            "cold": {k: round(v, 1) for k, v in r["cold"].items() if isinstance(v, float)},
            "cold_imports": {name: {k: (round(v, 1) if isinstance(v, float) else v) for k, v in row.items()} for name, row in r["cold"]["imports"].items()}, "rows": {name: {k: round(v, 3) if isinstance(v, float) else v for k, v in row.items()} for name, row in r["rows"].items()}}
        load.write(doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
