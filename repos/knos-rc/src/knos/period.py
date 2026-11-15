"""Each party signs a month of the log: counterpart acknowledgements, and when a month is closed.

A Merkle root, or the head of a chain of hashes, says that the lines under it are the lines that were put there. It
cannot say that both sides saw the same lines, or that one side did not add a line after the other looked. So each
party signs the month itself, with an Ed25519 key the terms name (`window.period_close` of Knos Terms 3):

    acknowledgement   the buyer, or the supplier, signs the month (yyyymm), the last line of the log it read, that
                      line's hash (the head: it commits to every line before it), the month's root (SHA-256 over the
                      hashes of that month's lines up to the last one) and how many there are, the terms' hash and the
                      day. One fact a line, as a transparency log's signed note and its witnesses' cosignatures put it.
    closure           the terms may let one party close a month alone after `silence_days` without an answer: that
                      party signs a closure naming its own acknowledgement, dated that many days or more after it.

A month is CLOSED only by both acknowledgements of the same last line and root, or by a closure the terms allow. After
that, a line missing or changed in the acknowledged range (`missing-after-ack`, `changed-after-ack`) or a counted event
of that month added later (`event-after-close`) is a named discrepancy, found here and by the stand-alone verifier an
evidence archive carries (`acks/`): the rule is written once, in knos.standalone_verify, and read here.

Days are each signer's own word: no clock signs them. Keys are the ones the terms name; who holds a key is the terms'
word too. Money on devnet is test USDC.
"""
from __future__ import annotations

import json
from typing import Iterable

from . import standalone_verify as V
from .ledger import Bad, canon, month_of

ROLES, ACK_KIND, CLOSE_KIND = V.ROLES, V.ACK_KIND, V.CLOSE_KIND


def _lines(log) -> tuple[list[str], list[int], list[str]]:
    return list(log.hashes), [e.month for e in log.events], [e.kind for e in log.events]


def root(log, month: int | str, last: int | None = None) -> tuple[str, int]:
    """(root, count) of one month of `log` (knos.events.Log) up to line `last` (default: the log's last line)."""
    hashes, months, _kinds = _lines(log)
    return V.period_root(hashes, months, month_of(month), len(hashes) - 1 if last is None else last)


def _sign(key, body: dict) -> dict:
    out = {**body, "key": str(key.pubkey()), "v": 1}
    return {**out, "signature": bytes(key.sign_message(V.period_text(out))).hex()}


def acknowledge(key, log, month: int | str, role: str, terms: str, day: str, last: int | None = None) -> dict:
    """The acknowledgement `role` signs with `key` (a solders Keypair) of `month` in `log`, up to line `last` (default:
    the last line of the log). `terms`: the hash of the Knos Terms 3 document that names the keys."""
    if role not in ROLES:
        raise Bad(f"the role is buyer or supplier, not {role!r}")
    m = month_of(month)
    upto = len(log.hashes) - 1 if last is None else last
    if not 0 <= upto < len(log.hashes):
        raise Bad(f"the log has lines 0 to {len(log.hashes) - 1}; line {upto} is not one of them")
    r, n = V.period_root(log.hashes, [e.month for e in log.events], m, upto)
    got = _sign(key, {"kind": ACK_KIND, "role": role, "month": m, "last": upto, "head": log.hashes[upto], "root": r, "events": n,
                      "terms": terms, "day": day, "signature": ""})
    why = V.period_shape(got)
    if why:
        raise Bad(f"this acknowledgement cannot be made: {why}")
    return got


def close_alone(key, ack: dict, silence_days: int, day: str) -> dict:
    """The closure the party that signed `ack` signs once the terms' `silence_days` have passed without an answer."""
    if ack.get("kind") != ACK_KIND:
        raise Bad("a closure names an acknowledgement of its own")
    got = _sign(key, {**{k: ack[k] for k in ("role", "month", "last", "head", "root", "events", "terms")}, "kind": CLOSE_KIND,
                      "acknowledged": ack["day"], "silence_days": int(silence_days), "day": day, "signature": ""})
    why = V.period_shape(got)
    if why:
        raise Bad(f"this closure cannot be made: {why}")
    return got


def rules_of(terms_docs: Iterable[dict]) -> dict[str, dict | None]:
    """terms hash -> `window.period_close` of each Knos Terms 3 document."""
    from . import terms3
    return {terms3.digest(d): terms3.period_close(d) for d in terms_docs}


def check(log, records: Iterable[dict], terms_docs: Iterable[dict]) -> dict[int, dict]:
    """month -> {closed, how, at, said, problems}: every month the records name, checked against `log`."""
    hashes, months, kinds = _lines(log)
    return V.periods(hashes, months, kinds, list(records), {k: v for k, v in rules_of(terms_docs).items() if v})


def close_problems(log, month: int | str, records: Iterable[dict], terms_docs: Iterable[dict]) -> list[str]:
    """Why `month` is not closed by the parties' signatures, in words; [] when it is."""
    m = month_of(month)
    got = check(log, records, terms_docs).get(m)
    if got is None:
        return [f"Nobody has signed {m}: each party signs it (`knos events sign`), or one does and closes it after the silence the terms allow."]
    return [*got["problems"], *([] if got["closed"] else got["said"] or [f"{m} is not closed by both signatures or by a closure the terms allow."])]


def load_key(path):
    """An Ed25519 signing key from a file: the JSON list of 64 numbers solana-keygen writes."""
    from pathlib import Path

    from solders.keypair import Keypair
    try:
        return Keypair.from_bytes(bytes(json.loads(Path(path).read_text(encoding="utf-8"))))
    except (ValueError, TypeError):
        raise Bad(f"{path} is not a key: the JSON list of 64 numbers solana-keygen writes") from None


def read(texts: Iterable[str]) -> list[dict]:
    out = []
    for t in texts:
        try:
            out.append(json.loads(t))
        except ValueError:
            raise Bad("an acknowledgement file is one JSON object") from None
    return out


def dumps(record: dict) -> str:
    return canon(record) + "\n"
