"""Anchoring the record on Solana devnet: the Merkle root of every line since the last anchor goes on chain in one
transaction of the SPL Memo program, signed by the anchoring wallet, and an `anchor` line naming the transaction is
appended to the record. Anyone can then read the memo back (`chain_memo`) and hold the file to it (knos.record.verify).

    memo   knos-record:v1 root=<merkle root> first=<seq> last=<seq> head=<hash of line `last`>

No program of Knos's is needed or changed: the Memo program is Solana's own. Devnet (or a localnet) only; mainnet is
refused, as everywhere in Knos. A send needs a funded devnet wallet (`--keypair`, or the file named by KNOS_RECORD_KEY).
Anchoring is never automatic: whoever keeps a record decides when, and pays the fee (5,000 lamports a signature on
devnet as of this writing; see docs/reference/KNOS_RECORD.md).
"""

from __future__ import annotations

import os
import re
from typing import Callable

from . import journal, merkle

MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"   # SPL Memo v2 (read from a devnet transaction the solana CLI sent with --with-memo, 13 Oct 2026)
PREFIX = "knos-record:v1"
MEMO_UNITS = 200_000          # the Memo program checks the signer and the UTF-8 of a ~210-byte memo: 50,000 units ran out on devnet
_MEMO = re.compile(r"^knos-record:v1 root=([0-9a-f]{64}) first=(\d+) last=(\d+) head=([0-9a-f]{64})$")
CLUSTERS = {"devnet": "https://api.devnet.solana.com", "localnet": "http://127.0.0.1:8899"}
# The anchoring keys a verifier trusts unless told otherwise. A rewritten journal re-anchored with any other wallet is
# refused. Whoever holds a pinned key can still rewrite and re-anchor: the pin moves trust to that key, it does not
# remove it (docs/reference/KNOS_RECORD.md). The key here is the record build's own devnet record wallet.
PINNED_SIGNERS = frozenset({"8aukezen9sAALWShcZKK3hi8WawBi4vR6qmLf764PGBv"})


def trusted_signers(given=None) -> frozenset:
    """The anchoring keys to hold anchors to: `given` (e.g. `--signer`, repeated), else KNOS_RECORD_SIGNERS
    (comma-separated public keys), else PINNED_SIGNERS. Never read from the journal being checked."""
    if given:
        return frozenset(str(k).strip() for k in given if str(k).strip())
    env = [k.strip() for k in os.environ.get("KNOS_RECORD_SIGNERS", "").split(",") if k.strip()]
    return frozenset(env) if env else PINNED_SIGNERS


class AnchorError(RuntimeError):
    pass


def memo_text(root: str, first: int, last: int, head: str) -> str:
    return f"{PREFIX} root={root} first={first} last={last} head={head}"


def parse_memo(text: str) -> dict | None:
    m = _MEMO.match((text or "").strip())
    if not m:
        return None
    return {"root": m.group(1), "first": int(m.group(2)), "last": int(m.group(3)), "head": m.group(4)}


def anchors(lines: list[dict]) -> list[dict]:
    return [e for e in lines if e.get("kind") == "anchor"]


def pending(lines: list[dict]) -> list[dict]:
    """The lines no anchor covers yet: every line after the last anchored one."""
    done = anchors(lines)
    start = int(done[-1]["payload"]["last"]) + 1 if done else 0
    return [e for e in lines if int(e["seq"]) >= start]


def plan(root=None) -> dict | None:
    """What the next anchor would put on chain: {first, last, count, root, head, memo}; None when nothing is pending."""
    batch = pending(journal.entries(root))
    if not batch:
        return None
    r = merkle.root([e["hash"] for e in batch])
    first, last, head = int(batch[0]["seq"]), int(batch[-1]["seq"]), batch[-1]["hash"]
    return {"first": first, "last": last, "count": len(batch), "root": r, "head": head, "memo": memo_text(r, first, last, head)}


def cluster() -> str:
    c = os.environ.get("KNOS_CLUSTER", "devnet")
    if c not in CLUSTERS:
        raise AnchorError(f"Knos Record anchors on devnet (or a localnet) only; {c!r} is not available.")
    return c


def rpc_url(name: str | None = None) -> str:
    return os.environ.get("KNOS_RPC") or CLUSTERS[name or cluster()]


def load_keypair(path: str | os.PathLike | None = None):
    """The anchoring wallet: the keypair file given, else the file KNOS_RECORD_KEY names. Its key is never printed."""
    from solders.keypair import Keypair
    import json
    where = path or os.environ.get("KNOS_RECORD_KEY")
    if not where:
        raise AnchorError("Anchoring signs with a funded devnet wallet: pass --keypair FILE (as solana-keygen writes it) "
                          "or set KNOS_RECORD_KEY to that file.")
    try:
        with open(where, encoding="utf-8") as f:
            return Keypair.from_bytes(bytes(json.loads(f.read())))
    except (OSError, ValueError) as why:
        raise AnchorError(f"That is not a Solana keypair file ({type(why).__name__}).") from None


def memo_instruction(text: str, signer):
    from solders.instruction import AccountMeta, Instruction
    from solders.pubkey import Pubkey
    return Instruction(Pubkey.from_string(MEMO_PROGRAM), text.encode("utf-8"), [AccountMeta(signer, True, False)])


def send_memo(text: str, keypair, url: str | None = None) -> dict:
    """Send the memo, wait for the cluster's commitment (finalized on Alpenglow, else confirmed:
    knos.platform.finality), return {tx, signer, slot, commitment, final_ms}."""
    from solders.compute_budget import set_compute_unit_limit
    from .. import chain
    from ..platform import finality
    led = chain.Ledger(url or rpc_url())
    sig = led.send([set_compute_unit_limit(MEMO_UNITS), memo_instruction(text, keypair.pubkey())], keypair)
    got = chain_memo(sig, url)
    t = finality.timing_of(sig) or {}
    return {"tx": sig, "signer": str(keypair.pubkey()), "slot": got.get("slot"), "commitment": led.commitment, "final_ms": t.get("final_ms")}


def chain_memo(signature: str, url: str | None = None) -> dict:
    """What the chain says a transaction carried: {found, err, memo, signers, slot, block_time}. The memo is read from
    the Memo program's own instruction in the transaction, not from any log another program could write."""
    from .. import chain
    got = chain.Ledger(url or rpc_url())._transaction(signature)     # Knos's one transaction reader: asks for version 1
    if not got:
        return {"found": False}
    msg = (got.get("transaction") or {}).get("message") or {}
    keys = [str(k) for k in msg.get("accountKeys") or []]
    nsig = int((msg.get("header") or {}).get("numRequiredSignatures") or 0)
    memos = []
    for ix in msg.get("instructions") or []:
        idx = ix.get("programIdIndex")
        if isinstance(idx, int) and idx < len(keys) and keys[idx] == MEMO_PROGRAM:
            memos.append(_b58decode(ix.get("data") or "").decode("utf-8", "replace"))
    return {"found": True, "err": (got.get("meta") or {}).get("err"), "memo": memos[0] if len(memos) == 1 else None,
            "memos": memos, "signers": keys[:nsig], "slot": got.get("slot"), "block_time": got.get("blockTime")}


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(text: str) -> bytes:
    n = 0
    for ch in text:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(text) - len(text.lstrip("1"))) + raw


def anchor(root=None, *, keypair=None, send: Callable[[str], dict] | None = None, dry_run: bool = False,
           store=None) -> dict | None:
    """Anchor every pending line: put the batch's Merkle root on chain, then append an `anchor` line naming the
    transaction. Returns that line (with dry_run, the plan only; nothing sent or written). None when nothing is
    pending. `send(memo) -> {tx, signer, slot}` replaces the devnet send (tests, a localnet)."""
    p = plan(root)
    if p is None or dry_run:
        return p
    name = cluster()
    if send is None:
        kp = keypair if keypair is not None and not isinstance(keypair, (str, os.PathLike)) else load_keypair(keypair)
        sent = send_memo(p["memo"], kp)
    else:
        sent = send(p["memo"])
    payload = {**{k: p[k] for k in ("first", "last", "count", "root", "head")}, "memo": p["memo"], "program": MEMO_PROGRAM,
               "cluster": name, "tx": sent["tx"], "signer": sent["signer"], "slot": sent.get("slot")}
    if sent.get("commitment"):      # how deep the anchor was when it was written, and how long that took ("final in N ms")
        payload["commitment"] = sent["commitment"]
        if sent.get("final_ms") is not None:
            payload["final_ms"] = int(sent["final_ms"])
    return journal.append("anchor", payload, root=root, store=store)
