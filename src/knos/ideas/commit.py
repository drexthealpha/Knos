"""The commitment file: what `knos idea commit` locked, and what `sign`, `release`, `refund` and `state` read.

    knos idea commit idea.json --units 10 --price 4 --payee orcid:0000-...@<wallet> --panel 2:<k1>,<k2>,<k3> \\
                               --program <knos_pay panel test build id> --wallet buyer.json --mint <mint>   -> idea.commit.json
    knos idea sign idea.commit.json stage1 --referee referee.json                -> one referee's signed verdict (a file)
    knos idea release idea.commit.json stage1 --sig a.json --sig b.json --wallet relayer.json   (m signatures: paid)
    knos idea refund idea.commit.json stage2 --sig a.json --sig b.json --wallet relayer.json    (m FAIL verdicts: refunded now)
    knos idea refund idea.commit.json stage2 --wallet relayer.json                              (past its deadline)
    knos idea state idea.commit.json                                              (what the chain holds; no flags repeated)

What is decided at commit and never after: the payee (named by --payee; there is no default), the judge of each stage
(a referee PANEL, m of n keys pinned on chain, or the GitHub-signed judge workflow), the stages, amounts and deadlines.
A panel is held to Knos's published referee registry (config/referees.yaml, knos.platform.referees.panel_rule): a panel
holding the funder's or the payee's own key is refused, and keys off the registry are refused unless the buyer passes
--unlisted-panel, in which case the commitment and every output say UNLISTED PANEL. A verdict is accepted only when it names the committed payee, the committed order and its
current funding, and is signed by a committed referee; the program checks the same on chain.

Referees sign where their keys are (`sign` runs on the referee's machine): the buyer never holds them.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from solders.pubkey import Pubkey
from solders.signature import Signature

from ..settle.v2 import pay
from . import IdeaError, check as check_record, now
from . import wanted as W

V = 1
KIND = "knos-idea-commitment"


# ---- the payee and the panel ----------------------------------------------------------------------------------------
def wallet_payee_id(addr: str) -> int:
    """The payee number of a payee named only by a wallet (no GitHub or ORCID iD): stable, derived from the address."""
    return int.from_bytes(hashlib.sha256(b"knos3:wallet" + bytes(Pubkey.from_string(addr))).digest()[:6], "little") + 10 ** 15


def parse_payee(text: str) -> dict:
    """`github:<id>[@<wallet>]`, `orcid:<iD>[@<wallet>]` or `<wallet>`. Who is paid when a stage is released."""
    from . import orcid_ok
    t = (text or "").strip()
    if not t:
        raise IdeaError("--payee is required: github:<id>@<wallet>, orcid:<iD>@<wallet> or a wallet address (no payee is assumed)")
    who, _, wallet = t.partition("@")
    if wallet:
        try:
            Pubkey.from_string(wallet)
        except ValueError:
            raise IdeaError(f"{wallet}: not a Solana address") from None
    if who.startswith("github:"):
        gid = who[7:]
        if not gid.isdigit() or not 1 <= int(gid) < 10 ** 15:
            raise IdeaError("github:<numeric account id> (api.github.com/users/<login> shows it)")
        return {"kind": "github", "id": int(gid), "wallet": wallet or None, "payee_id": int(gid)}
    if who.startswith("orcid:"):
        oid = who[6:].upper()
        if not orcid_ok(oid):
            raise IdeaError(f"{oid}: not a valid ORCID iD")
        return {"kind": "orcid", "id": oid, "wallet": wallet or None, "payee_id": oid}
    try:
        Pubkey.from_string(who)
    except ValueError:
        raise IdeaError(f"{who!r}: name the payee as github:<id>@<wallet>, orcid:<iD>@<wallet> or a wallet address") from None
    return {"kind": "wallet", "id": who, "wallet": who, "payee_id": wallet_payee_id(who)}


def payees_of(payee: dict) -> list:
    """The payees a release pays: one, or a `split` (up to knos_pay's 4 payees, basis points summing to 10,000), e.g. the
    maker and a referrer's share (apps/wanted knos_wanted.valley.split_payee)."""
    split = payee.get("split")
    if split:
        rows = [(s["payee_id"], int(s["bps"]), Pubkey.from_string(s["wallet"])) for s in split]
        if not 1 <= len(rows) <= pay.MAX_PAYEES or sum(b for _, b, _ in rows) != 10_000 or len({r[0] for r in rows}) != len(rows):
            raise IdeaError("payee split: 1 to 4 distinct payees whose basis points sum to 10,000")
        return rows
    return [(payee["payee_id"], 10_000, Pubkey.from_string(payee["wallet"]) if payee.get("wallet") else None)]


def payees_text(payee: dict) -> str:
    from ..proof import issuers
    return issuers.payees_text(payees_of(payee))


def parse_panel(text: str, funder: Pubkey | str | None = None, payee_wallet: str | None = None,
                unlisted_panel: bool = False) -> tuple[int, list[str], str]:
    """`M:key1,key2,key3` (base58 public keys) -> (M, keys, label). Refused: a malformed panel, repeated keys, the
    funder's or the payee's own key, and keys off Knos's referee registry unless `unlisted_panel` (label UNLISTED PANEL)."""
    from ..platform import referees
    m_text, _, rest = (text or "").partition(":")
    keys = [k.strip() for k in rest.split(",") if k.strip()]
    if not m_text.isdigit() or not keys:
        raise IdeaError("--panel M:key1,key2,key3 (M of the listed referee keys release a stage)")
    m = int(m_text)
    if not 1 <= m <= len(keys) <= 10 or len(set(keys)) != len(keys):
        raise IdeaError("a panel is 1 <= M <= N <= 10 distinct referee keys")
    for k in keys:
        try:
            Pubkey.from_string(k)
        except ValueError:
            raise IdeaError(f"{k}: not a public key") from None
    if funder is not None and str(funder) in keys:
        raise IdeaError("the panel contains the funder's own key: a buyer cannot referee its own commitment")
    if payee_wallet is not None and payee_wallet in keys:
        raise IdeaError("the panel contains the payee's own key: the payee cannot referee its own payment")
    try:
        label = referees.panel_rule(keys, funder=funder, payees=[payee_wallet] if payee_wallet else (), unlisted_panel=bool(unlisted_panel))
    except referees.PanelError as why:
        raise IdeaError(f"panel: {why}") from None
    return m, keys, label


def _panel_bytes(panel) -> tuple[int, list[bytes]]:
    return panel[0], [bytes(Pubkey.from_string(k)) for k in panel[1]]


# ---- the commitment file ---------------------------------------------------------------------------------------------
def plan_of(doc: dict) -> dict:
    """The plan recomputed from what was committed; refused when the file was changed after the commit."""
    claim = check_record(doc["claim"])
    a = doc["plan_args"]
    p = W.plan(claim, units=a["units"], price=a["price"], stages=[tuple(s) for s in a["stages"]], stage_work_s=a["stage_work_s"],
               demand_hash=a.get("demand"), maker_github_id=a.get("maker_github_id"))
    if p["commitment_hash"] != doc["commitment_hash"]:
        raise IdeaError("the commitment file does not match what was committed (its plan changed)")
    return p


def load(path: str | Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("kind") != KIND or doc.get("v") != V:
        raise IdeaError("not a Knos idea commitment file (knos idea commit writes one)")
    plan_of(doc)
    return doc


def is_commitment(path: str | Path) -> bool:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")).get("kind") == KIND
    except (OSError, ValueError, AttributeError):
        return False


def commit(claim: dict, *, units: int, price: int, payee: dict, funder, funder_token: Pubkey, mint: Pubkey, led,
           stages: list | None = None, stage_work_s: list[int] | None = None, panel: tuple[int, list[str]] | None = None,
           program: Pubkey = pay.PAY_ID, demand_hash: str | None = None, allow_retracted: bool = False,
           unlisted_panel: bool = False, criteria: dict | None = None) -> dict:
    """Lock every stage of a pull commitment and return the commitment document (the caller writes it). With
    `criteria` (a brief: knos.ready), nothing locks unless the brief is Ready to fund."""
    if criteria is not None:
        from knos import ready
        try:
            ready.require(criteria)
        except ready.NotReady as why:
            raise IdeaError(str(why)) from None
    check_record(claim)
    if W.retraction_warning(claim) and not allow_retracted:
        raise IdeaError(W.retraction_warning(claim) or "retracted")
    if panel is None and payee["kind"] != "github":
        raise IdeaError("a stage judged by the GitHub workflow pays a GitHub id: --payee github:<id>, or judge the stages by --panel")
    label = ""
    if panel is not None:
        if not payee.get("wallet"):
            raise IdeaError("a panel release pays an address: --payee <github:id|orcid:iD>@<wallet>, or a wallet")
        m_, keys_, label = parse_panel(f"{panel[0]}:{','.join(panel[1])}", funder.pubkey(), payee["wallet"], unlisted_panel)
        panel = (m_, keys_)
    p = W.plan(claim, units=units, price=price, stages=stages, stage_work_s=stage_work_s, demand_hash=demand_hash,
               maker_github_id=payee["id"] if payee["kind"] == "github" else None)
    if panel is not None and led.account(pay.ata(pay.FEE_OWNER, mint)) is None:
        led.send([pay.create_ata_ix(funder.pubkey(), pay.FEE_OWNER, mint)], funder)
    orders = {}
    for part in p["stages"]:
        if panel is not None:
            m, keys = _panel_bytes(panel)
            order = W.panel_address(p, part, funder.pubkey(), program=program)
            ix = W.fund_panel_ix(p, part, funder.pubkey(), funder_token, mint, m, keys, program=program, unlisted_panel=bool(unlisted_panel))
        else:
            order = W.address(p, part, funder.pubkey())
            ix = W.fund_ix(p, part, funder.pubkey(), funder_token, mint)
        sig = None if led.account(order) is not None else led.send([ix], funder)
        orders[part] = {"order": str(order), "oracle": p[part]["oracle"], "amount": p[part]["amount"], "work_s": p[part]["work_s"],
                        "signature": sig, "note": None if sig else "already funded"}
    return {"v": V, "kind": KIND, "claim": claim, "commitment_hash": p["commitment_hash"],
            "plan_args": {"units": units, "price": price, "stages": [[p[s]["oracle"], p["commitment"]["stages"][i]["bps"]] for i, s in enumerate(p["stages"])],
                          "stage_work_s": [p[s]["work_s"] for s in p["stages"]], "demand": demand_hash,
                          "maker_github_id": payee["id"] if payee["kind"] == "github" else None},
            "judge": "panel" if panel is not None else "github",
            "panel": {"m": panel[0], "keys": panel[1], "unlisted": bool(unlisted_panel), "label": label} if panel else None,
            "payee": payee, "program": str(program if panel is not None else pay.PAY_ID), "mint": str(mint), "funder": str(funder.pubkey()),
            "orders": orders, "warnings": p["warnings"], "made": now(), "cluster": "devnet"}


# ---- verdicts --------------------------------------------------------------------------------------------------------
def review_evidence(doc_or_claim: dict, oracle: str, passed: bool, review: Path) -> dict:
    """The evidence of a referee_pass / lab_qc verdict: the referee's (or the lab's) report file, by its sha256, and
    the result the referee signs. The same report gives the same evidence hash to every referee."""
    claim = doc_or_claim.get("claim", doc_or_claim)
    ev = {"oracle": oracle, "claim": claim["id"], "claim_hash": claim["hash"], "met": bool(passed),
          "why": f"{'referee review' if oracle == 'referee_pass' else 'lab protocol + QC report'} {'passed' if passed else 'did not pass'}",
          "report_sha256": hashlib.sha256(review.read_bytes()).hexdigest(), "source": "knos referee panel"}
    ev["evidence_hash"] = W._h({k: v for k, v in ev.items() if k not in ("read", "mode")})
    ev["read"] = now()
    return ev


def _order(doc: dict, stage: str, led):
    if stage not in doc["orders"]:
        raise IdeaError(f"stage: one of {', '.join(doc['orders'])}")
    order = Pubkey.from_string(doc["orders"][stage]["order"])
    o = pay.read_order(led.account(order))
    return order, o


def sign(doc: dict, stage: str, referee, led, *, f=None, passed: bool | None = None, review: Path | None = None) -> dict:
    """One referee's signed verdict on one stage (run where the referee's key is). Automatic oracles are read live;
    referee_pass / lab_qc need the referee's own result (--pass/--fail) and report file. Pending: nothing to sign."""
    if doc["judge"] != "panel":
        raise IdeaError("this commitment's stages are judged by the GitHub workflow, not a referee panel")
    key = str(referee.pubkey())
    if key not in doc["panel"]["keys"]:
        raise IdeaError("this key is not one of the commitment's referees")
    p = plan_of(doc)
    order, o = _order(doc, stage, led)
    if o is None:
        raise IdeaError(f"{stage}: the order is closed (already released or refunded)")
    oracle = p[stage]["oracle"]
    if oracle in ("referee_pass", "lab_qc"):
        if passed is None or review is None:
            raise IdeaError(f"{oracle}: give your result (--pass or --fail) and the report you judged (--review FILE)")
        ev = review_evidence(doc, oracle, passed, review)
    else:
        ev = W.check(doc["claim"], oracle, f)
    program = Pubkey.from_string(doc["program"])
    payees = payees_of(doc["payee"])
    verdict = W.verdict_of(ev)
    if verdict is None:
        raise IdeaError(f"{oracle}: {ev.get('why')}: no verdict can be signed yet")
    k, s = W.sign_stage(referee, order, o, ev, payees, program)
    digest = W.stage_digest(order, o, ev, payees, program)
    return {"v": V, "kind": "knos-idea-verdict", "claim": doc["claim"]["id"], "commitment_hash": doc["commitment_hash"], "stage": stage,
            "oracle": oracle, "order": str(order), "stamp": o.stamp, "verdict": verdict, "evidence_hash": ev["evidence_hash"],
            "evidence": {kk: v for kk, v in ev.items() if kk not in ("mode",)}, "payees": payees_text(doc["payee"]) if verdict == "PASS" else "FAIL",
            "key": key, "digest": digest.hex(), "sig": s.hex(), "signed": now()}


def _verify(rec: dict) -> bool:
    try:
        return Signature.from_bytes(bytes.fromhex(rec["sig"])).verify(Pubkey.from_string(rec["key"]), bytes.fromhex(rec["digest"]))
    except (KeyError, ValueError):
        return False


def count_signatures(recs: list, claim: dict, oracle: str, panel: tuple[int, list[str]]) -> dict:
    """The distinct committed referees whose signed verdicts agree (same verdict, same evidence), refused below M."""
    m, keys = panel
    good = [r for r in recs if isinstance(r, dict) and r.get("claim") == claim["id"] and r.get("oracle") == oracle
            and r.get("key") in keys and _verify(r)]
    if not good:
        raise IdeaError("no signature of the committed panel over this claim's stage")
    first = good[0]
    same = {r["key"] for r in good if r["verdict"] == first["verdict"] and r["evidence_hash"] == first["evidence_hash"]}
    if len(same) < m:
        raise IdeaError(f"{len(same)} of the panel's referees agree; the panel needs {m}")
    return {"verdict": first["verdict"], "evidence_hash": first["evidence_hash"], "keys": sorted(same)}


def _verdict_ixs(doc: dict, stage: str, recs: list, want: str, relayer, led) -> list[dict]:
    from ..proof import issuers
    p = plan_of(doc)
    order, o = _order(doc, stage, led)
    if o is None:
        raise IdeaError(f"{stage}: the order is closed (already released or refunded)")
    program = Pubkey.from_string(doc["program"])
    m, keys = _panel_bytes((doc["panel"]["m"], doc["panel"]["keys"]))
    committed = payees_text(doc["payee"])
    use, seen = [], set()
    for r in recs:
        if r.get("order") != str(order) or r.get("stage") != stage or r.get("commitment_hash") != doc["commitment_hash"]:
            raise IdeaError(f"a verdict for another order or commitment ({r.get('key')})")
        if r.get("stamp") != o.stamp:
            raise IdeaError(f"a verdict signed for an earlier funding of this order ({r.get('key')})")
        if r.get("verdict") != want:
            raise IdeaError(f"a {r.get('verdict')} verdict cannot {'release' if want == 'PASS' else 'refund'} a stage ({r.get('key')})")
        if want == "PASS" and r.get("payees") != committed:
            raise IdeaError(f"the verdict names other payees than the committed one ({r.get('payees')} != {committed})")
        if r.get("key") not in doc["panel"]["keys"]:
            raise IdeaError(f"{r.get('key')} is not one of the commitment's referees")
        ev = {"met": want == "PASS", "evidence_hash": r["evidence_hash"], "oracle": p[stage]["oracle"]}
        digest = W.stage_digest(order, o, ev, payees_of(doc["payee"]), program)
        if digest.hex() != r.get("digest") or not _verify(r):
            raise IdeaError(f"the signature of {r.get('key')} does not verify over this stage's verdict")
        if r["key"] not in seen:
            seen.add(r["key"])
            use.append((r, ev))
    if len({r["evidence_hash"] for r, _ in use}) > 1:
        raise IdeaError("the referees signed different evidence: they must agree on one reading")
    if len(use) < doc["panel"]["m"]:
        raise IdeaError(f"{len(use)} distinct referee verdicts; the panel needs {doc['panel']['m']}")
    vote = issuers.read_vote(led.account(issuers.vote_pda(order, bytes.fromhex(use[0][0]["digest"]), program)))
    done = vote["bits"] if vote else 0
    out = []
    for r, ev in use:
        idx = doc["panel"]["keys"].index(r["key"])
        if done >> idx & 1:
            continue                     # this referee's verdict is already recorded on chain
        ixs = W.stage_verdict_ixs(relayer.pubkey(), order, o, m, keys, ev, payees_of(doc["payee"]),
                                  [(bytes(Pubkey.from_string(r["key"])), bytes.fromhex(r["sig"]))], program,
                                  unlisted_panel=bool(doc["panel"].get("unlisted")))
        out.append({"key": r["key"], "ixs": ixs})
    return out


def _settle(doc: dict, stage: str, recs: list, want: str, relayer, led) -> dict:
    mint = Pubkey.from_string(doc["mint"])
    pre = [pay.create_ata_ix(relayer.pubkey(), w, mint) for w in (relayer.pubkey(), pay.FEE_OWNER) if led.account(pay.ata(w, mint)) is None]
    if pre:
        led.send(pre, relayer)
    sent = []
    for row in _verdict_ixs(doc, stage, recs, want, relayer, led):
        if led.account(Pubkey.from_string(doc["orders"][stage]["order"])) is None:
            break
        sent.append({"referee": row["key"], "signature": led.send(row["ixs"], relayer)})
    return outcome(doc, stage, led, sent, want)


def outcome(doc: dict, stage: str, led, sent: list | None = None, want: str | None = None) -> dict:
    """What happened to a stage, read from the chain: closed after PASS verdicts = released; closed after FAIL
    verdicts or a deadline refund = refunded; still open = locked (a verdict below M is recorded, nothing moved)."""
    order = Pubkey.from_string(doc["orders"][stage]["order"])
    closed = led.account(order) is None
    if not sent:
        status = "closed" if closed else "locked"
    elif closed:
        status = "released" if want == "PASS" else "refunded"
    else:
        status = "locked: verdict recorded, waiting for more referees"
    return {"stage": stage, "oracle": doc["orders"][stage]["oracle"], "status": status, "sent": sent or []}


def release(doc: dict, stage: str, recs: list, relayer, led) -> dict:
    """m committed referees' PASS verdicts on a stage: sent one per transaction; the program pays the committed payee."""
    if doc["judge"] != "panel":
        a = W.release_audience(plan_of(doc), stage, Pubkey.from_string(doc["orders"][stage]["order"]), "0" * 64)
        raise IdeaError("a GitHub-judged stage is released only by a GitHub-signed run of the judge workflow, audience: " + a["audience"])
    return _settle(doc, stage, recs, "PASS", relayer, led)


def refund(doc: dict, stage: str, recs: list, relayer, led) -> dict:
    """m FAIL verdicts refund a panel stage now; with no verdicts, RefundOrder once the stage is past its deadline."""
    if recs:
        if doc["judge"] != "panel":
            raise IdeaError("verdicts refund only a panel-judged stage; a GitHub-judged stage is refunded after its deadline")
        return _settle(doc, stage, recs, "FAIL", relayer, led)
    order, o = _order(doc, stage, led)
    if o is None:
        raise IdeaError(f"{stage}: the order is closed (already released or refunded)")
    if led.now() <= o.pay_until:
        raise IdeaError(f"{stage}: before its deadline only m FAIL verdicts of the panel refund it")
    sig = led.send([pay.refund_order_ix(relayer.pubkey(), order, o, program=Pubkey.from_string(doc["program"]))], relayer)
    return outcome(doc, stage, led, [{"referee": None, "signature": sig}], "FAIL")


def state(doc: dict, led) -> dict:
    """Every committed stage as the chain has it: locked amount, or closed; read from the commitment, no flags."""
    rows = {}
    for stage, row in doc["orders"].items():
        data = led.account(Pubkey.from_string(row["order"]))
        o = pay.read_order(data) if data is not None else None
        rows[stage] = {"oracle": row["oracle"], "order": row["order"], "locked": o.amount if o is not None and o.state == "open" else 0,
                       "state": o.state if o is not None else "closed (released or refunded)"}
    return {"claim": doc["claim"]["id"], "judge": doc["judge"], "payee": doc["payee"], "program": doc["program"], "mint": doc["mint"],
            "stages": rows, "locked_total": sum(r["locked"] for r in rows.values())}
