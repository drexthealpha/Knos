"""Who a researcher is, without needing GitHub: an ORCID iD (public record) as well as a GitHub account.

    orcid("0000-0002-1825-0097")   the public ORCID record, read anonymously from pub.orcid.org/v3.0 (no token)
    github("octocat")              the public GitHub account (api.github.com/users)
    parse("orcid:0000-..." | "github:login" | "https://orcid.org/0000-...")

What this proves, and what it does not: reading a public ORCID record shows the iD EXISTS and what its owner made
public; it does not show the person in front of Knos OWNS it. Ownership is "sign in with ORCID" (OAuth, the
/authenticate scope): binding an ORCID iD to a wallet with that token belongs to the knos_pay panel test build
(BindOrcid, knos.proof.issuers). This module never signs in, so an identity read here is marked `verified` as a public
record read, not signed in.

ORCID rules (info.orcid.org/faq/what-are-the-api-limits, read 14 Oct 2026): the anonymous API allows 12 requests/s,
burst 40, and 25,000 reads a day per IP; the registered Public API (client credentials) 100,000 reads a day per client.
"""
from __future__ import annotations

import re

from . import IdeaError, now
from .http import FetchError, Fetcher

_ORCID = re.compile(r"^(\d{4})-(\d{4})-(\d{4})-(\d{3}[\dX])$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def orcid_checksum_ok(oid: str) -> bool:
    """ISO 7064 MOD 11-2, the check digit of every ORCID iD (a bare iD here)."""
    from . import orcid_ok
    return bool(_ORCID.match(oid or "")) and orcid_ok(oid)


def parse(who: str) -> tuple[str, str]:
    w = (who or "").strip()
    for p in ("https://orcid.org/", "http://orcid.org/", "orcid.org/"):
        if w.lower().startswith(p):
            w = "orcid:" + w[len(p):]
    if w.lower().startswith("orcid:"):
        oid = w[6:].strip().upper()
        if not orcid_checksum_ok(oid):
            raise IdeaError(f"{oid}: not an ORCID iD (four groups of four, last character a valid check digit)")
        return "orcid", oid
    if w.lower().startswith("github:"):
        w = w[7:]
    if _ORCID.match(w.upper()):
        return parse("orcid:" + w)
    if _LOGIN.match(w) and "--" not in w:
        return "github", w
    raise IdeaError("name a researcher as orcid:0000-0000-0000-0000 or github:login")


def orcid(oid: str, f: Fetcher | None = None) -> dict:
    kind, oid = parse("orcid:" + oid if not oid.lower().startswith("orcid") else oid)
    f = f or Fetcher()
    url = f"https://pub.orcid.org/v3.0/{oid}/person"
    got, mode = f.json(url, {"Accept": "application/json"})
    name = got.get("name") or {}
    given = ((name.get("given-names") or {}).get("value")) or ""
    family = ((name.get("family-name") or {}).get("value")) or ""
    credit = ((name.get("credit-name") or {}).get("value")) or ""
    urls = [u.get("url", {}).get("value") for u in ((got.get("researcher-urls") or {}).get("researcher-url") or []) if u.get("url")]
    ext = [{"type": e.get("external-id-type"), "value": e.get("external-id-value")}
           for e in ((got.get("external-identifiers") or {}).get("external-identifier") or [])]
    return {"kind": "orcid", "id": oid, "url": f"https://orcid.org/{oid}", "name": credit or " ".join(x for x in (given, family) if x) or None,
            "researcher_urls": urls[:10], "external_ids": ext[:10], "mode": mode, "read": now(),
            "verified": "public record read, not signed in (sign in with ORCID proves ownership)"}


def github(login: str, f: Fetcher | None = None) -> dict:
    kind, login = parse("github:" + login)
    f = f or Fetcher()
    url = f"https://api.github.com/users/{login}"
    got, mode = f.json(url, {"Accept": "application/vnd.github+json"})
    return {"kind": "github", "id": got.get("id"), "login": got.get("login"), "url": got.get("html_url"), "name": got.get("name"),
            "mode": mode, "read": now(), "verified": "public account read, not signed in"}


def who(ref: str, f: Fetcher | None = None) -> dict:
    """The identity a reference names, read from its public record; unreachable -> the reference alone, unread."""
    kind, ident = parse(ref)
    try:
        return orcid(ident, f) if kind == "orcid" else github(ident, f)
    except FetchError as e:
        return {"kind": kind, "id": ident, "mode": "unread", "error": str(e), "verified": "not read"}


def short(ident: dict) -> dict:
    """What a Claim's origin.by keeps of an identity: kind, id, url, name."""
    return {k: ident.get(k) for k in ("kind", "id", "login", "url", "name", "verified") if ident.get(k) is not None}
