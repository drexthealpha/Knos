"""`knos verify`: the wired verifier. For a delivered job that names this key as its verifier: fetch the delivery from
the relay (checked against the hash on chain), re-run the brief's checks (code briefs in a clean venv), lint it against
the buyer's recalled preferences (Sibyl, deterministic), commit the evidence to a Merkle root, then pay on pass
(`market.verify_release`) or refund on fail (`market.verify_reject`). Each verdict is a signed line.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from solders.keypair import Keypair
from solders.pubkey import Pubkey

# The Knos reference verifier: the key the always-on `knos verify --all --once` worker signs with.
KNOS_VERIFIER = "9TGQPftNmrt8T6ETUZJ5CeQf27z3pFR8En3FkKrA2PbT"   # base58 public key of devnet-worker2; filled in from that key file (public half only)


def resolve(spec: str | None) -> Pubkey | None:
    """`--verify` value -> the verifier key: "knos" (or empty) is the reference verifier, "none" is no verifier,
    otherwise a base58 public key or a path to a keypair file."""
    if spec is None:
        return None
    s = spec.strip()
    if s.lower() in ("", "knos", "default"):
        if not KNOS_VERIFIER:
            raise ValueError("this build has no Knos reference verifier key yet: pass --verify <public key>")
        return Pubkey.from_string(KNOS_VERIFIER)
    if s.lower() in ("none", "off"):
        return None
    if Path(s).is_file():
        return load_key(Path(s)).pubkey()
    try:
        return Pubkey.from_string(s)
    except ValueError:
        raise ValueError(f"{spec!r} is not a public key, a keypair file, 'knos' or 'none'") from None


def load_key(path: Path) -> Keypair:
    return Keypair.from_bytes(bytes(json.loads(Path(path).read_text(encoding="utf-8"))))


@dataclass
class Verdict:
    job_id: bytes
    ok: bool
    root: bytes
    evidence: list[dict]
    signature: str = ""
    settled: str = ""
    problems: list[str] = field(default_factory=list)

    def message(self) -> bytes:
        return b"knos-verdict-v1|" + self.job_id + self.root + (b"\x01" if self.ok else b"\x00")

    def line(self) -> str:
        return (f"verdict {'PASS' if self.ok else 'FAIL'} job {self.job_id.hex()} root {self.root.hex()} "
                f"sig {self.signature}")


def open_delivery(ledger, relay, verifier: Keypair, job_id: bytes) -> bytes:
    """The deliverable under the hash the worker committed: opened with the verifier's key, or as plain text."""
    from . import market
    j = market.job(ledger, job_id)
    if j is None or j.result is None:
        raise LookupError("nothing delivered yet")
    blob = relay.get_delivery(j.result.hex())
    if hashlib.sha256(blob).digest() != j.result:
        raise ValueError("the relay's delivery does not match what the worker committed on chain")
    if blob.startswith(market.ENVELOPE):
        from ..team.registry import open_salt
        return market.open_envelope(blob, "verifier", lambda b: open_salt(b, verifier))
    try:
        return market.open_sealed(verifier, blob)
    except Exception:  # noqa: BLE001 - not sealed to us
        pass
    try:
        blob.decode("utf-8")
        return blob
    except UnicodeDecodeError:
        raise LookupError("the delivery is sealed to the buyer only; the worker must seal a copy to the verifier") \
            from None


def fresh_venv_tests(solution: str, tests: str, timeout: float = 280) -> tuple[bool, str]:
    """A python brief's tests, as a stranger would run them: a fresh venv (uv, else venv), pytest, the solution."""
    work = Path(tempfile.mkdtemp(prefix="knos-verify-"))
    try:
        (work / "solution.py").write_text(solution, encoding="utf-8")
        (work / "test_solution.py").write_text(tests, encoding="utf-8")
        venv = work / ".venv"
        py = venv / ("Scripts" if os.name == "nt" else "bin") / "python"
        uv = shutil.which("uv")
        steps = ([[uv, "venv", "-q", str(venv)], [uv, "pip", "install", "-q", "--python", str(py), "pytest"]] if uv
                 else [[sys.executable, "-m", "venv", str(venv)], [str(py), "-m", "pip", "install", "-q", "pytest"]])
        steps.append([str(py), "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_solution.py"])
        for cmd in steps:
            r = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=timeout)
            if r.returncode:
                tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
                return False, f"`{' '.join(cmd[-2:])}` in a fresh venv failed: {tail[0][:300]}"
        return True, "tests pass in a fresh venv"
    except subprocess.TimeoutExpired:
        return False, "tests timed out in a fresh venv"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def recalled_preferences(brief, buyer: str) -> list[str]:
    """What the buyer asked for before: shared in the brief, plus this machine's Sibyl memory for that buyer."""
    prefs = list(brief.preferences or [])
    try:
        from .buyer_memory import BuyerMemory
        prefs += [p for p in BuyerMemory(buyer).preferences() if p not in prefs]
    except Exception:  # noqa: BLE001 - no memory here is not a failure
        pass
    return prefs


def evaluate(brief, text: str, preferences: list[str], buyer: str = "", clean_venv: bool = True) -> list[dict]:
    """The evidence: the brief's checks, then the preference lint. Each entry {name, ok, evidence}."""
    from ..proof import history
    from . import checks
    ev = []
    c = brief.checks or {}
    if brief.kind == "python" and c.get("tests") and clean_venv:
        ok, why = fresh_venv_tests(text, c["tests"])
        if ok:
            rest = {k: v for k, v in c.items() if k != "tests"}
            ok, why = checks.run("text", rest, text) if rest else (True, why)
    else:
        ok, why = checks.run(brief.kind, c, text)
    ev.append({"name": "brief", "ok": ok, "evidence": why})
    found = history.lint_preferences(preferences, buyer or None, text)
    ev.append({"name": "preferences", "ok": not found,
               "evidence": [str(v) for v in found] or f"{len(preferences)} preference(s) hold"})
    return ev


def verify_job(ledger, relay, verifier: Keypair, job_id: bytes, preferences: list[str] | None = None,
               clean_venv: bool = True) -> Verdict:
    """Check one delivered job and settle it on chain. Raises LookupError when it is not ours to verify."""
    from ..proof import receipt
    from . import market
    j = market.job(ledger, job_id)
    if j is None:
        raise LookupError("No such job on this cluster.")
    if j.verifier != verifier.pubkey():
        raise LookupError("This job does not name you as its verifier.")
    if j.state != "delivered":
        raise LookupError(f"The job is {j.state}; this needs it delivered.")
    brief = market.Brief.decode(relay.get_brief(j.brief.hex()))
    text = open_delivery(ledger, relay, verifier, job_id).decode("utf-8", "replace")
    prefs = preferences if preferences is not None else recalled_preferences(brief, str(j.buyer))
    ev = evaluate(brief, text, prefs, str(j.buyer), clean_venv)
    ev.append({"name": "delivery", "ok": True, "evidence": j.result.hex()})
    root = receipt.merkle_root(receipt.leaves(ev))
    ok = all(e["ok"] for e in ev)
    v = Verdict(job_id, ok, root, ev)
    v.problems = [str(x) for e in ev if not e["ok"] for x in (e["evidence"] if isinstance(e["evidence"], list)
                                                              else [e["evidence"]])]
    if ok:
        market.verify_release(ledger, verifier, job_id, root)
        v.settled = "released"
    else:
        reject = getattr(market, "verify_reject", None)
        if reject is None:
            raise RuntimeError("this Knos build has no market.verify_reject yet: the failed work was not refunded")
        reject(ledger, verifier, job_id, root)
        v.settled = "rejected"
    v.signature = str(verifier.sign_message(v.message()))
    return v


def pending(ledger, relay, verifier: Pubkey) -> list[bytes]:
    """Every delivered job naming this verifier, by job id."""
    from . import market
    out = []
    for j in ledger.jobs("delivered"):
        if j.verifier == verifier:
            jid = market.job_id_for(ledger, j.address, relay=relay)
            if jid:
                out.append(jid)
    return out
