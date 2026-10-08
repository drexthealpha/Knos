#!/usr/bin/env python3
"""The second operator's drill as one command (docs/OPERATOR.md, "The drill"): a person who is not the founder shows
that they can operate Knos on devnet from a fork of their own, with a fee payer of their own.

    python scripts/second_operator.py --fork YOU/Knos --key relay.json

It runs five steps, prints what each one saw beside what it expected, and stops at the first that fails:

    1 status     `knos status` exits 0: the programs, the signing keys and the pending upgrades were read from the chain
    2 fee payer  the key file is yours, and its address holds devnet SOL (at least 0.05)
    3 relay      one pass of `knos relay` with YOUR key exits 0 (it sends whatever is due; a relay decides nothing)
    4 the fork   the fork is not the founder's repository, and it holds the secret KNOS_RELAY_KEY
    5 the chain  the relay's chain of runs is started in the fork (worker.yml, by hand, with `after` empty) and GitHub
                 lists the run

Steps 4 and 5 use the GitHub CLI (`gh`), signed in as you. It asks the founder nothing and reads no file of his.
What it cannot show is the drill's last condition: a payment or a refund whose fee payer is your address. The command
prints the line to look for and the row to send for docs/DRILLS.md; a person checks it on a block explorer.

`--simulate` runs the same steps against canned answers (no network, no key, no `gh`): it tests this script, and it
is not a drill. Nobody but the founder has run the real one.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

FOUNDER = "drexthealpha/Knos"
RPC = "https://api.devnet.solana.com"
MIN_LAMPORTS = 50_000_000                # 0.05 SOL: thousands of relay transactions at 5,000 lamports a signature
WORKFLOW = "worker.yml"
Runner = Callable[[list, dict], tuple]


class Failed(Exception):
    pass


def _run(cmd: list, env: dict) -> tuple:
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env={**os.environ, **env}, check=False, timeout=170)
    return done.returncode, (done.stdout + done.stderr).strip()


def _balance(address: str, rpc: str) -> int:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}).encode()
    with urllib.request.urlopen(urllib.request.Request(rpc, body, {"Content-Type": "application/json"}), timeout=30) as r:     # noqa: S310 - the RPC address the operator gave
        return int(json.load(r)["result"]["value"])


def _address(key: str) -> str:
    from solders.keypair import Keypair
    try:
        return str(Keypair.from_bytes(bytes(json.loads(key))).pubkey())
    except Exception:  # noqa: BLE001
        raise Failed("the key file is not a Solana keypair file (`solana-keygen new --outfile relay.json` writes one)") from None


def simulated(fork: str) -> tuple:
    """(run, balance, address) with canned answers: what a passing drill sees, for the test of this script."""
    def run(cmd: list, env: dict) -> tuple:
        if cmd[:2] == ["gh", "secret"]:
            return 0, "KNOS_RELAY_KEY\t2026-10-07T00:00:00Z"
        if cmd[:3] == ["gh", "run", "list"]:
            return 0, json.dumps([{"databaseId": 1, "status": "in_progress", "displayTitle": "relay", "event": "workflow_dispatch"}])
        return 0, "simulated"
    return run, (lambda address, rpc: 2_000_000_000), (lambda key: "SimuLatedFeePayer1111111111111111111111111")


def drill(fork: str, key: str, *, rpc: str = RPC, knos: list | None = None, run: Runner = _run, balance=_balance, address=_address,
          say: Callable[[str], object] = print, wait: Callable[[float], object] = time.sleep) -> dict:
    """The five steps. `key`: the fee payer's key file's contents. Raises Failed, in words, at the first step that does
    not hold. Returns {"fee_payer", "fork", "run"}."""
    knos = knos or [sys.executable, "-m", "knos"]
    if fork.lower() == FOUNDER.lower() or fork.count("/") != 1:
        raise Failed(f"--fork is a repository of your own, as you/name: {fork!r} is the founder's, or not a repository")
    code, out = run([*knos, "status"], {"KNOS_RPC": rpc})
    if code != 0:
        raise Failed(f"1 status: `knos status` exited {code}, expected 0. It names what is wrong:\n{out[-800:]}")
    say("1 status     ok: `knos status` exited 0 (expected 0)")
    mine = address(key)
    lamports = balance(mine, rpc)
    if lamports < MIN_LAMPORTS:
        raise Failed(f"2 fee payer: {mine} holds {lamports / 1e9:.3f} SOL, expected at least {MIN_LAMPORTS / 1e9:.2f}: `solana airdrop 2 {mine} --url {rpc}` or https://faucet.solana.com")
    say(f"2 fee payer  ok: {mine} holds {lamports / 1e9:.3f} SOL (expected at least {MIN_LAMPORTS / 1e9:.2f})")
    code, out = run([*knos, "relay"], {"KNOS_RELAY_KEY": key, "KNOS_RPC": rpc})
    if code != 0:
        raise Failed(f"3 relay: one pass of `knos relay` with your key exited {code}, expected 0:\n{out[-800:]}")
    say("3 relay      ok: one pass of `knos relay` with your key exited 0 (expected 0)")
    code, out = run(["gh", "secret", "list", "-R", fork], {})
    if code != 0 or "KNOS_RELAY_KEY" not in out.split():
        raise Failed(f"4 the fork: {fork} has no secret KNOS_RELAY_KEY (or `gh` is not signed in). Set it: `gh secret set KNOS_RELAY_KEY -R {fork} < relay.json`")
    say(f"4 the fork   ok: {fork} holds the secret KNOS_RELAY_KEY (expected: listed)")
    code, out = run(["gh", "workflow", "run", WORKFLOW, "-R", fork], {})
    if code != 0:
        raise Failed(f"5 the chain: GitHub did not start {WORKFLOW} in {fork} (enable Actions in the fork first: its Actions tab asks once):\n{out[-400:]}")
    started = None
    for _ in range(6):       # GitHub lists a run a few seconds after it takes the request
        wait(5)
        code, out = run(["gh", "run", "list", "-R", fork, "--workflow", WORKFLOW, "--limit", "5", "--json", "databaseId,status,displayTitle,event"], {})
        runs = json.loads(out) if code == 0 and out.startswith("[") else []
        started = next((r for r in runs if r.get("event") == "workflow_dispatch" and r.get("status") in ("queued", "in_progress", "completed")), None)
        if started:
            break
    if not started:
        raise Failed(f"5 the chain: {WORKFLOW} was asked to start in {fork} and GitHub lists no run of it after 30 seconds: look at the fork's Actions tab")
    say(f"5 the chain  ok: run {started['databaseId']} of {WORKFLOW} is {started['status']} in {fork} (expected: a run started by hand, which starts the next)")
    say("Not shown by this command: a payment or refund whose fee payer is your address. Fund an order in a repository of your own (docs/INSTALL.md), "
        f"then find the paying transaction on a block explorer: its fee payer must be {mine}.")
    say(f"The row for docs/DRILLS.md: date {time.strftime('%Y-%m-%d', time.gmtime())}, your handle, that transaction's signature, the minutes from clone to payment, "
        "and every step where docs/OPERATOR.md was not enough.")
    return {"fee_payer": mine, "fork": fork, "run": started["databaseId"]}


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description="The second operator's drill as one command (docs/OPERATOR.md).")
    ap.add_argument("--fork", required=True, help="your fork, as you/name")
    ap.add_argument("--key", type=Path, help="your fee payer's key file (relay.json)")
    ap.add_argument("--rpc", default=RPC)
    ap.add_argument("--simulate", action="store_true", help="canned answers, no network: tests this script and is not a drill")
    a = ap.parse_args(argv)
    try:
        if a.simulate:
            run, balance, address = simulated(a.fork)
            print("SIMULATED: canned answers, no network, no key. This is not a drill and records nothing.")
            drill(a.fork, "[]", rpc=a.rpc, run=run, balance=balance, address=address, wait=lambda _s: None)
            return 0
        if a.key is None:
            raise Failed("--key is your fee payer's key file (section 2 of docs/OPERATOR.md makes one)")
        drill(a.fork, a.key.read_text(encoding="utf-8").strip(), rpc=a.rpc)
        return 0
    except (Failed, OSError) as why:
        print(f"not passed: {why}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
