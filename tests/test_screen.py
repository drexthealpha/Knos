"""Screening a payout address against the Treasury's SDN list: reading its CSV, matching, the day's cache, and what is said
when the list cannot be had (never a clean screen)."""
from __future__ import annotations

import csv
import io
import json

import pytest

from knos import screen

SOL = "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo"           # a Solana address (case matters)
ETH = "0x098B716B8Aaf21512996dC57EB0615e2383E2f96"
XBT = "12QtD5BFwRsdNsAZY76UVE1xyCGNTojH9h"
CLEAN = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"


def sdn(*rows: tuple[str, str]) -> str:
    """An SDN.CSV: twelve columns, the name and the remarks being what matter."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    for n, (name, remarks) in enumerate(rows, 36):
        w.writerow([n, name, "-0- ", "CUBA", "-0- ", "-0- ", "-0- ", "-0- ", "-0- ", "-0- ", "-0- ", remarks])
    return out.getvalue()


LIST = sdn(("ACME, S.A.", "a.k.a. 'ACME'."),
           ("LAZARUS GROUP", f"Linked To: X; Digital Currency Address - XBT {XBT}; alt. Digital Currency Address - ETH {ETH}; alt. Digital Currency Address - SOL {SOL}; Website x.example."),
           ("TRON ONE", "Digital Currency Address - USDT TJDENsfBJs4RFETt1X1W8wMDc8M5XnJhCe;"),
           ("NO REMARKS", "-0- "))


def test_the_csv_gives_every_digital_currency_address_once_whatever_its_ticker():
    got = screen.parse(LIST + LIST)
    assert got == [XBT, ETH, SOL, "TJDENsfBJs4RFETt1X1W8wMDc8M5XnJhCe"]
    assert screen.parse("") == [] and screen.parse("not,a,list\n") == [] and screen.parse(sdn(("A", "Digital Currency Address - XBT short;"))) == []
    # a quoted name with commas and newlines does not move the remarks column
    assert screen.parse(sdn(('NAME, WITH "QUOTES"\nAND A NEWLINE', f"Digital Currency Address - SOL {SOL};"))) == [SOL]


def test_listed_matches_exactly_and_a_hex_address_in_any_case():
    entries = screen.parse(LIST)
    assert screen.listed(SOL, entries) and screen.listed(f"  {SOL}\n", entries)
    assert not screen.listed(SOL.lower(), entries) and not screen.listed(CLEAN, entries)             # base58 is case-sensitive
    assert screen.listed(ETH.lower(), entries) and screen.listed(ETH.upper().replace("0X", "0x"), entries)
    assert not screen.listed("", entries) and not screen.listed(None, entries) and not screen.listed(SOL, [])
    assert not screen.listed(SOL[:-1], entries)                                                          # a prefix is not the address


def _world(tmp_path, body=LIST, now=1_790_000_000):
    asked: list[str] = []
    cache = tmp_path / "ofac.json"

    def get(url):
        asked.append(url)
        if isinstance(body, Exception):
            raise body
        return body.encode() if isinstance(body, str) else body
    return asked, cache, get, now


def test_check_refuses_a_listed_address_and_clears_one_that_is_not(tmp_path):
    asked, cache, get, now = _world(tmp_path)
    ok, why = screen.check(SOL, now=now, get=get, cache=cache)
    assert ok is False and why == (f"{SOL} is on the US Treasury's sanctions list (OFAC SDN, digital currency addresses as of 2026-09-21): "
                                   "the payout is refused and held, not sent.")
    ok, why = screen.check(CLEAN, now=now + 5, get=get, cache=cache)
    assert ok is True and why == "screened against the US Treasury's list as of 2026-09-21 (4 addresses): not listed."
    assert asked == [screen.SDN_URL]                                 # one download served both, from the cache the first one wrote
    assert json.loads(cache.read_text())["addresses"] == [XBT, ETH, SOL, "TJDENsfBJs4RFETt1X1W8wMDc8M5XnJhCe"]


def test_the_list_is_cached_for_a_day_and_asked_again_after(tmp_path):
    asked, cache, get, now = _world(tmp_path)
    assert screen.fetch(now, get, cache) == sorted([XBT, ETH, SOL, "TJDENsfBJs4RFETt1X1W8wMDc8M5XnJhCe"])
    screen.fetch(now + screen.TTL - 1, get, cache)
    assert len(asked) == 1
    screen.fetch(now + screen.TTL, get, cache)
    assert len(asked) == 2 and screen.load(now + screen.TTL + 1, get, cache).fetched == now + screen.TTL
    # a clock that went backwards does not make an old copy fresh for ever
    screen.fetch(now - 10, get, cache)
    assert len(asked) == 3


def test_with_no_network_it_says_not_screened_and_leaves_the_decision_to_the_caller(tmp_path):
    asked, cache, get, now = _world(tmp_path, body=OSError("Network is unreachable"))
    ok, why = screen.check(SOL, now=now, get=get, cache=cache)
    assert ok is None and why == "not screened: the Treasury's list could not be had (Network is unreachable) and there is no earlier copy"
    with pytest.raises(screen.Unavailable, match="there is no earlier copy"):
        screen.fetch(now, get, cache)
    assert not cache.exists()
    assert screen.check("", now=now, get=get, cache=cache) == (None, "not screened: there is no address")


def test_an_older_copy_still_screens_and_says_how_old_it_is(tmp_path):
    asked, cache, get, now = _world(tmp_path)
    screen.fetch(now, get, cache)
    down = _world(tmp_path, body=OSError("503 Service Unavailable"))[2]
    later = now + 3 * 86_400 + 60
    ok, why = screen.check(SOL, now=later, get=down, cache=cache)
    assert ok is False                                                   # a listed address is still refused on an old copy
    ok, why = screen.check(CLEAN, now=later, get=down, cache=cache)
    assert ok is True and why.endswith("not listed; the Treasury could not be asked again, so this copy is 3 days old.")


@pytest.mark.parametrize("body", ["", "<html>Access Denied</html>", sdn(("ACME", "a.k.a. 'ACME'.")), b"\xff\xfe\x00 not utf-8 at all", "ent_num,SDN_Name\n1,X\n"])
def test_a_file_that_is_not_the_list_is_never_a_clean_screen(tmp_path, body):
    asked, cache, get, now = _world(tmp_path, body=body)
    ok, why = screen.check(CLEAN, now=now, get=get, cache=cache)
    assert ok is None and why.startswith("not screened: the Treasury's list could not be had (")
    assert not cache.exists()
    # and a good copy already held is not replaced by it
    cache.write_text(json.dumps({"fetched": now - 2 * screen.TTL, "source": "x", "addresses": [SOL]}))
    ok, why = screen.check(SOL, now=now, get=get, cache=cache)
    assert ok is False and json.loads(cache.read_text())["addresses"] == [SOL]


def test_a_damaged_cache_is_asked_for_again(tmp_path):
    asked, cache, get, now = _world(tmp_path)
    for junk in ("", "not json", "[]", '{"fetched": "x", "addresses": [1]}', '{"fetched": 1, "addresses": []}'):
        cache.write_text(junk)
        assert screen.listed(SOL, screen.fetch(now, get, cache))
    assert len(asked) == 5


def test_the_real_download_reads_a_bounded_amount_and_the_url_is_the_treasurys(monkeypatch):
    assert screen.SDN_URL.startswith("https://sanctionslistservice.ofac.treas.gov/") and screen.SDN_URL.endswith("/SDN.CSV")
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        seen["url"], seen["timeout"] = req.full_url, timeout
        return Resp(b"x" * (screen.MAX_BYTES + 10))
    monkeypatch.setattr(screen.urllib.request, "urlopen", urlopen)
    with pytest.raises(ValueError, match="larger than the list can be"):
        screen._download(screen.SDN_URL)
    assert seen == {"url": screen.SDN_URL, "timeout": 120}
