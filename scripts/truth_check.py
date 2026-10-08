"""Find statements in the public documents that contradict each other, the capability manifest or the source.

    python scripts/truth_check.py            # print every contradiction as file:line, exit 1 when there is one
    python scripts/truth_check.py --json     # the same, as JSON

What is read (`DOCS`): README.md, every docs/*.md, docs/submission/*.md, the site's web/*.js and web/*.html, and the
notes of docs/capabilities.json. What they are held
against: docs/capabilities.json (the stage of each capability, the version each public id runs), src/knos (who calls
what), src/knos/billing.py (the price book) and src/knos/fees.py with settle/v2/pay.py (the two fee rules).

The rules, each with a planted contradiction in tests/test_truth_check.py:

    stage     a statement says "not built", "not wired", "not deployed", "planned" about a capability whose stage is
              tested or higher; or says deployed, exercised or live about one whose stage is lower
    calls     a statement says nothing calls a function ("nothing calls it", "does not ask it yet") that the source calls
    price     a price that is not the price book's (Meter, Record, Control, Pilot, the Acceptance rate)
    fee       a fee rate that neither build of knos_pay charges
    version   a version said to be live at a public id that is not the one docs/capabilities.json records
    count     two documents count the same thing (programs, capabilities, tests passed) differently, or a count of
              capabilities is not the number of rows
    release   a page names a release older than pyproject.toml's version as the current one ("this release (0.3.18)",
              "as Knos 0.3.14 has it")
    live      a statement says the public knos_pay charges a fee, or has a quorum fix, that the build docs/capabilities.json
              records at its public id does not have ("today ... 0.30%" while 2.1 runs; "the quorum is fixed" before 2.2)
    published a statement says a package Knos has published (PUBLISHED: the two interface crates on crates.io, the JS
              client on npm) is "not published", "unpublished", "none published", "neither has been published" or
              "not on crates.io / npm"

A statement is one sentence of a paragraph, one table row or one list item. A statement about the past ("was",
"until", "withdrawn", "0.3.14") is not held to today's price. The checker reads; it changes nothing.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "docs/*.md", "docs/submission/*.md", "web/*.js", "web/*.html")
MANIFEST = "docs/capabilities.json"
STAGES = ("implemented", "tested", "deployed", "exercised", "reproduced")

# what a document may call a capability besides its id in backticks: the plain name a price book or a pitch uses
SUBJECTS: dict[str, str] = {
    "record_lookup_paid": r"\bRecord\b[^.]*\b(API|hosted lookup|lookup server)\b|\b(hosted lookup|machine-priced API)\b|\bAPI (\(|that is )not built",
    "approval_chains": r"\bapprovals?\.gate\b|\bthe approval gate\b",
    "work_orders": r"\bwork orders\b",
}

NOT_BUILT = re.compile(r"\b(not built|not wired|nothing calls it|not implemented|is planned|planned, not|not written yet)\b", re.I)
NOT_DEPLOYED = re.compile(r"\b(not deployed|never deployed|not on devnet|tested here only|tested locally only|only tested (?:here|locally)|local only)\b", re.I)
NOT_CALLED = re.compile(r"\b(nothing calls (it|this)|no(thing| code| workflow)? calls (it|this)|does not (ask|call) (it|the gate)( yet)?|is not called)\b", re.I)
SAYS = {"deployed": re.compile(r"\*\*Deployed on devnet:?\*\*:?|\b(is|are) deployed (on devnet|at (its|the) public)", re.I),
        "exercised": re.compile(r"\*\*Exercised on devnet:?\*\*:?|\b(is|are|was|were) exercised (on devnet|at (its|the) public)", re.I),
        "reproduced": re.compile(r"\*\*Reproduced by someone else:?\*\*:?|\b(is|are|was|were) reproduced by (someone|an outsider)", re.I)}
PAST = re.compile(r"\b(was|were|until|withdrawn|earlier|before|used to|no longer|old|replaced|0\.3\.1[0-7]|history|historic)\b", re.I)
NOT_LIVE_YET = re.compile(r"\b(propos\w*|pending|would|will|once|after|until|next|when|staging|upgrade\w*|replace\w*|approved|execut\w*|from|since|"
                          r"later|then|new|simulat\w*|rehears\w*|verified build)\b", re.I)
LIVE = re.compile(r"\b(LIVE|is live|are live|live at|live on|runs|run|running)\b")
MONEY = r"(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
THOUSANDS = r"(\d{1,3}(?:,\d{3})+|\d{4,})"                 # a yearly price: never a count of jobs or seats
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


@dataclass(frozen=True)
class Statement:
    file: str
    line: int
    text: str


@dataclass(frozen=True)
class Problem:
    rule: str
    file: str
    line: int
    said: str
    against: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: [{self.rule}] says: {self.said[:220]}\n    against: {self.against}"


def files(root: Path = ROOT, docs: Iterable[str] = DOCS) -> list[str]:
    out: list[str] = []
    for pattern in docs:
        out += sorted(Path(p).relative_to(root).as_posix() for p in glob.glob(str(root / pattern)) if Path(p).is_file())
    return out


_TAG = re.compile(r"<[^>]+>")
_END = re.compile(r"(?<=[.!?])[\"')*]*\s+(?=[A-Z`*\[(])")


def statements_of(rel: str, text: str) -> list[Statement]:
    """Markdown: a table row or a list item is one statement; a paragraph is split into its sentences, each at the line
    it starts on. Site files: one line is one statement, tags and comment-only lines dropped."""
    out: list[Statement] = []
    lines = text.splitlines()
    if not rel.endswith(".md"):
        for n, line in enumerate(lines, 1):
            s = _TAG.sub(" ", line).strip()
            if s and not s.startswith(("//", "*", "/*", "<!--")):
                out.append(Statement(rel, n, s))
        return out
    block: list[tuple[int, str]] = []

    def flush() -> None:
        if not block:
            return
        joined, starts, at = "", [], 0
        for n, piece in block:
            starts.append((at, n))
            joined += piece + " "
            at = len(joined)
        pos = 0
        for part in _END.split(joined.strip()):
            where = joined.find(part, pos)
            pos = where + len(part)
            line_no = max((n for a, n in starts if a <= where), default=block[0][0])
            if part.strip():
                out.append(Statement(rel, line_no, part.strip()))
        block.clear()

    fenced = False
    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        if not s or s.startswith("#"):
            flush()
        elif s.startswith("|"):
            flush()
            out.append(Statement(rel, n, s))
        elif re.match(r"([-*+]|\d+\.)\s", s):
            flush()
            block.append((n, s))
        else:
            block.append((n, s))
    flush()
    return out


def statements(root: Path = ROOT, docs: Iterable[str] = DOCS) -> list[Statement]:
    out: list[Statement] = []
    for rel in files(root, docs):
        out += statements_of(rel, (root / rel).read_text(encoding="utf-8", errors="replace"))
    data = load(root)
    raw = (root / MANIFEST).read_text(encoding="utf-8") if (root / MANIFEST).is_file() else ""
    for c in data.get("capabilities", []):
        if c.get("note"):                                    # a note is a public statement too: CAPABILITIES.md prints it
            at = raw.find(json.dumps(c["id"]))
            out.append(Statement(MANIFEST, raw.count("\n", 0, max(at, 0)) + 1, f"`{c['id']}`: {c['note']}"))
    return out


def load(root: Path = ROOT) -> dict:
    path = root / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def rank(stage: str | None) -> int:
    return STAGES.index(stage) + 1 if stage in STAGES else 0


def names_of(c: dict) -> re.Pattern[str]:
    """How a statement names a capability: its id in backticks, or its plain name in SUBJECTS."""
    parts = [r"`" + re.escape(c["id"]) + r"`"]
    if c["id"] in SUBJECTS:
        parts.append(SUBJECTS[c["id"]])
    return re.compile("|".join(f"(?:{p})" for p in parts))


# ---- stage


def _segments(text: str) -> list[tuple[str, str]]:
    """What a statement says is at which stage, as (stage, the text it says it of). A label, as in README's
    "**Exercised on devnet:** `a`, `b`. **Deployed on devnet:** `c`.", speaks of what follows it up to the next label;
    a verb ("`a` is deployed on devnet") speaks of its whole sentence."""
    marks = sorted((m.start(), m.end(), stage, m.group(0).startswith("**")) for stage, rx in SAYS.items() for m in rx.finditer(text))
    return [(stage, text[end:(marks[i + 1][0] if i + 1 < len(marks) else len(text))] if label else text)
            for i, (_start, end, stage, label) in enumerate(marks)]


def stage_problems(stmts: list[Statement], data: dict) -> list[Problem]:
    out: list[Problem] = []
    caps = [(c, names_of(c)) for c in data.get("capabilities", [])]
    for s in stmts:
        if s.file == "docs/CAPABILITIES.md" and s.text.startswith("|"):
            continue                                         # the generated table: scripts/capabilities.py check owns it
        low, undeployed = NOT_BUILT.search(s.text), NOT_DEPLOYED.search(s.text)
        segments = _segments(s.text)
        if not (low or undeployed or segments):
            continue
        for c, rx in caps:
            if not rx.search(s.text):
                continue
            stage = c.get("stage")
            if s.file == MANIFEST and not s.text.startswith(f"`{c['id']}`"):
                continue
            if low and rank(stage) >= rank("tested"):
                out.append(Problem("stage", s.file, s.line, s.text, f'{MANIFEST}: `{c["id"]}` is at stage "{stage}", and this says "{low.group(0)}"'))
            elif undeployed and rank(stage) >= rank("deployed"):
                out.append(Problem("stage", s.file, s.line, s.text, f'{MANIFEST}: `{c["id"]}` is at stage "{stage}", and this says "{undeployed.group(0)}"'))
            for said, tail in segments:
                if rx.search(tail) and rank(stage) < rank(said):
                    out.append(Problem("stage", s.file, s.line, s.text, f'{MANIFEST}: `{c["id"]}` is at stage "{stage or "not built"}", and this says {said}'))
    return out


# ---- calls


_DOTTED = re.compile(r"`(?:knos\.)?([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)(?:\(\))?`")


def callers(root: Path, module: str, name: str) -> list[str]:
    """The modules of src/knos, other than `module` itself, that call `module.name(`."""
    src = root / "src" / "knos"
    if not (src / f"{module}.py").is_file():
        return []
    call = re.compile(r"\b" + re.escape(module) + r"\." + re.escape(name) + r"\(")
    return sorted(p.relative_to(root).as_posix() for p in src.rglob("*.py")
                  if p.name != f"{module}.py" and call.search(p.read_text(encoding="utf-8", errors="replace")))


def call_problems(stmts: list[Statement], root: Path) -> list[Problem]:
    out: list[Problem] = []
    last: dict[str, tuple[str, str]] = {}                    # the function a file last named: "it" in the next sentence
    for s in stmts:
        named = [(m.group(1), m.group(2)) for m in _DOTTED.finditer(s.text)]
        if s.file == MANIFEST:                               # a note names its capability, whose source says the module
            named = named or last_named_in_note(s.text)
        if named:
            last[s.file] = named[-1]
        said = NOT_CALLED.search(s.text)
        if not said:
            continue
        for module, name in (named or ([last[s.file]] if s.file in last else [])):
            who = callers(root, module, name)
            if who:
                out.append(Problem("calls", s.file, s.line, s.text, f'{who[0]} calls {module}.{name}(), and this says "{said.group(0)}"'))
    return out


def last_named_in_note(text: str) -> list[tuple[str, str]]:
    return [("approvals", "gate")] if re.search(r"\b(the|its) gate\b", text) and "approv" in text else []


# ---- price and fee


def _constant(text: str, name: str) -> str | None:
    m = re.search(rf"(?m)^{name} = (?:Decimal\()?\"?([\d_.]+)", text)
    return m.group(1).replace("_", "") if m else None


def price_book(root: Path = ROOT) -> dict[str, str]:
    """The price book as src/knos/billing.py holds it: the one place a price is defined."""
    path = root / "src" / "knos" / "billing.py"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    book = {k: v for k, v in (("meter", _constant(text, "METER_PRICE")), ("meter_free", _constant(text, "METER_FREE")), ("record", _constant(text, "RECORD_PRICE")), ("pilot", _constant(text, "PILOT"))) if v}
    for tier in ("team", "business", "enterprise"):
        if m := re.search(rf'"{tier}": Decimal\(([\d_]+)\)', text):
            book[tier] = m.group(1).replace("_", "")
    rates = re.findall(r'Decimal\("(0\.00\d+)"\)', "\n".join(line for line in text.splitlines() if line.startswith(("ACCEPT_RATE", "ACCEPT_TIERS"))))
    if rates:
        book["acceptance"] = ",".join(sorted({_percent(r) for r in rates}))
    return book


def _percent(rate: str) -> str:
    return f"{float(rate) * 100:.2f}"


def fee_rates(root: Path = ROOT) -> set[str]:
    """Every rate, in percent, either build of knos_pay charges or lets a Plan set: src/knos/fees.py and settle/v2/pay.py."""
    src = root / "src" / "knos"
    bps: set[int] = set()
    if (src / "settle" / "v2" / "pay.py").is_file() and (m := re.search(r"(?m)^FEE_BPS = (\d+)", (src / "settle" / "v2" / "pay.py").read_text(encoding="utf-8"))):
        bps.add(int(m.group(1)))
    if (src / "fees.py").is_file():
        for line in (src / "fees.py").read_text(encoding="utf-8").splitlines():
            if re.match(r"(NEW|OLD) = Rule\(", line):
                nums = [int(n.replace("_", "")) for n in re.findall(r"(?<![\w.\"])(\d[\d_]*)(?![\w.\"])", line)]
                bps |= {n for n in nums if 0 < n <= 1000}
    return {f"{b / 100:.2f}" for b in bps}


PRICES: tuple[tuple[str, str, str], ...] = (
    ("record", rf"{MONEY} USD (?:a|per) lookup", "a Record lookup"),
    ("meter", rf"{MONEY} USD (?:an|per) evaluation|free per organisation, then {MONEY} USD|evaluations a month free, then {MONEY} USD", "a Meter evaluation"),
    ("meter_free", rf"\b{MONEY} evaluations a month free\b|\b{MONEY} (?:evaluations )?a month free per organisation", "the Meter's free evaluations a month"),
    ("team", rf"\bTeam:? {THOUSANDS}(?! evaluations)\b", "Control, Team, a year"),
    ("business", rf"\bBusiness:? {THOUSANDS}\b", "Control, Business, a year"),
    ("enterprise", rf"\bEnterprise:? from {THOUSANDS}\b", "Control, Enterprise, a year"),
    ("pilot", rf"{MONEY} USD, credited against year one", "a Pilot"),
)


CAPPED = re.compile(r"\bcapped at\b", re.I)
COST = re.compile(r"\b(cost|costs|margin|budget|leaves|deliver it|compute)\b", re.I)
FIRST_DEPLOYMENT = re.compile(r"\b(immutable|first deployment|0\.3\.[0-9]\b)", re.I)


def _number(text: str) -> str:
    return text.replace(",", "").rstrip("0").rstrip(".") if "." in text else text.replace(",", "")


def _cell(text: str, at: int) -> str:
    """The table cell of a row that holds position `at`, or the whole statement when it is not a table row."""
    if not text.startswith("|"):
        return text
    return text[text.rfind("|", 0, at) + 1:(text.find("|", at) + 1 or len(text) + 1) - 1]


def price_problems(stmts: list[Statement], book: dict[str, str], rates: set[str]) -> list[Problem]:
    out: list[Problem] = []
    allowed = {_number(r) for r in rates}
    accept = {_number(r) for r in book.get("acceptance", "").split(",") if r}
    for s in stmts:
        for key, rx, what in PRICES:
            if key not in book:
                continue
            for m in re.finditer(rx, s.text):
                said = _cell(s.text, m.start())              # a table row is held cell by cell: one cell's past is not another's
                if PAST.search(said) or (key.startswith("meter") and COST.search(said)):
                    continue                                 # a past price, or what an evaluation costs to deliver
                got = next(g for g in m.groups() if g)
                if _number(got) != _number(book[key]):
                    out.append(Problem("price", s.file, s.line, s.text, f"src/knos/billing.py: {what} is {book[key]}{'' if key == 'meter_free' else ' USD'}, and this says {got}"))
        if accept:
            for m in re.finditer(r"\bAcceptance\b[^|;:]{0,60}?[|;:]?\s*(\d+(?:\.\d+)?)%|\b(\d+(?:\.\d+)?)% of the reconciled accepted\b", s.text):
                got, said = m.group(1) or m.group(2), _cell(s.text, m.end() - 1)
                if PAST.search(said) or COST.search(said):     # a past rate, or a margin of the Acceptance line
                    continue
                if _number(got) not in accept:
                    out.append(Problem("price", s.file, s.line, s.text,
                                       f"src/knos/billing.py: the Acceptance rate is {' or '.join(sorted(accept))}%, and this says {got}%"))
            for m in CAPPED.finditer(s.text):
                said = _cell(s.text, m.start())
                if PAST.search(said) or not re.search(r"\b(Acceptance|accepted (invoice )?value)\b", said):
                    continue
                out.append(Problem("price", s.file, s.line, s.text, "src/knos/billing.py: the Acceptance line has no cap (ACCEPT_FLOOR), and this says it is capped"))
        if allowed and not PAST.search(s.text):
            for m in re.finditer(r"\bfee\b[^.|;%]{0,40}?\b(\d+(?:\.\d+)?)%|\b(\d+(?:\.\d+)?)% fee\b", s.text):
                got = m.group(1) or m.group(2)
                if _number(got) not in allowed | accept:
                    out.append(Problem("fee", s.file, s.line, s.text,
                                       f"src/knos/fees.py: knos_pay charges {', '.join(sorted(allowed, key=float))}% and no other rate, and this says {got}%"))
    return out


# ---- version


def version_problems(stmts: list[Statement], data: dict) -> list[Problem]:
    out: list[Problem] = []
    programs = data.get("programs", {})
    for s in stmts:
        if s.file == MANIFEST or (s.file == "docs/CAPABILITIES.md" and s.text.startswith("|")) or not LIVE.search(s.text) or NOT_LIVE_YET.search(s.text) or PAST.search(s.text):
            continue
        for m in re.finditer(r"\b(knos_[a-z]+|upgrade_gate) (\d+\.\d+)\b", s.text):
            want = programs.get(m.group(1), {}).get("on_chain")
            if want and str(want) != m.group(2):
                out.append(Problem("version", s.file, s.line, s.text, f"{MANIFEST}: the public id of {m.group(1)} runs {want}, and this says {m.group(2)} is live"))
    return out


# ---- count


COUNTS: tuple[tuple[str, str], ...] = (
    ("programs on devnet", r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten) (?:Solana |devnet |Solana devnet |on-chain |public )*programs\b(?! reading)"),
    ("capabilities", r"\b(\d+) capabilities\b"),
    ("tests passed", r"\b(\d{1,3}(?:,\d{3})+|\d{3,}) (?:tests )?passed\b"),
)


def count_problems(stmts: list[Statement], data: dict) -> list[Problem]:
    out: list[Problem] = []
    rows = len(data.get("capabilities", []))
    for what, rx in COUNTS:
        seen: dict[int, Statement] = {}
        for s in stmts:
            if PAST.search(s.text) or FIRST_DEPLOYMENT.search(s.text) or not s.file.endswith((".md", ".html")):
                continue
            for m in re.finditer(rx, s.text, re.I if what.startswith("programs") else 0):
                word = m.group(1).lower()
                n = WORDS.get(word) if not word[0].isdigit() else int(word.replace(",", ""))
                if n is None or (what.startswith("programs") and not re.search(r"\b(Knos|devnet|Solana|verifier|escrow)\b", s.text)):
                    continue
                if what == "capabilities" and rows and n != rows:
                    out.append(Problem("count", s.file, s.line, s.text, f"{MANIFEST} has {rows} capabilities, and this says {n}"))
                seen.setdefault(n, s)
        if len(seen) > 1:
            first, *rest = sorted(seen.items(), key=lambda kv: (kv[1].file, kv[1].line))
            for n, s in rest:
                out.append(Problem("count", s.file, s.line, s.text,
                                   f"{first[1].file}:{first[1].line} counts {first[0]} {what} ({first[1].text[:120]}), and this counts {n}"))
    return out


# ---- release


def current_release(root: Path = ROOT) -> str | None:
    path = root / "pyproject.toml"
    m = re.search(r'(?m)^version = "([\d.]+)"', path.read_text(encoding="utf-8")) if path.is_file() else None
    return m.group(1) if m else None


_V3 = r"v?(\d+\.\d+\.\d+)"
CURRENT = (rf"\b(?:this|the current|the latest) (?:release|version)\b,? \(?(?:Knos )?{_V3}",
           rf"\b(?:Knos )?{_V3},? \((?:this|the current|the latest) (?:release|version)\)",
           rf"\bas Knos {_V3} has it\b", rf"\bKnos {_V3} is the (?:current|latest)\b", rf"\bcurrent (?:release|version)(?: is|:)? (?:Knos )?{_V3}")


def release_problems(stmts: list[Statement], version: str | None) -> list[Problem]:
    out: list[Problem] = []
    if not version:
        return out
    for s in stmts:
        for rx in CURRENT:
            for m in re.finditer(rx, s.text, re.I):
                if m.group(1) != version:
                    out.append(Problem("release", s.file, s.line, s.text, f"pyproject.toml: the current release is {version}, and this names {m.group(1)} as the current one"))
    return out


# ---- live: the fee and the quorum of the build at the public id


def _ver(v: object) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", str(v or "0")))


NOW = re.compile(r"\b(today|now|currently|is live|are live)\b|\bthe public (?:program|id)s? (?:still )?(?:charges?|runs?)\b", re.I)
IF_LATER = re.compile(r"\b(until|before|once|when|after|from|would|will|propos\w*|pending|was|were|if|next|withdrawn|history)\b", re.I)
NEW_FEE = re.compile(r"\b0\.30?%(?: of the amount)?,? (?:with )?(?:at least|a minimum of|minimum|floor) 0\.05\b", re.I)
OLD_FEE = re.compile(r"\b(the 0\.3\.14 fee|2\.5% of the first 1,000|(?:at least|a minimum of|minimum) 0\.40)\b", re.I)
QUORUM_FIXED = re.compile(r"\bquorum\b[^.|]{0,80}\b(is|are|has been|have been) (fixed|corrected|closed)\b|\bquorum fix(es)? (is|are) live\b", re.I)
QUORUM_OPEN = re.compile(r"\bquorum (defects?|bugs?|flaws?)\b[^.|]{0,60}\b(are|is) (still )?(live|open)\b", re.I)
FIXED_IN = "2.2"                                             # the knos_pay build with the 0.30% fee and both quorum fixes


def live_problems(stmts: list[Statement], data: dict) -> list[Problem]:
    out: list[Problem] = []
    runs = (data.get("programs", {}).get("knos_pay") or {}).get("on_chain")
    if not runs:
        return out
    new = _ver(runs) >= _ver(FIXED_IN)
    where = f"{MANIFEST}: the public id of knos_pay runs {runs}"
    for s in stmts:
        if s.file == MANIFEST or IF_LATER.search(s.text):
            continue
        now = NOW.search(s.text)
        if now and not new and NEW_FEE.search(s.text):
            out.append(Problem("live", s.file, s.line, s.text, f"{where}, which charges the 0.3.14 fee, and this says the 0.30% fee holds {now.group(0)}"))
        if now and new and OLD_FEE.search(s.text):
            out.append(Problem("live", s.file, s.line, s.text, f"{where}, which charges 0.30% at least 0.05, and this says the 0.3.14 fee holds {now.group(0)}"))
        if not new and QUORUM_FIXED.search(s.text):
            out.append(Problem("live", s.file, s.line, s.text, f"{where}; both quorum fixes are in {FIXED_IN}, and this says the quorum is fixed"))
        if new and QUORUM_OPEN.search(s.text):
            out.append(Problem("live", s.file, s.line, s.text, f"{where}, which has both quorum fixes, and this says the defects are live"))
    return out


# ---- published


# what Knos has published, where, and the line that installs it (checked on the registries on 8 Oct 2026)
PUBLISHED: dict[str, tuple[str, str, str]] = {
    "knos-oidc-interface": ("crates.io", "0.3.14", "https://crates.io/crates/knos-oidc-interface"),
    "knos-pay-interface": ("crates.io", "0.3.14", "https://crates.io/crates/knos-pay-interface"),
    "knos-settle": ("npm", "0.3.20", "https://www.npmjs.com/package/knos-settle"),
}
UNPUBLISHED = re.compile(r"\b(neither\b[^.]{0,60}\b(?:is|are) on (?:crates\.io|npm)|neither (?:\w+ )?(?:has|have) been published|none (?:of them )?(?:is |are )?published|not (?:yet )?published|unpublished|not (?:yet )?(?:on|in) (?:crates\.io|npm)|is not on (?:crates\.io|npm)|no (?:crate|package) on (?:crates\.io|npm))\b", re.I)
PACKAGE = re.compile(r"\b(knos-(?:oidc|pay)-interface|knos-settle|interface crates?|crates?|crates\.io|npm|JS (?:SDK|client)|JavaScript client)\b", re.I)


def published_problems(stmts: list[Statement]) -> list[Problem]:
    out: list[Problem] = []
    for s in stmts:
        said = UNPUBLISHED.search(s.text)
        if not said or not PACKAGE.search(s.text) or re.search(r"\b(was|were|until|before)\b", s.text):
            continue
        named = [n for n in PUBLISHED if n in s.text] or list(PUBLISHED)
        out.append(Problem("published", s.file, s.line, s.text, "; ".join(f"{n} {PUBLISHED[n][1]} is on {PUBLISHED[n][0]} ({PUBLISHED[n][2]})" for n in named)
                           + f', and this says "{said.group(0)}"'))
    return out


def problems(root: Path = ROOT, docs: Iterable[str] = DOCS) -> list[Problem]:
    stmts, data = statements(root, docs), load(root)
    found = (stage_problems(stmts, data) + call_problems(stmts, root) + price_problems(stmts, price_book(root), fee_rates(root))
             + version_problems(stmts, data) + count_problems(stmts, data) + release_problems(stmts, current_release(root))
             + live_problems(stmts, data) + published_problems(stmts))
    return sorted(set(found), key=lambda p: (p.file, p.line, p.rule, p.against))


def main(argv: list[str] | None = None, say: Callable[[str], None] = print, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--json", action="store_true", help="print the contradictions as JSON")
    a = ap.parse_args(argv)
    found = problems(root)
    if a.json:
        say(json.dumps([asdict(p) for p in found], indent=1))
    else:
        for p in found:
            say(str(p))
        say(f"{len(found)} contradiction(s) in {len(files(root))} files" if found else f"no contradiction in {len(files(root))} files")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
