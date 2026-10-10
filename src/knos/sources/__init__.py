"""Signed results from systems other than CI, read as meter lines (docs/SOURCES.md).

A source is a system that signs a statement about work: "this file was built from this commit by this workflow".
An adapter does three things, and only these:

    fetch     get the signed evidence, as bytes, from where the source publishes it (needs a network)
    verify    check the signature against the keys the source's issuer publishes, with no network, and say what the
              evidence says (an `Evidence`), or refuse (`Refused`) with the reason in plain words
    line      turn evidence that matches an order's terms into one meter line (`knos.ledger.Evaluation`)

Only a source a third party can check is accepted: one signed with a public key, the key published by its issuer
(a key list or a transparency log). A webhook signed with a shared secret (HMAC) proves something only to the one
who holds the secret, so no adapter reads one. `knos.sources.sigstore` is the one adapter today.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from .. import ledger


class Refused(ValueError):
    """The evidence is not believed. The message says why, in plain words."""


@dataclass(frozen=True)
class Evidence:
    """What a verified signature says. Every field comes from signed bytes, never from the caller."""
    source: str                 # the adapter's name, e.g. "sigstore"
    issuer: str                 # who vouched for the signer's identity (the OpenID Connect issuer in the certificate)
    signer: str                 # the identity that signed: the workflow file, at its ref
    repository: str             # the source repository, as a URL
    commit: str                 # the commit the work was built from, 40 hex characters
    subjects: tuple             # ((name, algorithm, digest in hex), ...): what was built
    run: str                    # the run that signed, as a URL
    signed_at: int              # when the log recorded it, seconds since 1970 UTC
    log: str                    # where the record is public: the log and the entry's index
    digest: str                 # sha256 of the evidence (canonical JSON of the bundle), hex: the line's `evidence`


@dataclass(frozen=True)
class Terms:
    """What the order expects of a source's evidence, and the meter line's own fields."""
    buyer: int
    seller: int
    order: str                  # 32 bytes as hex
    policy: str                 # 32 bytes as hex
    milestone: int
    rate: int
    repository: str             # the repository URL the evidence must name, e.g. https://github.com/OWNER/REPO
    workflow: str = ""          # when set, the workflow path that must have signed, e.g. .github/workflows/release.yml
    subject: str = ""           # when set, the digest (hex) of the artifact that must be among the subjects
    currency: str = ""


class Source(Protocol):
    name: str

    def fetch(self, ref: str) -> bytes: ...

    def verify(self, raw: bytes) -> Evidence: ...


def problems(ev: Evidence, terms: Terms) -> list[str]:
    """Why this evidence does not meet these terms; empty when it does."""
    out = []
    if ev.repository.rstrip("/").lower() != terms.repository.rstrip("/").lower():
        out.append(f"the evidence is about {ev.repository}, not {terms.repository}")
    if terms.workflow and f"/{terms.workflow.strip('/')}@" not in ev.signer:
        out.append(f"the signer is {ev.signer}, not the workflow {terms.workflow}")
    if terms.subject and terms.subject.lower() not in {d for _n, _a, d in ev.subjects}:
        out.append(f"no built artifact has the digest {terms.subject}")
    return out


def line(ev: Evidence, terms: Terms) -> ledger.Evaluation:
    """One accepted meter line for evidence that meets the terms. The artifact is the commit the signed record names;
    the evaluator is the adapter; the run is the run that signed; `evidence` is the bundle's sha256."""
    why = problems(ev, terms)
    if why:
        raise Refused("; ".join(why))
    return ledger.Evaluation(terms.buyer, terms.seller, terms.order, ev.commit, terms.policy, terms.milestone, True, terms.rate,
                             verdict="accepted", evaluator=f"{ev.source}@1", run=ev.run[:200], currency=terms.currency,
                             evidence=ev.digest)


def describe(ev: Evidence) -> str:
    return json.dumps({k: (list(map(list, v)) if k == "subjects" else v) for k, v in ev.__dict__.items()}, indent=2)


def adapter(name: str) -> Source:
    if name == "sigstore":
        from . import sigstore
        return sigstore.Sigstore()
    raise Refused(f"no adapter is named {name!r}; the one adapter is sigstore")
