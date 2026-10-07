"""`knos decide`: the decision the moment the evidence arrives, before the chain settles.

    knos decide --refresh-keys                                    # once, with a network: keep the issuers' key lists
    knos decide --token-file FILE [--terms-file FILE] [--order ADDRESS] [--no-chain] [--out FILE]
    knos decide --token-file FILE [--terms-file FILE] --full      # the relay's whole precheck instead (many reads)
    knos decide --checks-file FILE [--out FILE]

THE DECISION IS SPLIT IN TWO (0.3.19), because the first half needs no network and the second must never be waited
for:

    offline       `offline`: the issuer's signature against the key lists KEPT on this machine (`kept_keys`; the
                  check is `knos.bundle.rs256`, the one `knos bundle verify --no-chain` runs), then the token's claims
                  and the terms that travel with it, by the relay's own rules for a token alone. No network, no chain.
                  Accepted here means exactly: "decided from the signed evidence; chain state not yet read".
    chain check   `chain_check`: only what the chain can answer (the token unused, funding not paused, the chain's
                  clock, the order or job when its address is given: open, before its deadline, and for a knos_meter
                  batch or claim, which keeps no marker, the batch the pair's Ledger account takes next), in ONE request
                  (getMultipleAccounts) with a timeout. `after_chain` writes the answer into a second provisional
                  receipt that names the first. A chain that does not answer in time changes nothing and stops nothing.

Neither half sends anything, and neither is the relay's precheck: a relay still makes every read of its own before it
spends a fee. `--full` (and `token(..., ledger=...)`, which `knos.flow` calls) is that precheck, as before.

A payment waits for a workflow run, then for a relay, then for two or three transactions (docs/LOAD.md, "The five
clocks"). The DECISION does not need the last two: once the forge has signed its token, everything the chain will ask
of it can be asked here, from reads. `token` asks it and answers accepted, rejected or insufficient evidence
(knos.ids.VERDICTS; nothing here is ever "disputed"), and `provisional` writes that answer down as a PROVISIONAL
receipt.

THE RULES ARE THE RELAY'S, NOT A COPY. `token` calls `knos.settle.v2.relay.precheck`: the reads a relay makes before
it spends a fee, which mirror what knos_oidc and knos_pay check (the issuer's signature, the token's times, its
audience, the order's state, its terms' hash, its payees). Whatever that function refuses, this one rejects, with the
same words. Nothing in this module names a rule of its own for a token. Three answers:

    accepted                `precheck` found nothing in the way (or the chain already shows the token done)
    rejected                `precheck` refused it; `why` is the relay's sentence
    insufficient_evidence   the chain was not read (`--no-chain`, or it did not answer), or the refusal is one that
                            may clear (the relay would try again). Never an acceptance, never the supplier's failure

For the free check there is no token and no chain: `checks` takes the conclusions of the named checks as
`knos.receipt.CONCLUSIONS` spells them (passed, failed, missing). Every one passed: accepted. Any failed: rejected.
Otherwise: insufficient evidence.

A PROVISIONAL RECEIPT IS NOT A RECEIPT OF PAYMENT. It says `"settlement": "provisional"` and
`"authorises_payment": false`, in every case, the accepted one too: only the program releases money, and only a
receipt that names a paying transaction says anything was paid. It is identified by its sha256 over
`knos.receipt.canonical`. The final receipt supersedes it by naming that hash: `supersede(final, provisional)` writes
the line `{final, supersedes}` and refuses a final receipt that is about another token. When the chain decides
otherwise than the provisional receipt said, the line says so (`agrees: false`) and the final receipt stands.

A cached decision: `Cached(ledger)` keeps what the chain answered for `ttl` seconds, so the same question asked again
(the status comment, the site, a second evaluator) is answered from memory. What is kept is what the chain said THEN:
the provisional receipt carries the time of the read.

Measured by `scripts/decide_bench.py` (docs/BENCH.md, "Decision time"); `tests/test_decide.py` holds the bounds. What
is measured is this machine's own time. Against devnet, four runs of the 0.3.18 command took 4.3 to 32.6 s; the split,
once on each of 24 real tokens, took a median of 356 ms offline and 854 ms for the chain check (docs/BENCH.md, after
the "Decision time" block; docs/RELAY.md has the command).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from . import ids
from . import receipt as rc

TYPE = "knos-provisional-receipt"
LINK = "knos-supersedes"
VERSION = 1
DECISIONS = ("accepted", "rejected", "insufficient_evidence")
SETTLEMENT = "provisional"
SAYS = ("Provisional: this is Knos's reading of the evidence before the chain has settled anything. It never authorises payment and records none. "
        "The final receipt names this one by its sha256 and replaces it.")
RULES_TOKEN = "knos.settle.v2.relay.precheck"
RULES_OFFLINE = "knos.decide.offline"
OFFLINE = "decided from the signed evidence; chain state not yet read"
CHAIN_TIMEOUT = 2.0     # seconds the chain check may take before it is left behind
KEYS_ENV = "KNOS_ISSUER_KEYS"       # a file of {issuer URL: its JWKS document}; default `keys_path()`
KEYS_TYPE = "knos-issuer-keys"
RULES_CHECKS = "every named check passed: accepted; any failed: rejected; otherwise insufficient evidence"
TTL = 30.0              # seconds `Cached` keeps an answer of the chain
_NO_KEY = hashlib.sha256(b"knos decide: a key that pays nothing, signs nothing that is sent, and holds nothing").digest()
_KEYS = ("type", "version", "settlement", "authorises_payment", "says", "decision", "why", "kind", "evidence", "subject", "rules", "decided_at", "limitations")


class Cached:
    """A ledger whose answers are kept for `ttl` seconds: every read (`account`, `infos`, `program_accounts`, `now`,
    `log_of`, ...) is asked once per argument list and answered from memory after that. Nothing is ever sent through
    it: `send` and `send_all` are refused. `reads` counts what reached the ledger, `hits` what did not."""

    def __init__(self, ledger: Any, ttl: float = TTL, clock: Callable[[], float] = time.monotonic) -> None:
        self._ledger, self._ttl, self._clock = ledger, ttl, clock
        self._kept: dict[tuple[str, str], tuple[float, Any]] = {}
        self.reads = self.hits = 0
        self.url = getattr(ledger, "url", None) or f"cached:{id(ledger)}"

    def __getattr__(self, name: str) -> Any:
        if name in ("send", "send_all"):
            raise AttributeError(f"a cached ledger decides and sends nothing: it has no {name}")
        got = getattr(self._ledger, name)
        if not callable(got):
            return got

        def asked(*args: Any, **kw: Any) -> Any:
            key = (name, repr((args, sorted(kw.items()))))
            kept = self._kept.get(key)
            if kept is not None and self._clock() - kept[0] <= self._ttl:
                self.hits += 1
                return kept[1]
            out = got(*args, **kw)
            self.reads += 1
            self._kept[key] = (self._clock(), out)
            return out
        return asked


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def _claims(jwt: str) -> dict[str, Any]:
    """A token's claims as written, unchecked ({} when it is not a token): what `knos.proof.ghrelay.claims` reads."""
    import base64
    try:
        body = jwt.split(".")[1]
        got = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001 - not a token: the relay's own words say so
        return {}


def token(jwt: str, terms: bytes | str | None = None, *, ledger: Any = None, payer: Any = None, jwks: dict | None = None,
          now: float | None = None) -> dict[str, Any]:
    """The decision on one signed token, by the relay's own reads (`relay.precheck`). `terms`: what travels with a
    fund token. `ledger`: the chain to read (a `Cached` one answers again from memory); None reads no chain, and the
    answer is then insufficient evidence unless the token itself is refused. `payer`: any key (it names the account a
    relay would verify the token in; nothing is sent). Returns {decision, why, kind, chain_read, already}."""
    from .settle.v2 import relay
    jwt = jwt.strip()
    raw = terms.encode() if isinstance(terms, str) else terms
    if payer is None:
        from solders.keypair import Keypair
        payer = Keypair.from_seed(_NO_KEY)
    kind = relay.kind_of(str(_claims(jwt).get("aud") or "")) if isinstance(_claims(jwt).get("aud"), str) else None
    out: dict[str, Any] = {"decision": "insufficient_evidence", "why": "", "kind": kind, "chain_read": ledger is not None, "already": False}
    if ledger is None:
        # the token alone: the part of the relay's reads that needs no chain. It can refuse; it cannot accept.
        try:
            t = relay._open(jwt, payer.pubkey(), jwks, None)
            out["kind"] = t.kind
            handler = relay._handler(t.aud)
            if handler is None:
                raise relay._no(None, f"not an audience of the second deployment: {t.aud[:60]!r}")
            at = int(time.time() if now is None else now)
            if int(t.c.get("exp", 0)) + relay.oidc.LATE <= at:
                raise relay._no(t.kind, "token expired")
            if handler.github:
                relay._github_token(t, at, handler.private)
            if t.kind == "fund" and t.aud.startswith(("knos2:", "knos3:")) and not relay.carries_terms(t.aud, raw):
                raise relay._no(t.kind, "its terms are missing, or are not the terms the token names")
        except relay._Stop as stop:
            return {**out, "decision": "rejected", "why": str(stop.result.get("why") or "refused"), "kind": stop.result.get("kind") or out["kind"]}
        except Exception as why:  # noqa: BLE001 - the issuer's keys could not be read: no answer
            return {**out, "why": f"the issuer's keys could not be read ({type(why).__name__}: {why})"}
        return {**out, "why": "the issuer signed this token and it asks for what it says; the order's state on chain was not read, so nothing is decided"}
    try:
        r = relay.precheck(ledger, payer, jwt, raw, jwks, now)
    except Exception as why:  # noqa: BLE001 - the chain did not answer: no decision, and nobody's failure
        return {**out, "why": f"the chain did not answer ({type(why).__name__}: {' '.join(str(why).split())[:200]})"}
    if r is None:
        return {**out, "decision": "accepted", "why": "everything the chain will ask of this token holds now"}
    out["kind"] = r.get("kind") or out["kind"]
    if r.get("ok"):
        return {**out, "decision": "accepted", "already": bool(r.get("already")), "why": "the chain already shows what this token asks for"}
    said = " ".join(str(r.get("why") or "refused").split())
    if r.get("retry"):
        return {**out, "why": f"not decided yet, and it may clear: {said}"}
    return {**out, "decision": "rejected", "why": said}


# -- the offline half: the signed evidence, and nothing fetched -----------------------------------------------------------
def keys_path() -> Path:
    """Where the issuers' key lists are kept on this machine: $KNOS_ISSUER_KEYS, else the user's cache folder."""
    named = os.environ.get(KEYS_ENV)
    if named:
        return Path(named)
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "knos" / "issuer_keys.json"


def kept_keys(path: Path | None = None) -> dict[str, dict]:
    """{issuer URL: JWKS document} as `keep_keys` wrote it; {} when nothing is kept or the file is not one."""
    try:
        doc = json.loads((path or keys_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    lists = doc.get("issuers") if isinstance(doc, dict) and doc.get("type") == KEYS_TYPE else None
    return {str(k): v for k, v in lists.items() if isinstance(v, dict)} if isinstance(lists, dict) else {}


def keep_keys(lists: Mapping[str, dict], at: int, path: Path | None = None) -> Path:
    """Keeps key lists for `offline`. `at`: when they were read from the issuers (Unix seconds)."""
    where = path or keys_path()
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_text(json.dumps({"type": KEYS_TYPE, "version": VERSION, "read_at": int(at), "issuers": dict(sorted(lists.items()))}, sort_keys=True) + "\n", encoding="utf-8")
    return where


def fetch_keys() -> dict[str, dict]:
    """The key lists of the issuers the escrow knows by number, read from them now. The one call here that uses a
    network; `offline` never makes it."""
    from .settle.v2 import relay
    return {url: relay.first.fetch_jwks(number) for number, url in sorted(relay.oidc.ISSUERS.items())}


def offline(jwt: str, terms: bytes | str | None = None, *, keys: Mapping[str, dict] | None = None, now: float | None = None) -> dict[str, Any]:
    """The decision from the signed evidence alone. `keys`: {issuer URL: JWKS document} (default: `kept_keys()`).
    `now`: Unix seconds (default: this machine's clock; the chain check compares with the chain's). Nothing is
    fetched and no chain is read. accepted: the issuer signed it, and it asks for what its claims and terms say.
    rejected: the signature is not the issuer's, or the relay's rules for a token alone refuse it (its words).
    insufficient_evidence: no key list is kept for its issuer, or the kept list has not the key the token names."""
    from . import bundle
    from .settle.v2 import relay
    jwt = jwt.strip()
    raw = terms.encode() if isinstance(terms, str) else terms
    out: dict[str, Any] = {"decision": "insufficient_evidence", "why": "", "kind": None, "chain_read": False, "already": False, "rules": RULES_OFFLINE}
    try:
        c, head = relay.claims_of(jwt), relay.header_of(jwt)
        aud = c["aud"] if isinstance(c["aud"], str) else c["aud"][0]
        iss, kid = c.get("iss"), head.get("kid")
    except Exception:  # noqa: BLE001 - not a token at all
        return {**out, "decision": "rejected", "why": "this is not a token GitHub Actions or GitLab CI issued"}
    out["kind"] = relay.kind_of(aud) if isinstance(aud, str) else None
    number = next((i for i, url in relay.oidc.ISSUERS.items() if url == iss), None)
    if number is None:
        return {**out, "why": "the keys of this token's issuer are the ones the verifier holds on chain, and chain state is not yet read"}
    doc = (kept_keys() if keys is None else keys).get(str(iss))
    if doc is None:
        return {**out, "why": f"no key list of {iss} is kept on this machine, and none was fetched (`knos decide --refresh-keys` keeps them)"}
    n = dict(relay.oidc.jwks_keys(doc)).get(str(kid))
    if n is None:
        return {**out, "why": f"the kept key list of {iss} has no key {str(kid)[:60]!r}: the issuer may have added one since (`knos decide --refresh-keys`)"}
    if not bundle.rs256(jwt, n):
        return {**out, "decision": "rejected", "why": "the signature is not the issuer's"}
    try:
        from solders.keypair import Keypair
        t = relay._open(jwt, Keypair.from_seed(_NO_KEY).pubkey(), {number: doc}, None)
        handler = relay._handler(t.aud)
        if handler is None:
            raise relay._no(None, f"not an audience of the second deployment: {t.aud[:60]!r}")
        at = int(time.time() if now is None else now)
        if int(t.c.get("exp", 0)) + relay.oidc.LATE <= at:
            raise relay._no(t.kind, "token expired")
        if handler.github:
            relay._github_token(t, at, handler.private)
        if t.kind == "fund" and t.aud.startswith(("knos2:", "knos3:")) and not relay.carries_terms(t.aud, raw):
            raise relay._no(t.kind, "its terms are missing, or are not the terms the token names")
    except relay._Stop as stop:
        return {**out, "decision": "rejected", "why": str(stop.result.get("why") or "refused"), "kind": stop.result.get("kind") or out["kind"]}
    if raw and t.kind != "fund" and hashlib.sha256(raw).hexdigest() not in t.aud.split(":"):
        return {**out, "why": "the terms given are not ones this token's audience names by their sha256"}
    return {**out, "decision": "accepted", "why": OFFLINE}


# -- the chain half: one request, a timeout, and never in the way --------------------------------------------------------
def _within(fn: Callable[[], Any], timeout: float) -> tuple[bool, Any]:
    """(answered, the answer or the error) of `fn`, left behind after `timeout` seconds: nothing waits for it."""
    import threading
    box: list[tuple[bool, Any]] = []

    def run() -> None:
        try:
            box.append((True, fn()))
        except Exception as why:  # noqa: BLE001 - whatever the endpoint said: no answer
            box.append((False, why))
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    return box[0] if box else (False, TimeoutError(f"no answer in {timeout:g} s"))


def chain_check(jwt: str, *, ledger: Any, order: Any = None, timeout: float = CHAIN_TIMEOUT) -> dict[str, Any]:
    """What the chain alone can answer about this token, read in ONE request (`ledger.infos`: getMultipleAccounts)
    and left behind after `timeout` seconds. `order`: the address of the order or job the token is for, when the
    caller knows it. Returns {read, round_trips, why, now, token_used, paused_until, order}: `order` is None (not
    asked), or {address, found, state, deadline}; for a knos_meter batch or claim token also `batch`: {address, claim,
    seq, next_seq} of the pair's Ledger account, read in the same request. It decides nothing: `after_chain` does."""
    from solders.pubkey import Pubkey

    from . import chain
    from .settle.v2 import pay
    asked = [chain.CLOCK, pay.used_pda(jwt.strip()), pay.pause_pda()]
    if order is not None:
        asked.append(order if isinstance(order, Pubkey) else Pubkey.from_string(str(order)))
    # knos_meter keeps no marker of a batch or claim token: the pair's Ledger account says which batch it takes next
    batch = _batch_of(jwt)
    if batch is not None:
        from .settle.v2 import meter
        claim, b = batch
        asked.append(meter.ledger_pda(b.buyer, b.seller, b.month, claim))
    out: dict[str, Any] = {"read": False, "round_trips": 1, "why": "", "now": None, "token_used": None, "paused_until": None, "order": None}
    if batch is not None:
        out["batch"] = None
    ok, got = _within(lambda: ledger.infos(asked), timeout)
    data = [g[1] if g else None for g in got] if ok and isinstance(got, list) and len(got) == len(asked) else None
    if data is None or data[0] is None or len(data[0]) < 40:
        said = " ".join(str(got).split())[:160] if not ok else "the chain's clock was not in the answer"
        return {**out, "why": f"the chain did not answer ({type(got).__name__ if not ok else 'RpcError'}: {said})"}
    out.update(read=True, now=int.from_bytes(data[0][32:40], "little", signed=True), token_used=pay.spent(data[1]), paused_until=pay.read_pause(data[2]))
    if order is not None:
        found = pay.read_order(data[3]) or pay.read_job(data[3])
        out["order"] = {"address": str(asked[3]), "found": found is not None, "state": found.state if found else None, "deadline": found.deadline if found else None}
    if batch is not None:
        from .settle.v2 import meter
        held = meter.read_ledger(data[-1])
        nxt = held.next_seq if held is not None else 0
        out["batch"] = {"address": str(asked[-1]), "claim": batch[0], "seq": batch[1].seq, "next_seq": nxt}
    return out


def _batch_of(jwt: str) -> tuple[bool, Any] | None:
    """(whether it is the seller's claim, the batch it names) for a knos_meter batch or claim token; None for any
    other token, or one whose audience cannot be read."""
    try:
        from . import ledger as meter_ledger
        from .settle.v2 import relay
        aud = str(relay.claims_of(jwt.strip()).get("aud") or "")
        return meter_ledger.parse_batch_audience(aud) if aud.startswith(("knosm:batch:", "knosm:claim:")) else None
    except Exception:  # noqa: BLE001 - not a token this half can read: the offline half has said why
        return None


def after_chain(d: Mapping[str, Any], seen: Mapping[str, Any], jwt: str | None = None) -> dict[str, Any]:
    """The offline decision `d` with what `chain_check` saw. A chain that did not answer leaves `d` as it was. A
    rejection stays one. An acceptance stays one only when nothing the chain showed is in its way."""
    out = {**d, "chain": dict(seen)}
    if not seen.get("read"):
        return {**out, "why": f"{d.get('why')}; {seen.get('why')}" if d.get("decision") == "accepted" else d.get("why")}
    out["chain_read"] = True
    if d.get("decision") != "accepted":
        return out
    now, o = int(seen["now"]), seen.get("order")
    if seen.get("token_used"):
        return {**out, "already": True, "why": "the chain shows this token used already: what it asks for is done or held"}
    b = seen.get("batch")
    if b is not None and b["next_seq"] > b["seq"]:
        return {**out, "already": True, "why": f"the chain shows batch {b['seq']} of this pair's month taken already (it takes {b['next_seq']} next): what this "
                                               "token asks for is done, unless another root took that number (`--full` reads which)"}
    if jwt is not None:
        from .settle.v2 import relay
        if int(relay.claims_of(jwt.strip()).get("exp", 0)) + relay.oidc.LATE <= now:
            return {**out, "decision": "rejected", "why": "token expired"}
    if d.get("kind") == "fund" and now < int(seen.get("paused_until") or 0):
        return {**out, "decision": "insufficient_evidence", "why": "not decided yet, and it may clear: new funding is paused"}
    if o is not None and not o["found"]:
        return {**out, "decision": "rejected", "why": f"nothing is in escrow at {o['address']} (never funded, or already paid or refunded)"}
    if o is not None and o["state"] != "open":
        return {**out, "decision": "insufficient_evidence", "why": f"the order at {o['address']} is {o['state']}, not open"}
    if o is not None and now > int(o["deadline"]):
        return {**out, "decision": "rejected", "why": "the deadline has passed: the money goes back to its funder"}
    if b is not None and b["next_seq"] < b["seq"]:
        return {**out, "decision": "insufficient_evidence", "why": f"not decided yet, and it may clear: the chain takes batch {b['next_seq']} of this pair's "
                                                                   f"month next, and this token names batch {b['seq']}"}
    shown = ("the token is unused" if b is None else f"batch {b['seq']} is the one the pair's Ledger account takes next") + \
        ("" if o is None else ", the order is open and before its deadline")
    return {**out, "why": f"decided from the signed evidence; the chain shows {shown}" + ("" if o is not None else "; the order's own state was not asked (no address given)")}


def checks(found: list[Mapping[str, Any]]) -> dict[str, Any]:
    """The decision of the free check, from the conclusions of its named checks: [{name, conclusion}], each
    conclusion one of `knos.receipt.CONCLUSIONS`. No check named at all is insufficient evidence."""
    rows = sorted(({"name": str(c.get("name")), "conclusion": str(c.get("conclusion"))} for c in found), key=lambda c: c["name"])
    bad = [c["name"] for c in rows if c["conclusion"] not in rc.CONCLUSIONS]
    if bad:
        raise ValueError(f"a check's conclusion is one of {', '.join(rc.CONCLUSIONS)}; not so for: {', '.join(bad)[:200]}")
    failed, missing = [c["name"] for c in rows if c["conclusion"] == "failed"], [c["name"] for c in rows if c["conclusion"] == "missing"]
    out: dict[str, Any] = {"kind": "check", "chain_read": False, "already": False, "checks": rows}
    if failed:
        return {**out, "decision": "rejected", "why": f"failed: {', '.join(failed)}"}
    if missing or not rows:
        return {**out, "decision": "insufficient_evidence", "why": f"no finished run found of: {', '.join(missing)}" if missing else "no check was named"}
    return {**out, "decision": "accepted", "why": f"all {len(rows)} named check{'' if len(rows) == 1 else 's'} passed"}


def _limits(source: str, decision: str, mode: str | None) -> list[str]:
    """What the evidence does not show: `knos.receipt.limitations_of` for a receipt with no payment and no re-run
    recorded. When the terms (and so the mode) are not known, the sentence about the mode is the one left out."""
    if mode in rc.MODES:
        return rc.limitations_of(source, decision, mode, False, False)
    both = [rc.limitations_of(source, decision, m, False, False) for m in rc.MODES]
    return [s for s in both[0] if s in both[1]]


def provisional(d: Mapping[str, Any], *, at: int, jwt: str | None = None, terms: bytes | str | None = None, subject: Mapping[str, Any] | None = None,
                updates: str | None = None) -> dict[str, Any]:
    """The provisional receipt of a decision `token` or `checks` gave. `at`: when it was decided (Unix seconds).
    `jwt` and `terms`: the token decided on, and what travelled with it. `subject`: for the free check, what was
    checked ({repository, commit, pull_request}; any strings and whole numbers). `updates`: the sha256 of the
    provisional receipt this one replaces (the offline one, once the chain has been read)."""
    if d.get("decision") not in DECISIONS:
        raise ValueError("a decision is accepted, rejected or insufficient_evidence")
    raw = terms.encode() if isinstance(terms, str) else terms
    mode = None
    if jwt is not None:
        c = _claims(jwt.strip())
        try:
            mode = str(json.loads(raw.decode()).get("mode")) if raw else None
        except (ValueError, AttributeError):
            mode = None
        evidence = {"kind": "issuer_token", "reference": _sha(jwt.strip()), "signed_by": c.get("iss") if isinstance(c.get("iss"), str) else None}
        about: dict[str, Any] = {"audience": c.get("aud") if isinstance(c.get("aud"), str) else None,
                                 **{k: (str(c[k]) if c.get(k) is not None else None) for k in ("repository_id", "run_id", "run_attempt", "sha")},
                                 "terms_sha256": _sha(raw) if raw else None}
        rules = {"by": str(d.get("rules") or RULES_TOKEN), "chain_read": bool(d.get("chain_read")), "already_on_chain": bool(d.get("already"))}
        if d.get("chain") is not None:      # the chain half ran: what it saw, and the receipt this one updates
            rules["chain"] = {k: d["chain"].get(k) for k in ("read", "round_trips", "now", "token_used", "paused_until", "order")}
        if updates is not None:
            rules["updates"] = updates
    else:
        rows = [dict(c) for c in d.get("checks") or []]
        about = {**{str(k): v for k, v in sorted((subject or {}).items())}, "checks": rows}
        evidence = {"kind": "run_record", "reference": _sha(rc.canonical(about)), "signed_by": None}
        rules = {"by": RULES_CHECKS, "chain_read": False, "already_on_chain": False}
    doc = {"type": TYPE, "version": VERSION, "settlement": SETTLEMENT, "authorises_payment": False, "says": SAYS,
           "decision": d["decision"], "why": " ".join(str(d.get("why") or "").split())[:400], "kind": d.get("kind"), "evidence": evidence, "subject": about,
           "rules": rules, "decided_at": int(at), "limitations": [*_limits(str(evidence["kind"]), str(d["decision"]), mode), SAYS]}
    why = check(doc)
    if why:
        raise ValueError(why)
    return doc


def digest(doc: Mapping[str, Any]) -> str:
    """The name of a provisional receipt: sha256 over its canonical bytes (`knos.receipt.canonical`)."""
    return hashlib.sha256(rc.canonical(dict(doc))).hexdigest()


def check(doc: Any) -> str | None:
    """Why `doc` is not a provisional receipt, or None. One that says anything but provisional, or that it
    authorises a payment, is not one."""
    if not isinstance(doc, dict) or set(doc) != set(_KEYS):
        return f"not a {TYPE}: its fields are {', '.join(_KEYS)}"
    if doc["type"] != TYPE or doc["version"] != VERSION:
        return f"not a {TYPE} of version {VERSION}"
    if doc["settlement"] != SETTLEMENT or doc["authorises_payment"] is not False or doc["says"] != SAYS:
        return "a provisional receipt says settlement provisional and authorises_payment false, with the sentence that says so: it never authorises payment"
    if doc["decision"] not in DECISIONS:
        return "decision is accepted, rejected or insufficient_evidence"
    e = doc["evidence"]
    if not isinstance(e, dict) or set(e) != {"kind", "reference", "signed_by"} or e["kind"] not in rc.EVIDENCE \
            or not (isinstance(e["reference"], str) and len(e["reference"]) == 64):
        return "evidence is {kind: issuer_token or run_record, reference: a sha256, signed_by}"
    if type(doc["decided_at"]) is not int or not isinstance(doc["limitations"], list) or SAYS not in doc["limitations"] or not isinstance(doc["subject"], dict):
        return "decided_at is whole seconds, subject an object, and limitations a list that ends with the provisional sentence"
    return None


def authorises_payment(doc: Any) -> bool:
    """Never. Here so that no caller has to remember it: a provisional receipt stands behind no payment."""
    return False


def supersede(final: Mapping[str, Any], prov: Mapping[str, Any]) -> dict[str, Any]:
    """The line by which a final receipt (any version `knos.receipt.check` passes) replaces a provisional one: it
    names both by sha256. Refused when either does not check, or when the final receipt is about another token.
    `agrees`: whether the chain decided what the provisional receipt said."""
    why = rc.check(dict(final)) or check(dict(prov))
    if why:
        raise ValueError(why)
    ia = final.get("issuer_authenticated") or final.get("judge") or {}
    if prov["evidence"]["kind"] == "issuer_token" and ia.get("token_sha256") != prov["evidence"]["reference"]:
        raise ValueError("this final receipt is about another token than the provisional one: it does not supersede it")
    verdict = ids.verdict(rc.verdict_of(dict(final)))
    return {"type": LINK, "version": VERSION,
            "final": {"sha256": rc.digest(dict(final)), "verdict": verdict, "settlement": "paid" if final.get("transaction") else "none"},
            "supersedes": {"sha256": digest(prov), "decision": prov["decision"], "settlement": SETTLEMENT},
            "agrees": verdict == prov["decision"]}


def superseded(prov: Mapping[str, Any], line: Mapping[str, Any], final: Mapping[str, Any] | None = None) -> bool:
    """Whether `line` replaces this provisional receipt (and, when `final` is given, names that final receipt)."""
    return (line.get("type") == LINK and (line.get("supersedes") or {}).get("sha256") == digest(prov)
            and (final is None or (line.get("final") or {}).get("sha256") == rc.digest(dict(final))))


def comment_line(doc: Mapping[str, Any]) -> str:
    """One line for a status comment, the moment the decision exists. It never says paid."""
    word = ids.VERDICT_WORDS[str(doc["decision"])]
    return f"Provisional: {word} ({doc['why']}). Not paid yet: the chain settles next. Provisional receipt {digest(doc)[:16]}."


def register(app: Any, help_lines: list | None = None) -> None:
    """`knos decide`, on the main app. `help_lines`: cli._HELP, which gets the command's line."""
    import importlib
    typer = importlib.import_module("typer")

    if help_lines is not None:
        help_lines.append(("decide", "For money", "The decision the moment the evidence arrives, as a provisional receipt. It never authorises payment."))

    @app.command("decide", rich_help_panel="For money")
    def decide_(token_file: Path = typer.Option(None, "--token-file", help="the forge's signed token (or the comment that carries it)"),
                terms_file: Path = typer.Option(None, "--terms-file", help="a fund token's terms, as they travel with it"),
                checks_file: Path = typer.Option(None, "--checks-file", help="the free check: JSON [{name, conclusion: passed, failed or missing}]"),
                no_chain: bool = typer.Option(False, "--no-chain", help="stop after the offline half: the signed evidence alone"),
                order: str = typer.Option(None, "--order", help="the order's or job's address: the chain check then says whether it is open"),
                keys_file: Path = typer.Option(None, "--keys-file", help=f"the kept key lists (default: ${KEYS_ENV}, else the cache folder)"),
                refresh_keys: bool = typer.Option(False, "--refresh-keys", help="read the issuers' key lists now and keep them; the one step that needs a network"),
                chain_timeout: float = typer.Option(CHAIN_TIMEOUT, "--chain-timeout", help="seconds the one chain request may take"),
                full: bool = typer.Option(False, "--full", help="the relay's whole precheck instead: every read a relay makes before it sends"),
                out: Path = typer.Option(None, "--out", help="write the provisional receipt here (default: print it)")) -> None:
        """Decide now, from the signed evidence; then ask the chain once. Prints a provisional receipt."""
        try:
            code = command(token_file, terms_file, checks_file, no_chain, order, keys_file, refresh_keys, chain_timeout, full, out,
                           say=typer.echo, note=lambda words: typer.echo(words, err=True))
        except ValueError as why:
            raise typer.BadParameter(str(why)) from None
        raise typer.Exit(code)


def command(token_file: Path | None = None, terms_file: Path | None = None, checks_file: Path | None = None, no_chain: bool = False,
            order: str | None = None, keys_file: Path | None = None, refresh_keys: bool = False, chain_timeout: float = CHAIN_TIMEOUT,
            full: bool = False, out: Path | None = None, say: Callable[[str], Any] = print, note: Callable[[str], Any] | None = None) -> int:
    """What `knos decide` does, with no command-line library in it: `knos decide` (typer) and `python -m knos.decide`
    (argparse) both call this. `say` prints the answer, `note` the lines about it (standard error). Returns the exit
    status: 0 for accepted, 1 otherwise. ValueError: the options do not name one thing to decide."""
    import sys
    note = note or (lambda words: print(words, file=sys.stderr))
    began = time.perf_counter()
    if refresh_keys:
        where = keep_keys(fetch_keys(), int(time.time()), keys_file)
        note(f"kept the issuers' key lists in {where}")
        if token_file is None and checks_file is None:
            return 0
    if (token_file is None) == (checks_file is None):
        raise ValueError("give --token-file or --checks-file, one of them")

    def write(doc: dict[str, Any]) -> None:
        if out is not None:
            out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    stages = ""
    if checks_file is not None:
        d = checks(json.loads(checks_file.read_text(encoding="utf-8")))
        doc = provisional(d, at=int(time.time()))
    else:
        assert token_file is not None
        import re
        text = token_file.read_text(encoding="utf-8")
        hit = re.search(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", text)     # the token, wherever the comment carries it
        jwt = hit.group(0) if hit else text.strip()
        terms = terms_file.read_bytes().strip() if terms_file is not None else None
        if full:
            from . import chain
            d = token(jwt, terms, ledger=chain.ledger())
            doc = provisional(d, at=int(time.time()), jwt=jwt, terms=terms)
        else:
            d = offline(jwt, terms, keys=kept_keys(keys_file))
            doc = provisional(d, at=int(time.time()), jwt=jwt, terms=terms)
            write(doc)                  # the offline answer exists before any network is touched
            stages = f" (offline {(time.perf_counter() - began) * 1000:.0f} ms"
            if not no_chain:
                from . import chain
                asked = time.perf_counter()
                d = after_chain(d, chain_check(jwt, ledger=chain.ledger(), order=order, timeout=chain_timeout), jwt)
                doc = provisional(d, at=int(time.time()), jwt=jwt, terms=terms, updates=digest(doc))
                stages += f", chain check {(time.perf_counter() - asked) * 1000:.0f} ms in 1 request" + ("" if d["chain"]["read"] else ", not answered")
            stages += ")"
    write(doc)
    say(json.dumps(doc, indent=1, sort_keys=True) if out is None else comment_line(doc))
    note(f"decided in {(time.perf_counter() - began) * 1000:.0f} ms{stages}; provisional receipt {digest(doc)}")
    return 0 if doc["decision"] == "accepted" else 1


def main(argv: list[str] | None = None) -> int:
    """`python -m knos.decide ...`: the same command with nothing else of the command line loaded. The options are read
    with argparse: no typer and no rich is imported, and the relay's rules (and solders under them) are imported only
    by the half that decides on a token. `--checks-file` and `--refresh-keys` alone import neither."""
    import argparse
    ap = argparse.ArgumentParser(prog="python -m knos.decide", description="Decide now, from the signed evidence; then ask the chain once. Prints a provisional receipt.")
    ap.add_argument("--token-file", type=Path, help="the forge's signed token (or the comment that carries it)")
    ap.add_argument("--terms-file", type=Path, help="a fund token's terms, as they travel with it")
    ap.add_argument("--checks-file", type=Path, help="the free check: JSON [{name, conclusion: passed, failed or missing}]")
    ap.add_argument("--no-chain", action="store_true", help="stop after the offline half: the signed evidence alone")
    ap.add_argument("--order", help="the order's or job's address: the chain check then says whether it is open")
    ap.add_argument("--keys-file", type=Path, help=f"the kept key lists (default: ${KEYS_ENV}, else the cache folder)")
    ap.add_argument("--refresh-keys", action="store_true", help="read the issuers' key lists now and keep them; the one step that needs a network")
    ap.add_argument("--chain-timeout", type=float, default=CHAIN_TIMEOUT, help="seconds the one chain request may take")
    ap.add_argument("--full", action="store_true", help="the relay's whole precheck instead: every read a relay makes before it sends")
    ap.add_argument("--out", type=Path, help="write the provisional receipt here (default: print it)")
    a = ap.parse_args(argv)
    try:
        return command(a.token_file, a.terms_file, a.checks_file, a.no_chain, a.order, a.keys_file, a.refresh_keys, a.chain_timeout, a.full, a.out)
    except ValueError as why:
        ap.error(str(why))


if __name__ == "__main__":
    raise SystemExit(main())
