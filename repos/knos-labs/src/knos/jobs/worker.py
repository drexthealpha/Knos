"""The reference worker (`knos work`): find an open job, claim it, do it with the operator's own model, run the brief's
checks and the buyer's shared preferences locally, and deliver the sealed result with its hash on chain.

It works the Solana escrow, and the Tempo escrow when given a `tempo` venue (knos.jobs.tempo.TempoVenue). It never
delivers work that fails the brief's own checks: it retries with the failure in the prompt, and if it still fails it
lets the work deadline pass, so the buyer is refunded in full by the escrow. A worker is paid only when the buyer
accepts, or stays silent through the review window.

With `memory` (a Sibyl MemoryClient for this worker), every delivery is remembered and the most similar past jobs
are recalled into the next prompt (knos.recall: the no-LLM recall measured at 96.8% on LongMemEval_s).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from solders.keypair import Keypair

from . import checks, market, models


@dataclass
class Outcome:
    job_id: bytes
    title: str
    delivered: bool
    note: str


@dataclass
class Worker:
    ledger: object
    relay: object
    key: Keypair
    model: Callable[[str], str]
    kinds: tuple[str, ...] = market.KINDS
    min_price: int = 0
    tries: int = 2
    log: Callable[[str], None] = field(default=lambda s: None)
    on_delivered: Callable[[bytes, str], None] = field(default=lambda jid, title: None)
    tempo: object = None      # a knos.jobs.tempo.TempoVenue: also work the Tempo escrow
    memory: object = None     # a Sibyl MemoryClient: remember deliveries, recall similar past jobs

    def prompt(self, brief: market.Brief, failure: str = "", past: list[str] | None = None) -> str:
        parts = [f"JOB: {brief.title}", "", brief.task]
        if brief.kind == "python":
            parts += ["", "Return one Python module (no fences). It will be imported as `solution`."]
        if brief.kind in ("csv", "json"):
            parts += ["", f"Return only the {brief.kind.upper()}."]
        if brief.checks and brief.checks.get("tests"):
            parts += ["", "It must pass these tests:", brief.checks["tests"]]
        rules = (brief.checks or {})
        if rules.get("must_include"):
            parts += ["", "It must include: " + "; ".join(rules["must_include"])]
        if rules.get("must_not_include"):
            parts += ["", "It must not include: " + "; ".join(rules["must_not_include"])]
        if rules.get("max_words"):
            parts += ["", f"At most {rules['max_words']} words."]
        if brief.preferences:
            parts += ["", "This buyer's standing preferences (follow every one):"] + [f"- {p}" for p in brief.preferences]
        if past:
            parts += ["", "Similar jobs you delivered before (for consistency; this brief wins where they differ):"]
            parts += [f"- {p}" for p in past]
        if failure:
            parts += ["", f"A previous attempt failed this check: {failure}. Fix it."]
        if brief.scripted_answer is not None:
            parts += ["", "SCRIPTED_ANSWER:\n" + brief.scripted_answer + "\n:END"]
        return "\n".join(parts)

    # -- memory of past jobs (knos.recall over this worker's own Sibyl store) ------------------------------------
    def recall(self, brief: market.Brief, k: int = 3) -> list[str]:
        if self.memory is None:
            return []
        from .. import recall
        try:
            return [r["text"].split(": ", 1)[-1][:600] for r in recall.retrieve(self.memory, f"{brief.title} {brief.task}", k=k)]
        except Exception:  # noqa: BLE001 - memory helps; it never stops a job
            return []

    def remember(self, job_key: str, brief: market.Brief, text: str) -> None:
        if self.memory is None:
            return
        from .. import recall
        try:
            day = time.strftime("%Y-%m-%d", time.gmtime())
            recall.index(self.memory, [{"id": f"job-{job_key}", "date": day, "turns": [
                {"role": "user", "content": f"{brief.title}. {brief.task}"},
                {"role": "assistant", "content": text}]}])
        except Exception:  # noqa: BLE001
            pass

    def produce(self, brief: market.Brief) -> tuple[bool, str, str]:
        """(passed, text, why): the model's work, retried with the failure until the brief's checks pass."""
        past, failure, text = self.recall(brief), "", ""
        for _ in range(self.tries + 1):
            text = models.strip_fences(self.model(self.prompt(brief, failure, past)))
            ok, why = checks.run(brief.kind, brief.checks, text, brief.preferences)
            if ok:
                return True, text, why
            failure = why
        return False, text, failure

    def wants(self, j, brief: market.Brief) -> bool:
        return brief.kind in self.kinds and j.amount >= self.min_price and j.buyer != self.key.pubkey()

    # -- Solana ----------------------------------------------------------------------------------------------------
    def do(self, j, brief: market.Brief) -> Outcome:
        jid = market.job_id_for(self.ledger, j.address, brief)
        if jid is None or not market.claim(self.ledger, self.key, jid):
            return Outcome(jid or b"", brief.title, False, "someone else claimed it")
        self.log(f"claimed  {brief.title}  ({j.amount / 1e6:.2f} USDC)")
        ok, text, why = self.produce(brief)
        if ok:
            market.deliver(self.ledger, self.relay, self.key, jid, j.buyer, text.encode(), brief.seal_to,
                           verifier=getattr(j, "verifier", None))
            self.remember(jid.hex(), brief, text)
            self.log(f"delivered {brief.title}: checks passed, sealed to the buyer, hash on chain")
            self.on_delivered(jid, brief.title)
            return Outcome(jid, brief.title, True, "delivered")
        self.log(f"gave up   {brief.title}: {why} (the buyer is refunded at the deadline)")
        return Outcome(jid, brief.title, False, f"checks failed: {why}")

    # -- Tempo -----------------------------------------------------------------------------------------------------
    def do_tempo(self, j, brief: market.Brief) -> Outcome:
        if not self.tempo.claim(j):
            return Outcome(j.id, brief.title, False, "someone else claimed it")
        self.log(f"claimed  {brief.title}  ({j.amount / 1e6:.2f} pathUSD, Tempo)")
        ok, text, why = self.produce(brief)
        if ok:
            self.tempo.deliver(j, text, brief.seal_to)
            self.remember(j.id.hex(), brief, text)
            self.log(f"delivered {brief.title} on Tempo: checks passed, sealed to the buyer, hash on chain")
            self.on_delivered(j.id, brief.title)
            return Outcome(j.id, brief.title, True, "delivered")
        self.log(f"gave up   {brief.title}: {why} (the buyer is refunded at the deadline)")
        return Outcome(j.id, brief.title, False, f"checks failed: {why}")

    def once(self) -> list[Outcome]:
        done = []
        for j, brief in market.open_jobs(self.ledger, self.relay):
            if self.wants(j, brief):
                done.append(self.do(j, brief))
        if self.tempo is not None:
            for j, brief in self.tempo.open():
                if brief.kind in self.kinds and j.amount >= self.min_price and j.buyer != self.tempo.key.address:
                    done.append(self.do_tempo(j, brief))
        return done

    def run(self, every: float = 5.0, until: float | None = None) -> None:
        while until is None or time.monotonic() < until:
            try:
                self.once()
            except Exception as why:  # noqa: BLE001 - a flaky RPC or relay must not stop the worker
                self.log(f"retrying: {type(why).__name__}: {why}")
            time.sleep(every)
