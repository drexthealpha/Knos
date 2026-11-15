"""programs/knos_escrow/idl.json agrees with the Python builders (src/knos/jobs/sol.py, the authority): every
instruction builder has an IDL entry with the same one-byte tag, account count and signer/writable flags, and the
Job / Config2 layouts have the sizes and offsets sol.py parses. Offline."""
import inspect
import json
import re
from pathlib import Path

from solders.pubkey import Pubkey

from knos.jobs import sol

IDL = json.loads((Path(__file__).resolve().parents[1] / "programs" / "knos_escrow" / "idl.json").read_text("utf-8"))
PID = Pubkey.from_string(sol.DEVNET_PROGRAM)
K = [Pubkey(bytes([i + 1]) * 32) for i in range(8)]
H = bytes(range(32))

# One call per instruction builder in sol.py (aliases included); keys are distinct so no meta is merged.
CALLS = {
    "init2": lambda: sol.init2(PID, K[0], K[1]),
    "init": lambda: sol.init(PID, K[0], K[1]),
    "set_pause": lambda: sol.set_pause(PID, K[0], True),
    "lower_cap": lambda: sol.lower_cap(PID, K[0], 5_000_000),
    "lower_fee": lambda: sol.lower_fee(PID, K[0], 250),
    "post": lambda: sol.post(PID, K[0], H, 2_000_000, 60, 60, H, K[1], K[2], verifier=K[3]),
    "claim": lambda: sol.claim(PID, K[0], H, K[1], K[2]),
    "deliver": lambda: sol.deliver(PID, K[0], H, H, K[1], K[2]),
    "settle": lambda: sol.settle(PID, K[0], H, K[1], K[2], K[3], release=True, buyer=K[4]),
    "accept": lambda: sol.accept(PID, K[0], H, K[1], K[2], K[3]),
    "release": lambda: sol.release(PID, K[0], H, K[1], K[2], K[3], K[4]),
    "verify_release": lambda: sol.verify_release(PID, K[0], H, H, H, K[1], K[2], K[3], K[4]),
    "reject": lambda: sol.reject(PID, K[0], H, K[1], K[2]),
    "refund": lambda: sol.refund(PID, K[0], H, K[1], K[2]),
    "verify_reject": lambda: sol.verify_reject(PID, K[0], H, H, K[1], K[2], K[3]),
    "crank": lambda: sol.crank(PID, K[0], H, K[1], K[2], K[3], K[4], K[5]),
    "register_key": lambda: sol.register_key(PID, K[0], "kid-1", (1 << 2047) | 3),
    "buffer_write": lambda: sol.buffer_write(PID, K[0], H, 100, 0, b"x" * 10),
    "verify_step1": lambda: sol.verify_step1(PID, K[0], H, K[1]),
    "verify_step2": lambda: sol.verify_step2(PID, K[0], H, K[1], K[2], K[3], K[4], K[5]),
    "post_github": lambda: sol.post_github(PID, K[0], H, 0, 60, 60, H, "o/r", "refs/heads/main", K[1], K[2]),
    "compute_limit": None,
    "post_bounty": lambda: sol.post_bounty(PID, K[0], H, 0, 60, 60, H, K[1], K[2], verifier=K[3]),
    "faucet": lambda: sol.faucet(PID, K[0], K[1], K[2], 100_000_000),
    "init_faucet_mint": lambda: sol.init_faucet_mint(PID, K[0], K[1], 100_000_000),
    "add_mint": lambda: sol.add_mint(PID, K[0], K[1], K[2]),
    "set_admin": lambda: sol.set_admin(PID, K[0], K[1]),
    "set_workflow": lambda: sol.set_workflow(PID, K[0], "ab" * 20),
    "set_fee_account": lambda: sol.set_fee_account(PID, K[0], K[1]),
    "register_issuer": lambda: sol.register_issuer(PID, K[0], 1, sol.GITLAB_ISSUER, sol.CLAIMS_GITLAB),
    "fund_with_token": lambda: sol.fund_with_token(PID, K[0], H, K[1], K[2], K[3], "ab" * 20, "o/r"),
    "version_ix": None,
}
BY_TAG = {ix["discriminator"][0]: ix for ix in IDL["instructions"]}
SIZES = {"u8": 1, "u16": 2, "u32": 4, "bytes": 0, "u64": 8, "i64": 8, "pubkey": 32}


def _size(t) -> int:
    return SIZES[t] if isinstance(t, str) else SIZES[t["array"][0]] * t["array"][1]


def test_every_builder_is_called():
    builders = {n for n, f in inspect.getmembers(sol, inspect.isfunction)
                if f.__module__ == sol.__name__ and not n.startswith("_") and inspect.signature(f).return_annotation == "Instruction"}
    assert builders == set(CALLS)


def test_builders_match_idl():
    seen = set()
    for name, call in CALLS.items():
        if call is None:          # compute_limit (ComputeBudget's), version_ix (29: no accounts, a log)
            continue
        ix = call()
        tag = ix.data[0]
        assert tag in BY_TAG, f"{name}: tag {tag} not in the IDL"
        entry = BY_TAG[tag]
        seen.add(tag)
        assert len(entry["discriminator"]) == 1
        assert len(ix.accounts) == len(entry["accounts"]), name
        keys = [m.pubkey for m in ix.accounts]
        for meta, acc in zip(ix.accounts, entry["accounts"]):
            want = (acc.get("signer", False), acc.get("writable", False))
            got = (meta.is_signer, meta.is_writable)
            if keys.count(meta.pubkey) > 1:     # the same key twice (accept: buyer signs and takes the rent)
                assert got[0] >= want[0] and got[1] >= want[1], (name, acc["name"])
            else:
                assert got == want, (name, acc["name"])
            if "address" in acc:
                assert str(meta.pubkey) == acc["address"], (name, acc["name"])
        arg_len = sum(_size(a["type"]) for a in entry["args"])
        if any(a["type"] == "bytes" for a in entry["args"]):   # a variable-length tail (kid, chunk)
            assert len(ix.data) > 1 + arg_len, name
        else:
            assert len(ix.data) == 1 + arg_len, name
    assert seen == set(BY_TAG) == set(range(1, 20)) | {20, 21, 22, 23, 24, 25, 26, 27, 28}


def _layout(name):
    t = next(t for t in IDL["types"] if t["name"] == name)
    off = 0
    for f in t["type"]["fields"]:
        assert re.match(rf"offset {off}, {_size(f['type'])} bytes", f["docs"][0]), (name, f["name"])
        off += _size(f["type"])
    assert f"size {off} bytes" in t["docs"][0]
    return off, {f["name"]: f for f in t["type"]["fields"]}


def test_account_layouts_match_sol():
    job_len, job = _layout("Job")
    assert job_len == sol.JOB_LEN == 225
    assert list(job) == ["state", "buyer", "worker", "amount", "deadline", "review", "brief", "result", "verifier",
                         "proof", "stake"]
    cfg_len, cfg = _layout("Config2")
    assert cfg_len == sol.CONFIG_LEN == 124
    assert list(cfg)[:8] == ["admin", "mint", "fee_token", "fee_bps", "min_fee", "min_amount", "max_amount", "paused"]
    assert {a["name"] for a in IDL["accounts"]} == {"Job", "Config2"}
    assert IDL["address"] == sol.DEVNET_PROGRAM and IDL["metadata"]["spec"] == "0.1.0"
