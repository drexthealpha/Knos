"""Screening a payout address against the US Treasury's sanctions list, before the money moves.

A payment to an address on the OFAC Specially Designated Nationals (SDN) list is refused and held, never sent. The list
is the Treasury's own file, and the digital currency addresses are in it:

    file     SDN.CSV, the Specially Designated Nationals list as comma-separated values
    url      https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV  (SDN_URL below). The older
             https://www.treasury.gov/ofac/downloads/sdn.csv answers with a redirect to it.
    page     https://ofac.treasury.gov/specially-designated-nationals-list-sdn-list  (the same data as SDN_ADVANCED.XML,
             https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN_ADVANCED.XML, where an address is
             a "Digital Currency Address - <ticker>" feature)
    format   twelve columns: ent_num, SDN_Name, SDN_Type, Program, Title, Call_Sign, Vess_type, Tonnage, GRT, Vess_flag,
             Vess_owner, Remarks. An address is in the Remarks column as `Digital Currency Address - <ticker> <address>;`,
             and a further one of the same entry as `alt. Digital Currency Address - <ticker> <address>;`. Tickers are
             XBT, ETH, TRX, USDC, USDT, SOL and others; USDC and USDT name no chain, so every address is kept whatever its
             ticker, and an address is matched exactly (a Solana address is case-sensitive; a 0x address is not).
    size     about 6 MB, updated whenever the Treasury changes the list

`fetch()` gives the addresses, cached for a day in ~/.knos (KNOS_HOME); `listed(address, entries)` says whether one is
there; `check(address)` is what a payout asks. A file that holds no digital currency address at all is not read as an
empty list: a changed format must never look like a clean screen.

    check(address) -> (ok, reason)    True: screened, not listed. False: listed: refuse and hold the payout.
                                      None: not screened (no network and no copy of the list, or a list that could not be
                                      read): the reason starts "not screened", and the caller decides what that means
                                      for its payout.
"""

from __future__ import annotations

import csv
import io
import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"
TTL = 86_400                    # a copy of the list is good for a day
MAX_BYTES = 50_000_000          # the file is about 6 MB; more than this is not the file
REMARKS = 11                    # the column of SDN.CSV that holds the remarks
_ADDRESS = re.compile(r"Digital Currency Address - ([A-Za-z0-9]{2,10})\s+([A-Za-z0-9]{20,120})")


class Unavailable(Exception):
    """The list could not be had or read. Its text says why, in words that follow "not screened: "."""


@dataclass(frozen=True)
class Listing:
    addresses: frozenset[str]
    fetched: int                # unix time the copy was made
    stale: bool = False         # it is older than a day: the Treasury could not be asked again
    source: str = SDN_URL


def parse(text: str) -> list[str]:
    """The digital currency addresses of an SDN.CSV, in the order they appear, each once."""
    seen: dict[str, None] = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) > REMARKS:
            for _ticker, address in _ADDRESS.findall(row[REMARKS]):
                seen.setdefault(address, None)
    return list(seen)


def _norm(address: str) -> str:
    """An address as it is compared: a 0x address (hex, any case) lowered; anything else, such as base58, as it is."""
    address = address.strip()
    return address.lower() if re.fullmatch(r"0[xX][0-9a-fA-F]{40,}", address) else address


def listed(address: str, entries) -> bool:
    """Whether `address` is one of `entries` (addresses, as `fetch` gives them)."""
    if not isinstance(address, str) or not address.strip():
        return False
    wanted = _norm(address)
    return any(_norm(str(e)) == wanted for e in entries)


def _download(url: str, timeout: float = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "knos", "Accept": "text/csv"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - a fixed https URL of the Treasury
        got = resp.read(MAX_BYTES + 1)
    if len(got) > MAX_BYTES:
        raise ValueError("the file is larger than the list can be")
    return got


def _cache() -> Path:
    from . import paths
    return paths.home() / "ofac-sdn.json"


def _read(path: Path) -> tuple[list[str], int] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if doc.get("addresses") and isinstance(doc["addresses"], list) and isinstance(doc.get("fetched"), int):
            return [str(a) for a in doc["addresses"]], doc["fetched"]
    except (OSError, ValueError, AttributeError):
        pass
    return None


def load(now: float | None = None, get=None, cache: Path | None = None, ttl: int = TTL) -> Listing:
    """The list: from the cache when it is under a day old, else from the Treasury (and cached). When the Treasury cannot
    be asked or its file cannot be read, an older copy is used and marked stale; with none, Unavailable."""
    now = int(time.time() if now is None else now)
    path = cache or _cache()
    have = _read(path)
    if have and 0 <= now - have[1] < ttl:
        return Listing(frozenset(have[0]), have[1])
    try:
        raw = (get or _download)(SDN_URL)
        text = raw.decode("utf-8-sig", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        found = parse(text)
        if not found:
            raise ValueError("it holds no digital currency address at all, so its format may have changed")
    except Exception as why:  # noqa: BLE001 - no network, a refusal, or a file that is not the list
        if have:
            return Listing(frozenset(have[0]), have[1], stale=True)
        words = " ".join(str(why).split())[:160].rstrip(".") or type(why).__name__
        raise Unavailable(f"the Treasury's list could not be had ({words}) and there is no earlier copy") from None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched": now, "source": SDN_URL, "addresses": found}), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass                    # a copy that cannot be kept is still a copy that was read
    return Listing(frozenset(found), now)


def fetch(now: float | None = None, get=None, cache: Path | None = None) -> list[str]:
    """The Treasury's digital currency addresses (every ticker), cached for a day. Raises Unavailable."""
    return sorted(load(now, get, cache).addresses)


def _day(t: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def check(address: str, now: float | None = None, get=None, cache: Path | None = None) -> tuple[bool | None, str]:
    """May a payout go to this address? (True, why): screened and not listed. (False, why): listed, so refuse and hold it.
    (None, "not screened: ..."): the list could not be had; the caller decides."""
    if not isinstance(address, str) or not address.strip():
        return None, "not screened: there is no address"
    try:
        got = load(now, get, cache)
    except Unavailable as why:
        return None, f"not screened: {why}"
    when = _day(got.fetched)
    if listed(address, got.addresses):
        return False, (f"{address} is on the US Treasury's sanctions list (OFAC SDN, digital currency addresses as of {when}): "
                       "the payout is refused and held, not sent.")
    old = f"; the Treasury could not be asked again, so this copy is {max(0, int((time.time() if now is None else now) - got.fetched) // 86_400)} days old" if got.stale else ""
    return True, f"screened against the US Treasury's list as of {when} ({len(got.addresses)} addresses): not listed{old}."
