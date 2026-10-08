"""The round `net-reserve` of scripts/exercise_public.py: a buyer's reserve for one supplier, on the programs as they are.

    1. a fund token locks the reserve: a standing order of knos_pay on the terms knos.netting.reserve_fund states
    2. a netted period (knos.netting) is bound to it, takes what fits and refuses the line past the reserve
    3. the period closes and each of its draws is signed and paid: one tranche a token, out of the order
    4. RefundOrder before the order's deadline is refused; after it, what no draw took is back where it came from

exercise_public.py lists it in ROUNDS as
    "net-reserve": (round_net_reserve.round_net_reserve, ("knos_oidc", "knos_pay"), ("netting_reserve",)),
and runs it with `run --only net-reserve` (`--simulate`: the local simulator, where the tokens are signed by the test
key). At the public ids the two kinds of token come from runs of the buyer's repository: the round says which audience
each must sign, and `--resume` goes on from there.
"""
from __future__ import annotations

import hashlib
import json

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from knos import netting
from knos.settle.v2 import pay

CAPABILITY = "netting_reserve"
FUNDED, TRANCHE, LINES, RATE = "10", "2", 32, "0.32"       # 10.00 locked, 2.00 a draw; 32 outcomes of 0.32 are offered and 31 fit


def _sha(*parts: object) -> str:
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()


def _is_reserve(ex, t) -> bool:
    """A fund token of an order that is a reserve: standing, on terms that name a pair."""
    terms = json.loads(t.terms or "{}")
    return bool(ex.fund_parts(t)["flags"] & pay.F_STANDING) and terms.get("mode") == "net-reserve" and set(terms.get("net", {})) == {"buyer", "seller", "unit"}


def period(order: Pubkey, facts: dict, buyer: int, seller: int, month: int) -> tuple[netting.Book, list[dict]]:
    """The round's period, the same from the same reserve: LINES outcomes of RATE offered, closed with what fit.
    Returns the book and what `add` refused."""
    text = netting.open_line(netting.Book(), buyer, seller, month, "500", reserve=facts) + "\n"
    items = [{"order": _sha("net-reserve", order)[:64], "milestone": i, "artifact": _sha("artifact", order, i)[:40], "policy": _sha("policy")[:64],
              "amount": RATE, "evidence": _sha("evidence", order, i)} for i in range(LINES)]
    lines, refused = netting.add(netting.read(text), items)
    text += "".join(line + "\n" for line in lines)
    _n, line = netting.close(netting.read(text), netting.read(text))
    return netting.read(text + line + "\n"), refused


def round_net_reserve(book, st: dict) -> None:
    """A buyer locks a reserve for one supplier before the work; a netted period spends no more than it holds and is
    paid by draws on it; what no draw took goes back to the buyer after the deadline, and not before."""
    import exercise_public as ex
    from knos.settle.v2 import meter
    w = book.w
    sim = w if isinstance(w, ex.Simulated) else None
    how = (f"in {w.repository}: print the audience with `knos net reserve --buyer <owner id> --seller <supplier id> --amount {FUNDED} --tranche {TRANCHE} "
           "--balance <the buyer's Balance> --issue <a new issue> --days 1`, and have the pinned fund.yml sign it with the terms it prints")
    if sim and "issue" not in st:
        st["issue"], st["seller"], st["wallet"] = sim.issue(), sim.o.user(), str(Keypair.from_seed(bytes([47]) * 32).pubkey())
    forge = None
    if sim:
        f = netting.reserve_fund(sim.o.OWNER, st["seller"], FUNDED, TRANCHE, sim.c.bal, st["issue"], 86_400)
        forge = lambda: sim.forge(f["fund_audience"], "fund.yml", f["terms"].encode(), event_name="issue_comment", actor_id=sim.o.MAINT,     # noqa: E731
                                  repository_id=sim.o.REPO, repository_owner_id=sim.o.OWNER)
    t = book.token(st, "fund", "fund", lambda x: _is_reserve(ex, x), forge, ("fund.yml", how))
    pair = json.loads(t.terms or "{}")["net"]
    buyer, seller = int(pair["buyer"]), int(pair["seller"])
    if "fund1" not in st:
        ex._fund(book, st, "fund1", t, "a comment locks a reserve for one supplier: a standing order, its fee on top")
    order = Pubkey.from_string(st["fund1"]["order"])
    if "period" not in st:
        o = ex.have(pay.read_order(w.account(order)), "the reserve order")
        facts = netting.reserve_of(o, order, buyer, seller, w.now(), pair["unit"])
        ex._check(w.tokens(pay.ov_pda(order)) == o.amount + o.fee and facts["funded"] == st["fund1"]["amount"], "the reserve order does not hold what was locked")
        sig, code = w.refused([pay.refund_order_ix(w.relayer.pubkey(), order, o)])
        ex._check(code == 83, f"RefundOrder before the reserve's deadline was not refused with 83 but {code}")
        book.tx(st, "RefundOrder before the reserve's deadline", sig, "knos_pay", 83, "nobody takes a reserve back before its deadline")
        st["period"] = {"facts": {k: facts[k] for k in ("order", "funded", "tranche", "deadline")}, "month": meter.yyyymm(w.now()), "returns_to": facts["returns_to"]}
    b, refused = period(order, st["period"]["facts"], buyer, seller, st["period"]["month"])
    p = b.periods[0]
    s = netting.reserve_state(p)
    ex._check(len(refused) == 1 and refused[0]["why"].startswith("past the reserve") and s["funded"] == s["consumed"] + s["free"] and p.exposure == 0,
              "the period took a line past its reserve, or its reserve does not add up")
    wallet = Pubkey.from_string(st["wallet"]) if st.get("wallet") else None
    draws = netting.draws(p, wallet)
    st["draws"] = [d["pay_audience"] for d in draws]
    how = (f"in {w.repository}: have the pinned prove.yml sign each of the {len(draws)} audiences this round wrote under `draws` in its evidence "
           "(the supplier must have bound a wallet when an audience names none)")
    paid = st.setdefault("paid", [])
    for d in draws[len(paid):]:
        aud = d["pay_audience"]
        signed = (lambda aud=aud: sim.forge(aud, repository_id=sim.o.REPO)) if sim else None       # noqa: E731
        proof = book.token(st, f"draw{d['draw']}", "pay", lambda x, aud=aud: x.aud == aud, signed, ("prove.yml", how))
        _i, _bps, named = pay.payees_of(proof.aud)[0]
        o = ex.have(pay.read_order(w.account(order)), "the reserve order")
        to = ex.have(pay.payee_wallet(w.account(pay.assign_pda(order, seller)), o, pay.read_bind(w.account(pay.bind_pda(seller))), named), "the supplier's wallet")
        dest = pay.ata(to, w.mint)
        had = w.tokens(dest)
        r = w.submit(proof)
        ex._check(bool(r.get("ok")), f"draw {d['draw']}: the relay answered: {r.get('why')}")
        if not r.get("already"):
            ex._check(w.tokens(dest) - had == s["tranche"], f"draw {d['draw']} did not pay the supplier one tranche")
        paid.append({"draw": d["draw"], "signature": r["sigs"][-1]})
        book.tx(st, f"draw {d['draw']} of {len(draws)}: one tranche of {ex.money(s['tranche'])} leaves the reserve for the supplier", r["sigs"][-1], "knos_pay")
    if "drawn" not in st:
        o = ex.have(pay.read_order(w.account(order)), "the reserve order after its draws")
        ex._check(o.amount == s["funded"] - s["drawn"] and w.tokens(pay.ov_pda(order)) == o.amount + o.fee, "the reserve does not hold what was locked less what was drawn")
        st["drawn"] = {"drawn": s["drawn"], "left": o.amount, "undrawn": s["undrawn"], "deadline": o.pay_until}
        book.done(st, CAPABILITY, "knos_pay", paid[-1]["signature"],
                  [f"{ex.money(s['funded'])} was locked for supplier {seller} before the period; RefundOrder before the deadline was refused (83)",
                   f"the period accepted {ex.money(s['consumed'])} and refused the line past the reserve; funded = consumed + free",
                   f"{len(draws)} draws paid {ex.money(s['drawn'])}; the order still holds {ex.money(o.amount)}, of which {ex.money(s['undrawn'])} is accepted and undrawn"])
    if "refund" not in st:
        w.wait_until(st["drawn"]["deadline"], "the reserve's deadline, after which what no draw took goes back to the buyer")
        last = pay.read_order(w.account(order))
        back = Pubkey.from_string(st["period"]["returns_to"])
        if last is None:                   # another relayer's sweep sent it first
            sig = next(iter(w.ledger.history(order, 5)), "")
        else:
            had = w.tokens(back)
            sig = w.send([pay.refund_order_ix(w.relayer.pubkey(), order, last)])
            ex._check(w.account(order) is None and w.tokens(back) - had == last.amount + last.fee, "what the reserve still held did not go back to where it came from")
        st["refund"] = {"signature": sig, "returned_to": str(back)}
        book.tx(st, "past the deadline: RefundOrder returns what no draw took to the buyer", sig, "knos_pay")
