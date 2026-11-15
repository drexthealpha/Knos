"""config/fees.yaml, THE one fee config: its loader, its validator and the arithmetic every caller uses.

    cfg = load()                        the file (KNOS_FEES, else the tree's config/fees.yaml, else the wheel's copy),
                                        validated: a problem raises FeeConfigError with one line per problem
    cfg.fee(kind, amount)               the fee of a value-based line, in the same units as `amount` (6-decimal base
                                        units of USDC: micro-units): payout, bounty, funding, graduation, task_package,
                                        bounty_platform, lab_order
    cfg.platform(kind, amount)          a whole Knos fee (bounty_platform 5%, lab_order 3%) split into the on-chain part
                                        knos_pay takes and the off-chain rest (the program's rate is compiled in)
    cfg.price(kind, count, used=0)      a count-based line: verification, x402_check, verified_merge (the month's free ones first)
    cfg.split(amount, roles=None)       the contributor split, rounded exactly as knos_pay pays several payees
    cfg.bounty(amount), cfg.task_package(price)
    cfg.credit_tiers, cfg.decided(), cfg.placeholders(), cfg.public()

The live lines mirror what the deployed program charges (knos.settle.v2.pay) and the proposed lines mirror the price
book (knos.billing). The decided lines are the starting prices of 14 Oct 2026 and the product's prices of
23 Oct 2026 (the 1% release fee among them), each with its source; none of them is live, because knos_pay charges only
its compiled payout fee (0.30%) until a timelocked program upgrade. Those numbers are compiled into the program and typed once in those modules; this file states
them again so a reader has one place, and `validate` refuses the file when one differs. So nothing can drift: a
change to a fee is a change to the program (an upgrade through the multisig) or to the price book, and this file and
its tests move with it.

Standard library at import (PyYAML when installed; else the small reader below, which reads the subset the file
uses and is held to PyYAML by tests/test_money_fees.py).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

MICRO = 1_000_000
STATUSES = ("live", "proposed", "decided", "placeholder")
DECIDED_KEYS = ("decided", "rationale", "source")       # a decided price says when, why and on whose word
PLATFORM_KINDS = ("bounty_platform", "lab_order")       # a whole Knos fee of which an on-chain line is one part
VALUE_KINDS = ("payout", "bounty", "funding", "graduation", "task_package") + PLATFORM_KINDS
COUNT_KINDS = ("verification", "x402_check", "verified_merge")
KINDS = VALUE_KINDS + COUNT_KINDS
ROLES = ("researcher", "agent", "lab", "referee")
ENV = "KNOS_FEES"


class FeeConfigError(ValueError):
    """The fee config is missing or says something the code, the program or the price book does not."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("config/fees.yaml: " + "; ".join(self.problems))


# -- the reader ------------------------------------------------------------------------------------------------------
def _scalar(text: str) -> Any:
    text = text.strip()
    if text == "" or text in ("null", "~"):
        return None
    if text.startswith('"'):
        return json.loads(text)
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)          # refused by the validator wherever money is meant: money is a quoted string
    return text


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == "\\" and quote == '"':
                out.append(ch)
                continue
            if ch == quote and not (quote == '"' and i and line[i - 1] == "\\"):
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def parse_yaml(text: str) -> Any:
    """The YAML subset of config/fees.yaml: mappings by indentation, block lists of mappings or scalars, and
    scalars (double-quoted JSON strings, single-quoted strings, integers, decimals, true/false/null, plain words)."""
    lines = []
    for raw in text.splitlines():
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise ValueError("a tab in the indentation")
        s = _strip_comment(raw)
        if s.strip():
            lines.append((len(s) - len(s.lstrip(" ")), s.strip()))
    pos = 0

    def block(indent: int) -> Any:
        nonlocal pos
        if pos < len(lines) and lines[pos][1].startswith("- "):
            out_list: list = []
            while pos < len(lines) and lines[pos][0] == indent and lines[pos][1].startswith("- "):
                first = lines[pos][1][2:]
                if re.match(r"[A-Za-z_][\w-]*:(\s|$)", first):
                    # a mapping item: its first key on the dash line, the rest indented under it
                    lines[pos] = (indent + 2, first)
                    out_list.append(mapping(indent + 2))
                else:
                    out_list.append(_scalar(first))
                    pos += 1
            return out_list
        return mapping(indent)

    def mapping(indent: int) -> dict:
        nonlocal pos
        out: dict = {}
        while pos < len(lines):
            ind, s = lines[pos]
            if ind < indent:
                break
            if ind > indent:
                raise ValueError(f"unexpected indentation at {s!r}")
            m = re.match(r"([A-Za-z_][\w-]*):(?:\s+(.*))?$", s)
            if not m:
                raise ValueError(f"not a key: {s!r}")
            key, rest = m.group(1), m.group(2)
            if key in out:
                raise ValueError(f"the key {key!r} twice")
            pos += 1
            if rest is not None and rest.strip() != "":
                out[key] = _scalar(rest)
            elif pos < len(lines) and (lines[pos][0] > ind or (lines[pos][0] == ind and lines[pos][1].startswith("- "))):
                out[key] = block(lines[pos][0])
            else:
                out[key] = None
        return out

    got = block(0) if lines else {}
    if pos != len(lines):
        raise ValueError(f"could not read from {lines[pos][1]!r}")
    return got


def read(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return parse_yaml(text)
    return yaml.safe_load(text)


def default_path() -> Path:
    """KNOS_FEES; else the tree's config/fees.yaml; else the copy the wheel carries (knos/_config/fees.yaml)."""
    named = os.environ.get(ENV, "").strip()
    if named:
        return Path(named)
    here = Path(__file__).resolve()
    tree = here.parents[3] / "config" / "fees.yaml"
    if tree.is_file():
        return tree
    return here.parents[1] / "_config" / "fees.yaml"


# -- money -----------------------------------------------------------------------------------------------------------
def usd(value: Any, where: str, problems: list[str] | None = None) -> Decimal | None:
    """A money string as a Decimal of whole USD, at most 6 decimals, never negative. A float is refused: money in the
    config is always a quoted string."""
    bad = None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        bad = f"{where}: money is a quoted decimal string, not {type(value).__name__}"
    else:
        try:
            d = Decimal(str(value))
        except InvalidOperation:
            d = None
        if d is None or not d.is_finite() or d < 0 or (d * MICRO) != (d * MICRO).to_integral_value():
            bad = f"{where}: {value!r} is not an amount of USD with at most 6 decimals"
        else:
            return d
    if problems is None:
        raise FeeConfigError([bad])
    problems.append(bad)
    return None


def micro(value: Any, where: str = "amount") -> int:
    d = usd(value, where)
    assert d is not None
    return int(d * MICRO)


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# -- the validator ---------------------------------------------------------------------------------------------------
def validate(doc: Any) -> list[str]:
    """Every problem with a fee config, one line each; [] when there is none."""
    from .. import billing, plan_floor
    from ..settle.v2 import pay

    p: list[str] = []
    if not isinstance(doc, dict):
        return ["the file is not a mapping"]
    if doc.get("version") != 1:
        p.append("version: 1 is the only version")
    for top in ("treasury", "onchain", "fees", "splits", "cloud", "sources"):
        if not isinstance(doc.get(top), dict):
            p.append(f"{top}: missing")
    if p:
        return p
    if doc.get("network") != "solana devnet":
        p.append("network: Knos's Solana programs run on devnet only")
    if str(doc.get("revenue_today")) != "0":
        p.append("revenue_today: on devnet every fee is test money, so it is \"0\"")

    t = doc["treasury"]
    if t.get("fee_owner") != str(pay.FEE_OWNER):
        p.append(f"treasury.fee_owner: the program sends fees to {pay.FEE_OWNER}, not {t.get('fee_owner')}")
    if t.get("squads_program") != pay.IDS.get("squads_program"):
        p.append("treasury.squads_program: not the Squads program of program_ids.json")

    o = doc["onchain"]
    want = {"rate_bps": pay.FEE_BPS, "plan_floor_bps": plan_floor.FLOOR_BPS, "max_payees": pay.MAX_PAYEES}
    for k, v in want.items():
        if o.get(k) != v:
            p.append(f"onchain.{k}: the program says {v}, the file {o.get(k)!r}")
    for k, v in {"floor_usd": pay.FEE_MIN, "relayer_tip_usd": pay.TIP, "relayer_tip_first_usd": pay.TIP_FIRST, "order_min_usd": pay.ORDER_MIN_AMOUNT}.items():
        d = usd(o.get(k), f"onchain.{k}", p)
        if d is not None and int(d * MICRO) != v:
            p.append(f"onchain.{k}: the program says {Decimal(v) / MICRO}, the file {o.get(k)}")
    if o.get("status") != "live":
        p.append("onchain.status: live (it is what the deployed program charges)")

    f = doc["fees"]
    for kind in KINDS:
        line = f.get(kind)
        if not isinstance(line, dict):
            p.append(f"fees.{kind}: missing")
            continue
        if line.get("status") not in STATUSES:
            p.append(f"fees.{kind}.status: one of {', '.join(STATUSES)}")
        if not isinstance(line.get("what"), str) or not line["what"].strip():
            p.append(f"fees.{kind}.what: one sentence saying what is charged")
    if any(x.startswith("fees.") and x.endswith(": missing") for x in p):
        return p
    for kind in ("payout", "bounty"):
        line = f[kind]
        if line.get("status") != "live":
            p.append(f"fees.{kind}.status: live (knos_pay charges it)")
        if line.get("rate_bps") != o.get("rate_bps"):
            p.append(f"fees.{kind}.rate_bps: the program's rate is {pay.FEE_BPS}")
        if usd(line.get("floor_usd"), f"fees.{kind}.floor_usd", p) is not None and line.get("floor_usd") != o.get("floor_usd"):
            p.append(f"fees.{kind}.floor_usd: the program's floor is {o.get('floor_usd')}")
    if f["bounty"].get("to") != "treasury":
        p.append("fees.bounty.to: treasury (the program sends the fee to the fee owner)")
    if f["funding"].get("rate_bps") != 0:
        p.append("fees.funding.rate_bps: 0 (the program takes the fee at release, and returns it on a refund)")
    v = f["verification"]
    for k in ("public_repos_usd", "self_host_usd"):
        if usd(v.get(k), f"fees.verification.{k}", p) not in (None, Decimal(0)):
            p.append(f"fees.verification.{k}: checking stays free (price book: Check, free forever)")
    each = usd(v.get("usd_each"), "fees.verification.usd_each", p)
    if each is not None and each != billing.METER_PRICE:
        p.append(f"fees.verification.usd_each: the price book says {billing.METER_PRICE}")
    if v.get("free_per_month") != billing.METER_FREE:
        p.append(f"fees.verification.free_per_month: the price book says {billing.METER_FREE}")
    x = f["x402_check"]
    x_each = usd(x.get("usd_each"), "fees.x402_check.usd_each", p)
    if x.get("status") == "proposed" and x.get("usd_each") != v.get("usd_each"):
        p.append("fees.x402_check.usd_each: a proposed paid check costs what a verification costs (the price book)")
    if x_each is not None and x_each <= 0 and x.get("status") != "placeholder":
        p.append("fees.x402_check.usd_each: a paid check has a price above 0")
    vm = f["verified_merge"]
    vm_each = usd(vm.get("usd_each"), "fees.verified_merge.usd_each", p)
    if vm_each is not None and vm_each <= 0 and vm.get("status") != "placeholder":
        p.append("fees.verified_merge.usd_each: a verified merge has a price above 0")
    if not _int(vm.get("free_first")) or vm["free_first"] < 0:
        p.append("fees.verified_merge.free_first: how many verifications of a new team are free, a whole number")
    if not str(vm.get("collected", "")).strip():
        p.append("fees.verified_merge.collected: say how a verified merge is billed and paid")
    for kind, key in (("graduation", "rate_bps"), ("task_package", "knos_bps")):
        r = f[kind].get(key)
        if not _int(r) or not 0 <= r <= 10_000:
            p.append(f"fees.{kind}.{key}: basis points, 0 to 10000")
    for kind in ("graduation", "task_package", "x402_check", "verified_merge") + PLATFORM_KINDS:
        if f[kind].get("status") == "live":
            p.append(f"fees.{kind}.status: not live (knos_pay charges only the payout fee, {pay.FEE_BPS} bps; more on chain needs a program upgrade)")
    for kind in PLATFORM_KINDS:
        line, r = f[kind], f[kind].get("rate_bps")
        if not _int(r) or not 0 <= r <= 10_000:
            p.append(f"fees.{kind}.rate_bps: basis points, 0 to 10000")
        if line.get("onchain_line") not in ("payout", "bounty"):
            p.append(f"fees.{kind}.onchain_line: payout or bounty (the on-chain fee that is part of this one)")
        elif _int(r) and r < f[line["onchain_line"]].get("rate_bps", 0):
            p.append(f"fees.{kind}.rate_bps: at least the on-chain {line['onchain_line']} rate it includes")
        if not str(line.get("collected", "")).strip():
            p.append(f"fees.{kind}.collected: say how the part above the on-chain fee is collected")
    for kind in KINDS:
        p += _decided_problems(f[kind], f"fees.{kind}")

    s = doc["splits"]
    roles = s.get("roles")
    if not isinstance(roles, dict) or not roles:
        p.append("splits.roles: missing")
    else:
        if set(roles) - set(ROLES):
            p.append(f"splits.roles: only {', '.join(ROLES)}")
        if len(roles) > pay.MAX_PAYEES:
            p.append(f"splits.roles: one order pays at most {pay.MAX_PAYEES} payees")
        if not all(_int(b) and b > 0 for b in roles.values()):
            p.append("splits.roles: each share is a whole number of basis points above 0")
        elif sum(roles.values()) != 10_000:
            p.append(f"splits.roles: the shares add up to {sum(roles.values())}, not 10000")
    if s.get("status") not in STATUSES:
        p.append("splits.status: one of " + ", ".join(STATUSES))
    p += _decided_problems(s, "splits")

    c = doc["cloud"]
    if c.get("status") not in STATUSES:
        p.append("cloud.status: one of " + ", ".join(STATUSES))
    if c.get("status") == "live":
        p.append("cloud.status: not live (nothing is sold)")
    p += _decided_problems(c, "cloud")
    if c.get("units_status", "placeholder") not in STATUSES:
        p.append("cloud.units_status: one of " + ", ".join(STATUSES))
    credit = usd(c.get("credit_usd"), "cloud.credit_usd", p)
    bonus = c.get("bonus_bps", 0)
    if not _int(bonus) or not 0 <= bonus <= 10_000:
        p.append("cloud.bonus_bps: basis points, 0 to 10000")
        bonus = None
    tiers = c.get("tiers")
    for x in tiers if isinstance(tiers, list) else []:
        if not isinstance(x, dict) or "credit_usd_month" not in x:
            continue
        name = x.get("name")
        price, worth = usd(x.get("usd_month"), f"cloud.tiers.{name}.usd_month", []), usd(x.get("credit_usd_month"), f"cloud.tiers.{name}.credit_usd_month", p)
        if price is not None and worth is not None and bonus is not None and worth != price * (10_000 + bonus) / 10_000:
            p.append(f"cloud.tiers.{name}.credit_usd_month: {price} USD with a {bonus / 100:g}% bonus is {price * (10_000 + bonus) / 10_000} of credit, not {worth}")
        if worth is not None and credit and _int(x.get("credits_month")) and Decimal(x["credits_month"]) * credit != worth:
            p.append(f"cloud.tiers.{name}.credits_month: {worth} USD of credit at {credit} a credit is {worth / credit} credits")
    if not isinstance(tiers, list) or not tiers:
        p.append("cloud.tiers: a list of tiers")
    else:
        names = [x.get("name") if isinstance(x, dict) else None for x in tiers]
        if None in names or len(set(names)) != len(names):
            p.append("cloud.tiers: each tier has a name of its own")
        for x in tiers:
            if isinstance(x, dict):
                usd(x.get("usd_month"), f"cloud.tiers.{x.get('name')}.usd_month", p)
                if not _int(x.get("credits_month")) or x["credits_month"] < 0:
                    p.append(f"cloud.tiers.{x.get('name')}.credits_month: a whole number")
    if not isinstance(c.get("consumes"), dict) or not all(_int(n) and n >= 0 for n in c["consumes"].values()):
        p.append("cloud.consumes: credits per use, whole numbers")
    if "source" not in str(c.get("shape_from", "")).lower() and "techcrunch" not in str(c.get("shape_from", "")).lower():
        p.append("cloud.shape_from: an outside figure carries its source beside it")

    for name, src in doc["sources"].items():
        if not isinstance(src, dict) or not src.get("said") or not src.get("source") or src.get("audited") is not False:
            p.append(f"sources.{name}: said, source and audited: false (no outside figure without its source)")
    return p


def _decided_problems(line: dict, where: str) -> list[str]:
    """A decided price carries when it was decided, why, and its source (an outside figure only with its link and date)."""
    if line.get("status") != "decided":
        return []
    return [f"{where}.{k}: a decided price says {k}" for k in DECIDED_KEYS if not str(line.get(k) or "").strip()]


# -- the config ------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FeeConfig:
    doc: dict
    path: str = ""
    _units: dict = field(default_factory=dict, compare=False, repr=False)

    # value-based lines -------------------------------------------------------------------------------------------
    def fee(self, kind: str, amount: int, bps: int | None = None) -> int:
        """The fee of `amount` (base units of a 6-decimal mint) under the line `kind`. payout and bounty are exactly
        knos_pay's order fee (rate, rounded down, at least the floor); funding is 0 (the program takes the fee at
        release); graduation and task_package are their rate, rounded down, with no floor. `bps`: for payout and
        bounty, the rate an order actually pays when it is not the standard one: its own `fee_bps` (pay.Order, fixed at
        funding) or an owner's Plan, from the contract floor (onchain.plan_floor_bps) up to the standard rate."""
        if kind in COUNT_KINDS:
            raise ValueError(f"{kind} is priced per use: cfg.price({kind!r}, count)")
        if kind not in VALUE_KINDS:
            raise ValueError(f"no fee line {kind!r}: one of {', '.join(KINDS)}")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise ValueError("amount: base units, a whole number from 0")
        line = self.doc["fees"][kind]
        if kind in ("payout", "bounty"):
            rate = line["rate_bps"] if bps is None else bps
            if isinstance(rate, bool) or not isinstance(rate, int) or not self.doc["onchain"]["plan_floor_bps"] <= rate <= line["rate_bps"]:
                raise ValueError(f"bps: {self.doc['onchain']['plan_floor_bps']} to {line['rate_bps']} (a Plan only lowers the rate, never below the floor)")
            return max(amount * rate // 10_000, micro(line["floor_usd"]))
        if bps is not None:
            raise ValueError(f"{kind}: no per-order rate")
        if kind == "funding":
            return 0
        bps = line["knos_bps"] if kind == "task_package" else line["rate_bps"]
        return amount * bps // 10_000

    def platform(self, kind: str, amount: int, bps: int | None = None) -> dict:
        """A whole Knos fee (bounty_platform, lab_order) split into what knos_pay takes on chain and what is left to
        collect off chain. The on-chain fee is PART of the whole one, never added to it: knos_pay's rate is compiled
        into the program, so the rest waits for a program upgrade and is invoiced until then. `bps`: the order's own
        on-chain rate (as cfg.fee). The off-chain part is never below 0 (a floor-sized on-chain fee can cover it all)."""
        if kind not in PLATFORM_KINDS:
            raise ValueError(f"{kind} is not a whole Knos fee: one of {', '.join(PLATFORM_KINDS)}")
        line = self.doc["fees"][kind]
        whole = self.fee(kind, amount)
        onchain = self.fee(line["onchain_line"], amount, bps=bps)
        return {"kind": kind, "amount": amount, "rate_bps": line["rate_bps"], "fee": max(whole, onchain), "onchain": onchain,
                "onchain_line": line["onchain_line"], "offchain": max(0, whole - onchain), "status": line["status"],
                "collected": line["collected"]}

    def bounty(self, amount: int) -> dict:
        """A bounty of `amount`: the funder pays amount + fee; the payee receives the amount; the fee goes to the treasury."""
        fee = self.fee("bounty", amount)
        return {"amount": amount, "fee": fee, "total": amount + fee, "payer": self.doc["fees"]["payout"]["payer"],
                "fee_to": "treasury", "treasury": self.doc["treasury"]["fee_owner"], "status": self.doc["fees"]["bounty"]["status"]}

    def task_package(self, price: int) -> dict:
        knos = self.fee("task_package", price)
        return {"price": price, "knos": knos, "maintainer": price - knos, "knos_bps": self.doc["fees"]["task_package"]["knos_bps"],
                "status": self.doc["fees"]["task_package"]["status"]}

    # count-based lines -------------------------------------------------------------------------------------------
    def price(self, kind: str, count: int, used: int = 0, public: bool = False) -> int:
        """What `count` uses cost (base units), after `used` this month. A public repository's check is free."""
        if kind not in COUNT_KINDS:
            raise ValueError(f"{kind} is a fee on a value: cfg.fee({kind!r}, amount)")
        if public:
            return 0
        line = self.doc["fees"][kind]
        free = self.doc["fees"]["verification"]["free_per_month"] if kind == "verification" else 0
        paid = max(0, used + count - max(free, used))
        return paid * micro(line["usd_each"])

    # splits ------------------------------------------------------------------------------------------------------
    @property
    def roles(self) -> dict[str, int]:
        return dict(self.doc["splits"]["roles"])

    def shares(self, roles=None) -> list[tuple[str, int]]:
        """(role, bps) for the roles present, in the config's order, adding up to 10000: a role that is absent leaves
        its share to the others in proportion (rounded down; the remainder to the first)."""
        all_ = self.roles
        names = [r for r in all_ if roles is None or r in roles]
        if roles is not None:
            unknown = [r for r in roles if r not in all_]
            if unknown:
                raise ValueError(f"unknown role(s) {unknown}: one of {', '.join(all_)}")
        if not names:
            raise ValueError("a split needs at least one role")
        whole = sum(all_[r] for r in names)
        out = [(r, all_[r] * 10_000 // whole) for r in names]
        out[0] = (out[0][0], out[0][1] + 10_000 - sum(b for _, b in out))
        return out

    def split(self, amount: int, roles=None) -> list[tuple[str, int]]:
        """(role, base units) of `amount`, exactly as knos_pay pays several payees: each share rounded down, the
        last payee the rest. Sums to `amount`."""
        sh = self.shares(roles)
        return list(zip([r for r, _ in sh], amounts(amount, [b for _, b in sh])))

    # the rest ----------------------------------------------------------------------------------------------------
    @property
    def credit_tiers(self) -> list[dict]:
        return [dict(t) for t in self.doc["cloud"]["tiers"]]

    def placeholders(self) -> list[str]:
        """Every number not set yet: the lines whose status is placeholder, with their values."""
        out = []
        for kind, line in self.doc["fees"].items():
            if line.get("status") == "placeholder":
                out += [f"fees.{kind}.{k} = {v}" for k, v in line.items() if k.endswith(("_bps", "_usd"))]
        if self.doc["splits"].get("status") == "placeholder":
            out += [f"splits.roles.{k} = {v}" for k, v in self.roles.items()]
        c = self.doc["cloud"]
        if c.get("status") == "placeholder":
            out.append(f"cloud.credit_usd = {c['credit_usd']}")
            out += [f"cloud.tiers.{t['name']} = {t['usd_month']} USD/month, {t['credits_month']} credits" for t in c["tiers"]]
        elif c.get("units_status", "placeholder") == "placeholder":
            out.append(f"cloud.credit_usd = {c['credit_usd']}")
            out += [f"cloud.consumes.{k} = {v}" for k, v in c["consumes"].items()]
            out += [f"cloud.tiers.{t['name']}.credits_month = {t['credits_month']}" for t in c["tiers"]]
        return out

    def decided(self) -> list[str]:
        """Every starting price set, each with its date and source (status decided)."""
        out = []
        for kind, line in self.doc["fees"].items():
            if line.get("status") == "decided":
                out += [f"fees.{kind}.{k} = {v} ({line['decided']}; {line['source']})" for k, v in line.items() if k.endswith(("_bps", "_usd")) or k == "usd_each"]
        s = self.doc["splits"]
        if s.get("status") == "decided":
            out += [f"splits.roles.{k} = {v} ({s['decided']}; {s['source']})" for k, v in self.roles.items()]
        c = self.doc["cloud"]
        if c.get("status") == "decided":
            out += [f"cloud.tiers.{t['name']} = {t['usd_month']} USD/month, {t.get('credit_usd_month', t['usd_month'])} USD of credit ({c['decided']}; {c['source']})" for t in c["tiers"]]
        return out

    def public(self) -> dict:
        """The config as JSON for a page (the revenue dashboard), with each line's status, the decided prices and the
        placeholder list."""
        return {"version": self.doc["version"], "network": self.doc["network"], "revenue_today": self.doc["revenue_today"],
                "treasury": self.doc["treasury"], "onchain": self.doc["onchain"], "fees": self.doc["fees"], "splits": self.doc["splits"],
                "cloud": self.doc["cloud"], "sources": self.doc["sources"], "decided": self.decided(), "placeholders": self.placeholders()}


def amounts(amount: int, bps: list[int]) -> list[int]:
    """knos_pay's division of an order among payees (order_pay.rs): each amount * bps / 10000 rounded down, the last
    payee what is left."""
    if sum(bps) != 10_000:
        raise ValueError("the shares must add up to 10000 basis points")
    out = [amount * b // 10_000 for b in bps[:-1]]
    return out + [amount - sum(out)]


def load(path: str | os.PathLike | None = None) -> FeeConfig:
    """The fee config, validated. Raises FeeConfigError (one line per problem) when it cannot be trusted."""
    where = Path(path) if path is not None else default_path()
    if not where.is_file():
        raise FeeConfigError([f"no fee config at {where}"])
    try:
        doc = read(where)
    except Exception as why:  # noqa: BLE001 - a file that does not parse is one problem, said in a line
        raise FeeConfigError([f"{where} does not parse: {why}"]) from None
    problems = validate(doc)
    if problems:
        raise FeeConfigError(problems)
    return FeeConfig(doc, str(where))
