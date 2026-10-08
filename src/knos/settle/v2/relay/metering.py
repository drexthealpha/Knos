"""Plans for knos_meter (one evaluation, a batch and its claim) and for the upgrade gate's record."""
from __future__ import annotations

from .. import gate, live, meter, oidc, pay

from .pins import _CU, _HEX40, _HEX64, _Stop, _no
from .tokens import _address, _ints, _workflow
from .reads import _batch_taken, _data, _last, _read, credits_for
from .plans import _Ask, _Plan


def _plan_eval(a: _Ask) -> _Plan:
    """knosm:eval: knos_meter records one evaluation (Record) against credits the buyer prepaid for the workflows
    that ran. An evaluation is billed once: a token for one the meter already has costs this relay nothing."""
    kind, ledger, me, t, now = "eval", a.ledger, a.me, a.t, a.now
    c = t.c
    try:
        e = meter.parse_audience(t.aud)
        if (len(e.order), len(e.policy)) != (32, 32) or not _HEX40.fullmatch(e.artifact) or not 0 <= e.milestone < 2 ** 32 or e.buyer_id == 0:
            raise ValueError(t.aud)
        owner, = _ints(c, "repository_owner_id")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    wf_repo, wf_file, wf_sha = _workflow(c)
    if wf_file not in meter.WORKFLOWS:
        raise _no(kind, "an evaluation is recorded from attest.yml or prove.yml")
    if str(c.get("run_attempt")) != "1":
        raise _no(kind, "this token is from a re-run, and only a run's first attempt is counted; run the workflow again")
    if owner != e.buyer_id:
        raise _no(kind, "the run was not in a repository of the buyer its audience names")
    mark = meter.mark_pda(e.buyer_id, e.key)
    got = _read(ledger, [mark, meter.plan_pda(e.buyer_id), meter.METER_ID])
    result = dict(kind=kind, buyer_id=e.buyer_id, seller_id=e.seller_id, order=e.order.hex(), artifact=e.artifact, milestone=e.milestone)
    before = meter.read_mark(_data(got, mark))
    if before is not None:      # counted already (by this token or by another run): the first verdict stands, and a retry is free
        raise _Stop({"ok": True, **result, "sigs": _last(ledger, mark), "already": True, "accepted": before.accepted, "rate": before.rate, "fee": before.fee,
                     "month": before.month})
    if _data(got, meter.METER_ID) is None:      # what this needs is knos_meter (and the verifier it reads), never a version of the escrow
        raise _no(kind, f"knos_meter ({meter.METER_ID}) is not deployed on this cluster, so no evaluation can be counted here")
    pinned = [(addr, cr, held) for addr, cr, held in credits_for(ledger, e.buyer_id) if (cr.wf_repo_hash, cr.wf_sha) == (wf_repo, wf_sha)]
    if not pinned:
        raise _no(kind, "the buyer has no credits opened for these workflows at this commit; a wallet opens them (knos_meter OpenCredits), and "
                        "the first 10,000 evaluations of a month then cost nothing")
    plan_ = meter.read_plan(_data(got, meter.plan_pda(e.buyer_id)))
    paying = [(addr, cr, held) for addr, cr, held in pinned if held >= meter.quote(plan_, cr.decimals, now)]
    if not paying:
        raise _no(kind, "the buyer's credits hold less than the fee of this evaluation; a plain transfer to their token account adds to them")
    credits, cr, _held = max(paying, key=lambda x: x[2])
    fee = meter.quote(plan_, cr.decimals, now)
    home = pay.ata(meter.FEE_OWNER, cr.mint, cr.token_program)
    first = [pay.create_ata_ix(me, meter.FEE_OWNER, cr.mint, cr.token_program)] if fee and _data(_read(ledger, [home]), home) is None else []

    def done(sigs: list[str]) -> dict:
        made = meter.read_mark(ledger.account(mark))
        if made is None:
            return {"ok": False, "kind": kind, "why": "the evaluation did not reach the chain"}
        try:        # the one log of events, when this relay keeps one (KNOS_EVENTS): best effort, after the confirmation
            from .... import events
            if sigs and events.where():
                events.keep(events.where(), lambda: events.from_records([t.aud + " " + sigs[-1]], made.month))
        except Exception:  # noqa: BLE001, S110 - the evaluation is on chain whatever a log file says
            pass
        return {"ok": True, **result, "sigs": sigs, "accepted": made.accepted, "rate": made.rate, "fee": made.fee, "month": made.month}
    return _Plan(t, [([*first, meter.record_ix(me, t.account, t.key, credits, cr, t.aud, now)], _CU["ata"] * len(first) + _CU["record"])], done)


def _plan_batch(a: _Ask, claim: bool = False) -> _Plan:
    """knosm:batch: the buyer's count of many evaluations in one token (RecordBatch), under Record's rules and paid
    from the same credits. knosm:claim: the seller's own count (ClaimBatch), from any workflow in a repository the
    seller owns, with no credits and no fee. A batch token is taken once: its seq must be the Ledger's next. A token
    for a batch the chain already took (its seq, its numbers and its root in the Ledger's recent logs) is answered
    "already", with that transaction: another relayer carried it."""
    kind, ledger, me, t, now = "claim" if claim else "batch", a.ledger, a.me, a.t, a.now
    try:
        is_claim, b = meter.parse_batch_audience(t.aud)
        owner, = _ints(t.c, "repository_owner_id")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    if is_claim != claim or not 1 <= b.count <= meter.MAX_BATCH or b.accepted > b.count or b.month not in (meter.yyyymm(now), meter.prev_month(meter.yyyymm(now))):
        raise _no(kind, meter.ERRORS[meter.E_BATCH])
    wf_repo, wf_file, wf_sha = _workflow(t.c)
    if not claim and wf_file not in meter.WORKFLOWS:
        raise _no(kind, "a batch is recorded from attest.yml or prove.yml")
    if not claim and str(t.c.get("run_attempt")) != "1":
        raise _no(kind, "this token is from a re-run, and only a run's first attempt is counted; run the workflow again")
    if owner != (b.seller if claim else b.buyer):
        raise _no(kind, "the run was not in a repository of the seller its audience names" if claim else "the run was not in a repository of the buyer its audience names")
    where = meter.ledger_pda(b.buyer, b.seller, b.month, claim)
    got = _read(ledger, [where, meter.plan_pda(b.buyer), meter.METER_ID])
    if _data(got, meter.METER_ID) is None:
        raise _no(kind, f"knos_meter ({meter.METER_ID}) is not deployed on this cluster, so no batch can be counted here")
    if old := live.needs(ledger, a.payer, "knos_meter", now):     # the batch mode is 1.1's: 1.0 runs until the upgrade executes
        raise _no(kind, old)
    before = meter.read_ledger(_data(got, where))
    result = dict(kind=kind, buyer_id=b.buyer, seller_id=b.seller, month=b.month, seq=b.seq, count=b.count, accepted=b.accepted, value=b.value, root=b.root.hex())
    if before is not None and before.next_seq > b.seq and (taken := _batch_taken(ledger, where, kind, b)):
        raise _Stop({"ok": True, **result, **taken, "already": True})     # this very batch is counted: another relayer carried it
    if (before.next_seq if before else 0) != b.seq:     # a seq another batch took, a batch out of order, or one that is missing: nothing is sent
        raise _no(kind, meter.ERRORS[meter.E_SEQ], next_seq=before.next_seq if before else 0)
    want = meter.chain_hash(before.chain if before else meter.ZERO, b.root, b.seq, b.count, b.accepted, b.value)

    def done(sigs: list[str]) -> dict:
        made = meter.read_ledger(ledger.account(where))
        if made is None or made.next_seq <= b.seq or (made.next_seq == b.seq + 1 and made.chain != want):
            return {"ok": False, "kind": kind, "why": "the batch did not reach the chain"}
        return {"ok": True, **result, "sigs": sigs, "fee": made.fees - (before.fees if before else 0), "chain": want.hex()}
    if claim:
        return _Plan(t, [([meter.claim_batch_ix(me, t.account, t.key, t.aud)], meter.CU_CLAIM)], done)
    pinned = [(addr, cr, held) for addr, cr, held in credits_for(ledger, b.buyer) if (cr.wf_repo_hash, cr.wf_sha) == (wf_repo, wf_sha)]
    if not pinned:
        raise _no(kind, "the buyer has no credits opened for these workflows at this commit; a wallet opens them (knos_meter OpenCredits), and "
                        "the first 10,000 evaluations of a month then cost nothing")
    plan_ = meter.read_plan(_data(got, meter.plan_pda(b.buyer)))
    paying = [(addr, cr, held) for addr, cr, held in pinned if held >= meter.batch_fee(plan_, b.count, cr.decimals, now)]
    if not paying:
        raise _no(kind, "the buyer's credits hold less than the fee of this batch, and a batch is taken whole or not at all; a plain transfer to "
                        "their token account adds to them, and the same token can be sent again while it is good")
    credits, cr, _held = max(paying, key=lambda x: x[2])
    home = pay.ata(meter.FEE_OWNER, cr.mint, cr.token_program)
    first = [pay.create_ata_ix(me, meter.FEE_OWNER, cr.mint, cr.token_program)] if meter.batch_fee(plan_, b.count, cr.decimals, now) and _data(_read(ledger, [home]), home) is None else []
    return _Plan(t, [([*first, meter.record_batch_ix(me, t.account, t.key, credits, cr, t.aud)], _CU["ata"] * len(first) + meter.CU_BATCH)], done)


# -- the upgrade gate: GitHub's word on which bytes its runner built ----------------------------------------------------
def _plan_gate(a: _Ask) -> _Plan:
    """gate:<program>:<executable hash>: examples/upgrade_gate records that GitHub's runner built these bytes for this
    program (its one instruction, Record). The token is program.yml's gate job's: Knos's repository, that file at the
    commit it built, main or a release tag, a GitHub-hosted runner. A record is written once, so a later run that
    built the same bytes costs this relay nothing."""
    kind, ledger, me, t = "gate", a.ledger, a.me, a.t
    c, p = t.c, t.aud.split(":")
    try:
        if len(p) != 3 or not _HEX64.fullmatch(p[2]):
            raise ValueError(t.aud)
        program, executable = _address(p[1]), bytes.fromhex(p[2])
        repo, = _ints(c, "repository_id")
    except (KeyError, ValueError, TypeError):
        raise _no(kind, "malformed audience or claims") from None
    ref, sha = str(c.get("ref", "")), str(c.get("sha", ""))
    if not (t.issuer == oidc.GITHUB and repo == gate.KNOS_REPO_ID and str(c.get("job_workflow_ref", "")).startswith(gate.WORKFLOW + "@")
            and c.get("runner_environment") == "github-hosted" and (ref == "refs/heads/main" or ref.startswith("refs/tags/v"))
            and _HEX40.fullmatch(sha) and c.get("job_workflow_sha") == sha):
        raise _no(kind, "a build is recorded only on a run of Knos's own program.yml on a GitHub-hosted runner, at a commit of main or of a "
                        "release tag, with the workflow file of that same commit")
    at = gate.record_pda(program, executable)
    got = _read(ledger, [at, gate.GATE_ID])
    result = dict(kind=kind, program=str(program), hash=p[2], record=str(at))

    def done(sigs: list[str], rec: gate.Record | None = None) -> dict:
        rec = rec or gate.read_record(ledger.account(at))
        if rec is None:
            return {"ok": False, "kind": kind, "why": "the record did not reach the chain"}
        return {"ok": True, **result, "sigs": sigs, "commit": rec.sha, "run_id": rec.run_id}
    before = gate.read_record(_data(got, at))
    if before is not None:      # recorded already, by this token or by an earlier run that built the same bytes: the first commit stays
        raise _Stop({**done(_last(ledger, at), before), "already": True})
    if _data(got, gate.GATE_ID) is None:
        raise _no(kind, f"the upgrade gate ({gate.GATE_ID}) is not deployed on this cluster, so no build can be recorded here")
    return _Plan(t, [([gate.record_ix(me, t.account, t.key, program, executable)], _CU["gate"])], done)
