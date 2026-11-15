"""A referee verdict, off chain: the message m of n re-runners sign, and the rule that releases or refunds on it.

This is the off-chain mirror of the knos_pay panel test build's referee-panel path (programs-v2/knos_pay/src/order_proof.rs):

    on chain                                  here
    the order's address                       job
    the order's terms + the evidence hash     evidence_hash
    PayOrderVerdict / RefundOrderVerdict      verdict "PASS" -> outcome "release" / "FAIL" -> outcome "refund"
    the order's amount, the payee's address   amount, recipient
    the order's deadline                      expiry (after it RefundOrder refunds with no signature)
    the order's funding stamp                 nonce (a verdict for one funding pays no later funding)
    the panel pinned at funding (m of n)      keys, m
    the ed25519 precompile, distinct keys     check(): distinct registered keys with a valid signature

The program signs over its own 32-byte digest (knos.proof.issuers.verdict_digest); this module's message is the
same facts in a fixed layout a re-runner can read before signing. Nothing here holds a key.

Layout (139 bytes): b"knos-verdict-v1" | job 32 | evidence_hash 32 | "PASS" or "FAIL" | amount u64 LE | recipient 32 |
expiry i64 LE | nonce u64 LE.
"""
from __future__ import annotations

MAGIC = b"knos-verdict-v1"
VERDICTS = ("PASS", "FAIL")
LENGTH = len(MAGIC) + 32 + 32 + 4 + 8 + 32 + 8 + 8
FIELDS = ("job", "evidence_hash", "verdict", "amount", "recipient", "expiry", "nonce")


def _b32(v, name: str) -> bytes:
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
    elif hasattr(v, "__bytes__") and not isinstance(v, (str, int)):
        b = bytes(v)          # a solders Pubkey
    else:
        raise ValueError(f"{name} must be 32 bytes")
    if len(b) != 32:
        raise ValueError(f"{name} must be 32 bytes, not {len(b)}")
    return b


def _int(v, name: str, lo: int, hi: int) -> int:
    if not isinstance(v, int) or isinstance(v, bool):
        raise ValueError(f"{name} must be an integer")
    if not lo <= v <= hi:
        raise ValueError(f"{name} out of range")
    return v


def message(job, evidence_hash, verdict: str, amount: int, recipient, expiry: int, nonce: int) -> bytes:
    """The bytes every referee signs. ValueError for a field of the wrong size, a verdict other than PASS or FAIL, or
    an integer out of its range (amount and nonce: u64; expiry: i64 unix seconds)."""
    if verdict not in VERDICTS:
        raise ValueError('verdict must be "PASS" or "FAIL"')
    return (MAGIC + _b32(job, "job") + _b32(evidence_hash, "evidence_hash") + verdict.encode()
            + _int(amount, "amount", 0, 2 ** 64 - 1).to_bytes(8, "little") + _b32(recipient, "recipient")
            + _int(expiry, "expiry", -(2 ** 63), 2 ** 63 - 1).to_bytes(8, "little", signed=True)
            + _int(nonce, "nonce", 0, 2 ** 64 - 1).to_bytes(8, "little"))


def parse(msg: bytes) -> dict:
    """The seven fields of a message, by name; ValueError for anything that is not one."""
    b = bytes(msg)
    if len(b) != LENGTH or not b.startswith(MAGIC):
        raise ValueError("not a verdict message")
    at = len(MAGIC)

    def take(n: int) -> bytes:
        nonlocal at
        at += n
        return b[at - n:at]
    job, evidence, verdict = take(32), take(32), take(4).decode("ascii", "replace")
    if verdict not in VERDICTS:
        raise ValueError("not a verdict message: verdict")
    amount, recipient = int.from_bytes(take(8), "little"), take(32)
    expiry, nonce = int.from_bytes(take(8), "little", signed=True), int.from_bytes(take(8), "little")
    return {"job": job, "evidence_hash": evidence, "verdict": verdict, "amount": amount, "recipient": recipient, "expiry": expiry, "nonce": nonce}


def outcome(msg: bytes) -> str:
    """"release" for a PASS (the payee is paid), "refund" for a FAIL (the funder gets the money back)."""
    return "release" if parse(msg)["verdict"] == "PASS" else "refund"


def _valid(key: bytes, sig: bytes, msg: bytes) -> bool:
    """An Ed25519 check with solders (a runtime dependency), so a plain `pip install knos` needs no `cryptography`."""
    from solders.pubkey import Pubkey
    from solders.signature import Signature
    try:
        return len(key) == 32 and len(sig) == 64 and Signature.from_bytes(sig).verify(Pubkey.from_bytes(key), msg)
    except ValueError:
        return False


SPENT: set = set()   # accepted (job, nonce) of this process, besides the persistent store below


class SpentStore:
    """The verdicts this machine has accepted, kept across processes: one empty file per spent (job, nonce) under
    KNOS_HOME/verdicts/spent, created with O_CREAT|O_EXCL. Creating a file that exists fails atomically, so of two
    processes that check the same verdict at the same moment exactly one accepts it."""
    def __init__(self, root=None):
        from pathlib import Path
        if root is None:
            from .. import paths
            root = paths.home() / "verdicts" / "spent"
        self.root = Path(root)

    def _file(self, job: bytes, nonce: int):
        import hashlib
        return self.root / hashlib.sha256(b"knos-verdict-spent" + bytes(job) + int(nonce).to_bytes(8, "little")).hexdigest()

    def __contains__(self, item) -> bool:
        job, nonce = item
        return self._file(job, nonce).exists()

    def spend(self, job: bytes, nonce: int) -> bool:
        """True when this call spent it; False when it was spent already (by this or any other process)."""
        import os
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self._file(job, nonce), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        os.close(fd)
        return True

    def add(self, item) -> None:
        self.spend(*item)


def default_store() -> SpentStore:
    return SpentStore()


def check(msg: bytes, sigs, keys, m: int, *, now: int, used=None, record: bool = True, funder=None, payees=(),
          unlisted_panel: bool | None = None) -> tuple[bool, str]:
    """True only with at least `m` valid signatures over `msg` by distinct keys of `keys` (the registered re-runners),
    `now` before the message's expiry and (job, nonce) not in `used`. An unregistered key, a key counted already and a
    signature that does not verify count for nothing; a message changed after signing (another amount, another
    recipient) verifies under none of them. Returns (ok, why).
    SPENDING. A verdict it ACCEPTS is spent: (job, nonce) is added to `used`, or, when `used` is None or read-only, to
    the persistent store under KNOS_HOME (`SpentStore`), which every process on the machine reads: a second check of
    the same verdict, in this process or another, is refused as a replay, as knos_pay refuses it on chain (E_REPLAY).
    record=False is a dry run; a refusal spends nothing.
    THE PANEL (referees.panel_rule): `keys` holding the funder's key or the recipient's (or `payees`') is refused unless
    unlisted_panel=True; keys outside Knos's published registry (config/referees.yaml) are refused with
    unlisted_panel=False, and accepted with the reason starting "UNLISTED PANEL" otherwise."""
    from . import referees
    persistent = used is None or not hasattr(used, "add")
    store = default_store() if persistent else used
    try:
        f = parse(msg)
    except ValueError as e:
        return False, f"malformed: {e}"
    if not isinstance(m, int) or isinstance(m, bool) or m < 1:
        return False, "m must be at least 1"
    try:
        label = referees.panel_rule(keys, funder=funder, payees=[*payees, f["recipient"]], unlisted_panel=unlisted_panel)
    except referees.PanelError as why:
        return False, f"panel: {why}"
    if not now < f["expiry"]:
        return False, "expired"
    item = (f["job"], f["nonce"])
    if item in store or item in SPENT:
        return False, "replay: this job and nonce were used"
    if used is not None and persistent and item in used:
        return False, "replay: this job and nonce were used"
    registered = {bytes(k) for k in keys}
    counted: set[bytes] = set()
    for it in sigs:
        try:
            key, sig = bytes(it[0]), bytes(it[1])
        except (TypeError, IndexError):
            continue
        if len(key) != 32 or len(sig) != 64 or key not in registered or key in counted:
            continue
        if _valid(key, sig, bytes(msg)):
            counted.add(key)
    if len(counted) < m:
        return False, f"below threshold: {len(counted)} of {m}"
    if record:
        if persistent:
            if not store.spend(*item):
                return False, "replay: this job and nonce were used"
        else:
            store.add(item)
    said = f"{len(counted)} of {m} distinct registered re-runners signed"
    return True, f"{label}; {said}" if label else said


def sign(msg: bytes, keypair) -> tuple[bytes, bytes]:
    """(public key, signature) of `msg` under a solders Keypair: what a re-runner returns."""
    return bytes(keypair.pubkey()), bytes(keypair.sign_message(bytes(msg)))
