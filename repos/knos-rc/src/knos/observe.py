"""What an outside observer can infer about a work order: `knos observe`.

Hiding a repository's name is not privacy when the counterparties, the amounts and the timing are public. This module
plays the outsider and nothing more: it reads ONLY what anyone can read with no account and no permission,

    the chain    the transactions that named an order, its Balance or wallet, and the token accounts its instructions
                 took: their log lines (records.events_of), their instruction data (a token GitHub signed is written to
                 knos_oidc whole, and stays in that data after the account is closed) and the order's account while it
                 is open;
    GitHub       the public API, with no credential: `repositories/<id>` and `user/<id>` turn an id into a name
                 (a private repository answers 404). Skipped with `--offline`.

and says, fact by fact, whether the outsider learns it ("yes"), learns only a hash of it ("only a hash") or does not
("no"), and from which account field or log line. `order_facts` is the table of one order; `graph` is what the whole
history says of one GitHub id: who it pays, who pays it, how much and how often.

A source of chain data is anything with `transactions(address, limit)` (the successful transactions that named the
address, oldest first, as `getTransaction` gives them with encoding "json"), `transaction(signature)` and
`account(address)`: `Rpc` asks a cluster, `Recorded` holds transactions a test recorded. The tables in docs/reference/PRIVACY.md
are written by `python -m knos.observe --render-doc` from tests/data/observe.json, which tests/test_observe.py records
from the programs' test builds and holds to them.

Nothing here is a privacy guarantee: it is a list of what was found, and a careful outsider may find more."""

from __future__ import annotations

import base64
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

from . import chain, records
from .bundle import _ixs, _unb58
from .settle.v2 import oidc
from .settle.v2 import pay as pay2

YES, HASH, NO = "yes", "only a hash", "no"
PAY, OIDC = str(pay2.PAY_ID), str(oidc.OIDC_ID)
ROOT = Path(__file__).resolve().parents[2]
FIXTURE, DOC = ROOT / "tests" / "data" / "observe.json", ROOT / "docs" / "reference" / "PRIVACY.md"
_ACCOUNT = "the order's account, while the order is open"
RECENT = 200           # how many of an address's newest transactions are read: an order has a handful, a busy Balance more
SIBLINGS = 50          # how many of a source's newest orders are read for what they paid: each is one more request


# ---- where public chain data comes from -------------------------------------------------------------------------------
def sig_of(tx: dict) -> str:
    return str((tx.get("transaction") or {}).get("signatures", [""])[0])


def keys_of(tx: dict) -> list[str]:
    message, loaded = tx["transaction"]["message"], (tx.get("meta") or {}).get("loadedAddresses") or {}
    return [k if isinstance(k, str) else k.get("pubkey") for k in message["accountKeys"]] + list(loaded.get("writable") or []) + list(loaded.get("readonly") or [])


class Recorded:
    """Transactions and accounts someone recorded: {"txs": [...], "accounts": {address: hex}}."""

    def __init__(self, txs: list[dict], accounts: dict[str, str] | None = None):
        self.txs, self.accounts, self.unread = list(txs), dict(accounts or {}), 0

    def transactions(self, address: str, limit: int = 1000) -> list[dict]:
        return [tx for tx in self.txs if address in keys_of(tx)][-limit:]

    def transaction(self, sig: str) -> dict | None:
        return next((tx for tx in self.txs if sig_of(tx) == sig), None)

    def account(self, address: str) -> bytes | None:
        return bytes.fromhex(self.accounts[address]) if address in self.accounts else None


class Rpc:
    """A cluster's public RPC endpoint. `unread` counts the transactions it would not give (throttled): never guessed."""

    def __init__(self, url: str):
        self.url, self.unread = url, 0
        self._seen: dict[str, dict | None] = {}

    def transaction(self, sig: str) -> dict | None:
        if sig not in self._seen:
            try:
                self._seen[sig] = chain.call(self.url, "getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                                                               "maxSupportedTransactionVersion": 1}], timeout=30)
            except Exception:  # noqa: BLE001 - still throttled after the backoff, or not a signature: counted, never guessed
                self.unread += 1
                return None
        tx = self._seen[sig]
        return tx if tx and (tx.get("meta") or {}).get("err") is None else None

    def transactions(self, address: str, limit: int = 1000) -> list[dict]:
        got = chain.call(self.url, "getSignaturesForAddress", [address, {"limit": min(limit, 1000)}], timeout=30) or []
        txs = [self.transaction(s["signature"]) for s in reversed(got) if s.get("err") is None]
        return [tx for tx in txs if tx]

    def account(self, address: str) -> bytes | None:
        got = chain.call(self.url, "getAccountInfo", [address, {"encoding": "base64", "commitment": "confirmed"}], timeout=30)
        value = (got or {}).get("value")
        return base64.b64decode(value["data"][0]) if value else None


def public_github(path: str) -> dict:
    """GitHub's public API with NO credential, whatever the environment holds: what a stranger is answered."""
    req = urllib.request.Request(f"https://api.github.com/{path}", headers={"Accept": "application/vnd.github+json", "User-Agent": "knos"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 - api.github.com
        return json.loads(resp.read())


def events_in(txs: list[dict]) -> list[dict]:
    """The Knos programs' log lines in these transactions, oldest first, each with its transaction."""
    seen, out = set(), []
    for tx in txs:
        if sig_of(tx) not in seen:
            seen.add(sig_of(tx))
            out += [{**ev, "tx": sig_of(tx)} for ev in records.events_of(tx)]
    return sorted(out, key=lambda ev: ev["at"])


def token_claims(src, account: str) -> dict | None:
    """The claims of the token that was written to the knos_oidc account `account`, put together from the instruction
    data of the transactions that wrote it. None when they are not there (or it is no token account)."""
    bufs: dict[bytes, dict[int, bytes]] = {}      # a token's id -> its pieces: an account that is no token account sees several
    total = 0
    for tx in src.transactions(account, 200):
        for data, keys in _ixs(tx, OIDC):
            if data[:1] == b"\x00" and len(data) > 37 and account in keys:
                total = int.from_bytes(data[33:35], "little")
                bufs.setdefault(data[1:33], {})[int.from_bytes(data[35:37], "little")] = data[37:]
    if len(bufs) != 1:
        return None
    [buf] = bufs.values()
    raw = b"".join(buf[off] for off in sorted(buf))
    if not raw or len(raw) != total or raw.count(b".") != 2:
        return None
    try:
        body = raw.split(b".")[1]
        got = json.loads(base64.urlsafe_b64decode(body + b"=" * (-len(body) % 4)))
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def tokens_of(src, txs: list[dict], order: str) -> dict[str, dict]:
    """{fund, pay, take: the claims GitHub signed} for the tokens the order's own instructions took."""
    out: dict[str, dict] = {}
    for tx in txs:
        for data, keys in _ixs(tx, PAY):
            at = pay2.TOKEN_AT.get(data[0]) if data else None
            if at is None or len(keys) <= at or order not in keys:
                continue
            claims = token_claims(src, keys[at])
            kind = str((claims or {}).get("aud", "")).split(":")[1:2]
            if claims and kind:
                out.setdefault({"auto": "pay"}.get(kind[0], kind[0]), claims)
    return out


# ---- one order ------------------------------------------------------------------------------------------------------------
def _when(t) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(int(t))) if t else ""


def _span(seconds: int) -> str:
    d, rest = divmod(max(int(seconds), 0), 86_400)
    return (f"{d} d " if d else "") + f"{rest // 3600} h {rest % 3600 // 60:02d} min"


def _row(fact: str, clear=(), hashed=(), absent: str = "") -> dict:
    """One line of the table. `clear`: (value, where) for each public place that holds the fact itself; `hashed`: the
    same for places that hold only a hash of it; `absent`: why it is in neither (shown as where)."""
    for learns, found in ((YES, clear), (HASH, hashed)):
        found = [(str(v), w) for v, w in found if v not in (None, "", 0, "0")]
        if found:
            return {"fact": fact, "learns": learns, "value": found[0][0], "where": "; ".join(dict.fromkeys(w for _v, w in found))}
    return {"fact": fact, "learns": NO, "value": "", "where": absent or "nowhere in what the programs wrote"}


def _name(names, kind: str, number) -> tuple[str, str]:
    """(the name GitHub gives for an id, where from). Offline the lookup is named and not made."""
    if not number:
        return "", ""
    path = f"repositories/{number}" if kind == "repo" else f"user/{number}"
    if names is None:
        return "not looked up (--offline)", f"GitHub's public API, `{path}`: an id is a public number, and this turns it into a name"
    got = str(names.repo(number).get("full_name", "")) if kind == "repo" else names.user(number)
    return got or "(GitHub's public API gives no name: private, or gone)", f"GitHub's public API, `{path}`"


def _find(src, target: str) -> tuple[str, list[dict]]:
    """(the order's address, the transactions that named it) for an order's address or one of its transactions."""
    try:
        size = len(_unb58(target))
    except ValueError:
        size = 0
    if size == 32:
        return target, src.transactions(target, RECENT)
    tx = src.transaction(target) if size == 64 else None
    order = next((str(ev["order"]) for ev in (records.events_of(tx) if tx else []) if ev["event"].startswith("order_") and ev.get("order")), "")
    return order, src.transactions(order, RECENT) if order else []


def _bounty(src, target: str, txs: list[dict]) -> dict | None:
    """The first line of an issue's bounty (a job: knos2:funded, paid, ...) in `txs`, or in the transaction `target`
    names; None when there is none. A bounty is not a work order, and is not to be called nothing."""
    if not txs:
        try:
            txs = [tx for tx in [src.transaction(target)] if tx] if len(_unb58(target)) == 64 else []
        except ValueError:
            txs = []
    return next((ev for ev in events_in(txs) if ev["event"] in records.JOB_EVENTS and "repo" in ev), None)


def _about(events: list[dict], address: str) -> list[dict]:
    """The events of one order: the lines that name it, and the terms line that follows its funding (which names none)."""
    out: list[dict] = []
    for ev in events:
        if str(ev.get("order", "")) == address or (ev["event"] == "order_terms" and out and out[-1]["event"] == "order_funded" and out[-1]["tx"] == ev["tx"]):
            out.append(ev)
    return out


def order_facts(src, target: str, names=None) -> dict:
    """What an outsider learns of one work order: {"order", "private", "rows": [{fact, learns, value, where}],
    "still_public": the facts learned in full, "unread"}. `target`: the order's address or a transaction of it.
    `names`: records.Names over the PUBLIC API, or None (offline). Raises LookupError when no order is found."""
    address, txs = _find(src, target)
    mine = _about(events_in(txs), address)
    orders, _ = records.orders_of(mine)
    if not orders:
        bounty = _bounty(src, target, txs)
        if bounty is not None:
            raise LookupError(f"{target} is an issue's bounty (repository id {bounty['repo']}, issue {bounty['issue']}), not a work order, and this "
                              f"table covers work orders only. To see its payments, run: knos observe --graph <the funder's GitHub id>")
        raise LookupError(f"No work order was found for {target}: the Knos programs logged nothing about it in the transactions this cluster gave.")
    o = orders[-1]                    # an address is used again once its order is closed: the newest one
    private, source = o["private"], o["source"]
    beside = src.transactions(source, RECENT) if source else []
    known = records._balances(events_in(beside)).get(source) or {}
    # the source's own history names every order it funded; what each paid is in that order's own transactions
    others = list(dict.fromkeys(str(ev["order"]) for ev in events_in(beside) if ev["event"] == "order_funded" and str(ev.get("source", "")) == source))[-SIBLINGS:]
    siblings = [s for s in records.orders_of(events_in(beside + [tx for other in others for tx in src.transactions(other, RECENT)]))[0] if s["source"] == source]
    acct = pay2.read_order(src.account(address))
    tok = tokens_of(src, txs, address)
    fund, paid, take = tok.get("fund", {}), tok.get("pay", {}), tok.get("take", {})
    fund_ix = next((data for tx in txs if sig_of(tx) == o["tx"] for data, _k in _ixs(tx, PAY) if data[:1] == b"\x10"), b"")
    aud = str(paid.get("aud", "")).split(":")                  # knos3:pay:<order>:<head>:<terms hash>:<mode>:<pr>:<payees>
    try:
        terms = json.loads(o["terms"]) if o["terms"] else None
    except ValueError:
        terms = None
    pays = [p for p in o["payments"] if p["kind"] in ("paid", "released")]
    first = pays[0] if pays else {}
    owner = known.get("owner") or (acct.owner_id if acct else 0) or (int(fund.get("repository_owner_id") or 0))
    repo_owner = names.repo(o["repo"]).get("owner", {}) if names is not None and o["repo"] else {}
    judge = (acct.judge_repo_id if acct else 0) or (int(paid.get("repository_id") or 0) if private else 0)
    line = lambda field, event="funded": f"`{field}=` of the `knos3:{event}` log line"  # noqa: E731
    claim = lambda field, which: f"`{field}` in the {which} token GitHub signed (knos_oidc instruction data)"  # noqa: E731
    window = [(text, where) for text, where in (
        (o.get("paid_at") and f"{_span(o['paid_at'] - o['at'])} from funding to payment", "the two block times"),
        (o.get("deadline") and f"open for work until {_when(o['deadline'])}", line("deadline")),
        (o.get("warranty_until") and f"a part held back until {_when(o['warranty_until'])}", "`until=` of the `knos3:warranty` log line"),
        (o.get("held_until") and f"held for its payee until {_when(o['held_until'])}", "`until=` of the `knos3:held` log line")) if text]
    reserved = [(o.get("reserved_by") and f"GitHub id {o['reserved_by']}, until {_when(o.get('reserved_until'))}", line("taker", "reserved")),
                (acct and acct.reserved_by and f"GitHub id {acct.reserved_by}", f"bytes 128..136 of {_ACCOUNT}"), (take.get("actor"), claim("actor", "reserving"))]
    rows = [
        _row("buyer organisation: GitHub id", [(known.get("owner"), "`owner=` of the Balance's `knos2:balance` log line"),
                                               (acct and acct.owner_id, f"bytes 168..176 of {_ACCOUNT}"),
                                               (fund.get("repository_owner_id"), claim("repository_owner_id", "funding")),
                                               (repo_owner.get("id"), "GitHub's public API, the repository's owner")],
             absent="a wallet funded it, and no Balance names an organisation: the wallet below is what is public"),
        _row("buyer organisation: name", [(fund.get("repository_owner"), claim("repository_owner", "funding")),
                                          (repo_owner.get("login"), "GitHub's public API, the repository's owner"),
                                          _name(names, "user", owner)], absent="no organisation id is public (see the line above)"),
        _row("who gave the funding command", [(o["by"], line("by")), (fund.get("actor"), claim("actor", "funding"))],
             absent="a wallet funded it: no GitHub account signed"),
        _row("where the money came from (a Balance or a wallet)", [(source, line("source"))]),
        _row("repository: id", [(o["repo"], line("repo"))],
             [(acct and private and acct.scope.hex(), f"bytes 24..56 of {_ACCOUNT}: sha256(salt, repository id, issue); the salt is not on chain"),
              (private and len(fund_ix) == 65 and fund_ix[1:33].hex(), "the funding instruction's data: the same salted hash")]),
        _row("repository: name", [(not private and fund.get("repository"), claim("repository", "funding")),
                                  (not private and paid.get("repository"), claim("repository", "pay")), _name(names, "repo", o["repo"])],
             absent="no id to look up, and no token names it: the tokens are the attestor repository's"),
        _row("issue", [(o["issue"], line("issue"))], [(private and len(fund_ix) == 65 and fund_ix[1:33].hex(), "the same salted hash as the repository")]),
        _row("pull request", [(not private and first.get("pr"), line("pr", "paid"))],
             [(private and first.get("pr"), line("pr", "paid") + ": a number made from the salt and the pull request's, not the number itself")],
             absent="nothing was paid yet"),
        _row("branch", [(not private and paid.get("ref"), claim("ref", "pay")), (not private and fund.get("ref"), claim("ref", "funding"))],
             absent="the tokens name the attestor repository's branch, never the private repository's" if private else "no token of this order was found"),
        _row("supplier (payee): GitHub id", [(first.get("payee"), line("payee", "paid")), (o.get("held_until") and o.get("payee"), line("payee", "held"))], absent="nothing was paid yet"),
        _row("supplier (payee): name", [_name(names, "user", first.get("payee") or o.get("payee"))], absent="nothing was paid yet"),
        _row("supplier (payee): wallet", [(first.get("to"), line("to", "paid"))], absent="nothing was paid yet"),
        _row("amount", [(records.units_text(o["amount"]), line("amount")), (acct and records.units_text(acct.amount), f"bytes 64..72 of {_ACCOUNT}")]),
        _row("fee", [(f"{records.units_text(o['fee_escrowed'])} on top, paid by the funder", line("fee")),
                     (o["fee"] and f"{records.units_text(o['fee'])} taken at payment", "`fee=` and `tip=` of the `knos3:settled` log line")]),
        _row("mint (which money)", [(known.get("mint"), "`mint=` of the Balance's `knos2:balance` log line"), (acct and str(acct.mint), f"bytes 288..320 of {_ACCOUNT}")],
             absent="the accounts of the funding transaction (the mint is one of them); no log line names it for a wallet's order"),
        _row("funding time", [(_when(o["at"]), "the block time of the funding transaction")]),
        _row("acceptance time", [(_when(o.get("paid_at")), "the block time of the paying transaction")], absent="nothing was paid yet"),
        _row("review window", [("; ".join(text for text, _w in window), "; ".join(w for _t, w in window))]),
        _row("checks named in the terms", [(terms is not None and (", ".join(str(c.get("name")) for c in terms.get("checks") or []) or "(none named)"),
                                            "`checks` in the `knos3:terms` log line")],
             [(acct and acct.terms.hex(), f"bytes 320..352 of {_ACCOUNT}: the hash of the terms"), (len(aud) > 4 and aud[4], "the terms hash in the pay token's audience"),
              (private and len(fund_ix) == 65 and fund_ix[33:65].hex(), "the funding instruction's data: the hash of the terms")]),
        _row("allowed paths", [(terms is not None and (", ".join(map(str, terms.get("paths") or [])) or "(none named: any path)"), "`paths` in the `knos3:terms` log line")],
             [(acct and acct.terms.hex(), "the same hash of the terms"), (len(aud) > 4 and aud[4], "the same hash of the terms")]),
        _row("terms text", [(o["terms"], "the `knos3:terms` log line, whole")], [(acct and acct.terms.hex(), "the same hash of the terms"), (len(aud) > 4 and aud[4], "the same hash of the terms")]),
        _row("workflow commit", [(acct and acct.wf_sha.strip("\0"), f"bytes 384..424 of {_ACCOUNT}"), (paid.get("job_workflow_sha"), claim("job_workflow_sha", "pay")),
                                 (fund.get("job_workflow_sha"), claim("job_workflow_sha", "funding"))]),
        _row("accepted commit", [(len(aud) > 3 and aud[3], "the head commit in the pay token's audience" + (": it says nothing without the repository, and confirms a guess" if private else ""))],
             absent="nothing was paid yet, or the pay token's transactions were not found"),
        _row("whether a reservation named someone", reserved if any(v for v, _w in reserved) else [("none was made", "no `knos3:reserved` log line names this order")]),
        _row("judge (attestor) repository", [(paid.get("repository") and f"{paid['repository']} (id {paid.get('repository_id')})", claim("repository", "pay")),
                                             (judge and f"id {judge}", f"bytes 184..192 of {_ACCOUNT}" if acct and acct.judge_repo_id else claim("repository_id", "pay")),
                                             (not private and o["repo"] and "the order's own repository", "`judge=` of the `knos3:settled` log line")]),
        _row("who started the run that judged it", [(paid.get("actor") and f"{paid['actor']} (id {paid.get('actor_id')})", claim("actor", "pay"))],
             absent="nothing was paid yet, or the pay token's transactions were not found"),
        _row("other orders of the same Balance or wallet", [(f"{len(siblings)} in all, {records.units_text(sum(s['amount'] for s in siblings))} funded", line("source") + ", the same on each")]),
        _row("order sizes with this supplier", [(_sizes(siblings, first.get("payee")), "`amount=` and `payee=` across those orders: repeated sizes mark a standing relationship")],
             absent="nothing was paid yet"),
    ]
    return {"order": address, "private": private, "state": o["state"], "rows": rows, "still_public": [r["fact"] for r in rows if r["learns"] == YES],
            "unread": getattr(src, "unread", 0)}


def _sizes(orders: list[dict], payee) -> str:
    got = [p["amount"] for s in orders for p in s["payments"] if payee and p["payee"] == payee and p["kind"] in ("paid", "released")]
    return f"{len(got)} payment{'' if len(got) == 1 else 's'}: " + ", ".join(records.units_text(a) for a in got) if got else ""


# ---- the whole history of one id --------------------------------------------------------------------------------------
def _cadence(times: list[int]) -> dict:
    gaps = [b - a for a, b in zip(times, times[1:])]
    return {"first": _when(times[0]), "last": _when(times[-1]), "payments": len(times),
            "median_days_between": round(statistics.median(gaps) / 86_400, 2) if gaps else None}


def _owner(o: dict) -> int:
    """The GitHub id whose money an order or a bounty is: its Balance's owner, or the commenter who funded it from a
    Balance the history read does not show opened (the devnet faucet's, opened long before)."""
    return int(o["owner"] or (o.get("by") or 0 if o.get("from_balance", True) else 0))


def _payments(o: dict) -> list[dict]:
    """An order's payments; a bounty's one payment, once it is paid, in the same shape."""
    if "payments" in o:
        return o["payments"]
    return [{"payee": o["payee"], "amount": o["net"], "to": o.get("to", ""), "at": o["paid_at"], "kind": "paid"}] if o["state"] == "paid" else []


def graph(events: list[dict], owner_id: int, names=None) -> dict:
    """The commercial relationships of one GitHub id, from the escrow's log alone: {"owner", "name", "orders",
    "bounties" (issues' bounties, paid as an order is), "private_orders", "funded", "pays": [...], "paid_by": [...]}. `pays`: each supplier a Balance of this id paid
    ({id, name, wallets, orders, paid, sizes, first, last, payments, median_days_between}); `paid_by`: each funder that
    paid this id. A private order is in it like any other: its line names the payee, the amount and the time."""
    work, _ = records.work_of(events)     # work orders (knos3) and issues' bounties (knos2): a bounty is paid as an order is
    sides: dict[str, dict] = {"pays": {}, "paid_by": {}}
    for o in work:
        for p in _payments(o):
            if p["kind"] not in ("paid", "released", "kill") or not p["payee"]:
                continue
            for side, who, here in (("pays", p["payee"], _owner(o) == owner_id), ("paid_by", o["funder"], p["payee"] == owner_id)):
                if here:
                    c = sides[side].setdefault(who, {"orders": set(), "wallets": set(), "units": 0, "sizes": [], "times": [], "private": 0})
                    c["orders"].add((o["address"], o["tx"]))
                    c["wallets"] |= {p["to"]} if p["to"] else set()
                    c["units"] += p["amount"]
                    c["sizes"].append(p["amount"])
                    c["times"].append(p["at"])
                    c["private"] += o.get("private", False)
    def told(who, c: dict) -> dict:
        number = who if isinstance(who, int) else int(who[3:]) if str(who).startswith("gh:") else 0
        return {"id": who, "name": names.user(number) if names is not None and number else "", "wallets": sorted(c["wallets"]), "orders": len(c["orders"]),
                "paid": records.units_text(c["units"]), "paid_units": c["units"], "sizes": [records.units_text(a) for a in c["sizes"]],
                "payments_of_private_orders": c["private"], **_cadence(sorted(c["times"]))}
    mine = [o for o in work if _owner(o) == owner_id]
    orders = [o for o in mine if "payments" in o]
    return {"owner": owner_id, "name": names.user(owner_id) if names is not None else "", "orders": len(orders), "bounties": len(mine) - len(orders),
            "private_orders": sum(o["private"] for o in orders),
            "funded": records.units_text(sum(o["amount"] for o in mine)), "sources": sorted({o["source"] for o in mine}),
            **{side: sorted((told(who, c) for who, c in got.items()), key=lambda r: -r["paid_units"]) for side, got in sides.items()}}


# ---- as text ------------------------------------------------------------------------------------------------------------
def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def table_md(facts: dict, values: bool = True) -> str:
    head = ["fact", "does an outsider learn it?", *(["what they read"] if values else []), "from where"]
    rows = [[r["fact"], r["learns"], *([f"`{r['value']}`" if r["value"] else ""] if values else []), r["where"]] for r in facts["rows"]]
    return "\n".join("| " + " | ".join(_cell(c) for c in row) + " |" for row in [head, ["---"] * len(head), *rows])


def graph_md(g: dict) -> str:
    head = ["direction", "counterparty (GitHub id)", "wallets paid", "orders", "total", "sizes", "first payment", "last payment", "median days between"]
    rows = [[word, c["id"], ", ".join(f"`{w}`" for w in c["wallets"]), c["orders"], c["paid"], ", ".join(c["sizes"]), c["first"], c["last"],
             "" if c["median_days_between"] is None else c["median_days_between"]] for side, word in (("pays", "pays"), ("paid_by", "is paid by")) for c in g[side]]
    return "\n".join("| " + " | ".join(_cell(c) for c in row) + " |" for row in [head, ["---"] * len(head), *rows])


def table_text(facts: dict) -> list[str]:
    wide = max(len(r["fact"]) for r in facts["rows"])
    out = [f"Work order {facts['order']} ({'private' if facts['private'] else 'public'}, {facts['state']}): what anyone can read, with no account and no permission."]
    for r in facts["rows"]:
        out += [f"{r['fact']:<{wide}}  {r['learns']:<11}  {r['value']}", f"{'':<{wide}}  {'':<11}  from: {r['where']}"]
    if facts["private"]:
        out.append("A private order hides its repository, issue and terms. It still shows: " + "; ".join(facts["still_public"]) + ".")
    if facts.get("unread"):
        out.append(f"{facts['unread']} transactions could not be read (the public RPC throttled): a line that says `no` may be one of them.")
    return out + ["This is what was found, not a guarantee that nothing else can be."]


def graph_text(g: dict) -> list[str]:
    out = [f"GitHub id {g['owner']}{' (' + g['name'] + ')' if g['name'] else ''}: {g['orders']} work orders "
           + (f"and {g['bounties']} {'bounty on an issue' if g['bounties'] == 1 else 'bounties on issues'} " if g.get("bounties") else "")
           + f"funded from its Balances ({g['private_orders']} private), {g['funded']} in all."]
    for side, word in (("pays", "It pays"), ("paid_by", "It is paid by")):
        for c in g[side]:
            every = "" if c["median_days_between"] is None else f", a payment every {c['median_days_between']} days (median)"
            out.append(f"{word} {c['id']}{' (' + c['name'] + ')' if c['name'] else ''}: {c['paid']} in {c['payments']} payments on {c['orders']} orders "
                       f"({', '.join(c['sizes'])}), {c['first']} to {c['last']}{every}; wallets: {', '.join(c['wallets']) or 'not named in the log'}.")
    if not g["pays"] and not g["paid_by"]:
        out.append("The escrow's history that was read shows no payment from or to this id.")
    return out + ["An outsider reads this from the escrow's log lines alone. Private orders are in it: their lines name the payee, the amount and the time."]


# ---- docs/reference/PRIVACY.md ----------------------------------------------------------------------------------------------------
def doc_blocks(fixture: dict) -> dict[str, str]:
    """The text between each pair of `<!-- observe:NAME -->` marks of docs/reference/PRIVACY.md, from the recorded fixture."""
    src = Recorded(fixture["txs"], fixture["accounts"])
    return {"public": table_md(order_facts(src, fixture["public"])), "private": table_md(order_facts(src, fixture["private"])),
            "graph": graph_md(graph(events_in(fixture["txs"]), fixture["owner"]))}


def render_doc(text: str, fixture: dict) -> str:
    for name, block in doc_blocks(fixture).items():
        a, b = f"<!-- observe:{name} -->", f"<!-- /observe:{name} -->"
        if a not in text or b not in text:
            raise ValueError(f"docs/reference/PRIVACY.md has no {a} ... {b} marks")
        text = text[:text.index(a) + len(a)] + "\n" + block + "\n" + text[text.index(b):]
    return text


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] != ["--render-doc"]:
        print("python -m knos.observe --render-doc [--check]: write the tables of docs/reference/PRIVACY.md from tests/data/observe.json. The command itself is `knos observe`.")
        return 2
    old = DOC.read_text(encoding="utf-8")
    new = render_doc(old, json.loads(FIXTURE.read_text(encoding="utf-8")))
    if "--check" in args:
        print("docs/reference/PRIVACY.md is current." if new == old else "docs/reference/PRIVACY.md is stale: run python -m knos.observe --render-doc")
        return int(new != old)
    DOC.write_text(new, encoding="utf-8", newline="\n")
    print("Wrote the tables of docs/reference/PRIVACY.md." if new != old else "docs/reference/PRIVACY.md was current.")
    return 0


# ---- the command line ---------------------------------------------------------------------------------------------------
def register(app, help_lines: list | None = None) -> None:
    """`knos observe`, on the main app. `help_lines`: cli._HELP, which gets the command's line."""
    import typer

    if help_lines is not None:
        help_lines.append(("observe", "For money", "What an outsider can infer about an order, or about an organisation's whole history, from public data alone."))

    @app.command("observe", rich_help_panel="For money")
    def observe_(target: str = typer.Argument(..., help="a work order's address, one of its transactions, or (with --graph) a GitHub owner id"),
                 rpc: str = typer.Option("", "--rpc", help="the RPC endpoint to read (default: the cluster knos is set to)"),
                 as_graph: bool = typer.Option(False, "--graph", help="the whole history of a GitHub id: who it pays and who pays it, how much, how often"),
                 offline: bool = typer.Option(False, "--offline", help="do not ask GitHub's public API for the names behind ids"),
                 as_json: bool = typer.Option(False, "--json", help="print JSON"),
                 limit: int = typer.Option(1000, "--limit", help="with --graph: how many of the escrow's newest transactions to read (at most 1000)")) -> None:
        """Show what anyone can learn about a work order from public data alone: the Knos programs' accounts and logs,
        and GitHub's public API without a login. Each fact is marked learned, learned only as a hash, or not
        learned, with where it came from. For a private order it lists what still leaks: amounts, payees,
        wallets, timing, the attestor repository, and links between orders paid from one balance. With --graph
        it shows who one GitHub id pays and is paid by. This is a list of findings, not a privacy guarantee."""
        from . import cli
        url = rpc or cli._ledger().url
        names = None if offline else records.Names(public_github)
        try:
            if as_graph:
                if not target.isdigit():
                    raise cli.Stop(f"--graph takes a GitHub id (a number, like 424242); {target!r} is not one.", "Find an id with: gh api users/<login> --jq .id")
                events, unread, cut = records.history(url, pay2.PAY_ID, max(1, min(limit, 1000)))
                got = {**graph(events, int(target), names), "unread": unread, "history_cut": cut}
                said = graph_text(got) + ([f"{unread} transactions could not be read (the public RPC throttled): the totals are a lower bound."] if unread else []) \
                    + ([f"Only the escrow's newest {limit} transactions were read: older payments are not here."] if cut else [])
            else:
                got = order_facts(Rpc(url), target, names)
                said = table_text(got)
        except LookupError as why:
            raise cli.Stop(str(why), "Give a work order's address or a transaction that funded or paid one; for an organisation, add --graph.") from None
        except (chain.RpcError, OSError) as why:
            raise cli.Stop(f"Solana did not answer at {url}: {str(why).splitlines()[0] if str(why) else type(why).__name__}.", "Try again, or name another endpoint with --rpc.") from None
        for problem in (names.problems if names is not None else []):
            cli.err.print(f"{problem} Names it could not get are left empty; --offline skips the lookups.", markup=False)
        typer.echo(json.dumps(got, indent=1) if as_json else "\n".join(said))


if __name__ == "__main__":
    raise SystemExit(main())
