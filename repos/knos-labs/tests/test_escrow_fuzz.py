"""Model-based fuzz of the Solana escrow program in the Solana runtime (LiteSVM + real SPL Token). Nightly (`-m slow`).

KNOS_FUZZ_N random steps (default 10,000; KNOS_FUZZ_SEED picks the run) by five funded actors on a pool of job ids:
post (with or without a verifier, sometimes under the minimum or over the cap, sometimes on a settled and closed id),
claim (with the worker's stake; sometimes by the buyer or the verifier), deliver (sometimes after the claim timed out),
accept, release, reject (sometimes on a verified job), refund, verify_release (right and wrong result hash),
verify_reject, the deadline crank (settle), pause/unpause, lower the cap, and clock jumps. A plain Python model of the
0.3.5 escrow predicts, before every step, whether the program must accept or refuse it and what every token account
must hold afterwards. Checked after every step:

    the program agrees with the model (no action succeeds that should fail, and none fails that should succeed)
    conservation: every token account matches the model, and their sum never changes
    no double payout: the vault holds exactly the price and the claim stake of every job still open, claimed or
                      delivered, and the fee account exactly the fee of every released job
    settled jobs are closed: no account remains for a released or refunded job
Every 1,000 steps the episode ends: every job is driven to a terminal state by the deadline crank (which must
succeed) and the vault must be empty: no stuck funds.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import time

import pytest

pytest.importorskip("solders.litesvm")

from _jobharness import Escrow  # noqa: E402

from knos.jobs import sol  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

pytestmark = pytest.mark.slow
U = 1_000_000
EPISODE = 1_000
# Read at import: the suite's autouse fixture strips KNOS_* settings from each test's environment.
N = int(os.environ.get("KNOS_FUZZ_N", "10000"))
SEED = int(os.environ.get("KNOS_FUZZ_SEED", "3405"))
LIVE = ("open", "claimed", "delivered")
GH_KID, GH_REPO, GH_REF = "fuzz-kid", "octo/widgets", "refs/heads/main"
GH_KEY: list = []


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


GH_WF_SHA = "ab" * 20


def gh_prove(e, who, jid: bytes, worker_tok, good: bool) -> bool:
    """Write a GitHub-style OIDC token for `jid` (signed by the fuzz key; `good` False: audience of another job) and run
    BufferWrite, VerifyStep1, VerifyStep2. True if all of them succeeded."""
    payout = sol.Pubkey.from_bytes(bytes(e.svm.get_account(worker_tok).data)[32:64])
    claims = {"aud": sol.gh_audience(jid if good else bytes(32), "cd" * 20, bytes(32), payout), "sha": "cd" * 20, "ref": GH_REF, "repository": GH_REPO,
              "job_workflow_sha": GH_WF_SHA, "iss": sol.GH_ISSUER, "exp": 4_000_000_000}
    head = _b64(json.dumps({"alg": "RS256", "kid": GH_KID}).encode())
    body = _b64(json.dumps(claims).encode())
    sig = GH_KEY[0].sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    t = f"{head}.{body}.{_b64(sig)}".encode()
    p, k = e.pid, sol.gh_key_pda(e.pid, GH_KID)
    j = e.job(jid)
    buyer = j.buyer if j else who.pubkey()
    for off in range(0, len(t), 800):
        if not e.send([sol.buffer_write(p, who.pubkey(), jid, len(t), off, t[off:off + 800])], who, [who]):
            return False
    return (e.send([sol.compute_limit(), sol.verify_step1(p, who.pubkey(), jid, k)], who, [who]) and
            e.send([sol.compute_limit(), sol.verify_step2(p, who.pubkey(), jid, k, e.vault, worker_tok, e.fee_token,
                                                          buyer, GH_WF_SHA)], who, [who]))


class Model:
    def __init__(self, e: Escrow, actors):
        self.e, self.actors = e, actors
        self.bal = {t: e.balance(t) for t in [t for _, t in actors] + [e.fee_token, e.vault]}
        self.jobs: dict[bytes, dict] = {}
        self.paused, self.cap = False, 0
        self.released_fees = 0
        self.tried = self.ok = 0
        self.settled = {"released": 0, "refunded": 0, "proven": 0, "verify_rejected": 0, "cranked": 0,
                        "proven_github": 0}

    def now(self) -> int:
        return int(self.e.svm.get_clock().unix_timestamp)

    def held(self) -> int:
        return sum(j["amount"] + j["stake"] for j in self.jobs.values() if j["state"] in LIVE)

    def pay(self, j: dict, payee_tok) -> None:
        c = self.e.config(); fee = sol.fee_for(j["amount"], c["fee_bps"], c["min_fee"], c["min_amount"])
        self.bal[self.e.vault] -= j["amount"]
        self.bal[payee_tok] += j["amount"] - fee
        self.bal[self.e.fee_token] += fee
        self.released_fees += fee
        j["state"] = "released"
        self.settled["released"] += 1

    def refund(self, j: dict, buyer_tok) -> None:
        self.bal[self.e.vault] -= j["amount"] + j["stake"]
        self.bal[buyer_tok] += j["amount"] + j["stake"]
        j["state"], j["stake"] = "refunded", 0
        self.settled["refunded"] += 1


def _step(rng: random.Random, m: Model, ids: list[bytes]) -> None:
    e, actors = m.e, m.actors
    a = rng.randrange(100)
    live = [i for i in ids if i in m.jobs and m.jobs[i]["state"] in LIVE]
    fresh = [i for i in ids if i not in m.jobs]
    if a < 18 and fresh and rng.random() < 0.8:
        jid = rng.choice(fresh)                                   # mostly, new posts on new ids
    elif a >= 18 and live and rng.random() < 0.8:
        jid = rng.choice(live)                                    # mostly, act on jobs under way
    else:
        jid = rng.choice(ids)
    j = m.jobs.get(jid)
    now = m.now()
    tok_of = {bytes(k.pubkey()): t for k, t in actors}
    who, tok = rng.choice(actors)
    if j is not None and rng.random() < 0.6:   # most of the time, the party the job is waiting for acts
        want = {"deliver": j["worker"], "accept": j["buyer"], "reject": j["buyer"], "refund": j["buyer"],
                "verify": j["verifier"]}.get("deliver" if 30 <= a < 42 else "accept" if 42 <= a < 52 else
                                             "verify" if 60 <= a < 72 or 90 <= a < 93 else
                                             "reject" if 72 <= a < 80 else "refund" if 80 <= a < 88 else "")
        if want is not None:
            who, tok = next((k, t) for k, t in actors if k.pubkey() == want)
    if a < 18:                                                   # post (a settled id is free again: closed)
        amount = rng.choice([U - 1, U, 2 * U, 3 * U, 7 * U])
        work, review = rng.choice([30, 120, 600]), rng.choice([30, 120, 600])
        gh = rng.random() < 0.3                              # 0.3.7: a github job (paid on proof), 0 = a bounty
        if gh:
            amount, ver = rng.choice([0, 0, U - 1, U, 3 * U]), None
        else:
            ver = rng.choice(actors)[0] if rng.random() < 0.5 else None
        ok = ((j is None or j["state"] not in LIVE) and not m.paused
              and (amount >= sol.MIN_JOB_UNITS or (gh and amount == 0))
              and (m.cap == 0 or amount <= m.cap))
        if gh:
            got = e.send([sol.post_github(e.pid, who.pubkey(), jid, amount, work, review, bytes(32), GH_REPO, GH_REF,
                                          tok, e.vault, stake_required=True)], who, [who])
        else:
            got = e.post(who, tok, jid, amount, work=work, review=review, verifier=ver.pubkey() if ver else None)
        if ok:
            m.jobs[jid] = {"state": "open", "buyer": who.pubkey(), "worker": None, "amount": amount,
                           "deadline": now + work, "review": review, "result": None,
                           "verifier": ver.pubkey() if ver else None, "stake": 0, "github": gh}
            m.bal[tok] -= amount
            m.bal[e.vault] += amount
    elif a < 30:                                                 # claim, staking from the worker's own account
        if j is not None and j["state"] == "open" and rng.random() < 0.15:
            who, tok = next((k, t) for k, t in actors if k.pubkey() == j["buyer"])     # the buyer tries
        ok = (j is not None and j["state"] == "open" and now <= j["deadline"] and who.pubkey() != j["buyer"]
              and who.pubkey() != j["verifier"])
        got = e.claim(who, jid, tok)
        if ok:
            j["state"], j["worker"], j["stake"] = "claimed", who.pubkey(), sol.stake_for(j["amount"])
            m.bal[tok] -= j["stake"]
            m.bal[e.vault] += j["stake"]
    elif a < 42 and j is not None and j.get("github") and rng.random() < 0.6:   # 0.3.7: prove a github job
        good = rng.random() < 0.8
        payee = tok_of[bytes(j["worker"])] if j["worker"] and rng.random() < 0.9 else tok
        ok = (j["state"] == "claimed" and now <= j["deadline"] and good and payee == tok_of[bytes(j["worker"])])
        got = gh_prove(e, who, jid, payee, good)
        if ok:
            c = e.config(); fee = sol.fee_for(j["amount"], c["fee_bps"], c["min_fee"], c["min_amount"])
            m.bal[e.vault] -= j["amount"] + j["stake"]
            m.bal[payee] += j["amount"] - fee + j["stake"]
            m.bal[e.fee_token] += fee
            m.released_fees += fee
            j["state"], j["stake"] = "released", 0
            m.settled["released"] += 1
            m.settled["proven_github"] += 1
    elif a < 42:                                                 # deliver (the stake comes back)
        ok = (j is not None and j["state"] == "claimed" and j["worker"] == who.pubkey() and now <= j["deadline"]
              and not j.get("github"))
        got = e.deliver(who, jid, worker_token=tok)
        if ok:
            j["state"], j["result"], j["deadline"] = "delivered", e.result_hash(jid), now + j["review"]
            m.bal[tok] += j["stake"]
            m.bal[e.vault] -= j["stake"]
            j["stake"] = 0
    elif a < 52:                                                 # accept (sometimes paying the wrong account)
        payee = tok_of[bytes(j["worker"])] if j and j["worker"] and rng.random() < 0.8 else tok
        ok = (j is not None and j["state"] == "delivered" and j["buyer"] == who.pubkey()
              and payee == tok_of[bytes(j["worker"])])
        got = e.accept(who, jid, payee)
        if ok:
            m.pay(j, payee)
    elif a < 60:                                                 # release by anyone after the review window
        payee = tok_of[bytes(j["worker"])] if j and j["worker"] else tok
        ok = j is not None and j["state"] == "delivered" and now > j["deadline"]
        got = e.accept(who, jid, payee, release=True)
        if ok:
            m.pay(j, payee)
    elif a < 72:                                                 # verify_release, right or wrong hash
        payee = tok_of[bytes(j["worker"])] if j and j["worker"] else tok
        signer = next((k for k, _ in actors if j and j["verifier"] == k.pubkey()), who) if rng.random() < 0.7 else who
        right = rng.random() < 0.75
        h = e.result_hash(jid) if right else hashlib.sha256(b"unproven" + jid).digest()
        ok = (j is not None and j["verifier"] is not None and j["verifier"] == signer.pubkey()
              and j["worker"] != signer.pubkey() and j["state"] == "delivered" and right)
        got = e.verify_release(signer, jid, payee, result_hash=h, proof_root=hashlib.sha256(h).digest())
        if ok:
            m.pay(j, payee)
            m.settled["proven"] += 1
    elif a < 80:                                                 # reject inside the review window, no verifier
        ok = (j is not None and j["state"] == "delivered" and j["buyer"] == who.pubkey() and now <= j["deadline"]
              and j["verifier"] is None)
        got = e.reject(who, jid, tok)
        if ok:
            m.refund(j, tok)
    elif a < 88:                                                 # refund after the work deadline
        ok = (j is not None and j["state"] in ("open", "claimed") and j["buyer"] == who.pubkey()
              and now > j["deadline"])
        got = e.refund(who, jid, tok)
        if ok:
            m.refund(j, tok)
    elif a < 89:                                                 # the admin pauses or unpauses (or a stranger tries)
        admin = rng.random() < 0.7
        on = not m.paused and rng.random() < 0.2
        got = e.set_pause(on, admin=None if admin else who)
        ok = admin
        if ok:
            m.paused = on
    elif a < 90:                                                 # lower the cap (only downward, never under 1 USDC)
        if rng.random() >= 0.1:
            return
        cap = rng.choice([U - 1, 3 * U, 5 * U, 10 * U, 20 * U])
        ok = cap >= sol.MIN_JOB_UNITS and (m.cap == 0 or cap <= m.cap)
        got = e.lower_cap(cap)
        if ok:
            m.cap = cap
    elif a < 93:                                                 # verify_reject inside the review window
        buyer_tok = tok_of[bytes(j["buyer"])] if j and rng.random() < 0.85 else tok
        ok = (j is not None and j["verifier"] is not None and j["verifier"] == who.pubkey()
              and j["state"] == "delivered" and now <= j["deadline"] and buyer_tok == tok_of[bytes(j["buyer"])])
        got = e.verify_reject(who, jid, buyer_tok, proof_root=hashlib.sha256(b"fail" + jid).digest())
        if ok:
            m.refund(j, buyer_tok)
            m.settled["verify_rejected"] += 1
    elif a < 96:                                                 # the deadline crank, by anyone
        ok = j is not None and j["state"] in LIVE and now > j["deadline"]
        got = e.settle(who, jid)
        if ok:
            m.settled["cranked"] += 1
            if j["state"] == "delivered":
                m.pay(j, tok_of[bytes(j["worker"])])
            else:
                m.refund(j, tok_of[bytes(j["buyer"])])
    else:                                                        # time passes
        e.warp(rng.choice([1, 5, 20, 90]))
        return
    m.tried += 1
    m.ok += ok
    assert got == ok, f"program {'accepted' if got else 'refused'} what the model {'allows' if ok else 'refuses'}"
    if ok and jid in m.jobs:
        chain, want = e.job(jid), m.jobs[jid]
        if want["state"] in LIVE:
            assert chain.state == want["state"] and chain.amount == want["amount"] and chain.stake == want["stake"]
        else:
            assert chain is None, "a settled job's account was not closed"


def _check(m: Model, total: int) -> None:
    e = m.e
    for t, want in m.bal.items():
        assert e.balance(t) == want, "a token account differs from the model"
    assert sum(m.bal.values()) == total, "tokens created or destroyed"
    assert e.balance(e.vault) == m.held(), "the vault does not hold exactly the unsettled jobs"
    assert e.balance(e.fee_token) == m.released_fees, "a fee was paid twice or not at all"


def _drain(m: Model) -> None:
    e = m.e
    e.warp(10_000)
    by_key = {bytes(k.pubkey()): (k, t) for k, t in m.actors}
    cranker = m.actors[0][0]
    for jid, j in m.jobs.items():
        if j["state"] == "delivered":
            assert e.settle(cranker, jid), "a delivered job could not be settled at the deadline"
            m.pay(j, by_key[bytes(j["worker"])][1])
        elif j["state"] in ("open", "claimed"):
            assert e.settle(cranker, jid), "an undelivered job could not be refunded at the deadline"
            m.refund(j, by_key[bytes(j["buyer"])][1])
        assert e.job(jid) is None and j["state"] in ("released", "refunded")
    assert e.balance(e.vault) == 0, "funds stuck in escrow"


def test_escrow_fuzz_model_conservation_no_double_payout_no_stuck_funds():
    n, seed = N, SEED
    rng = random.Random(seed)
    e = Escrow()
    actors = [e.party(10 ** 12) for _ in range(5)]
    GH_KEY.append(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    assert e.send([sol.register_key(e.pid, e.admin.pubkey(), GH_KID, GH_KEY[0].public_key().public_numbers().n)],
                  e.admin, [e.admin])
    assert e.send([sol.set_workflow(e.pid, e.admin.pubkey(), GH_WF_SHA)], e.admin, [e.admin])
    m = Model(e, actors)
    total = sum(m.bal.values())
    t0, steps, episode = time.perf_counter(), 0, 0
    while steps < n:
        ids = [hashlib.sha256(f"fz-{seed}-{episode}-{k}".encode()).digest() for k in range(150)]
        for _ in range(min(EPISODE, n - steps)):
            _step(rng, m, ids)
            _check(m, total)
            steps += 1
        _drain(m)
        _check(m, total)
        episode += 1
    took = time.perf_counter() - t0
    s = m.settled
    print(f"\nescrow fuzz: {steps} steps ({m.tried} transactions: {m.ok} accepted, {m.tried - m.ok} refused, all as "
          f"the model predicted; 0 violations), {episode} episodes, {s['released']} released ({s['proven']} on "
          f"proof), {s['refunded']} refunded ({s['verify_rejected']} by a verifier), {s['cranked']} by the deadline "
          f"crank, {s['proven_github']} on a GitHub Actions proof, seed {seed}, {took:.1f} s")
    assert steps == n and s["released"] and s["refunded"] and (s["proven"] or n < 2000)
