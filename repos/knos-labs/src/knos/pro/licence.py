"""Whether this machine may use Knos Pro: a 14-day trial, a licence paid on chain, or a signed licence code.

~/.knos/licence.json is written by `knos pro buy` after the payment is verified on Solana or Tempo (it records the
transaction, which anyone can look up) or by `knos pro activate <code>`, where the code is signed with the Knos
licence key (Ed25519; the public half is below). There is no server and no account.

Gating is honest-user gating: the code is MIT and a determined person can edit it. The point is that
paying is one command and the trial is long enough to know.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import paths
from .prices import PLANS, TRIAL_DAYS

# The public half of the Knos licence key (Ed25519), hex. The private half never leaves the founder's machine; codes
# it signs are for buyers who paid by card or bank.
PUBLIC_KEY_HEX = "e6010293594641d669018713557cab282486fdd4de7f1683ba25b210d57f88e1"


def licence_path() -> Path:
    return paths.home() / "licence.json"


def trial_path() -> Path:
    return paths.home() / "trial.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def canonical(body: dict) -> bytes:
    return json.dumps({k: v for k, v in body.items() if k != "sig"}, sort_keys=True, separators=(",", ":")).encode()


def verify_signed(body: dict, public_hex: str = "") -> bool:
    key = public_hex or PUBLIC_KEY_HEX
    if not key or not body.get("sig"):
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(
            base64.urlsafe_b64decode(str(body["sig"]) + "=="), canonical(body))
        return True
    except (InvalidSignature, ValueError):
        return False


def read() -> dict | None:
    try:
        got = json.loads(licence_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def write(body: dict) -> Path:
    path = licence_path()
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def valid(body: dict | None) -> bool:
    """A licence counts when it has not expired and is backed by a chain payment or a good signature."""
    if not body:
        return False
    ends = _parse(str(body.get("expires", "")))
    if ends is None or ends <= _now():  # "ends now" is over (Windows' clock can return the same instant twice)
        return False
    if str(body.get("via", "")).startswith(("solana:", "tempo:")):
        # re-checked against the chain at most daily (reverify); offline, it counts for 7 days after the last check
        seen = _parse(str(body.get("verified_at") or body.get("issued") or ""))
        return seen is not None and _now() - seen <= timedelta(days=1 + GRACE_DAYS)
    return verify_signed(body)


GRACE_DAYS = 7


def reverify(rpc_check=None) -> dict | None:
    """Re-check a chain-paid licence's transaction, at most once a day. Called by Pro commands (never by the guard,
    which must not open a socket). An unreachable RPC changes nothing: the licence rides on its grace period."""
    body = read()
    if not body or not str(body.get("via", "")).startswith(("solana:", "tempo:")):
        return body
    seen = _parse(str(body.get("verified_at") or body.get("issued") or ""))
    if seen is not None and _now() - seen < timedelta(days=1):
        return body
    chain, tx = str(body["via"]).split(":", 1)
    network = str(body.get("network", "mainnet"))
    try:
        if rpc_check is not None:
            ok = rpc_check(chain, network, tx)
        elif chain == "solana":
            from . import solana

            got = solana.transaction(network, tx)
            ok = bool(got) and (got.get("meta") or {}).get("err") is None
        else:
            from . import tempo

            got = tempo.rpc(network, "eth_getTransactionReceipt", [tx])
            ok = bool(got) and str(got.get("status", "")).lower() in ("0x1", "1")
    except (OSError, ValueError):
        return body  # offline: keep the grace period running
    if ok:
        body["verified_at"] = _now().isoformat()
    else:
        body["revoked"] = f"the {chain} transaction {tx} no longer shows a successful payment"
        body["expires"] = _now().isoformat()
    write(body)
    return body


def _used_path() -> Path:
    return paths.home() / "used-payments.json"


def was_used(chain: str, tx: str) -> bool:
    """A payment activates Pro once on this machine: a transaction replayed into a second activation is refused."""
    try:
        return f"{chain}:{tx}".lower() in json.loads(_used_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False


def mark_used(chain: str, tx: str) -> None:
    try:
        seen = json.loads(_used_path().read_text(encoding="utf-8"))
        if not isinstance(seen, list):
            seen = []
    except (OSError, ValueError):
        seen = []
    seen.append(f"{chain}:{tx}".lower())
    _used_path().write_text(json.dumps(seen), encoding="utf-8")


def trial(start: bool = False) -> dict:
    """{'started', 'ends', 'days_left'}; `start` begins it the first time a Pro command is used."""
    path = trial_path()
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
        began = _parse(got.get("started", ""))
    except (OSError, ValueError, AttributeError):
        began = None
    if began is None:
        if not start:
            return {"started": None, "ends": None, "days_left": TRIAL_DAYS}
        began = _now()
        path.write_text(json.dumps({"started": began.isoformat()}) + "\n", encoding="utf-8")
    ends = began + timedelta(days=TRIAL_DAYS)
    left = (ends - _now()).total_seconds() / 86400
    return {"started": began.isoformat(), "ends": ends.isoformat(), "days_left": max(0.0, left)}


def status(start_trial: bool = False) -> dict:
    """{'active': bool, 'why': 'licence'|'trial'|'expired'|'none', ...}"""
    lic = read()
    if valid(lic):
        return {"active": True, "why": "licence", "plan": lic.get("plan"), "expires": lic.get("expires"),
                "via": lic.get("via")}
    t = trial(start=start_trial)
    if t["started"] and t["days_left"] > 0:
        return {"active": True, "why": "trial", "days_left": t["days_left"], "expires": t["ends"]}
    if t["started"]:
        return {"active": False, "why": "expired", "expires": t["ends"]}
    return {"active": False, "why": "none"}


def from_payment(plan: str, signature: str, reference: str, network: str, paid_usdc: float,
                 seats: int = 1, chain: str = "solana", payer: str = "") -> dict:
    days = PLANS[plan]["days"]
    now = _now()
    current = read()
    begins = now
    if valid(current):  # renewing early adds to what is left
        ends = _parse(str(current.get("expires")))
        if ends and ends > now:
            begins = ends
    return {"plan": plan, "seats": seats, "issued": now.isoformat(), "verified_at": now.isoformat(),
            "expires": (begins + timedelta(days=days)).isoformat(),
            "via": f"{chain}:{signature}", "chain": chain, "network": network, "reference": reference,
            "payer": payer, "paid": paid_usdc}


def decode_code(code: str) -> dict:
    """A licence code is base64url(JSON with a 'sig')."""
    raw = base64.urlsafe_b64decode(code.strip() + "=" * (-len(code.strip()) % 4))
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise ValueError("not a licence")
    return body
