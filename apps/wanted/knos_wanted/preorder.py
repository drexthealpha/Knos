"""Pre-orders on an OPEN demand report, paid to the maker only on proof: Knos's staged vault (knos.ideas.commit).

One pre-order = one commitment with ONE stage, "milestone" (oracle referee_pass), locked on the knos_pay 0.3.34 TEST
program on devnet as a PANEL order: 2 of 3 referee keys release it to the maker's wallet; past its deadline anyone
refunds it to the buyer. Who is who on this server (all devnet TEST keys, no real money):
  buyer     the signed-in person's own passkey wallet (knos_wanted.wallets: a LazorKit smart wallet; the passkey signs)
  maker     the payee: a wallet made for this one receivable, owned by the passkey of the maker who claimed the milestone
  referees  KNOS_WANTED_REFEREE_KEYS: a JSON list of 3 secret keys (base58 strings or byte arrays) the SERVER holds.
            One server holding all three is NOT an independent panel; the commitment says UNLISTED PANEL (the keys are
            not in Knos's referee registry, config/referees.yaml).
  relayer   KNOS_WANTED_RELAYER_KEYPAIR (default: the app's devnet test wallet KNOS_WANTED_DEVNET_KEYPAIR) pays fees and
            rents, relays the passkeys' transactions and the verdicts, and is the test mint's authority (the faucet).
The milestone is verified by code before any referee signs: the maker's evidence URL is fetched over https (public
addresses only, no redirects, size and time limits) and must contain the commitment's claim id. Verified: 2 referees
sign PASS over that page (its sha256 is the evidence) and the server releases. Not verified: nothing is signed, the
money stays locked, and after the deadline it is refunded. The maker is paid only once the report's reserve is met.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import company, escrow

PROGRAM_034_TEST = "FaMHCjzyUexFncZrmNyFQNz3gBdsLbhTLke7QBFykJY4"   # knos_pay 0.3.34 TEST build on devnet
FIELD = "Business, Management and Accounting"
PRICE = 1                       # test units per pre-ordered unit
MAX_PRICE = 4                   # the premium tier (check.TIERS)
MAX_DAYS = 90                   # knos_pay's longest stage deadline
MAX_EVIDENCE = 512_000
EVIDENCE_TIMEOUT_S = 10
_lock = threading.Lock()


class Unavailable(escrow.EscrowUnavailable):
    pass


class NotVerified(ValueError):
    pass


def _kp(v):
    from solders.keypair import Keypair
    if isinstance(v, list):
        return Keypair.from_bytes(bytes(v))
    if isinstance(v, str) and v.strip().startswith("["):
        return Keypair.from_bytes(bytes(json.loads(v)))
    if isinstance(v, str) and Path(v).expanduser().is_file():
        return _kp(json.loads(Path(v).expanduser().read_text(encoding="utf-8")))
    return Keypair.from_base58_string(str(v).strip())


def referees() -> list:
    raw = os.environ.get("KNOS_WANTED_REFEREE_KEYS", "")
    if not raw:
        raise Unavailable("holding money is unavailable on this server (no referee keys: KNOS_WANTED_REFEREE_KEYS)")
    try:
        got = json.loads(raw) if raw.strip().startswith("[") else json.loads(Path(raw).expanduser().read_text(encoding="utf-8"))
        keys = [_kp(k) for k in got]
    except Exception:  # noqa: BLE001 - never echo the value
        raise Unavailable("holding money is unavailable on this server (KNOS_WANTED_REFEREE_KEYS is not a JSON list of 3 secret keys)") from None
    if len(keys) != 3 or len({str(k.pubkey()) for k in keys}) != 3:
        raise Unavailable("holding money is unavailable on this server (KNOS_WANTED_REFEREE_KEYS: 3 distinct keys)")
    return keys


def panel() -> tuple[int, list[str]]:
    """The panel every new order pins: the FROST referee group (1 of 1: its group key; 2 of 3 hosts sign it,
    knos_wanted.referee) when this server is a FROST host, else 2 of the 3 server-held keys (UNLISTED PANEL)."""
    from . import referee
    if referee.enabled():
        return referee.panel()
    return 2, [str(r.pubkey()) for r in referees()]


def ready() -> tuple[bool, str]:
    from . import referee
    if not (os.environ.get("KNOS_WANTED_REFEREE_KEYS") or referee.enabled()) or not os.environ.get("KNOS_WANTED_DEVNET_KEYPAIR"):
        return False, "holding money is unavailable on this server"
    try:
        escrow.knos()
        from knos.ideas import commit  # noqa: F401
    except Exception as why:  # noqa: BLE001
        return False, f"holding money is unavailable on this server ({type(why).__name__})"
    return True, "ok"


def _need() -> None:
    ok, why = ready()
    if not ok:
        raise Unavailable(why)


def program():
    from solders.pubkey import Pubkey
    return Pubkey.from_string(os.environ.get("KNOS_WANTED_PROGRAM") or PROGRAM_034_TEST)


def relayer():
    v = os.environ.get("KNOS_WANTED_RELAYER_KEYPAIR")
    return _kp(v) if v else escrow.demo_key()


RELAYER_LOW_SOL = 0.5          # below this the app says so: a release costs about 0.003 SOL, the faucet is often dry
_funds: dict = {}


def relayer_funds(max_age_s: float = 60.0) -> dict:
    """The relayer's devnet SOL, read from the chain at most once a minute, with an alert below RELAYER_LOW_SOL (the
    release of 24 Oct 2026 failed at 0.00083 SOL: the payout's token account could not be paid for)."""
    if _funds and time.monotonic() - _funds.get("_at", 0) < max_age_s:
        return {k: v for k, v in _funds.items() if k != "_at"}
    try:
        from knos import chain
        who = str(relayer().pubkey())
        sol = int(chain.call(escrow.ledger().url, "getBalance", [who])["value"]) / 1e9
    except Exception as why:  # noqa: BLE001 - no wallet configured, or the RPC did not answer: said, not guessed
        return {"read": False, "why": f"{type(why).__name__}: {str(why)[:120]}"}
    low = sol < RELAYER_LOW_SOL
    if low and not _funds.get("low"):
        print(f"knos relayer: {who} holds {sol:.4f} devnet SOL, under {RELAYER_LOW_SOL}: releases may fail", file=sys.stderr, flush=True)
    _funds.clear()
    _funds.update({"read": True, "address": who, "sol": round(sol, 6), "low": low, "floor_sol": RELAYER_LOW_SOL, "_at": time.monotonic(),
                   **({"alert": f"the relayer holds {sol:.4f} devnet SOL, under {RELAYER_LOW_SOL}: top it up before releases fail"} if low else {})})
    return {k: v for k, v in _funds.items() if k != "_at"}


def _counted(rec: dict) -> None:
    if rec.get("status") == "locked":
        from . import outside
        outside.note("commitment", rec.get("order") or "", rec.get("via_kind") or "preorder", rec.get("buyer"))


def _dir() -> Path:
    d = escrow._state_dir() / "commitments"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save(rec: dict) -> None:
    f = _dir() / f"{rec['order']}.commit"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    os.replace(tmp, f)
    _counted(rec)                          # a locked commitment, once, on the outside counter (knos_wanted.outside)


def load(order: str) -> dict:
    if not isinstance(order, str) or not order.isalnum() or not 32 <= len(order) <= 44:
        raise ValueError("commitment: the order address a pre-order returned")
    f = _dir() / f"{order}.commit"
    if not f.exists():
        raise ValueError("unknown commitment on this server")
    return json.loads(f.read_text(encoding="utf-8"))


def of_report(report_hash: str) -> list[dict]:
    out = []
    for f in sorted(_dir().glob("*.commit")):
        try:
            r = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if r.get("report") == report_hash:
            out.append({k: r[k] for k in ("order", "units", "buyer", "status", "claim_id", "made") if k in r})
    return out


PREORDER_VIA = "pre-order signed by the buyer's passkey (test money)"
FUNDER_VIA = ("funder money: a funder's money, held for this milestone (its own devnet order and claim id, beside the pre-orders; "
              "paid to the maker on proof, refunded after the deadline)")


def fee_line(units: int | None = None, unit_price: int | None = None) -> dict:
    """What Knos takes, from config/fees.yaml: the payout fee, held with the money and taken only at release."""
    try:
        from knos.money import fees_config
        cfg = fees_config.load()
        f = cfg.doc["fees"]
        bps = int(f["payout"]["rate_bps"])
        out = {"rate_bps": bps, "percent": bps / 100, "floor": f["payout"].get("floor_usd"), "status": f["payout"]["status"],
               "funding_fee_bps": int(f["funding"]["rate_bps"]), "graduation": {"rate_bps": int(f["graduation"]["rate_bps"]),
               "status": f["graduation"]["status"], "collected": f["graduation"].get("collected")},
               "text": f"Knos takes {bps / 100:g}% (at least {f['payout'].get('floor_usd')} test units) only on money released on proof; "
                       "a refund costs the buyer nothing", "source": "config/fees.yaml (fees.payout, fees.funding)"}
        if units:
            amount = int(units) * int(unit_price or PRICE)                   # the order's amount: what the release settles
            out["on_this_preorder"] = cfg.fee("payout", amount * escrow.UNIT) / escrow.UNIT
            out["on_amount"] = amount
        return out
    except Exception as why:  # noqa: BLE001
        return {"text": "fees: knos is not installed on this server", "why": type(why).__name__}


# ---- lock ------------------------------------------------------------------------------------------------------------
def lock(report: dict, units: int, buyer_label: str, maker_wallet: str | None = None, days: int | None = None, led=None,
         funder: bool = False) -> dict:
    """Refused: since this release a pre-order is signed by the buyer's own passkey (knos_wanted.wallets.prepare_preorder,
    then wallets.sign). No server key buys for anyone. The report's checks still run first, so the reason given is the
    first one that applies."""
    d = report.get("decision") or {}
    if d.get("verdict") != "OPEN" or report.get("label", "").startswith("NO QLOO"):
        raise ValueError("pre-orders open only on a report whose decision is OPEN on live Qloo evidence")
    _need()
    from .wallets import NeedPasskey
    raise NeedPasskey("a pre-order is signed by the buyer's own passkey: POST /api/preorder returns the challenge, "
                      "your passkey signs it, POST /api/sign relays it")


def all_public(n: int = 50) -> list[dict]:
    out = []
    for f in sorted(_dir().glob("*.commit"), key=lambda f: f.stat().st_mtime, reverse=True)[:n]:
        try:
            out.append(public(json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError):
            continue
    return out


def _finality(sigs: dict) -> dict:
    """Measured time to finality per signature this process sent (knos.platform.finality: Alpenglow-aware)."""
    try:
        from knos.platform import finality
        rows = {k: finality.timing_of(v) for k, v in sigs.items()}
        return {k: v for k, v in rows.items() if v}
    except Exception:  # noqa: BLE001
        return {}


VERIFIER = ("verdicts checked on chain by knos_pay: an ed25519 pre-instruction carries the 2-of-3 referee signatures "
            "over the evidence pin, and the program pays only when they verify; knos_oidc verifies GitHub-OIDC-judged "
            "stages (not used for this panel stage). Test units stand in for USDC on devnet (6 decimals).")


def public(rec: dict) -> dict:
    sigs = {k: v for k, v in rec.get("signatures", {}).items() if v}
    return {"commitment": rec["order"], "claim_id": rec["claim_id"], "report": rec["report"], "units": rec["units"],
            "unit_price": rec.get("unit_price", PRICE), "via": rec.get("via", PREORDER_VIA), "via_kind": rec.get("via_kind", "preorder"), "factoring": rec.get("factoring"),
            "idea": rec.get("idea"),
            "buyer": rec["buyer"], "maker_wallet": rec["maker_wallet"], "status": rec["status"], "milestone": "stage1 (referee_pass)",
            "panel": {"m": 2, "of": 3, "keys": rec["doc"]["panel"]["keys"], "label": rec["doc"]["panel"]["label"] or "UNLISTED PANEL",
                      "note": "the three referee keys are held by this one server: not an independent panel"},
            "program": rec["doc"]["program"], "mint": rec["doc"]["mint"], "deadline_days": rec["deadline_days"],
            "signatures": sigs, "explorer": {k: escrow.explorer(v) for k, v in sigs.items() if isinstance(v, str)},
            "order_explorer": escrow.explorer(rec["order"], "address"), "evidence": rec.get("evidence"),
            "how_to_prove": f"publish a public https page that contains {rec['claim_id']} and post its URL as the milestone evidence",
            "money": "test units of this app's own devnet test mint: test money, 0 revenue", "fees": fee_line(rec["units"], rec.get("unit_price", PRICE)),
            "record": rec.get("record"), "release_record": rec.get("release_record"),
            "finality": _finality(sigs), "verifier": VERIFIER}


# ---- milestone evidence ----------------------------------------------------------------------------------------------
def _public_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise NotVerified(f"{host}: does not resolve") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise NotVerified(f"{host}: resolves to a private or reserved address; evidence must be on the public internet")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        raise NotVerified("the evidence URL redirects; post the final https URL")


def fetch_evidence(url: str, opener=None, resolve=_public_host) -> bytes:
    u = urllib.parse.urlparse(str(url or "").strip())
    if u.scheme != "https" or not u.hostname or u.username or u.password or (u.port not in (None, 443)):
        raise NotVerified("evidence_url: a public https URL (port 443, no credentials)")
    if len(url) > 2000:
        raise NotVerified("evidence_url: at most 2,000 characters")
    resolve(u.hostname)
    op = opener or urllib.request.build_opener(_NoRedirect).open
    req = urllib.request.Request(url, headers={"User-Agent": "knos-demand-check milestone verifier", "Accept": "text/html,text/plain,application/json"})
    try:
        with op(req, timeout=EVIDENCE_TIMEOUT_S) as r:
            body = r.read(MAX_EVIDENCE + 1)
    except NotVerified:
        raise
    except urllib.error.HTTPError as e:
        raise NotVerified(f"the evidence URL answered HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NotVerified(f"the evidence URL could not be read ({type(e).__name__})") from None
    if len(body) > MAX_EVIDENCE:
        raise NotVerified(f"the evidence page is larger than {MAX_EVIDENCE:,} bytes")
    return body


CHANGING = ("this page changes on every load (two fetches gave different bytes): each referee host fetches it itself "
            "and signs the sha256 of exactly those bytes, so a page that echoes the request (its headers, time or address) "
            "can never be signed. Use a static page: a file in a repository or a gist, a published report")


def static_evidence(url: str, fetch) -> bytes:
    """The evidence page, fetched twice: the referee hosts each fetch it and sign over its bytes, so bytes that differ
    between two loads (an echo service, a page with a timestamp) are refused here, before anyone is asked to sign."""
    body = fetch(url)
    if fetch(url) != body:
        raise NotVerified(CHANGING)
    return body


def verify(rec: dict, url: str, opener=None, resolve=_public_host) -> tuple[dict, bytes]:
    body = static_evidence(url, lambda u: fetch_evidence(u, opener, resolve))
    if rec["claim_id"].encode() not in body:
        raise NotVerified(f"the evidence page does not contain the commitment's claim id {rec['claim_id']}")
    return {"url": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "contains_claim_id": True}, body


def reserve_status(report: dict, held: dict | None = None) -> dict:
    """Units pre-ordered vs the reserve, from this server's commitment files (locked or released orders)."""
    if held is not None:
        pre = held.get("preorders") or {}
        return {"pre_ordered_units": pre.get("units", 0), "reserve_units": held.get("reserve_units") or 0,
                "met": pre.get("units", 0) >= (held.get("reserve_units") or 0), "source": "Knos Record (Sibyl)"}
    locked = sum(r["units"] for r in of_report(report["hash"]) if r.get("status") in ("locked", "released"))
    need = (report.get("decision") or {}).get("reserve_units") or 0
    return {"pre_ordered_units": locked, "reserve_units": need, "met": locked >= need, "source": "this server's commitment files"}


class NotOwner(PermissionError):
    """Evidence on a commitment from an account that does not own it (HTTP 403)."""


def must_own(rec: dict, user: dict | None) -> None:
    """Only the maker whose passkey claimed the milestone posts its evidence: the session's sub must be the
    commitment's receivable maker_sub. A guest session, anyone else, or a commitment that names no owner is refused
    here, before any page is fetched, signed or released."""
    owner = str((rec.get("receivable") or {}).get("maker_sub") or "")
    if not owner or str((user or {}).get("sub") or "") != owner:
        if not owner:
            raise NotOwner("this commitment names no maker who owns it, so no evidence is taken for it")
        raise NotOwner(f"only the maker who owns commitment {rec.get('order', '')} posts its evidence, and this session is not that maker")


class Settled(ValueError):
    """The order is closed on chain: knos_pay paid (or refunded) it, and a stage is paid once."""


def chain_gate(rec: dict, led) -> None:
    """Before any release: read the order account on devnet. A closed order (released or refunded) is refused here,
    and the program would refuse it too (no order account, nothing to pay)."""
    from solders.pubkey import Pubkey
    if led.account(Pubkey.from_string(rec["order"])) is None:
        raise Settled(f"refused: the order {rec['order']} is closed on devnet (already released or refunded); "
                      "knos_pay pays a stage once")


def evidence_pin(doc: dict, review) -> dict:
    """THE canonical evidence pin, the one the referees sign and the program checks on chain: knos.ideas.commit.review_evidence
    over the saved evidence page. Its `evidence_hash` is sha256 of the signed structure (oracle, claim id and hash, the
    result, and the page's sha256 as report_sha256). The page shows this same value beside the page's own sha256."""
    from knos.ideas import commit as C
    return C.review_evidence(doc, "referee_pass", True, review)


def milestone(report: dict, order: str, url: str, led=None, opener=None, resolve=_public_host) -> dict:
    """Verify the maker's evidence; when verified and the reserve is met, 2 referees sign PASS and the server releases."""
    rec = load(order)
    _need()
    from knos.ideas import commit as C
    led = led or escrow.ledger()
    chain_gate(rec, led)                 # the chain decides: a closed order is never released again
    if rec["status"] != "locked":
        raise ValueError(f"this commitment is already {rec['status']}")
    res = reserve_status(report, None)
    if not res["met"]:
        raise ValueError(f"reserve not met: {res['pre_ordered_units']} of {res['reserve_units']} units pre-ordered; the maker is paid once it is")
    ev, body = verify(rec, url, opener, resolve)
    doc = rec["doc"]
    review = _dir() / f"{order}.evidence"           # the page the referees sign over
    review.write_bytes(body)
    pin = evidence_pin(doc, review)                  # the ONE pin: what the verdicts carry and the chain records
    ev["chain_pin"] = pin["evidence_hash"]
    ev["chain_pin_of"] = ("sha256 of the signed evidence structure (oracle, claim id and hash, result, and the page's "
                          "sha256): knos.ideas.commit.review_evidence; this is the hash in the release transaction")
    if (doc.get("panel") or {}).get("m") == 1:
        # a FROST group panel: two of the three referee hosts sign, each after its own check; the release is sent
        # when the second share arrives (knos_wanted.referee._released)
        from . import referee
        if not referee.enabled():
            raise Unavailable("this commitment's referee group is not configured on this server")
        sig = referee.start(rec, url, led)
        with _lock:
            rec["evidence"], rec["referee_session"] = ev, {"id": sig["session"], "github": sig["github"]}
            _save(rec)
        return {**public(rec), "verified": ev, "release": "signing: " + sig["needs"], "session": sig["session"], "reserve": res}
    refs = referees()
    with _lock:
        recs = [C.sign(doc, "stage1", r, led, passed=True, review=review) for r in refs[:2]]
        if any(r["evidence_hash"] != ev["chain_pin"] for r in recs):
            raise RuntimeError("the displayed evidence pin diverged from the signed verdicts")
        got = C.release(doc, "stage1", recs, relayer(), led)
        rec["status"] = got["status"] if got["status"] in ("released", "refunded") else "locked"
        rec["evidence"] = ev
        for i, s in enumerate(got["sent"], 1):
            rec["signatures"][f"referee_{i}_pass"] = s["signature"]
        if rec["status"] == "released":
            rec["release_record"] = company.record_release(rec["report"], order, [s["signature"] for s in got["sent"]], ev["chain_pin"])
        _save(rec)
    return {**public(rec), "verified": ev, "release": got["status"], "reserve": res}


def refund(order: str, led=None) -> dict:
    """Past the deadline, the locked pre-order goes back to the buyer (knos.ideas.commit.refund, no verdicts)."""
    _need()
    from knos.ideas import commit as C
    rec = load(order)
    led = led or escrow.ledger()
    with _lock:
        got = C.refund(rec["doc"], "stage1", [], relayer(), led)
        rec["status"] = got["status"]
        if got["sent"]:
            rec["signatures"]["refund"] = got["sent"][0]["signature"]
        _save(rec)
    return public(rec)


# ---- preflight: is the money path really working on this server? ----------------------------------------------------
PREFLIGHT_TTL_S = 600
_pre: dict = {"at": 0.0, "ok": False, "why": "not checked yet"}
_pre_lock = threading.Lock()


TX_LIMIT, TX_BUDGET = 1232, 1182          # Solana's packet limit, and Knos's ceiling (a 50-byte margin)


def tx_size(ixs, payer, signers) -> int:
    from solders.hash import Hash
    from solders.message import Message
    from solders.transaction import Transaction
    return len(bytes(Transaction(signers, Message.new_with_blockhash(ixs, payer, Hash.default()), Hash.default())))


def largest_preorder_txs() -> dict:
    """The sizes, in bytes, of the transactions a pre-order sends for the LARGEST allowed inputs: a 500-character idea,
    an 80-character buyer label, 1,000 units, the longest deadline, a 3-key panel, a fresh mint and fresh token accounts.
    lock sends the PANEL order alone (C.commit); the preflight simulates top-up + ATAs + order together."""
    from solders.keypair import Keypair

    from knos import ideas
    from knos.ideas import wanted as W
    from knos.settle.v2 import pay
    buyer, mint, refs = Keypair(), Keypair().pubkey(), [Keypair() for _ in range(3)]
    claim = ideas.claim(f"Pre-order 9999 for: {'x' * 500} (Knos demand report {'f' * 16})", field_name=FIELD, kind="person",
                        by={"app": "knos demand check", "report": "f" * 64, "buyer": "b" * 80})
    p = W.plan(claim, units=1000, price=MAX_PRICE, stages=[("referee_pass", 10_000)], stage_work_s=[MAX_DAYS * 86_400])
    tok = pay.ata(buyer.pubkey(), mint)
    fund = W.fund_panel_ix(p, "stage1", buyer.pubkey(), tok, mint, 2, [bytes(r.pubkey()) for r in refs], program=program(), unlisted_panel=True)
    setup = [pay.create_ata_ix(buyer.pubkey(), w, mint) for w in (buyer.pubkey(), pay.FEE_OWNER)]
    wallet = Keypair()                                      # a Blink: the wallet's token account, the top-up, the order
    wtok = pay.ata(wallet.pubkey(), mint)
    wfund = W.fund_panel_ix(p, "stage1", wallet.pubkey(), wtok, mint, 2, [bytes(r.pubkey()) for r in refs], program=program(), unlisted_panel=True)
    blink_ixs = [pay.create_ata_ix(wallet.pubkey(), wallet.pubkey(), mint), escrow._mint_to_ix(mint, wtok, buyer.pubkey(), 4001), wfund]
    # the passkey pre-order (knos_wanted.wallets): [secp256r1, LazorKit Execute(FundOrderWallet)] in a v0 transaction
    # through the relayer's shared table and the wallet's own table
    from solders.hash import Hash
    from solders.instruction import Instruction
    from solders.transaction import VersionedTransaction

    from knos.settle.v2 import passkey_smart as ps
    cred, key = bytes(32), bytes([2]) + bytes(range(1, 33))
    w = ps.wallet_pda(ps.user_seed("main", cred))
    v = ps.vault_pda(w)
    pfund = W.fund_panel_ix(p, "stage1", v, pay.ata(v, mint), mint, 2, [bytes(r.pubkey()) for r in refs], program=program(), unlisted_panel=True)
    prep = ps.execute(buyer.pubkey(), w, ps.authority_pda(w, cred)[0], [pfund], slot=2 ** 40, counter=2 ** 31, rp_id="knos.onrender.com", key=key)
    pk_ixs = [ps.secp256r1_ix(key, bytes([1]) * 64, prep.auth_data + bytes(32)),
              Instruction(prep.program, bytes([prep.discriminator]) + prep.data_payload + prep.auth_payload, prep.accounts)]
    tables = [(Keypair().pubkey(), ps.table_addresses(program(), mint)), (Keypair().pubkey(), ps.wallet_table_addresses(w, cred, mint))]
    passkey = len(bytes(VersionedTransaction(ps.message_v0(buyer.pubkey(), pk_ixs, tables, Hash.default()), [buyer])))
    return {"blink": tx_size(blink_ixs, wallet.pubkey(), [wallet, buyer]), "passkey_preorder": passkey,
            "preorder": tx_size([fund], buyer.pubkey(), [buyer]),
            "preflight": tx_size([*setup, escrow._mint_to_ix(mint, tok, buyer.pubkey(), 1001), fund], buyer.pubkey(), [buyer])}


def _simulate(led, ixs, payer, signers) -> dict:
    """simulateTransaction (nothing is sent): the cluster runs the transaction against current state."""
    import base64

    from solders.hash import Hash
    from solders.message import Message
    from solders.transaction import Transaction

    from knos import chain
    tx = Transaction(signers, Message.new_with_blockhash(ixs, payer, Hash.default()), Hash.default())
    got = chain.call(led.url, "simulateTransaction", [base64.b64encode(bytes(tx)).decode(),
                                                      {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True,
                                                       "commitment": "confirmed"}], timeout=20)
    return got.get("value") or {}


def preflight(led=None) -> tuple[bool, str]:
    """Build the transaction a 5-unit pre-order sends (test mint top-up, the stage's PANEL order with the panel new
    orders pin: preorder.panel) and SIMULATE it on devnet with the app's devnet test wallet as the funder (a health check: nothing is sent,
    no one buys; real pre-orders are signed by the buyer's passkey). Every import, key, config file and the wallet's SOL are
    exercised; nothing is sent. (False, why) on any failure."""
    ok, why = ready()
    if not ok:
        return False, why
    try:
        from solders.pubkey import Pubkey

        from knos import ideas
        from knos.ideas import wanted as W
        from knos.settle.v2 import pay
        led = led or escrow.ledger()
        buyer, (pm, pkeys), prog = escrow.demo_key(), panel(), program()
        ixs, signers = [], [buyer]
        try:
            mint = escrow.mint(led, create=False)
        except escrow.EscrowUnavailable:
            # no test mint yet: make it now, once (the first pre-order would), so the pre-order itself can be simulated.
            # Creating it inside the simulated transaction made it 1,233 bytes on a fresh host (limit 1,232).
            mint = escrow.mint(led, create=True)
            print(f"knos-demand-check: created the devnet test mint {mint} for pre-orders", flush=True)
        tok = pay.ata(buyer.pubkey(), mint)
        ixs += [pay.create_ata_ix(buyer.pubkey(), w, mint) for w in (buyer.pubkey(), pay.FEE_OWNER) if led.account(pay.ata(w, mint)) is None]
        ixs.append(escrow._mint_to_ix(mint, tok, buyer.pubkey(), 6))
        claim = ideas.claim("Knos demand check preflight: a 5-unit pre-order, simulated only", field_name=FIELD, kind="agent")
        p = W.plan(claim, units=5, price=PRICE, stages=[("referee_pass", 10_000)], stage_work_s=[30 * 86_400])
        ixs.append(W.fund_panel_ix(p, "stage1", buyer.pubkey(), tok, mint, pm, [bytes(Pubkey.from_string(k)) for k in pkeys], program=prog,
                                   unlisted_panel=True))
        n = tx_size(ixs, buyer.pubkey(), signers)
        if n > TX_BUDGET:
            return False, f"pre-order preflight: the transaction is {n} bytes, above Knos's budget of {TX_BUDGET} (Solana's limit is 1,232)"
        v = _simulate(led, ixs, buyer.pubkey(), signers)
    except Exception as e:  # noqa: BLE001 - the reason is shown on /api/status (no secrets: names and types only)
        return False, f"pre-order preflight failed: {type(e).__name__}: {str(e)[:160]}"
    if v.get("err") is not None:
        logs = [x for x in (v.get("logs") or []) if "rror" in x][-1:]
        return False, f"pre-order preflight: devnet simulation failed ({v.get('err')}{'; ' + logs[0][:160] if logs else ''})"
    return True, f"ok: a pre-order transaction simulated on devnet ({v.get('unitsConsumed', '?')} compute units)"


def preflight_status(force: bool = False, led=None) -> dict:
    with _pre_lock:
        if force or time.time() - _pre["at"] > PREFLIGHT_TTL_S:
            ok, why = preflight(led)
            _pre.update(at=time.time(), ok=ok, why=why)
        return {"available": _pre["ok"], "why": _pre["why"], "checked": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_pre["at"])),
                "preflight": "simulateTransaction of a 5-unit pre-order on devnet, every 10 minutes",
                "label": ("health check, nothing is sent: the app's devnet test wallet is the funder only inside the "
                          "simulation; every real pre-order is signed by the buyer's own passkey")}
