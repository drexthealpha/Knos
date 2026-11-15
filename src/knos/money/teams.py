"""Usage metering per team and per agent, invoices checked against the chain, and the team dashboard's numbers.

Who pays: a TEAM that runs coding agents (Claude Code, Codex, Hermes, Devin, a Nemotron agent on Token Factory...).
What it pays (config/fees.yaml, read through knos.money.fees_config; nothing here types a price):

    bounty_platform  a planned share of a bounty the team funded in knos_pay (held until its test passes); the program
                     takes its on-chain fee (`onchain`: rate_bps, floor_usd) at payout, the rest would be invoiced off chain

Nobody pays for a check: a verification and an x402 test payment are counted in the usage, never put on an invoice.

The usage record is an append-only JSONL file (one event a line, `record`), written by the flow that did the work
(`python -m knos.nebius flow`, the Gate, `knos verify`). An event that names a transaction is billed only when the
chain says that transaction landed and did not fail (`chain_check`); an event the chain cannot confirm is shown and
not billed. LiteSVM evidence is labelled and never billed.

    python -m knos.money.teams usage     --file usage.jsonl [--team T]
    python -m knos.money.teams invoice   --file usage.jsonl --team T [--month 2026-10] [--chain]
    python -m knos.money.teams dashboard --file usage.jsonl --team T [--chain] [--out <file>]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Callable, Iterable

from . import fees_config

KINDS = ("verification", "x402_check", "escrow_funded", "payout")
ENV = "KNOS_USAGE"
ChainCheck = Callable[[str], dict]      # signature -> {"found", "err", "finalized", "slot", "block_time"}


def default_path() -> Path:
    return Path(os.environ.get(ENV) or Path.home() / ".knos" / "usage.jsonl")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event(kind: str, team: str, agent: str, **fields) -> dict:
    """One usage event. Fields a flow fills: task, passed, cheats (rule ids), agent_tests_passed (the agent said its
    tests pass), sig + network ("devnet" | "litesvm"), amount_units + decimals + mint, final_ms, label."""
    if kind not in KINDS:
        raise ValueError(f"no usage kind {kind!r}; one of {', '.join(KINDS)}")
    if not team or not agent:
        raise ValueError("a usage event names its team and its agent")
    return {"v": 1, "at": fields.pop("at", None) or now_iso(), "kind": kind, "team": team, "agent": agent, **fields}


def record(ev: dict, path: Path | None = None) -> dict:
    """Append one event (append-only: nothing here rewrites a line)."""
    p = Path(path) if path else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ev, sort_keys=True, separators=(",", ":")) + "\n")
    return ev


def load(path: Path | None = None) -> list[dict]:
    p = Path(path) if path else default_path()
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _month(ev: dict) -> str:
    return str(ev.get("at", ""))[:7]


def blocked_failing_merge(ev: dict) -> bool:
    """A failing merge blocked: the agent said its work passes (its own tests passed) and the referee refused it."""
    return ev.get("kind") == "verification" and ev.get("passed") is False and bool(ev.get("agent_tests_passed"))


def usage(events: Iterable[dict], team: str | None = None, month: str | None = None) -> dict:
    """Per team, per agent: verifications, verified (passed), refused, cheats caught, failing merges blocked, paid checks."""
    out: dict = defaultdict(lambda: defaultdict(Counter))
    for ev in events:
        if (team and ev.get("team") != team) or (month and _month(ev) != month):
            continue
        c = out[ev["team"]][ev["agent"]]
        if ev["kind"] == "verification":
            c["verifications"] += 1
            c["verified" if ev.get("passed") else "refused"] += 1
            c["cheats_caught"] += len(ev.get("cheats") or [])
            c["failing_merges_blocked"] += blocked_failing_merge(ev)
        elif ev["kind"] == "x402_check":
            c["paid_checks"] += 1
        elif ev["kind"] == "escrow_funded":
            c["escrows_funded"] += 1
        elif ev["kind"] == "payout":
            c["payouts"] += 1
    return {t: {a: dict(c) for a, c in agents.items()} for t, agents in out.items()}


def _usd(units: int, decimals: int = 6) -> Decimal:
    return Decimal(int(units)) / (10 ** int(decimals))


def pct(bps) -> str:
    """Basis points as a percentage: 500 -> '5%', 30 -> '0.30%'."""
    b = int(bps)
    return f"{b // 100}%" if b % 100 == 0 else f"{Decimal(b) / 100:.2f}%"


def _q(d: Decimal) -> str:
    return str(d.quantize(Decimal("0.01"), ROUND_HALF_UP))


def _on_chain(ev: dict, check: ChainCheck | None) -> dict:
    """What the chain says about the event's transaction: billable only when found, finalized and not failed."""
    sig, net = ev.get("sig"), ev.get("network")
    if not sig:
        return {"evidence": "no transaction (an off-chain event)", "billable": True}
    if net == "litesvm":
        return {"evidence": "LiteSVM (testkeys build), not a cluster: shown, never billed", "billable": False, "sig": sig}
    if check is None:
        return {"evidence": "chain not read for this invoice", "billable": True, "sig": sig, "checked": False}
    try:
        got = check(sig)
    except Exception as why:  # noqa: BLE001 - an unreachable chain bills nothing it cannot see
        return {"evidence": f"chain did not answer ({type(why).__name__})", "billable": False, "sig": sig, "checked": True}
    ok = bool(got.get("found")) and not got.get("err") and bool(got.get("finalized"))
    return {"evidence": "finalized on devnet" if ok else "not finalized or failed on chain: not billed", "billable": ok, "sig": sig,
            "checked": True, "slot": got.get("slot")}


def invoice(events: Iterable[dict], team: str, month: str | None = None, *, check: ChainCheck | None = None,
            cfg: fees_config.FeeConfig | None = None) -> dict:
    """The team's invoice for a month (all months when None), line by line, each with the chain's evidence. Only the
    bounty lines are on it: a verification or an x402 test payment is usage (`usage`), never a charge."""
    cfg = cfg or fees_config.load()
    f = cfg.doc["fees"]
    evs = sorted((e for e in events if e.get("team") == team), key=lambda e: e.get("at", ""))
    lines, due = [], Decimal(0)
    for ev in evs:
        if month is not None and _month(ev) != month:
            continue
        if ev["kind"] == "escrow_funded":
            ch = _on_chain(ev, check)
            lines.append({"at": ev["at"], "agent": ev["agent"], "task": ev.get("task"), "line": "bounty funded, held until its test passes", "usd": "0.00",
                          "held_usd": _q(_usd(ev.get("amount_units", 0), ev.get("decimals", 6))), **ch,
                          "why": "the team's own money, held by knos_pay until a verdict pays it or the deadline returns it: no charge"})
        elif ev["kind"] == "payout":
            amount = _usd(ev.get("amount_units", 0), ev.get("decimals", 6))
            whole = amount * Decimal(f["bounty_platform"]["rate_bps"]) / 10_000
            onchain = max(amount * Decimal(f["bounty"]["rate_bps"]) / 10_000, Decimal(f["bounty"]["floor_usd"]))
            rest = max(Decimal(0), whole - onchain)
            ch = _on_chain(ev, check)
            usd = rest if ch["billable"] else Decimal(0)
            lines.append({"at": ev["at"], "agent": ev["agent"], "task": ev.get("task"), "line": f"bounty paid: Knos bounty fee ({pct(f['bounty_platform']['rate_bps'])}), off-chain part",
                          "usd": _q(usd), "paid_usd": _q(amount), "onchain_part_usd": _q(onchain), "whole_fee_usd": _q(whole),
                          "would_bill_usd": _q(rest), **ch,
                          "why": f"{pct(f['bounty_platform']['rate_bps'])} of the bounty (a planned price): the program takes its "
                          f"{pct(f['bounty']['rate_bps'])} (at least {f['bounty']['floor_usd']}) at payout, the rest is invoiced"
                          + ("" if ch["billable"] else "; not billed: this payout is not a confirmed devnet transaction")})
            due += usd
    return {"team": team, "month": month or "all", "currency": "USD", "lines": lines, "due_usd": _q(due),
            "test_money": True, "pay_with": "USDC on Solana, taken by knos_pay at payout or invoiced",
            "note": "devnet: every amount is test money, and Knos's revenue is 0"}


def latency(events: Iterable[dict]) -> dict:
    """'Paid and final in N ms': send -> finalized of the devnet transactions in the record (our own traffic)."""
    ms = sorted(int(e["final_ms"]) for e in events if e.get("network") == "devnet" and e.get("final_ms") is not None)
    if not ms:
        return {"n": 0, "p50_ms": None, "p95_ms": None}
    p95 = ms[min(len(ms) - 1, max(0, int(round(0.95 * len(ms))) - 1))]
    return {"n": len(ms), "p50_ms": int(statistics.median(ms)), "p95_ms": p95, "max_ms": ms[-1],
            "label": "measured: send -> finalized on devnet, Knos's own test traffic"}


def dashboard(events: list[dict], team: str, *, check: ChainCheck | None = None, cfg: fees_config.FeeConfig | None = None) -> dict:
    cfg = cfg or fees_config.load()
    mine = [e for e in events if e.get("team") == team]
    u = usage(mine, team).get(team, {})
    tot: Counter[str] = Counter()
    for c in u.values():
        tot.update(c)
    rules = Counter(r for e in mine if e["kind"] == "verification" for r in (e.get("cheats") or []))
    labels = sorted({e["label"] for e in mine if e.get("label")})
    synthetic = sum(1 for e in mine if e.get("synthetic"))
    if synthetic:
        labels.append(f"{synthetic} synthetic event(s) included (a scripted cheater; the referee's decisions on them are real)")
    return {"team": team, "generated": now_iso(), "labels": labels, "synthetic_events": synthetic,
            "totals": {k: int(tot.get(k, 0)) for k in ("verifications", "verified", "refused", "cheats_caught", "failing_merges_blocked",
                                                       "paid_checks", "escrows_funded", "payouts")},
            "money_saved": {"failing_merges_blocked": int(tot.get("failing_merges_blocked", 0)),
                            "means": "pull requests whose agent said its tests pass and the referee refused: each one is a failing merge that did not happen. No dollar value is put on it here (none is sourced)."},
            "cheats_by_rule": dict(rules), "per_agent": u, "paid_and_final": latency(mine),
            "invoice": invoice(mine, team, check=check, cfg=cfg)}


def rpc_check(url: str | None = None) -> ChainCheck:
    """A chain_check over JSON-RPC (KNOS_RPC or devnet): getSignatureStatuses with history."""
    from .. import chain

    def check(sig: str) -> dict:
        u = url or os.environ.get("KNOS_RPC") or chain.CLUSTERS["devnet"]
        st = chain.call(u, "getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])["value"][0]
        if not st:
            return {"found": False}
        return {"found": True, "err": st.get("err"), "finalized": st.get("confirmationStatus") == "finalized", "slot": st.get("slot")}
    return check


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m knos.money.teams")
    ap.add_argument("what", choices=("usage", "invoice", "dashboard"))
    ap.add_argument("--file", type=Path, default=None, help=f"the usage record (default ${ENV} or ~/.knos/usage.jsonl)")
    ap.add_argument("--team", default=None)
    ap.add_argument("--month", default=None, help="YYYY-MM")
    ap.add_argument("--chain", action="store_true", help="check each transaction on devnet before billing it")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    evs = load(a.file)
    check = rpc_check() if a.chain else None
    if a.what == "usage":
        got = usage(evs, a.team, a.month)
    elif not a.team:
        print("--team is needed", file=sys.stderr)
        return 2
    elif a.what == "invoice":
        got = invoice(evs, a.team, a.month, check=check)
    else:
        got = dashboard(evs, a.team, check=check)
    text = json.dumps(got, indent=1)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
