"""The round `meter-single`: one attested evaluation counted once by knos_meter, with no escrow, and a retry of the same
token free. The token is the one attest.yml posts for an evaluation (audience `knosm:eval:...`), in a repository of the
buyer whose credits are open.

    python scripts/exercise_public.py run --only meter-single --simulate
    python scripts/exercise_public.py run --only meter-single --rpc URL --keys DIR [--resume]

On the simulator the token is signed by the test key and the buyer's credits are the simulator's. `xp` is
scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

from typing import Any

ROUND = {"name": "meter-single", "needs": ("knos_oidc", "knos_meter"), "caps": ("meter_single",), "phase": "any"}
HOW = ("in the buyer's repository, with credits open (`knos meter open`): start the pinned attest.yml for one evaluation (`-f kind=eval`); it "
       "posts the token. Then run this again")


def _xp() -> Any:
    return globals()["xp"]


def run(book, st: dict) -> None:
    """One attested evaluation is counted once on chain, with no escrow; the same token again costs nothing."""
    x, w = _xp(), book.w
    if "retry" in st:
        return
    forge = None
    if w.mode != "public":
        sim = w
        aud = x.meter.eval_audience(sim.m.BUYER, sim.m.SELLER, bytes([0x5E]) * 32, "e" * 40, bytes([0x5F]) * 32, 1, True, 2 * x.USDC)
        forge = lambda: sim.forge(aud, "attest.yml", repository_owner_id=sim.m.BUYER, run_attempt=1)  # noqa: E731
    tok = book.token(st, "eval", "eval", lambda t: t.aud.startswith("knosm:eval:"), forge, ("attest.yml", HOW))
    e = x.meter.parse_audience(tok.aud)
    mark = x.meter.mark_pda(e.buyer_id, e.key)
    if "counted" not in st:
        r = w.submit(tok)
        x._check(bool(r.get("ok")), f"the evaluation: the relay answered: {r.get('why')}")
        m = x.meter.read_mark(w.account(mark))
        x._check(m is not None, f"the evaluation's mark {mark} is not on chain: it was not counted")
        first = list(w.ledger.history(mark))
        x._check(bool(first), f"no transaction wrote the mark {mark}")
        sig = first[-1]         # the oldest: the transaction that counted it
        st["counted"] = {"signature": sig, "mark": str(mark), "buyer": e.buyer_id, "seller": e.seller_id, "accepted": bool(m.accepted),
                         "fee": int(m.fee), "already": bool(r.get("already"))}
        book.tx(st, f"one evaluation of seller {e.seller_id} for buyer {e.buyer_id} is counted", sig, "knos_meter")
    again = w.submit(tok)
    x._check(bool(again.get("ok")) and bool(again.get("already")), f"the same token again was not answered as counted already: {again}")
    x._check(not again.get("fee") or int(again.get("fee", 0)) == st["counted"]["fee"], "the retry was charged again")
    st["retry"] = {"already": True}
    book.done(st, "meter_single", "knos_meter", st["counted"]["signature"],
              [f"the evaluation's mark {st['counted']['mark']} holds its verdict ({'accepted' if st['counted']['accepted'] else 'rejected'}) and its fee",
               "the same token again was answered `already`: counted once, and the retry sent nothing"])


simulate = run
