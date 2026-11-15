"""`knos bench jobs`: full jobs end to end, timed, with the money checked after every one.

    knos bench jobs                  Solana escrow in the Solana runtime (LiteSVM, in-process): no network
    knos bench jobs --live           Solana devnet: the deployed program, real RPC, real finality
    knos bench jobs --tempo          Tempo escrow on a local anvil (needs Foundry)

Every result says where it ran. Numbers from the in-process runtime and anvil measure the code, not a network.
"""

from __future__ import annotations

import shutil
import socket
import statistics
import subprocess
import time
from contextlib import contextmanager

UNITS = 1_000_000


def _summary(times: dict[str, list[float]]) -> dict:
    return {k: {"p50_s": round(statistics.median(v), 4), "max_s": round(max(v), 4)} for k, v in times.items() if v}


def solana_local(jobs: int = 20) -> dict:
    import hashlib
    from .localsvm import Escrow
    env = Escrow()
    buyer, _ = env.party(jobs * 2 * UNITS)
    worker, wtok = env.party()
    times: dict[str, list[float]] = {"post": [], "claim": [], "deliver": [], "accept": []}
    for i in range(jobs):
        jid = hashlib.sha256(f"bench{i}".encode()).digest()
        for step, fn in (("post", lambda: env.post(buyer, env.accounts[bytes(buyer.pubkey())], jid, UNITS)),
                         ("claim", lambda: env.claim(worker, jid)), ("deliver", lambda: env.deliver(worker, jid)),
                         ("accept", lambda: env.accept(buyer, jid, wtok))):
            t = time.perf_counter()
            assert fn(), step
            times[step].append(time.perf_counter() - t)
    assert env.balance(wtok) == jobs * UNITS * 95 // 100 and env.balance(env.vault) == 0
    return {"where": "Solana runtime in-process (LiteSVM), no network", "jobs": jobs,
            "worker_paid_usdc": env.balance(wtok) / UNITS, "fee_usdc": env.balance(env.fee_token) / UNITS,
            "latency": _summary(times)}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def anvil_path() -> str | None:
    from pathlib import Path
    return shutil.which("anvil") or next((str(p) for p in (Path.home() / ".foundry" / "bin" / "anvil",
                                                            Path.home() / ".foundry" / "bin" / "anvil.exe")
                                          if p.exists()), None)


@contextmanager
def anvil(binary: str | None = None):
    """A throwaway local EVM. Its dev accounts are public test keys, printed by anvil itself; never fund them."""
    binary = binary or anvil_path()
    if not binary:
        raise FileNotFoundError("anvil not found: install Foundry (https://getfoundry.sh)")
    port = _free_port()
    proc = subprocess.Popen([binary, "--port", str(port), "--silent"], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        from .tempo import Chain
        c = Chain(url, timeout=2)
        for _ in range(100):
            try:
                c.rpc("eth_chainId", [])
                break
            except OSError:
                time.sleep(0.05)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()


def tempo_setup(url: str, review_s: int = 60, cap_units: int = 0):
    """Deploy a test token and the escrow on a dev chain; return (chain, escrow, token, buyer, worker, fee address)."""
    from eth_abi import encode
    from eth_account import Account
    from .tempo import TEST_TOKEN, Chain, Escrow, _sel
    chain = Chain(url)
    accts = chain.rpc("eth_accounts", [])
    admin, buyer, worker, fee = (Account.create() for _ in range(4))
    for a in (admin, buyer, worker):   # dev chain: fund fresh keys from the node's unlocked account
        chain.rpc("eth_sendTransaction", [{"from": accts[0], "to": a.address, "value": hex(10**19)}])
    token = chain.deploy(admin, TEST_TOKEN, [], [])
    chain.send(admin, token, _sel("mint(address,uint256)") + encode(["address", "uint256"], [buyer.address, 10**15]))
    esc = Escrow.deploy(chain, admin, token, fee.address, 500, review_s, cap_units=cap_units)
    return chain, esc, token, buyer, worker, fee.address


def tempo_local(jobs: int = 20, binary: str | None = None) -> dict:
    import hashlib
    with anvil(binary) as url:
        chain, esc, token, buyer, worker, fee = tempo_setup(url)
        times: dict[str, list[float]] = {"post": [], "claim": [], "deliver": [], "accept": []}
        for i in range(jobs):
            jid = hashlib.sha256(f"bench{i}".encode()).digest()
            for step, fn in (("post", lambda: esc.post(buyer, jid, UNITS, 600)), ("claim", lambda: esc.claim(worker, jid)),
                             ("deliver", lambda: esc.deliver(worker, jid, hashlib.sha256(b"r").digest())),
                             ("accept", lambda: esc.accept(buyer, jid))):
                t = time.perf_counter()
                fn()
                times[step].append(time.perf_counter() - t)
        paid, cut = chain.balance(token, worker.address), chain.balance(token, fee)
        assert paid == jobs * UNITS * 95 // 100 and cut == jobs * UNITS * 5 // 100
        assert chain.balance(token, esc.address) == 0
        return {"where": "Tempo escrow on a local anvil (EVM), no network", "jobs": jobs,
                "worker_paid_usdc": paid / UNITS, "fee_usdc": cut / UNITS, "latency": _summary(times)}


def solana_live(jobs: int = 3) -> dict:
    """Devnet, with the operator's own funded key (KNOS_MEMBER_KEY or ~/.knos/team/member.json) as buyer and a fresh
    worker it funds with 0.01 SOL. Prints nothing secret."""
    from solders.keypair import Keypair
    from solders.system_program import TransferParams, transfer
    from . import market, net
    from .relay import DirRelay
    import tempfile
    ledger, key = net.ledger(), net.key()
    relay = DirRelay(tempfile.mkdtemp(prefix="knos-bench-"))
    worker = Keypair()
    ledger.send([transfer(TransferParams(from_pubkey=key.pubkey(), to_pubkey=worker.pubkey(), lamports=10_000_000))],
                key)
    times: dict[str, list[float]] = {"post": [], "claim": [], "deliver": [], "accept": []}
    for i in range(jobs):
        t = time.perf_counter()
        jid = market.post(ledger, relay, key, market.Brief(f"bench {i}", "bench"), UNITS, 600, 600)   # the minimum job
        times["post"].append(time.perf_counter() - t)
        t = time.perf_counter()
        assert market.claim(ledger, worker, jid)
        times["claim"].append(time.perf_counter() - t)
        t = time.perf_counter()
        market.deliver(ledger, relay, worker, jid, key.pubkey(), b"ok")
        times["deliver"].append(time.perf_counter() - t)
        t = time.perf_counter()
        market.accept(ledger, key, jid)
        times["accept"].append(time.perf_counter() - t)
        assert market.job(ledger, jid).state == "released"
    return {"where": f"Solana devnet (live RPC, waiting for '{ledger.commitment}')", "jobs": jobs,
            "price_usdc_each": 1.0, "latency": _summary(times)}


def run(live: bool = False, tempo: bool = False, jobs: int | None = None) -> dict:
    if tempo and live:
        raise NotImplementedError("A live Tempo bench is not built in: the Moderato numbers in docs/BENCH.md are recorded runs")
    if tempo:
        return tempo_local(jobs or 20)
    if live:
        return solana_live(jobs or 3)
    return solana_local(jobs or 20)
