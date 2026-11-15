"""`.knos/policy.yml`: what an organisation lets Knos do with its money, as a file on the default branch.

    version: 1
    who_may_fund: [alice, 1234567]    # GitHub logins or ids that may fund an order (absent: anyone who may fund today)
    cap_per_order: 100                # the most one order may take, in whole units of the money (20 means 20 USDC)
    monthly_budget: 1000              # the most all orders funded in one calendar month (UTC) may take
    payees: [carol, dave]             # who may be paid (absent: anyone)
    vendors: [acme-agents]            # which vendors may be paid by a standing offer
    checks: [test, lint]              # the checks an order names when its funder names none
    offers:                           # standing offers: each merged change of a vendor that meets `checks` pays `rate`
      - vendor: acme-agents
        rate: 20
        budget: 400                   # the most the offer pays in one month
        checks: [test]
    warranty_days: 14                 # a share of each payment waits this long (0 to 90) in case the work is reverted
    holdback_percent: 10              # that share (0 to 50); it needs warranty_days
    arbiter: erin                     # who rules when a payment is disputed
    private: false                    # true: the repository's name and the terms stay off the chain (hashes only)
    attestor: acme/knos-settle        # with private: the one repository whose workflow funds and pays the private orders
    targets: [acme/app, acme/api]     # with attestor: the repositories it does that for (it reads them, they run nothing)

A PRIVATE organisation keeps this file in its ATTESTOR repository, and that copy is the policy of every target: the
targets hold no workflow and no policy of their own. A private order is asked for and answered nowhere else.

The file is read here and nowhere else, as a small subset of YAML written by hand (pyyaml is a development dependency
only, and the tests check this reader against it): block mappings and lists by indentation (spaces), one-line `[a, b]`
and `{a: 1}`, quoted or plain strings, numbers, true, false and null, and `#` comments. JSON, being YAML, is read as
JSON. Anchors, tags, multi-line strings and several documents are refused, and so is a rule it does not know, a number
that is not one, and anything that cannot hold (a monthly budget under the cap per order): every refusal is `Refused`,
whose words begin with the file and the line. A policy that does not load must stop funding, never mean "anything goes".

    load(text) -> Policy
    allows(policy, actor_id, amount, month_spent, login="") -> (ok, reason naming the line)
    digest(policy) -> sha256 of the canonical JSON (what is hashed into the terms of every order)
    order_opts(policy, vendor=None) -> the defaults a funding takes from it
    attests(policy, here, target=None) -> (ok, reason): whether `here` is the attestor of the policy's private orders

Amounts are whole units of the money as a person writes them (Decimal, int or float): the caller divides raw token units
by 10 ** decimals first. Logins are compared without case.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

PATH = ".knos/policy.yml"
RULES = ("version", "who_may_fund", "cap_per_order", "monthly_budget", "payees", "vendors", "checks", "offers",
         "warranty_days", "holdback_percent", "arbiter", "private", "attestor", "targets")
OFFER_KEYS = ("vendor", "rate", "budget", "checks")
MAX_WARRANTY_DAYS, MAX_HOLDBACK_PERCENT = 90, 50        # knos-pay's limits: warranty_days <= 90, holdback_bps <= 5000
_LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:\[bot\])?|[0-9]{1,20}")
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}")      # owner/name, as GitHub writes a repository
MAX_TARGETS = 50                                        # the repositories one attestor reads on each of its runs


class Refused(ValueError):
    """The policy file cannot be used. The first words are the file and the line."""


@dataclass(frozen=True)
class Offer:
    vendor: str
    rate: Decimal
    budget: Decimal | None = None
    checks: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Policy:
    who_may_fund: tuple[str, ...] | None = None
    cap_per_order: Decimal | None = None
    monthly_budget: Decimal | None = None
    payees: tuple[str, ...] | None = None
    vendors: tuple[str, ...] | None = None
    checks: tuple[str, ...] | None = None
    offers: tuple[Offer, ...] = ()
    warranty_days: int | None = None
    holdback_bps: int | None = None
    arbiter: str | None = None
    private: bool = False
    attestor: str | None = None                 # owner/name, lower case: where a private order is funded and paid
    targets: tuple[str, ...] = ()               # owner/name, lower case: the repositories the attestor does that for
    lines: dict = field(default_factory=dict, compare=False, repr=False)       # rule (or "offers.0.rate") -> its line


# ---- the YAML subset -------------------------------------------------------------------------------------------------

class _Reader:
    """Lines of the subset, parsed into dicts, lists and scalars, remembering the line of every key and item."""

    def __init__(self, text: str):
        self.lines: dict[str, int] = {}
        self.items: list[tuple[int, int, str]] = []         # (line number, indent, text without comment)
        rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for n, raw in enumerate(rows, 1):
            body = self._uncomment(raw, n)
            if not body.strip():
                continue
            if body.strip() == "---" and not self.items:
                continue
            if body.strip() in ("---", "...") or body.startswith("%"):
                raise Refused(f"{PATH} line {n}: several documents (or directives) are not supported; a policy is one document.")
            lead = body[:len(body) - len(body.lstrip(" \t"))]
            if "\t" in lead:
                raise Refused(f"{PATH} line {n}: indent with spaces, not tabs.")
            self.items.append((n, len(lead), body.strip()))

    @staticmethod
    def _uncomment(raw: str, n: int) -> str:
        """The line without its comment: a `#` starts one at the start of the line or after a space, outside quotes."""
        quote = ""
        for i, ch in enumerate(raw):
            if quote:
                if ch == quote and not (quote == '"' and raw[i - 1] == "\\"):
                    quote = ""
            elif ch in "\"'" and (i == 0 or raw[i - 1] in " \t[{,:-"):
                quote = ch
            elif ch == "#" and (i == 0 or raw[i - 1] in " \t"):
                return raw[:i].rstrip()
        if quote and quote in raw.strip()[:1]:
            raise Refused(f"{PATH} line {n}: a quote is opened and never closed.")
        return raw.rstrip()

    def read(self):
        if not self.items:
            return {}
        value, at = self.block(0, self.items[0][1], "")
        if at < len(self.items):
            raise Refused(f"{PATH} line {self.items[at][0]}: this line is indented differently from the lines before it.")
        return value

    # blocks
    def block(self, i: int, indent: int, path: str):
        text = self.items[i][2]
        return self.sequence(i, indent, path) if text == "-" or text.startswith("- ") else self.mapping(i, indent, path)

    def mapping(self, i: int, indent: int, path: str):
        out: dict = {}
        while i < len(self.items) and self.items[i][1] == indent:
            n, _ind, text = self.items[i]
            if text == "-" or text.startswith("- "):
                raise Refused(f"{PATH} line {n}: a list item where a `name: value` line was expected.")
            key, rest = self.split(text, n)
            if key in out:
                raise Refused(f"{PATH} line {n}: `{key}` appears twice.")
            here = f"{path}.{key}" if path else key
            self.lines[here] = n
            i += 1
            if rest:
                out[key] = self.value(rest, n)
            elif i < len(self.items) and (self.items[i][1] > indent or (self.items[i][1] == indent and self.items[i][2].startswith("-") and
                                                                          (self.items[i][2] == "-" or self.items[i][2].startswith("- ")))):
                out[key], i = self.block(i, self.items[i][1], here)
            else:
                out[key] = None
        if i < len(self.items) and self.items[i][1] > indent:
            raise Refused(f"{PATH} line {self.items[i][0]}: this line is indented " + ("more than the one before it, which has nothing to nest." if self.items[i - 1][1] == indent
                                                                                        else "differently from the lines before it."))
        return out, i

    def sequence(self, i: int, indent: int, path: str):
        out: list = []
        while i < len(self.items) and self.items[i][1] == indent and (self.items[i][2] == "-" or self.items[i][2].startswith("- ")):
            n, _ind, text = self.items[i]
            here = f"{path}.{len(out)}"
            self.lines[here] = n
            rest = text[1:].strip()
            if not rest:
                i += 1
                if i < len(self.items) and self.items[i][1] > indent:
                    item, i = self.block(i, self.items[i][1], here)
                else:
                    item = None
            elif rest == "-" or rest.startswith("- "):
                raise Refused(f"{PATH} line {n}: a list inside a list on one line is not supported; put the inner list on its own lines.")
            elif self.is_entry(rest):        # `- key: value`: a mapping whose first line is this one
                offset = len(text) - len(rest)
                self.items[i] = (n, indent + offset, rest)
                item, i = self.mapping(i, indent + offset, here)
            else:
                item, i = self.value(rest, n), i + 1
            out.append(item)
        return out, i

    # one line
    @staticmethod
    def is_entry(text: str) -> bool:
        return bool(re.match(r"""^(?:"[^"]*"|'[^']*'|[^\s:#"'\[\]{},&*!|>%@`-][^:#]*?)\s*:(?:\s|$)""", text))

    def split(self, text: str, n: int) -> tuple[str, str]:
        m = re.match(r"""^(?P<key>"[^"]*"|'[^']*'|[^\s:#"'\[\]{},&*!|>%@`][^:#]*?)\s*:(?:\s+(?P<rest>.*))?$""", text)
        if not m:
            raise Refused(f"{PATH} line {n}: expected `name: value`, found `{text[:40]}`.")
        key = m.group("key")
        return (key[1:-1] if key[0] in "\"'" else key), (m.group("rest") or "").strip()

    def value(self, text: str, n: int):
        text = text.strip()
        if text[:1] in "[{":
            got, at = self.flow(text, 0, n)
            if text[at:].strip():
                raise Refused(f"{PATH} line {n}: unexpected `{text[at:].strip()[:20]}` after the list or mapping.")
            return got
        return self.scalar(text, n)

    def flow(self, text: str, at: int, n: int):
        """A one-line `[a, b]` or `{a: 1}` starting at text[at]; (value, the index after it)."""
        close = "]" if text[at] == "[" else "}"
        out_list: list = []
        out_map: dict = {}
        at += 1
        while True:
            at = self.skip(text, at)
            if at >= len(text):
                raise Refused(f"{PATH} line {n}: `{text[:1]}` is never closed on the line (a list or mapping must end on the line it starts).")
            if text[at] == close:
                return (out_list if close == "]" else out_map), at + 1
            if text[at] in "]}":
                raise Refused(f"{PATH} line {n}: `{text[at]}` closes something that was not opened here.")
            if text[at] == ",":
                at += 1
                continue
            key = None
            if close == "}":
                m = re.compile(r"""\s*("[^"]*"|'[^']*'|[^\s:,\[\]{}"'][^:,\[\]{}]*?)\s*:\s*""").match(text, at)
                if not m:
                    raise Refused(f"{PATH} line {n}: expected `name: value` inside `{{ }}`.")
                key, at = m.group(1), m.end()
                key = key[1:-1] if key[0] in "\"'" else key
            if at < len(text) and text[at] in "[{":
                item, at = self.flow(text, at, n)
            else:
                end = at
                if text[at:at + 1] in "\"'":
                    end = self.closing(text, at, n)
                else:
                    while end < len(text) and text[end] not in ",]}":
                        end += 1
                item, at = self.scalar(text[at:end].strip(), n), end
            if key is None:
                out_list.append(item)
            elif key in out_map:
                raise Refused(f"{PATH} line {n}: `{key}` appears twice.")
            else:
                out_map[key] = item
            at = self.skip(text, at)
            if at < len(text) and text[at] not in f",{close}":
                raise Refused(f"{PATH} line {n}: expected `,` or `{close}` after `{text[max(0, at - 12):at].strip()}`, found `{text[at]}`.")

    @staticmethod
    def skip(text: str, at: int) -> int:
        while at < len(text) and text[at] in " \t":
            at += 1
        return at

    @staticmethod
    def closing(text: str, at: int, n: int) -> int:
        quote, i = text[at], at + 1
        while i < len(text):
            if text[i] == "\\" and quote == '"':
                i += 2
                continue
            if text[i] == quote:
                if quote == "'" and text[i + 1:i + 2] == "'":
                    i += 2
                    continue
                return i + 1
            i += 1
        raise Refused(f"{PATH} line {n}: a quote is opened and never closed.")

    def scalar(self, text: str, n: int):
        if not text or text in ("~", "null", "Null", "NULL"):
            return None
        if text in ("true", "True", "TRUE"):
            return True
        if text in ("false", "False", "FALSE"):
            return False
        if text[0] == '"':
            if self.closing(text, 0, n) != len(text):
                raise Refused(f"{PATH} line {n}: text after the closing quote.")
            try:
                return json.loads(text)
            except ValueError:
                raise Refused(f"{PATH} line {n}: `{text[:30]}` has an escape this reader does not know (use \\\\, \\\" , \\n or \\t).") from None
        if text[0] == "'":
            if self.closing(text, 0, n) != len(text):
                raise Refused(f"{PATH} line {n}: text after the closing quote.")
            return text[1:-1].replace("''", "'")
        if text[0] in "&*!|>%@`":
            raise Refused(f"{PATH} line {n}: `{text[0]}` (an anchor, alias, tag or multi-line string) is not supported; quote the text if it is meant literally.")
        if ": " in text or text.endswith(":"):
            raise Refused(f"{PATH} line {n}: `{text[:40]}` has a colon in plain text; put it in quotes.")
        if re.fullmatch(r"[-+]?[0-9]+", text):
            if re.fullmatch(r"[-+]?0[0-9]+", text):
                raise Refused(f"{PATH} line {n}: write {text.lstrip('+-').lstrip('0') or '0'}, not {text} (a leading zero means octal in YAML).")
            return int(text)
        if re.fullmatch(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+][0-9]+)?", text):      # as pyyaml: an exponent needs its sign, and a point
            return float(text)
        return text


def _parse(text: str) -> tuple[dict, dict]:
    """(the document as dicts, lists and scalars, the line of every key and item as {"a.b.0": line})."""
    if not isinstance(text, str):
        raise Refused(f"{PATH} is not text.")
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped[:1] and stripped[:1] in "{[":
        try:
            doc = json.loads(stripped)
        except ValueError as why:
            raise Refused(f"{PATH} line {getattr(why, 'lineno', 1)}: not valid JSON ({why}).") from None
        if not isinstance(doc, dict):
            raise Refused(f"{PATH} line 1: a policy is a mapping of rules, not a list.")
        lines = {k: _json_line(text, k) for k in doc}
        for k, v in doc.items():
            if isinstance(v, dict):
                lines.update({f"{k}.{kk}": _json_line(text, kk, lines[k]) for kk in v})
            elif isinstance(v, list):
                lines.update({f"{k}.{i}": lines[k] for i in range(len(v))})
        return doc, lines
    reader = _Reader(text)
    doc = reader.read()
    if not isinstance(doc, dict):
        raise Refused(f"{PATH} line {reader.items[0][0]}: a policy is `name: value` lines, not a list.")
    return doc, reader.lines


def _json_line(text: str, key: str, after: int = 1) -> int:
    """The line of `"key"` in a JSON policy, from line `after` on (best effort: 0 when it is not found)."""
    for n, row in enumerate(text.splitlines(), 1):
        if n >= after and f'"{key}"' in row:
            return n
    return 0


# ---- the rules -------------------------------------------------------------------------------------------------------

def _where(lines: dict, path: str) -> str:
    n = lines.get(path) or lines.get(path.split(".")[0]) or 0
    return f"{PATH} line {n}" if n else PATH


def _number(value, lines: dict, path: str, *, low: Decimal | None = None, high: Decimal | None = None, whole: bool = False, positive: bool = True) -> Decimal:
    name = path.split(".")[-1]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise Refused(f"{_where(lines, path)}: {name} must be a number, not `{value}`.")
    try:
        number = Decimal(str(value).strip())
    except InvalidOperation:
        raise Refused(f"{_where(lines, path)}: {name} must be a number, not `{value}`.") from None
    if not number.is_finite():
        raise Refused(f"{_where(lines, path)}: {name} must be a number, not `{value}`.")
    if whole and number != number.to_integral_value():
        raise Refused(f"{_where(lines, path)}: {name} must be a whole number, not {value}.")
    if positive and number <= 0:
        raise Refused(f"{_where(lines, path)}: {name} must be more than 0, not {value}.")
    if low is not None and number < low or high is not None and number > high:
        raise Refused(f"{_where(lines, path)}: {name} must be from {low} to {high}, not {value}.")
    return number


def _names(value, lines: dict, path: str, *, logins: bool = True) -> tuple[str, ...]:
    """A non-empty list of GitHub logins or ids (or of plain names), without case and without repeats."""
    name = path.split(".")[-1]
    items = value if isinstance(value, list) else None
    if not items:
        raise Refused(f"{_where(lines, path)}: {name} must be a list with at least one name, like [alice, bob]" +
                      ("; an empty list would mean nobody." if items == [] else "."))
    out = []
    for item in items:
        text = str(item).strip() if isinstance(item, (str, int)) and not isinstance(item, bool) else ""
        if not text or (logins and not _LOGIN.fullmatch(text)) or (not logins and (len(text) > 100 or "\n" in text or "`" in text or "," in text)):
            raise Refused(f"{_where(lines, path)}: `{item}` in {name} is not " + ("a GitHub login or id." if logins else "a name (up to 100 characters, no commas or backticks)."))
        out.append(text.lower() if logins else text)
    if len(set(out)) != len(out):
        raise Refused(f"{_where(lines, path)}: {name} names {next(x for x in out if out.count(x) > 1)} twice.")
    return tuple(out)


def _login(value, lines: dict, path: str) -> str:
    text = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not _LOGIN.fullmatch(text):
        raise Refused(f"{_where(lines, path)}: `{value}` is not a GitHub login or id.")
    return text.lower()


def _repos(value, lines: dict, path: str) -> tuple[str, ...]:
    """A non-empty list of repositories as owner/name, without case and without repeats."""
    name, items = path.split(".")[-1], value if isinstance(value, list) else [value] if path == "attestor" else None
    if not items:
        raise Refused(f"{_where(lines, path)}: {name} must be a list of repositories, like [acme/app, acme/api].")
    out = [str(item).strip().lower() if isinstance(item, str) else "" for item in items]
    for item, text in zip(items, out):
        if not _REPO.fullmatch(text):
            raise Refused(f"{_where(lines, path)}: `{item}` in {name} is not a repository; write it as owner/name.")
    if len(set(out)) != len(out):
        raise Refused(f"{_where(lines, path)}: {name} names {next(x for x in out if out.count(x) > 1)} twice.")
    if len(out) > MAX_TARGETS:
        raise Refused(f"{_where(lines, path)}: {name} lists {len(out)} repositories, and one attestor reads at most {MAX_TARGETS}.")
    return tuple(out)


def _offers(value, lines: dict, vendors: tuple[str, ...] | None) -> tuple[Offer, ...]:
    if not isinstance(value, list) or not value:
        raise Refused(f"{_where(lines, 'offers')}: offers is a list; each item has a vendor and a rate.")
    out: list[Offer] = []
    for i, item in enumerate(value):
        at = f"offers.{i}"
        if not isinstance(item, dict):
            raise Refused(f"{_where(lines, at)}: an offer is `vendor: ...` and `rate: ...` lines, not `{item}`.")
        for key in item:
            if key not in OFFER_KEYS:
                near = difflib.get_close_matches(str(key), OFFER_KEYS, 1)
                raise Refused(f"{_where(lines, f'{at}.{key}')}: an offer has no `{key}`" + (f"; did you mean `{near[0]}`?" if near else f"; it has {', '.join(OFFER_KEYS)}."))
        for need in ("vendor", "rate"):
            if need not in item:
                raise Refused(f"{_where(lines, at)}: an offer needs a {need}.")
        vendor = _login(item["vendor"], lines, f"{at}.vendor")
        rate = _number(item["rate"], lines, f"{at}.rate")
        budget = _number(item["budget"], lines, f"{at}.budget") if item.get("budget") is not None else None
        if budget is not None and budget < rate:
            raise Refused(f"{_where(lines, f'{at}.budget')}: the budget {budget} is under the rate {rate}: the offer could never pay once.")
        if vendors is not None and vendor not in vendors:
            raise Refused(f"{_where(lines, f'{at}.vendor')}: the offer is for {vendor}, but vendors (line {lines.get('vendors', 0)}) does not list them.")
        if any(o.vendor == vendor for o in out):
            raise Refused(f"{_where(lines, f'{at}.vendor')}: there are two offers for {vendor}.")
        checks = _names(item["checks"], lines, f"{at}.checks", logins=False) if item.get("checks") is not None else None
        out.append(Offer(vendor, rate, budget, checks))
    return tuple(out)


def load(text: str) -> Policy:
    """The policy in `.knos/policy.yml`'s text. Raises Refused, with the line, for anything that is not one."""
    doc, lines = _parse(text)
    for key in doc:
        if key == "labels":         # no workflow funds an issue from its labels: a rule that promised it would fund nothing, silently
            raise Refused(f"{_where(lines, 'labels')}: `labels` is not a rule: a label on an issue funds nothing. A person who may fund "
                          "comments `/knos fund <amount>` on the issue.")
        if key not in RULES:
            near = difflib.get_close_matches(str(key), RULES, 1)
            raise Refused(f"{_where(lines, str(key))}: `{key}` is not a rule" + (f"; did you mean `{near[0]}`?" if near else f". The rules are: {', '.join(RULES)}."))
    given = lambda key: doc.get(key) is not None  # noqa: E731 - a rule left empty (`cap_per_order:`) is a rule not given
    if given("version") and doc["version"] != 1:
        raise Refused(f"{_where(lines, 'version')}: version {doc['version']} is not one this Knos reads (it reads 1).")
    cap = _number(doc["cap_per_order"], lines, "cap_per_order") if given("cap_per_order") else None
    budget = _number(doc["monthly_budget"], lines, "monthly_budget") if given("monthly_budget") else None
    if cap is not None and budget is not None and budget < cap:
        raise Refused(f"{_where(lines, 'monthly_budget')}: the monthly budget {budget} is under the cap per order {cap} (line {lines.get('cap_per_order', 0)}): no order at the cap could ever fit.")
    vendors = _names(doc["vendors"], lines, "vendors") if given("vendors") else None
    days = int(_number(doc["warranty_days"], lines, "warranty_days", low=Decimal(0), high=Decimal(MAX_WARRANTY_DAYS), whole=True, positive=False)) if given("warranty_days") else None
    holdback = None
    if given("holdback_percent"):
        percent = _number(doc["holdback_percent"], lines, "holdback_percent", low=Decimal(0), high=Decimal(MAX_HOLDBACK_PERCENT), positive=False)
        if percent * 100 != (percent * 100).to_integral_value():
            raise Refused(f"{_where(lines, 'holdback_percent')}: holdback_percent has at most two decimals, not {doc['holdback_percent']}.")
        holdback = int(percent * 100)
        if holdback and not days:
            raise Refused(f"{_where(lines, 'holdback_percent')}: a holdback is released after the warranty, so it needs warranty_days (line {lines.get('warranty_days', 0) or 'missing'}).")
    if given("private") and not isinstance(doc["private"], bool):
        raise Refused(f"{_where(lines, 'private')}: private is true or false, not `{doc['private']}`.")
    if given("attestor") and not isinstance(doc["attestor"], str):
        raise Refused(f"{_where(lines, 'attestor')}: attestor is one repository, as owner/name.")
    attestor = _repos(doc["attestor"], lines, "attestor")[0] if given("attestor") else None
    targets = _repos(doc["targets"], lines, "targets") if given("targets") else ()
    if (attestor or targets) and not doc.get("private"):
        rule = "attestor" if attestor else "targets"
        raise Refused(f"{_where(lines, rule)}: {rule} is for private orders, so it needs `private: true` (line {lines.get('private', 0) or 'missing'}).")
    if targets and not attestor:
        raise Refused(f"{_where(lines, 'targets')}: targets are the repositories an attestor reads, so it needs `attestor: owner/name` (line missing).")
    if attestor in targets:
        raise Refused(f"{_where(lines, 'targets')}: {attestor} is the attestor itself; targets are the other repositories it reads.")
    return Policy(
        who_may_fund=_names(doc["who_may_fund"], lines, "who_may_fund") if given("who_may_fund") else None,
        cap_per_order=cap, monthly_budget=budget,
        payees=_names(doc["payees"], lines, "payees") if given("payees") else None, vendors=vendors,
        checks=_names(doc["checks"], lines, "checks", logins=False) if given("checks") else None,
        offers=_offers(doc["offers"], lines, vendors) if given("offers") else (),
        warranty_days=days, holdback_bps=holdback, arbiter=_login(doc["arbiter"], lines, "arbiter") if given("arbiter") else None,
        private=bool(doc.get("private")), attestor=attestor, targets=targets, lines=lines)


# ---- what it says ----------------------------------------------------------------------------------------------------

def _money(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _plain(d: Decimal) -> str:
    return format(d.normalize(), "f")


def _listed(names: tuple[str, ...] | None, who, login: str = "") -> bool:
    return names is None or str(who).strip().lower() in names or bool(login) and login.strip().lower() in names


def _at(policy: Policy, rule: str) -> str:
    n = policy.lines.get(rule, 0)
    return f"{PATH} line {n}" if n else PATH


def allows(policy: Policy, actor_id, amount, month_spent, login: str = "") -> tuple[bool, str]:
    """May this person fund an order of `amount`, when `month_spent` has been funded already this month? (ok, why): the
    reason names the line of the rule that says no, and is empty when nothing does. `actor_id` is a GitHub id (or login);
    `login` is given as well when it is known, since the file may list either."""
    amount, spent = _money(amount), _money(month_spent)
    if not _listed(policy.who_may_fund, actor_id, login):
        who = f"{login} ({actor_id})" if login else str(actor_id)
        return False, f"{_at(policy, 'who_may_fund')}: only {', '.join(policy.who_may_fund or ())} may fund; {who} is not one of them."
    if policy.cap_per_order is not None and amount > policy.cap_per_order:
        return False, f"{_at(policy, 'cap_per_order')}: an order may take at most {_plain(policy.cap_per_order)}, and this one is {_plain(amount)}."
    if policy.monthly_budget is not None and spent + amount > policy.monthly_budget:
        left = max(Decimal(0), policy.monthly_budget - spent)
        return False, (f"{_at(policy, 'monthly_budget')}: the monthly budget is {_plain(policy.monthly_budget)} and {_plain(spent)} is already spent this month, "
                       f"so {_plain(amount)} more would pass it ({_plain(left)} left).")
    return True, ""


def payee_allowed(policy: Policy, payee_id, login: str = "") -> tuple[bool, str]:
    """May this account be paid at all? Under `payees` only those listed."""
    if _listed(policy.payees, payee_id, login):
        return True, ""
    return False, f"{_at(policy, 'payees')}: only {', '.join(policy.payees or ())} may be paid; {login or payee_id} is not one of them."


def offer_for(policy: Policy, vendor, login: str = "") -> Offer | None:
    """The standing offer for this vendor (a login or id), if there is one."""
    return next((o for o in policy.offers if _listed((o.vendor,), vendor, login)), None)


def canonical(policy: Policy) -> bytes:
    """The policy as canonical JSON: only what it says (no comments, no line numbers, no order a person happened to write
    sets in), keys sorted, no spaces, amounts as plain decimals."""
    doc: dict = {"version": 1, "private": policy.private}
    for key in ("who_may_fund", "payees", "vendors", "checks"):
        if getattr(policy, key) is not None:
            doc[key] = sorted(getattr(policy, key))
    for key in ("cap_per_order", "monthly_budget"):
        if getattr(policy, key) is not None:
            doc[key] = _plain(getattr(policy, key))
    if policy.offers:
        doc["offers"] = [{"vendor": o.vendor, "rate": _plain(o.rate), **({"budget": _plain(o.budget)} if o.budget is not None else {}),
                          **({"checks": sorted(o.checks)} if o.checks is not None else {})} for o in sorted(policy.offers, key=lambda o: o.vendor)]
    for key, name in (("warranty_days", "warranty_days"), ("holdback_bps", "holdback_bps"), ("arbiter", "arbiter"), ("attestor", "attestor")):
        if getattr(policy, key) is not None:
            doc[name] = getattr(policy, key)
    if policy.targets:
        doc["targets"] = sorted(policy.targets)
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(policy: Policy) -> str:
    """sha256 (hex) of the canonical JSON: what every order's terms carry, so an order says which policy it was funded under."""
    return hashlib.sha256(canonical(policy)).hexdigest()


def attests(policy: Policy | None, here: str, target: str | None = None) -> tuple[bool, str]:
    """May a run in the repository `here` fund and pay PRIVATE orders (of `target`, when one is named)? Only the
    repository the policy names as its attestor may, and only for a repository its `targets` list. (ok, why)."""
    if policy is None or not policy.private or not policy.attestor:
        return False, (f"{PATH} of {here} names no attestor: private orders need `private: true`, `attestor: {here}` and "
                       "`targets: [owner/name, ...]` there.")
    if policy.attestor != here.strip().lower():
        return False, (f"{_at(policy, 'attestor')}: the attestor is {policy.attestor}, and this run is in {here}. A private order is funded "
                       "and paid only from the attestor repository.")
    if target is not None and target.strip().lower() not in policy.targets:
        return False, f"{_at(policy, 'targets' if policy.targets else 'attestor')}: targets does not list that repository, so this attestor does nothing for it."
    return True, ""


def order_opts(policy: Policy, vendor=None, login: str = "") -> dict:
    """What a funding takes from the policy when its funder says nothing: {"private", "arbiter" (login or id, or None),
    "warranty_days", "holdback_bps", "checks" (names or None), "standing", "rate", "budget"}. With a `vendor` that has a
    standing offer, the order is standing and takes the offer's rate (whole units), monthly budget and checks (its own
    when it names some, else the policy's)."""
    offer = offer_for(policy, vendor, login) if vendor is not None else None
    return {"private": policy.private, "arbiter": policy.arbiter, "warranty_days": policy.warranty_days or 0,
            "holdback_bps": policy.holdback_bps or 0,
            "checks": list((offer.checks if offer and offer.checks is not None else policy.checks) or ()) if (offer and offer.checks is not None) or policy.checks is not None else None,
            "standing": offer is not None, "rate": offer.rate if offer else None, "budget": offer.budget if offer else None}
