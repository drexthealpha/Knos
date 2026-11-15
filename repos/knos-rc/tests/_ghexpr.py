"""GitHub Actions expressions, enough of them to run a job's `if:` against an event without GitHub.

    runs("github.event_name == 'push' && startsWith(github.ref, 'refs/heads/')", {"github": {...}})

The rules are GitHub's (docs: "Evaluate expressions in workflows and actions"): strings compare without regard to case,
values of different types are compared as numbers (null and '' are 0, a string that is no number is NaN), `&&` and
`||` give back one of their operands, a missing property is null, and `contains`, `startsWith` and `endsWith` ignore
case. A job with `needs` whose condition calls no status function runs only when every job it needs succeeded.
Anything this file does not know raises: a condition must not pass a test by being misread.
"""
from __future__ import annotations

import json
import math
import re

_TOKEN = re.compile(r"\s*(?:(?P<num>\d+(?:\.\d+)?)|'(?P<str>(?:[^']|'')*)'|(?P<op>\|\||&&|==|!=|[()!,.])|(?P<name>[A-Za-z_][\w-]*))")
_STATUS = re.compile(r"\b(always|cancelled|success|failure)\s*\(")


def truthy(v) -> bool:
    if isinstance(v, float) and math.isnan(v):
        return False
    return not (v is None or v is False or v == "" or (isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0))


def _number(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip()) if v.strip() else 0.0
        except ValueError:
            return math.nan
    return math.nan      # an object or an array


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (dict, list)):
        return "Object" if isinstance(v, dict) else "Array"
    return str(v)


def equal(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a.lower() == b.lower()
    plain = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)  # noqa: E731
    if (plain(a) and plain(b)) or type(a) is type(b):
        return a is b if isinstance(a, (dict, list)) else a == b
    return _number(a) == _number(b)      # NaN equals nothing


def _format(fmt, *args) -> str:
    out = re.sub(r"\{(\d+)\}", lambda m: _text(args[int(m.group(1))]), _text(fmt).replace("{{", "\0").replace("}}", "\1"))
    return out.replace("\0", "{").replace("\1", "}")


def _contains(search, item) -> bool:
    if isinstance(search, list):
        return any(equal(x, item) for x in search)
    return _text(item).lower() in _text(search).lower()


class _Run:
    def __init__(self, text: str, context: dict, status: str):
        self.toks, at = [], 0
        while at < len(text.rstrip()):
            m = _TOKEN.match(text, at)
            if not m:
                raise ValueError(f"cannot read the expression at: {text[at:at + 30]!r}")
            self.toks.append((m.lastgroup, m.group(m.lastgroup)))
            at = m.end()
        self.i, self.context, self.status = 0, context, status
        self.functions = {
            "startsWith": lambda a, b: _text(a).lower().startswith(_text(b).lower()),
            "endsWith": lambda a, b: _text(a).lower().endswith(_text(b).lower()),
            "contains": _contains, "format": _format, "fromJSON": lambda s: json.loads(_text(s)),
            "always": lambda: True, "cancelled": lambda: status == "cancelled",
            "success": lambda: status == "success", "failure": lambda: status == "failure",
        }

    def peek(self, kind: str, value: str | None = None) -> bool:
        return self.i < len(self.toks) and self.toks[self.i][0] == kind and value in (None, self.toks[self.i][1])

    def take(self, kind: str, value: str | None = None) -> str:
        if not self.peek(kind, value):
            raise ValueError(f"expected {value or kind} at token {self.i}: {self.toks[self.i:self.i + 3]}")
        self.i += 1
        return self.toks[self.i - 1][1]

    def either(self):                        # a || b
        left = self.both()
        while self.peek("op", "||"):
            self.i += 1
            right = self.both()
            left = left if truthy(left) else right
        return left

    def both(self):                          # a && b
        left = self.same()
        while self.peek("op", "&&"):
            self.i += 1
            right = self.same()
            left = right if truthy(left) else left
        return left

    def same(self):                          # a == b, a != b
        left = self.one()
        while self.peek("op", "==") or self.peek("op", "!="):
            op = self.take("op")
            right = self.one()
            left = equal(left, right) if op == "==" else not equal(left, right)
        return left

    def one(self):
        if self.peek("op", "!"):
            self.i += 1
            return not truthy(self.one())
        if self.peek("op", "("):
            self.i += 1
            value = self.either()
            self.take("op", ")")
            return value
        if self.peek("num"):
            return float(self.take("num"))
        if self.peek("str"):
            return self.take("str").replace("''", "'")
        name = self.take("name")
        if name in ("true", "false", "null"):
            return {"true": True, "false": False, "null": None}[name]
        if self.peek("op", "("):
            self.i += 1
            args = []
            while not self.peek("op", ")"):
                args.append(self.either())
                if not self.peek("op", ")"):
                    self.take("op", ",")
            self.i += 1
            if name not in self.functions:
                raise ValueError(f"no function {name}() here")
            return self.functions[name](*args)
        if name not in self.context:
            raise ValueError(f"no context {name} here")
        value = self.context[name]
        while self.peek("op", "."):
            self.i += 1
            key = self.take("name")
            value = value.get(key) if isinstance(value, dict) else None      # a missing property is null
        return value


def value(text: str, context: dict, status: str = "success"):
    """What the expression evaluates to. `status` answers always(), cancelled(), success() and failure()."""
    run = _Run(text, context, status)
    got = run.either()
    if run.i != len(run.toks):
        raise ValueError(f"the expression goes on after its end: {run.toks[run.i:run.i + 3]}")
    return got


def runs(condition: str | None, context: dict, needs: dict[str, str] | None = None, cancelled: bool = False) -> bool:
    """Whether a job with this `if:` runs. `needs`: the result of each job it needs (success, failure, skipped,
    cancelled), also given to the expression as needs.<job>.result unless the context has its own `needs`."""
    needs = needs or {}
    context = {"needs": {job: {"result": result, "outputs": {}} for job, result in needs.items()}, **context}
    condition = "success()" if condition is None else str(condition)
    ok = not cancelled and all(result == "success" for result in needs.values())
    if not _STATUS.search(condition) and not ok:
        return False             # GitHub puts `success() &&` before a condition that calls no status function
    return truthy(value(condition, context, "cancelled" if cancelled else "success" if ok else "failure"))
