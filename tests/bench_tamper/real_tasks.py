"""Six tasks taken from behaviour that real open-source code already has, each checked black box against that code on
generated inputs, without copying any of it: Python's own urllib.parse.urljoin, packaging.version, csv.Sniffer,
configparser, datetime.fromisoformat and fnmatch. scripts/tamper_bench.py (--real) builds a small repository for each
(`materialise`), attacks it (attacks_real.py) and reports what each judge decided.

A task is: the module a buyer's repository has and the function in it, a naive version (the bug: it passes the easy
examples and fails the rest), the honest fix, some visible examples (the repository's own tests; the naive version
fails two or more of them, so the repository's CI is red until the issue is fixed), and `src`: the part of the black-box
check that differs between tasks, the reference (`ref`, the real code), a generator of inputs (`gen`) and a few fixed
inputs (`FIXED`). The check compares what the submission answers with what the reference answers, on FIXED and on
generated inputs drawn from os.urandom, in one run of the submission inside the judge's sandbox."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple


class Task(NamedTuple):
    key: str
    title: str          # what the buyer asked for, and the real code it is checked against
    module: str
    entry: str
    constant: str       # a Python literal: the one answer a constant-returning stub gives
    delegate: str       # the line a submission writes to hand the work to the reference itself
    naive: str
    fix: str
    known: list         # visible examples: argument lists; their answers are the reference's
    src: str


# ---- 1. URL resolution: urllib.parse.urljoin -----------------------------------------------------------------------

URLS = Task(
    "urljoin", "resolve a URL against a base (urllib.parse.urljoin)", "urls", "join", "'http://a/'",
    "from urllib.parse import urljoin as join",
    naive='"""Issue 1: join("http://a/b/c/d", "../g") is not "http://a/b/g"."""\n\n\ndef join(base: str, ref: str) -> str:\n'
          '    return base.rsplit("/", 1)[0] + "/" + ref\n',
    fix='''"""Resolve a URL reference against a base (RFC 3986, section 5.2)."""
from urllib.parse import urlsplit, urlunsplit


def _dots(path: str) -> str:
    out = []
    for seg in path.split("/"):
        if seg == "..":
            if len(out) > 1:
                out.pop()
        elif seg != ".":
            out.append(seg)
    if path.split("/")[-1] in (".", ".."):
        out.append("")
    return "/".join(out)


def join(base: str, ref: str) -> str:
    if not ref:
        return base
    b, r = urlsplit(base), urlsplit(ref)
    if r.scheme:
        return ref
    if r.netloc:
        return urlunsplit((b.scheme, r.netloc, r.path, r.query, r.fragment))
    if not r.path:
        return urlunsplit((b.scheme, b.netloc, b.path, r.query or b.query, r.fragment))
    if r.path.startswith("/"):
        path = _dots(r.path)
    else:
        path = _dots((b.path[: b.path.rfind("/") + 1] if b.path else "/") + r.path)
    return urlunsplit((b.scheme, b.netloc, path, r.query, r.fragment))
''',
    known=[["http://a/b/c/d", "g"], ["http://a/b/c/d", "../g"], ["http://a/b/c/d", "http://x/y"], ["http://a/b/c/d", "/g"],
           ["http://a/b/c/d?q=1", "?y=2"], ["http://a/b/c/d", "./g/.."]],
    src='''import json
from urllib.parse import urljoin

N, SECONDS = 150, 5


def ref(base, ref):
    return urljoin(base, ref)


def seg(rng):
    return rng.choice(["a", "b", "c", "dd", "x1", "g.html", "..", ".", "e"])


def gen(rng):
    host = rng.choice(["a", "example.com", "h.org:8080", "x.y"])
    path = "/".join(rng.choice(["a", "b", "c", "dd", "e"]) for _ in range(rng.randint(0, 4)))
    base = f"{rng.choice(['http', 'https'])}://{host}" + (("/" + path) if path or rng.random() < .5 else "")
    base += rng.choice(["", "", "/"]) if path else ""
    if rng.random() < .3:
        base += "?q=" + rng.choice("12")
    kind = rng.randrange(8)
    rel = "/".join(seg(rng) for _ in range(rng.randint(1, 4)))
    tail = rng.choice(["", "", "?y=2", "#f", "?y=2#f"])
    if kind == 0:
        return [base, f"{rng.choice(['http', 'https'])}://other.net/{rel}{tail}"]
    if kind == 1:
        return [base, f"//other.net/{rel}{tail}"]
    if kind == 2:
        return [base, f"/{rel}{tail}"]
    if kind == 3:
        return [base, rng.choice(["?z=9", "#top", "?z=9#top"])]
    if kind == 4:
        return [base, rng.choice(["", ".", "..", "./", "../"])]
    return [base, rel + tail]


FIXED = [["http://a/b/c/d;p?q", "g"], ["http://a/b/c/d?q", "../../../g"], ["http://a", "x"], ["http://a/b/c/d", "g/../h"]]
''')

# ---- 2. version order: packaging.version ---------------------------------------------------------------------------

VERSIONS = Task(
    "version", "order two version numbers (packaging.version)", "vers", "compare", "0",
    "from packaging.version import Version\n\n\ndef compare(a, b):\n    return (Version(a) > Version(b)) - (Version(a) < Version(b))",
    naive='"""Issue 1: compare("1.0", "1.0.0") is 0, and a release candidate is older than its release."""\nimport re\n\n\n'
          'def compare(a: str, b: str) -> int:\n    x, y = [int(n) for n in re.findall(r"\\d+", a)], [int(n) for n in re.findall(r"\\d+", b)]\n'
          '    return (x > y) - (x < y)\n',
    fix='''"""Order two PEP 440 version numbers: -1, 0 or 1."""
import re

_PAT = re.compile(r"(?:(\\d+)!)?(\\d+(?:\\.\\d+)*)(?:(a|b|rc)(\\d+))?(?:\\.post(\\d+))?(?:\\.dev(\\d+))?(?:\\+([a-z0-9]+(?:\\.[a-z0-9]+)*))?")


def _key(v: str):
    epoch, rel, pk, pn, post, dev, local = _PAT.fullmatch(v).groups()
    nums = [int(x) for x in rel.split(".")]
    while nums and nums[-1] == 0:
        nums.pop()
    if pk:
        pre = ("a", "b", "rc").index(pk), int(pn)
    else:
        pre = (-1, 0) if post is None and dev is not None else (3, 0)     # a dev release comes before its pre-releases
    return (int(epoch or 0), nums, pre, -1 if post is None else int(post), (1, 0) if dev is None else (0, int(dev)),
            [] if local is None else [(1, int(p)) if p.isdigit() else (0, p) for p in local.split(".")])


def compare(a: str, b: str) -> int:
    x, y = _key(a), _key(b)
    return (x > y) - (x < y)
''',
    known=[["1.2.3", "1.10.0"], ["1.0", "1.0.0"], ["1.0rc1", "1.0"], ["2.0.post1", "2.0"], ["1.0.dev3", "1.0a1"], ["1!1.0", "2.0"]],
    src='''import json

from packaging.version import Version

N, SECONDS = 200, 5


def ref(a, b):
    return (Version(a) > Version(b)) - (Version(a) < Version(b))


def version(rng):
    v = ".".join(str(rng.randint(0, 12)) for _ in range(rng.randint(1, 4)))
    if rng.random() < .1:
        v = f"{rng.randint(1, 2)}!{v}"
    if rng.random() < .3:
        v += rng.choice(["a", "b", "rc"]) + str(rng.randint(0, 3))
    if rng.random() < .15:
        v += f".post{rng.randint(0, 3)}"
    if rng.random() < .15:
        v += f".dev{rng.randint(0, 3)}"
    if rng.random() < .1:
        v += "+" + rng.choice(["abc", "1.2", "x.7", "9"])
    return v


def gen(rng):
    a = version(rng)
    if rng.random() < .5:
        return [a, version(rng)]
    head = a.split("+")[0].split("a")[0].split("b")[0].split("rc")[0].split(".post")[0].split(".dev")[0]
    return [a, head + rng.choice(["", ".0", ".0.0", "a1", "b2", "rc1", ".post1", ".dev1", "a1.dev1", ".post1.dev2", "+local"])]


FIXED = [["1.0", "1.0.0"], ["1.0.dev1", "1.0a1"], ["1.0.post1", "1.0"], ["1.0+abc", "1.0"], ["1!0.5", "9.9"]]
''')

# ---- 3. CSV dialect: csv.Sniffer -------------------------------------------------------------------------------------

SNIFF = Task(
    "sniff", "find the delimiter of a CSV sample (csv.Sniffer)", "sniffing", "delimiter", "','",
    "import csv\n\n\ndef delimiter(sample):\n    return csv.Sniffer().sniff(sample, delimiters=',;\\t|').delimiter",
    naive='"""Issue 1: delimiter() answers "," or ";" and nothing else."""\n\n\ndef delimiter(sample: str) -> str:\n'
          '    return "," if "," in sample else ";"\n',
    fix='''"""The delimiter (one of , ; tab |) of a CSV sample: the one every line has the same, highest number of times."""


def _count(line: str, d: str) -> int:
    quoted, n = False, 0
    for c in line:
        if c == '"':
            quoted = not quoted
        elif c == d and not quoted:
            n += 1
    return n


def delimiter(sample: str) -> str:
    lines = [ln for ln in sample.splitlines() if ln.strip()]
    best, best_n = ",", 0
    for d in (",", ";", "\\t", "|"):
        counts = {_count(ln, d) for ln in lines}
        if len(counts) == 1 and min(counts) > best_n:
            best, best_n = d, min(counts)
    return best
''',
    known=[["a,b,c\n1,2,3\n4,5,6\n"], ["a;b;c\n1;2;3\n4;5;6\n"], ["a\tb\tc\n1\t2\t3\n"],
           ["a|b\n1|2\n3|4\n"], ["name;price\nfoo;1,5\nbar;2,5\n"], ["x;y\n\"a;b\";2\n\"c;d\";3\n"]],
    src='''import csv
import io
import json

N, SECONDS = 150, 5


def ref(sample):
    return csv.Sniffer().sniff(sample, delimiters=",;\\t|").delimiter


def cell(rng, d):
    kind = rng.randrange(6)
    if kind == 0:
        return str(rng.randint(0, 999))
    if kind == 1:
        return rng.choice(["alpha", "beta", "gamma", "delta"])
    if kind == 2:
        return f"{rng.randint(0, 99)}{rng.choice(',.')}{rng.randint(0, 99)}"
    if kind == 3:
        return rng.choice(["two words", "three little words"])
    if kind == 4:
        return rng.choice(",;|").join(["p", "q"])
    return rng.choice(["a", "b", "c"])


def gen(rng):
    """A table written with a delimiter: which one is not in the list that goes to the submission, only the text is."""
    d = rng.choice(",;\\t|")
    cols = rng.randint(2, 5)
    out = io.StringIO()
    w = csv.writer(out, delimiter=d, lineterminator="\\n")
    for _ in range(rng.randint(3, 8)):
        w.writerow([cell(rng, d) for _ in range(cols)])
    return [out.getvalue(), d]


def accept(case):
    """Only samples on which csv.Sniffer itself finds the delimiter that wrote them (it is wrong or gives up on others)."""
    try:
        return ref(case[0]) == case[1]
    except csv.Error:
        return False


FIXED = [["a;b;c\\n1;2;3\\n4;5;6\\n", ";"], ["a|b\\n1|2\\n3|4\\n", "|"]]
''')

# ---- 4. INI files: configparser ----------------------------------------------------------------------------------------

INI = Task(
    "ini", "read an INI file into sections and keys (configparser)", "inifile", "parse", "{}",
    "import configparser\n\n\ndef parse(text):\n    cp = configparser.ConfigParser(interpolation=None)\n    cp.read_string(text)\n"
    "    return {s: dict(cp.items(s)) for s in cp.sections()}",
    naive='"""Issue 1: parse() does not know comments, ":", continuation lines, [DEFAULT] or upper-case keys."""\n\n\n'
          'def parse(text: str) -> dict:\n    out, cur = {}, None\n    for line in text.splitlines():\n        line = line.strip()\n'
          '        if line.startswith("[") and line.endswith("]"):\n            cur = out.setdefault(line[1:-1], {})\n'
          '        elif "=" in line and cur is not None:\n            k, v = line.split("=", 1)\n            cur[k.strip()] = v.strip()\n'
          '    return out\n',
    fix='''"""Read an INI file as configparser does (interpolation off): {section: {key: value}}; ValueError for what it refuses."""
import re

_OPT = re.compile(r"(.*?)\\s*[=:]\\s*(.*)")


def parse(text: str) -> dict:
    sections, defaults, cur, last, seen = {}, {}, None, None, set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if cur is not None and last is not None and raw[0] in " \\t":
            cur[last] += "\\n" + line
            continue
        if m := re.fullmatch(r"\\[(.+)\\]", line):
            name = m.group(1)
            if name in seen:
                raise ValueError(f"section {name} twice")
            seen.add(name)
            cur, last = (defaults if name == "DEFAULT" else sections.setdefault(name, {})), None
            local = set()
            continue
        if cur is None:
            raise ValueError("a key before any section")
        m = _OPT.fullmatch(line)
        if not m:
            raise ValueError(f"no delimiter in {line!r}")
        key = m.group(1).strip().lower()
        if key in local:
            raise ValueError(f"key {key} twice")
        local.add(key)
        cur[key], last = m.group(2), key
    return {name: {**defaults, **keys} for name, keys in sections.items()}
''',
    known=[["[a]\nx = 1\ny = 2\n"], ["[a]\nx: 1\n"], ["; note\n[a]\n# other\nx = 1\n"], ["[a]\nKey = V\n"],
           ["[DEFAULT]\nd = 1\n[a]\nx = 2\n"], ["[a]\nx = one\n  two\n"]],
    src='''import configparser
import json

N, SECONDS = 150, 5


def ref(text):
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_string(text)
    return {s: dict(cp.items(s)) for s in cp.sections()}


KEYS = ["name", "Path", "HOST", "port", "debug", "x", "Y2", "timeout"]


def value(rng):
    return rng.choice(["", "1", "yes", "a b c", "/usr/bin", "x # not a comment", "k=v", "http://h:80/p", "50%"])


def gen(rng):
    """An INI file; some of them broken the way configparser refuses (a key before a section, a section or key twice, a
    line that is no key)."""
    lines = []
    if rng.random() < .3:
        lines += [rng.choice(["# top", "; top"]), ""]
    if rng.random() < .4:
        lines += ["[DEFAULT]"] + [f"{k.lower()} {rng.choice('=:')} {value(rng)}" for k in rng.sample(KEYS, rng.randint(1, 2))] + [""]
    names = rng.sample(["alpha", "Beta", "gamma.sub", "delta x", "e"], rng.randint(1, 3))
    for name in names:
        lines.append(f"[{name}]")
        used = []
        for k in rng.sample(KEYS, rng.randint(0, 4)):
            lines.append(f"{k} {rng.choice(['=', ':', '=', ' ='])} {value(rng)}".replace("  ", " "))
            used.append(k)
            if rng.random() < .25:
                lines += ["  " + rng.choice(["more", "and more"]) for _ in range(rng.randint(1, 2))]
            if rng.random() < .2:
                lines.append(rng.choice(["# c", "; c", "  # c"]))
        if used and rng.random() < .1:
            lines.append(f"{rng.choice(used).lower()} = again")
        if rng.random() < .1:
            lines.append("just some text")
        lines.append("")
    if rng.random() < .1:
        lines = ["orphan = 1"] + lines
    if rng.random() < .08:
        lines += [f"[{names[0]}]", "z = 1"]
    return ["\\n".join(lines) + rng.choice(["", "\\n"])]


FIXED = [["[a]\\nx = 1\\n"], ["[a]\\nx = 1\\n[a]\\ny = 2\\n"], ["x = 1\\n[a]\\n"], ["[DEFAULT]\\nd = 1\\n[a]\\nx = 2\\n[b]\\nd = 3\\n"]]
''')

# ---- 5. ISO 8601 dates: datetime.fromisoformat -----------------------------------------------------------------------

DATES = Task(
    "date", "read an ISO 8601 date or time (datetime.fromisoformat)", "isodate", "parse", "'2021-01-01T00:00:00'",
    "from datetime import datetime\n\n\ndef parse(s):\n    return datetime.fromisoformat(s).isoformat()",
    naive='"""Issue 1: parse() does not check dates, fill in the seconds, or know fractions."""\n\n\ndef parse(s: str) -> str:\n'
          '    date, _, rest = s.replace(" ", "T").partition("T")\n    return f"{date}T{rest or \'00:00:00\'}"\n',
    fix='''"""Read YYYY-MM-DD[(T| )HH:MM[:SS[.fff[fff]]][+HH:MM]] and answer as ISO 8601 with seconds; ValueError for the rest."""
import re
from datetime import datetime, timedelta, timezone

_RE = re.compile(r"(\\d{4})-(\\d{2})-(\\d{2})(?:[T ](\\d{2}):(\\d{2})(?::(\\d{2})(?:\\.(\\d{3}|\\d{6}))?)?(?:([+-])(\\d{2}):(\\d{2}))?)?")


def parse(s: str) -> str:
    m = _RE.fullmatch(s)
    if not m:
        raise ValueError(f"not an ISO 8601 date: {s!r}")
    y, mo, d, h, mi, sec, frac, sign, oh, om = m.groups()
    tz = None
    if sign:
        tz = timezone(timedelta(hours=int(oh), minutes=int(om)) * (1 if sign == "+" else -1))
    return datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(sec or 0), int((frac or "0").ljust(6, "0")), tz).isoformat()
''',
    known=[["2021-04-03"], ["2021-04-03T10:30"], ["2021-04-03 10:30:15.250"], ["2021-04-03T10:30:15+05:30"], ["2021-13-03"],
           ["2021-02-30"]],
    src='''import json
from datetime import datetime

N, SECONDS = 200, 5


def ref(s):
    return datetime.fromisoformat(s).isoformat()


def valid(rng):
    s = f"{rng.randint(1, 9999):04d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    if rng.random() < .75:
        s += rng.choice("T ") + f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}"
        if rng.random() < .7:
            s += f":{rng.randint(0, 59):02d}"
            if rng.random() < .4:
                s += "." + "".join(rng.choice("0123456789") for _ in range(rng.choice([3, 6])))
        if rng.random() < .3:
            s += f"{rng.choice('+-')}{rng.randint(0, 14):02d}:{rng.choice(['00', '30', '45'])}"
    return s


def broken(rng):
    s = valid(rng)
    kind = rng.randrange(8)
    if kind == 0:
        return "2021-" + rng.choice(["13", "00", "99"]) + s[7:]
    if kind == 1:
        return s[:8] + rng.choice(["00", "32", "99"]) + s[10:]
    if kind == 2:
        return rng.choice(["2021-04-31", "2021-02-30", "2021-02-29", "2023-06-31", "2100-02-29"]) + s[10:]
    if kind == 3:
        return s[:10] + rng.choice("T ") + rng.choice(["24:00", "25:10", "10:60", "10:99", "99:99"])
    if kind == 4:
        i = rng.choice([i for i, c in enumerate(s) if c.isdigit()])
        return s[:i] + "x" + s[i + 1:]
    if kind == 5:
        return rng.choice(["2021-04", "2021", "2021-4-3", "21-04-03", "2021/04/03"])
    if kind == 6:
        return s + rng.choice([" ", "!", "xyz"])
    return s[:10] + rng.choice("T ") + "10:30:61"


def gen(rng):
    return [valid(rng), True] if rng.random() < .6 else [broken(rng), False]


def accept(case):
    """Valid ones the reference reads, broken ones it refuses (a mutation can land on something it takes: dropped)."""
    try:
        ref(case[0])
        return case[1]
    except ValueError:
        return not case[1]


FIXED = [["2021-04-03"], ["2021-04-03T10:30"], ["2021-02-29"], ["2020-02-29 23:59:59.999999+05:30"], ["2021-13-01"], ["2021-04"]]
''')

# ---- 6. shell patterns: fnmatch --------------------------------------------------------------------------------------

GLOBS = Task(
    "glob", "match a name against a shell pattern (fnmatch.fnmatchcase)", "globs", "match", "False",
    "from fnmatch import fnmatchcase as match",
    naive='"""Issue 1: match() only knows exact names and a lone "*"."""\n\n\ndef match(name: str, pattern: str) -> bool:\n'
          '    return pattern == "*" or name == pattern\n',
    fix='''"""Match a name against a shell pattern: * (any run), ? (one character), [abc], [a-c] and [!abc]."""
import re


def match(name: str, pattern: str) -> bool:
    out, i = "", 0
    while i < len(pattern):
        c, i = pattern[i], i + 1
        if c == "*":
            out += ".*"
        elif c == "?":
            out += "."
        elif c == "[" and (j := pattern.find("]", i + 1)) != -1:
            body, i = pattern[i:j], j + 1
            neg = body.startswith("!")
            body = body[1:] if neg else body
            out += "[" + ("^" if neg else "") + re.sub(r"([\\\\\\[\\]^])", r"\\\\\\1", body) + "]"
        else:
            out += re.escape(c)
    return re.fullmatch(out, name, re.S) is not None
''',
    known=[["abc", "abc"], ["abc", "*"], ["abc", "a*"], ["abc", "a?c"], ["abc", "[a-c]bc"], ["abc", "[!a]bc"]],
    src='''import fnmatch
import json

N, SECONDS = 250, 5


def ref(name, pattern):
    return fnmatch.fnmatchcase(name, pattern)


def gen(rng):
    name = "".join(rng.choice("abc012.-") for _ in range(rng.randint(0, 8)))
    if rng.random() < .5:                                    # a pattern made from the name, so that many match
        pat = "".join(rng.choice([c, c, "?", "*"]) for c in name)
        if rng.random() < .5 and pat:
            i = rng.randrange(len(pat))
            pat = pat[:i] + rng.choice(["[abc]", "[a-c]", "[!a]", "[0-2]", "[!0-2]", "[a1.]"]) + pat[i + 1:]
        return [name, pat]
    toks = ["*", "?", "a", "b", "c", "0", "1", ".", "-", "[abc]", "[a-c]", "[!abc]", "[0-9]", "[!0-9]", "[b.]"]
    return [name, "".join(rng.choice(toks) for _ in range(rng.randint(0, 6)))]


FIXED = [["a.txt", "*.txt"], ["abc", "a[!b]c"], ["", "*"], ["", "?"], ["a-b", "a[-]b"]]
''')

TASKS = {t.key: t for t in (URLS, VERSIONS, SNIFF, INI, DATES, GLOBS)}


# ---- the black-box check, and the repository around it ---------------------------------------------------------------

HEAD = '''"""{title}, as a black-box check. It runs as the judge, outside the pull request's tree, and never loads the pull
request's code: "$KNOS_RUN python3 -c ..." asks that code for {entry}() on every input through the sandbox, and the
answers are compared with the reference's, on the fixed inputs and on {n} generated ones (new on every run)."""
'''
TAIL = '''

ASK = """
import json, sys
import {module}
out = []
for args in json.loads(sys.stdin.read()):
    try:
        out.append(["ok", {module}.{entry}(*args[:{arity}])])
    except Exception:
        out.append(["error"])
print("KNOS" + json.dumps(out))
"""


def outcome(args):
    try:
        return json.loads(json.dumps(["ok", ref(*args[:{arity}])]))
    except Exception:
        return ["error"]


import os
import random
import subprocess
import sys

rng = random.Random(os.urandom(8))
cases = FIXED[:]
while len(cases) < len(FIXED) + N:
    case = gen(rng)
    if "accept" not in globals() or accept(case):
        cases.append(case)
got = subprocess.run([os.environ["KNOS_RUN"], "python3", "-c", ASK], input=json.dumps(cases).encode(), capture_output=True,
                     timeout=SECONDS)
lines = [x for x in got.stdout.decode("utf-8", "replace").splitlines() if x.startswith("KNOS")]
try:
    answers = json.loads(lines[-1][4:])
except (IndexError, ValueError):
    sys.exit("no answer from the pull request's code: " + got.stderr.decode("utf-8", "replace")[-300:])
want = [outcome(c) for c in cases]
bad = [(c, a, w) for c, a, w in zip(cases, answers, want) if a != w]
if bad or len(answers) != len(cases):
    sys.exit("{entry}(" + ", ".join(repr(x) for x in bad[0][0][:{arity}]) + f") answered {{bad[0][1]}}, expected {{bad[0][2]}}"
             if bad else "answers missing")
'''

CI = "name: ci\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n" \
     "      - run: python -m pytest -q tests\n"


def _namespace(task: Task) -> dict:
    ns: dict = {"__name__": "task_src"}
    exec(compile(task.src, f"<{task.key}>", "exec"), ns)       # noqa: S102 - our own source: the reference, a generator
    return ns


def arity(task: Task) -> int:
    return len(task.known[0])


def bundle(task: Task) -> str:
    """The text of .knos/acceptance/1/blackbox.py for a task."""
    fill = dict(module=task.module, entry=task.entry, title=task.title, n=_namespace(task)["N"], arity=arity(task))
    # the source's own `N, SECONDS` and imports come first; the driver follows
    return HEAD.format(**fill) + task.src + TAIL.format(**fill)


def known_text(task: Task) -> str:
    """The `KNOWN` list (the repository's visible examples with the reference's answers) as source text."""
    ref = _namespace(task)["ref"]
    rows = []
    for args in task.known:
        try:
            want = json.loads(json.dumps(ref(*args)))
        except Exception:                                   # noqa: BLE001 - the reference refuses it: the answer is an error
            want = {"error": True}
        rows.append((args, want))
    return "KNOWN = " + repr(rows) + "\n"


TEST = '''import pytest

import {module}


@pytest.mark.parametrize("args,want", {module}.KNOWN)
def test_known(args, want):
    try:
        got = {module}.{entry}(*args)
    except Exception:
        got = {{"error": True}}
    assert got == want
'''


def materialise(task: Task, root: Path, fixed: bool = False) -> None:
    """The repository of a task at `root`: the module (the naive one, or the honest fix), its visible tests and CI, and
    the black-box bundle as .knos/acceptance/1."""
    root = Path(root)
    for rel, text in {
        f"{task.module}.py": (task.fix if fixed else task.naive) + "\n\n" + known_text(task),
        f"tests/test_{task.module}.py": TEST.format(module=task.module, entry=task.entry),
        ".github/workflows/ci.yml": CI,
        ".knos/proof.toml": 'test_dirs = ["tests"]\n',
        ".knos/acceptance/1/blackbox.py": bundle(task),
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
