"""The round `tip`: a job funded by one comment from the repository owner's Balance, and paid to the pull request's
author on GitHub's signature of the merge. With knos_pay 2.2 live, `/knos fund` makes a work order; `/knos tip` on a
merged pull request still makes a job (knos2:fund) and pays it (knos2:pay), so a tip is the path that exercises the two
job capabilities at the public ids, with the maintainer's own repository, Balance and bound wallet.

    python scripts/exercise_public.py run --only tip --rpc URL --keys DIR [--resume]

The tokens are those knos.yml posted in the round's repository (<keys>/exercise.json "repository"). The repository's
own run carries them to the chain first, so the round finds the transaction that took each token and reads what
knos_pay logged in it: never assumed. Nothing to simulate: the simulator's chain holds work orders only.
`xp` is scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

from typing import Any

ROUND = {"name": "tip", "needs": ("knos_oidc", "knos_pay"), "caps": ("fund_by_comment", "pay_on_merge"), "phase": "any"}
FUNDED, PAID, HELD = "knos2:funded ", "knos2:paid ", "knos2:held "


def _xp() -> Any:
    return globals()["xp"]


def _line(w, sig: str, prefix: str) -> dict[str, str] | None:
    """What knos_pay itself logged in one transaction on a line starting with `prefix`, as key=value; None when nothing."""
    x = _xp()
    said = [s for s in x.chain.said(w.ledger.logs(sig), x.pay.PAY_ID) if s.startswith(prefix)]
    return dict(kv.split("=", 1) for kv in said[0].split()[1:] if "=" in kv) if said else None


def _carried(w, tok, prefix: str) -> tuple[str, dict[str, str]] | None:
    """The transaction that took this token, and knos_pay's line in it: sent now, or found where the repository's own
    run sent it first."""
    r = w.submit(tok)
    if r.get("ok") and r.get("sigs"):
        for sig in reversed(r["sigs"]):
            got = _line(w, sig, prefix)
            if got is not None:
                return sig, got
    took = w.consumed(tok, prefix)
    return (took[0], _line(w, took[0], prefix) or {}) if took else None


def run(book, st: dict) -> None:
    """A tip: one comment funds a job from the owner's Balance, and GitHub's signature of the merge pays the author."""
    x, w = _xp(), book.w
    if "paid" in st:
        return
    how = (f"in {w.repository}: merge a pull request whose author is the maintainer (a wallet is bound to that account), then comment `/knos tip 1` on "
           "it. knos.yml funds a job on the pull request's own number from the owner's Balance and its settle job pays it. Then run this again")
    fund = book.token(st, "fund", "fund", lambda t: t.aud.startswith("knos2:fund:"), None, ("knos.yml (/knos tip)", how))
    p = fund.aud.split(":")
    repo, issue, amount, balance = int(fund.c["repository_id"]), int(p[2]), int(p[3]), p[7]
    if "funded" not in st:
        got = _carried(w, fund, FUNDED)
        if got is None:
            raise x.Failed("the fund token was taken by no transaction of knos_pay: the relay did not carry it and nothing else did")
        sig, said = got
        x._check(said.get("repo") == str(repo) and said.get("issue") == str(issue) and said.get("amount") == str(amount),
                 f"the funding {sig} is not the job the token names: {said}")
        x._check(said.get("source") == balance, f"the funding {sig} spent {said.get('source')}, not the Balance the token names ({balance})")
        st["funded"] = {"signature": sig, "repo": repo, "issue": issue, "amount": amount, "balance": balance}
        book.tx(st, f"one comment funds a job of {x.money(amount)} from the owner's Balance", sig, "knos_pay")
    pay_tok = book.token(st, "pay", "pay", lambda t: t.aud.startswith(f"knos2:pay:{repo}:{issue}:"), None, ("knos.yml (settle)", how))
    payee = pay_tok.aud.split(":")[4]
    got = _carried(w, pay_tok, PAID)
    if got is None and w.consumed(pay_tok, HELD):
        raise x.Cannot(f"the job was held for payee {payee}: that account has no wallet bound, so this round paid nobody. Tip a pull request whose "
                       "author has bound a wallet (the maintainer's own)")
    if got is None:
        raise x.Failed("the pay token was taken by no transaction of knos_pay")
    sig, said = got
    x._check(said.get("repo") == str(repo) and said.get("issue") == str(issue) and said.get("payee") == payee,
             f"the payment {sig} is not the job and payee the token names: {said}")
    st["paid"] = {"signature": sig, "payee": int(payee), "amount": int(said.get("amount", 0)), "fee": int(said.get("fee", 0)), "to": said.get("to")}
    book.tx(st, "GitHub's signature of the merge pays the author", sig, "knos_pay")
    book.done(st, "fund_by_comment", "knos_pay", st["funded"]["signature"],
              [f"a `/knos tip` comment in repository {repo} funded job #{issue} with {x.money(amount)} from the Balance {balance}, as the token named"])
    book.done(st, "pay_on_merge", "knos_pay", sig,
              [f"the merge GitHub signed paid {x.money(st['paid']['amount'])} to the author ({payee}) at {said.get('to')}, fee {x.money(st['paid']['fee'])}"])
