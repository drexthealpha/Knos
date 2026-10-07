"""`knos decide`: the decision the moment the evidence arrives, before the chain settles.

    knos decide --token-file FILE [--terms-file FILE] [--no-chain] [--out FILE]
    knos decide --checks-file FILE [--out FILE]

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

Measured by `scripts/decide_bench.py` (docs/BENCH.md, "Decision time"); `tests/test_decide.py` holds the bounds.
"""
from __future__ import annotations

import hashlib
import json
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
    from .proof import ghrelay
    try:
        got = ghrelay.claims(jwt)
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


def provisional(d: Mapping[str, Any], *, at: int, jwt: str | None = None, terms: bytes | str | None = None, subject: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The provisional receipt of a decision `token` or `checks` gave. `at`: when it was decided (Unix seconds).
    `jwt` and `terms`: the token decided on, and what travelled with it. `subject`: for the free check, what was
    checked ({repository, commit, pull_request}; any strings and whole numbers)."""
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
        rules = {"by": RULES_TOKEN, "chain_read": bool(d.get("chain_read")), "already_on_chain": bool(d.get("already"))}
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
                no_chain: bool = typer.Option(False, "--no-chain", help="read no chain: the token alone can be rejected, never accepted"),
                out: Path = typer.Option(None, "--out", help="write the provisional receipt here (default: print it)")) -> None:
        """Decide now, from the evidence at hand, by the rules the chain will apply. Prints a provisional receipt."""
        began = time.perf_counter()
        if (token_file is None) == (checks_file is None):
            raise typer.BadParameter("give --token-file or --checks-file, one of them")
        if checks_file is not None:
            d = checks(json.loads(checks_file.read_text(encoding="utf-8")))
            doc = provisional(d, at=int(time.time()))
        else:
            from .proof import ghrelay
            text = token_file.read_text(encoding="utf-8")
            hit = ghrelay.TOKEN.search(text)
            jwt = hit.group(2) if hit else text.strip()
            terms = terms_file.read_bytes().strip() if terms_file is not None else None
            ledger = None
            if not no_chain:
                from . import chain
                ledger = chain.ledger()
            d = token(jwt, terms, ledger=ledger)
            doc = provisional(d, at=int(time.time()), jwt=jwt, terms=terms)
        text = json.dumps(doc, indent=1, sort_keys=True)
        if out is not None:
            out.write_text(text + "\n", encoding="utf-8")
        typer.echo(text if out is None else comment_line(doc))
        typer.echo(f"decided in {(time.perf_counter() - began) * 1000:.0f} ms; provisional receipt {digest(doc)}", err=True)
        raise typer.Exit(0 if doc["decision"] == "accepted" else 1)


def main(argv: list[str] | None = None) -> int:
    """`python -m knos.decide ...`: the same command with nothing else of the command line loaded."""
    import importlib
    typer = importlib.import_module("typer")
    app = typer.Typer(add_completion=False)
    register(app)
    got = app(args=argv, standalone_mode=False)
    return int(got) if isinstance(got, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
