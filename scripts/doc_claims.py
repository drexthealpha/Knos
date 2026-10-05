"""One registry of the facts that more than one document states, each computed from ONE source, and the check that no
document says otherwise.

    python scripts/doc_claims.py            exit 1 and say, one line each, where a document contradicts a source or
                                            another document (the test suite runs this)
    python scripts/doc_claims.py --write    first write what is generated: the README's table of programs and every
                                            "stage" cell of a table of capabilities
    python scripts/doc_claims.py --facts    print every registered fact with its value and its source

The sources (SOURCES), and nothing else:

    docs/capabilities.json        how many capabilities stand at each stage, on which program ids the exercised ones
                                  ran, and the version each program runs on devnet
    web/upgrades.json             the upgrade proposals: which are pending, their builds, and the times on chain. The
                                  committed file is a copy (its `generated` says of when); the site's build writes it
                                  again from the chain, and `knos status` reads the chain itself
    programs-v2/program_ids.json  the programs
    docs/bench.json               what was measured on devnet: the `[[stat: name]]` slots of scripts/bench_docs.py

A document states such a fact through a slot or a generated block, or in words that stay true as the state changes
("the live state is in web/upgrades.json", "docs/CAPABILITIES.md lists each capability's stage"). What this refuses:

    counts     a number of capabilities at a stage, of programs, or of pending proposals that is not the source's;
               "nothing is recorded as exercised" while something is; a sentence that gives a whole release one stage
               ("tested locally and not yet on devnet"), which no source can hold
    stages     a table with a "stage" column, or "(`id`, `id`; stage)" in a sentence, that is not the manifest's words
    times      a time or a day for an upgrade that web/upgrades.json does not give for a PENDING proposal. A withdrawn
               proposal's times may stand only in the history (HISTORY), in a sentence that says it is history
    fees       a maximum for the fee, or the old 500 limit of an order, said as current
    payments   a total of payments on devnet without the day it was read; two documents with different totals
    slots      a slot nobody filled, and two documents that give one measured fact two values (bench_docs.py)

Nothing here needs a time that exists only after the release is pushed: that is the point. The one commit is complete
before the push, and what the chain says afterwards is published by the site's build.
"""

from __future__ import annotations

import html
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST, UPGRADES, IDS, BENCH = "docs/capabilities.json", "web/upgrades.json", "programs-v2/program_ids.json", "docs/bench.json"
SOURCES = [MANIFEST, UPGRADES, IDS, BENCH, "docs/backtest.json"]
# Where a withdrawn proposal's times may stand, in a sentence that says they are history (WAS).
HISTORY = {"CHANGELOG.md", "docs/GOVERNANCE.md"}
WAS = re.compile(r"withdr[ae]w|replaced|cancel|could have run|never ran|never executed|was proposed")
# Written by scripts/drills.py from a local validator's own clock: their times are the drill's, not the upgrade's.
GENERATED = {"docs/DRILLS.md", "docs/drills_recovery.md"}
# Read line by line besides the documents: the site's scripts, the command line's help, and what the registries show.
OTHER = ["src/knos/cli.py", "server.json", "gemini-extension.json", "glama.json", ".claude-plugin/marketplace.json",
         "plugin/.claude-plugin/plugin.json", "plugin/.codex-plugin/plugin.json"]
PROGRAMS_START, PROGRAMS_END = "<!-- programs:start -->", "<!-- programs:end -->"
REHEARSAL = "## The 0.3.14 rehearsal on devnet"     # the section of docs/CAPABILITIES.md that names the staging addresses
NAMES = {"knos_oidc": "the verifier", "knos_pay": "the escrow", "knos_meter": "the count", "knos_passkey": "a wallet from a passkey"}
_WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
          "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"]
_NUM = r"(\d+|" + "|".join(_WORDS[1:]) + r"|no|none|zero)"
_STAGE = r"(implemented|tested|deployed|exercised|reproduced)"
_SCRIPTS = Path(__file__).resolve().parent


def _script(name: str):
    """A sibling script as a module, loaded by path so that this works from the tests and from the command line."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _json(root: Path, rel: str) -> dict:
    return json.loads((root / rel).read_text(encoding="utf-8"))


def _int(word: str) -> int:
    word = word.lower()
    return 0 if word in ("no", "none", "zero") else _WORDS.index(word) if word in _WORDS else int(word)


# ---- the registry ----------------------------------------------------------------------------------------------------
def _stage_count(stage):
    return lambda root: sum(c["stage"] == stage for c in _json(root, MANIFEST)["capabilities"])


def _where_count(where: str):
    cap = _script("capabilities")
    return lambda root: sum(cap.ids_of(c, root) == where for c in _json(root, MANIFEST)["capabilities"] if c["stage"] == "exercised")


def programs(root: Path = ROOT) -> list[str]:
    """The programs of the second deployment, by name: the `knos_*` addresses of programs-v2/program_ids.json."""
    return [k for k in _json(root, IDS) if k.startswith("knos_")]


def pending(root: Path = ROOT) -> list[dict]:
    return [e for e in _json(root, UPGRADES)["entries"] if e.get("status") == "pending"]


def _minute(seconds) -> str:
    return datetime.fromtimestamp(int(seconds), timezone.utc).strftime("%Y-%m-%d %H:%M")


def upgrade_times(root: Path = ROOT) -> tuple[set[str], set[str]]:
    """(the times of the pending proposals, the times of every other proposal), each "YYYY-MM-DD HH:MM" in UTC: when a
    proposal was approved and the first moment it can run (`earliest_execution`, and the time lock before it), and
    `since`, which for a withdrawn proposal is when it was withdrawn."""
    feed = _json(root, UPGRADES)
    now, past = set(), set()
    for e in feed["entries"]:
        at = [e[k] for k in ("since", "earliest_execution") if e.get(k)]
        at += [e["earliest_execution"] - feed["time_lock"]] if e.get("earliest_execution") and feed.get("time_lock") else []
        (now if e.get("status") == "pending" else past).update(_minute(t) for t in at)
    return now, past - now


def _registry() -> dict:
    cap = _script("capabilities")
    reg = {f"capabilities.{s}": (f"capabilities whose stage is `{s}`", MANIFEST, _stage_count(s)) for s in cap.STAGES}
    reg["capabilities.not_built"] = ("capabilities this tree does not hold yet", MANIFEST, _stage_count(None))
    reg["capabilities.all"] = ("capabilities listed", MANIFEST, lambda root: len(_json(root, MANIFEST)["capabilities"]))
    for where in ("public", "staging", "unknown"):
        reg[f"capabilities.exercised.{where}"] = (
            f"exercised capabilities whose devnet transaction ran on {where} program ids", MANIFEST, _where_count(where))
    reg["programs"] = ("programs of the second deployment", IDS, lambda root: len(programs(root)))
    for name in NAMES:
        reg[f"programs.{name}.on_chain"] = (f"the version of {name} devnet runs at its public id", MANIFEST,
                                            lambda root, n=name: _json(root, MANIFEST)["programs"][n]["on_chain"])
    reg["upgrades.pending"] = ("upgrade proposals pending, in the committed copy", UPGRADES, lambda root: len(pending(root)))
    reg["upgrades.proposals"] = ("upgrade proposals in all, in the committed copy", UPGRADES, lambda root: len(_json(root, UPGRADES)["entries"]))
    reg["upgrades.generated"] = ("when the committed copy was read from the chain", UPGRADES, lambda root: _json(root, UPGRADES)["generated"])
    bd = _script("bench_docs")
    for slot, (what, _path) in bd.SLOTS.items():
        reg[f"stat.{slot}"] = (what, BENCH, lambda root, s=slot: bd._kept(_json(root, BENCH), s))
    return reg


def value(name: str, root: Path = ROOT):
    """A registered fact, computed from its one source."""
    return _registry()[name][2](root)


def said_as(v) -> str:
    """A fact as the documents print it."""
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else f"{v:,.1f}" if isinstance(v, float) else str(v)


# ---- what is generated -----------------------------------------------------------------------------------------------
def stage_words(ids: list[str], root: Path = ROOT) -> str:
    """The manifest's stage of each capability named, in the words the documents use. A capability exercised on
    staging ids says so: that is not a run of the public program."""
    cap = _script("capabilities")
    by_id = {c["id"]: c for c in _json(root, MANIFEST)["capabilities"]}

    def one(cid: str) -> str:
        c = by_id[cid]
        return cap.WORDS[c["stage"]] + (", on staging program ids" if cap.ids_of(c, root) == "staging" else "")
    said: dict[str, list[str]] = {}
    for cid in ids:
        said.setdefault(one(cid), []).append(f"`{cid}`")
    return next(iter(said)) if len(said) == 1 else "; ".join(f"{', '.join(who)}: {what}" for what, who in said.items())


def programs_table(root: Path = ROOT) -> str:
    """README.md's table of programs, from the manifest: the version each runs at its public id, and how far the next
    one has got. Worded to be true before and after an upgrade executes; the manifest's `on_chain` moves with it
    (`python scripts/capabilities.py check --rpc` holds it to devnet)."""
    cap = _script("capabilities")
    data, ids = _json(root, MANIFEST), _json(root, IDS)
    # a staging run is named from the rehearsal's own section, never from the manifest: no stage counts it
    full = (root / cap.FULL).read_text(encoding="utf-8") if (root / cap.FULL).is_file() else ""
    rehearsal = full.split(REHEARSAL, 1)[1] if REHEARSAL in full else ""
    lines = [f"| program | address | on devnet, as [`{MANIFEST}`]({MANIFEST}) records it |", "|---|---|---|"]
    for name in programs(root):
        p = data["programs"][name]
        later = p["versions"][p["versions"].index(p["on_chain"]) + 1:]
        staged = re.search(rf"\b{name}\s+`[1-9A-HJ-NP-Za-km-z]{{32,44}}`", rehearsal) is not None
        state = f"runs `{p['on_chain']}`"
        if later:
            state += (f"; `{later[0]}` is proposed through the multisig and runs at this address only once its proposal has executed"
                      + (f"; the 0.3.14 rehearsal ran it at a staging address of its own ([{cap.FULL}]({cap.FULL}))" if staged else ""))
        lines.append(f"| `{name.replace('_', '-')}`, {NAMES.get(name, 'a program')} | `{ids[name]}` | {state} |")
    return "\n".join(lines)


def _blocks(text: str, root: Path) -> str:
    if PROGRAMS_START in text and PROGRAMS_END in text:
        a, b = text.index(PROGRAMS_START) + len(PROGRAMS_START), text.index(PROGRAMS_END)
        text = text[:a] + "\n" + programs_table(root) + "\n" + text[b:]
    return text


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _stage_tables(text: str, root: Path, known: set[str]):
    """(line number, the ids the row names, the stage cell, the line with the manifest's words in that cell) for every
    row of a table that has a "stage" column and names a capability in the column before it."""
    lines, col = text.split("\n"), None
    for i, line in enumerate(lines):
        if not line.lstrip().startswith("|"):
            col = None
            continue
        cells = _cells(line)
        if col is None:
            col = next((k for k, c in enumerate(cells) if c.lower().startswith("stage")), -1)
            continue
        if col < 1 or len(cells) <= col or set(cells[col]) <= set("-: "):
            continue
        ids = [m for m in re.findall(r"`([a-z][a-z0-9_]*)`", cells[col - 1]) if m in known]
        if ids:
            want = stage_words(ids, root)
            yield i, ids, cells[col], "| " + " | ".join([*cells[:col], want, *cells[col + 1:]]) + " |"


def write(root: Path = ROOT) -> list[str]:
    """Write the generated parts. Returns the documents that changed."""
    known, changed = {c["id"] for c in _json(root, MANIFEST)["capabilities"]}, []
    for doc in documents(root):
        if not doc.endswith(".md"):
            continue
        old = (root / doc).read_text(encoding="utf-8")
        new = _blocks(old, root)
        lines = new.split("\n")
        for i, _ids, _cell, line in _stage_tables(new, root, known):
            lines[i] = line
        new = "\n".join(lines)
        if new != old:
            (root / doc).write_text(new, encoding="utf-8")
            changed.append(doc)
    return changed


# ---- the text --------------------------------------------------------------------------------------------------------
def documents(root: Path = ROOT) -> list[str]:
    """Every public document and the site's page (bench_docs.py's list)."""
    return _script("bench_docs").public_text(root)


def units(root: Path, doc: str) -> list[tuple[str, str]]:
    """A file as (section, sentence) pairs. Code is left out (it names syntax and expected output, not facts), a table
    row is one unit, a page's tags are removed. `section` is "old" under a release of CHANGELOG.md that is not the
    newest, else ""."""
    text = (root / doc).read_text(encoding="utf-8")
    if not doc.endswith((".md", ".html")):
        return [("", " ".join(line.split())) for line in text.splitlines() if line.strip()]
    parts = [("", text)]
    if doc == "CHANGELOG.md":
        head, *rest = text.split("\n## ")
        parts = [("", head + ("\n## " + rest[0] if rest else ""))] + [("old", "## " + r) for r in rest[1:]]
    out = []
    for section, part in parts:
        for pat in (r"```.*?```", r"`[^`\n]*`", r"<script.*?</script>", r"<!--.*?-->"):
            part = re.sub(pat, " ", part, flags=re.S)
        if doc.endswith(".html"):
            part = html.unescape(re.sub(r"<[^>]+>", " ", part))
        for block in re.split(r"\n\s*\n|\n(?=\s*(?:[-*] |\d+\. |\|))", part.replace("**", "")):
            flat = " ".join(block.split())
            out += [(section, s) for s in ([flat] if flat.startswith("|") else re.split(r"(?<=[.!?])\s+(?=[A-Z(\[\"'])", flat)) if s]
    return out


_TIME = re.compile(r"\b(20\d\d-\d\d-\d\d)(?:[ T]| at )(\d\d:\d\d)|\b(\d{1,2}) (Oct)(?:ober)?(?: (20\d\d))?,?(?: at)? (\d\d:\d\d)")
_DAY = re.compile(r"(?:execut\w*|can run|could run|runs?|goes? live|is live|eligible|pending)\b[^.;|]{0,60}?\b(?:on|from|until|after|before|by) "
                  r"(?:(20\d\d-\d\d-\d\d)|(\d{1,2}) (Oct)(?:ober)?)\b(?![ T,]? ?(?:at )?\d\d:\d\d)")
_UPGRADE = re.compile(r"upgrade|proposal|proposed|approved|time lock|multisig|timer|execut", re.I)
_FEE_MAX = re.compile(r"(?:at most|max(?:imum)?(?: of)?|capped at|up to) 25(?:\.00)?\b(?! ?%)|\(capped\)|fee (?:is )?capped|fee cap\b", re.I)
_OLD_LIMIT = re.compile(r"\b500(?:\.00)? (?:test )?USDC\b|\b(?:and|to|most|than|of) 500\b(?!,| USD\b| an? (?:hour|minute|second|day)\b| requests?\b)|\bcap\w*\b[^.;|]{0,30}?\b500\b(?!,)", re.I)
_SUPERSEDED = re.compile(r"no maximum|replaced|before 0\.3\.14|until 0\.3\.14|first deployment|built before|100,000|newest 500", re.I)
_BLANKET = re.compile(r"tested locally[^.;|]{0,60}?not (?:yet )?(?:on devnet|deployed)|tested locally and waiting for an upgrade|"
                      r"nothing new in this release was deployed", re.I)
_COUNT = re.compile(rf"\b{_NUM} (?:of (?:the|its) )?capabilit(?:y|ies)\b[^.;|]{{0,50}}?\b{_STAGE}\b", re.I)
_NONE = re.compile(rf"\b(?:nothing|none|no capability)\b[^.;|]{{0,70}}?\b(?:recorded|marked|listed) as {_STAGE}(?: or {_STAGE})?", re.I)
_WHERE = re.compile(rf"\b{_NUM}(?: of (?:them|those|these))?(?: ran| were exercised| was exercised)? on (?:the |its )?(public|staging)\b", re.I)
_PROGRAMS = re.compile(rf"\b{_NUM} programs on Solana devnet\b|\ball {_NUM} programs\b|\bthe {_NUM} programs (?:above|that change|of the second deployment)\b", re.I)
_PENDING = re.compile(rf"\b{_NUM} (?:upgrade )?proposals? (?:is|are) pending\b", re.I)
_PAYMENTS = re.compile(r"(?<!over )\b(\d+) payments on devnet\b|\bmade (\d+) payments\b")
_DATED = re.compile(r"\b\d{1,2} (?:Sep|Oct|Nov)\w* 20\d\d\b|\b20\d\d-\d\d-\d\d\b")
# a word one of the patterns above needs: a sentence without any is not read further
_ANY = re.compile(r"capabilit|nothing|none|tested locally|programs|proposal|payments|\b25\b|\b500\b|capped|fee cap|\d\d:\d\d|"
                  r"\bOct|20\d\d-\d\d-\d\d", re.I)
_INLINE = re.compile(r"\(((?:`[a-z][a-z0-9_]*`(?:, | and )?)+); ([^()]+)\)")


def _stamp(m: re.Match) -> str:
    if m.group(1):
        return f"{m.group(1)} {m.group(2)}"
    return f"{m.group(5) or '2026'}-10-{int(m.group(3)):02d} {m.group(6)}"


def problems(root: Path = ROOT) -> list[str]:
    """Everything a document says against a source or against another document, one line each."""
    bd = _script("bench_docs")
    out: list[str] = []
    counts = {s: value(f"capabilities.{s}", root) for s in _script("capabilities").STAGES}
    now, past = upgrade_times(root)
    known = {c["id"] for c in _json(root, MANIFEST)["capabilities"]}
    totals: dict[str, list[str]] = {}
    docs = documents(root)
    for doc in [*docs, *sorted(f"web/{p.name}" for p in (root / "web").glob("*.js")), *[o for o in OTHER if (root / o).is_file()]]:
        say = lambda text: out.append(f"{doc}: {text}")        # noqa: E731
        for section, s in units(root, doc):
            if not _ANY.search(s):                             # most sentences state none of these facts
                continue
            short = s[:110] + ("..." if len(s) > 110 else "")
            # counts and stages, against the manifest
            for m in _COUNT.finditer(s):
                if _int(m.group(1)) != counts[m.group(2).lower()] and not section:
                    say(f"says {m.group(1)} capabilities {m.group(2)}, and {MANIFEST} has {counts[m.group(2).lower()]}: {short}")
            for m in _NONE.finditer(s) if not section else []:
                for stage in filter(None, m.groups()):
                    if counts[stage.lower()]:
                        say(f"says nothing is {stage}, and {MANIFEST} has {counts[stage.lower()]}: {short}")
            if _COUNT.search(s) and not section:
                for m in _WHERE.finditer(s):
                    if _int(m.group(1)) != (have := value(f"capabilities.exercised.{m.group(2).lower()}", root)):
                        say(f"says {m.group(1)} exercised on {m.group(2)} ids, and {MANIFEST} has {have}: {short}")
            if (m := _BLANKET.search(s)) and not section and counts["exercised"] and doc.endswith((".md", ".html")):
                say(f"gives a whole release one stage ({m.group(0)!r}); {MANIFEST} has each capability's, and "
                    f"{counts['exercised']} are exercised: {short}")
            for m in _PROGRAMS.finditer(s) if not section else []:
                if _int(next(filter(None, m.groups()))) != value("programs", root):
                    say(f"counts {next(filter(None, m.groups()))} programs, and {IDS} has {value('programs', root)}: {short}")
            for m in _PENDING.finditer(s) if not section else []:
                if _int(m.group(1)) != value("upgrades.pending", root):
                    say(f"says {m.group(1)} proposals are pending, and {UPGRADES} has {value('upgrades.pending', root)}: {short}")
            # the upgrade's times, against the upgrade record
            if doc not in GENERATED and _UPGRADE.search(s):
                history = doc in HISTORY and bool(WAS.search(s))
                for m in _TIME.finditer(s):
                    t = _stamp(m)
                    if t not in now and not (history and t in past):
                        say(f"names {t} UTC for an upgrade, and {UPGRADES} " + ("gives that time to a proposal that is not pending: it may stand only in "
                            f"{' or '.join(sorted(HISTORY))}, in a sentence that says it was withdrawn" if t in past else "has no such time") + f": {short}")
                for m in _DAY.finditer(s):
                    day = m.group(1) or f"2026-10-{int(m.group(2)):02d}"
                    if day not in {t[:10] for t in now} and not (history and day in {t[:10] for t in past}):
                        say(f"names {day} as a day an upgrade runs, and {UPGRADES} has no pending proposal for that day: {short}")
            # the fee and the order's limit
            if not _SUPERSEDED.search(s):
                if m := _FEE_MAX.search(s):
                    say(f"gives the fee a maximum ({m.group(0)!r}); it has none since 0.3.14: {short}")
                # under an older release only "an order holds ... 500" is this limit: `order` is 0.3.13's word, and older
                # releases had other limits of their own
                about = r"\border\b" if section else r"order|bount|job|task|\bcap\b|holds?\b"
                if (m := _OLD_LIMIT.search(s)) and re.search(about, s, re.I) and doc.endswith((".md", ".html")):
                    say(f"gives the old limit of 500 as current ({m.group(0)!r}); an order holds up to 100,000 on devnet: {short}")
            # a total of payments is a reading of one day
            for m in _PAYMENTS.finditer(s) if not section else []:
                n = m.group(1) or m.group(2)
                if doc not in totals.setdefault(n, []):
                    totals[n].append(doc)
                if not _DATED.search(s):
                    say(f"gives a total of {n} payments on devnet without the day it was read: {short}")
        if doc.endswith(".md"):
            text = (root / doc).read_text(encoding="utf-8")
            for i, ids, cell, _line in _stage_tables(text, root, known):
                if cell != stage_words(ids, root):
                    say(f"line {i + 1}: the stage of {', '.join(ids)} is {cell!r}, and {MANIFEST} says {stage_words(ids, root)!r} "
                        "(`python scripts/doc_claims.py --write`)")
            for m in _INLINE.finditer(text):
                ids = re.findall(r"`([a-z][a-z0-9_]*)`", m.group(1))
                if set(ids) <= known and m.group(2).strip() != stage_words(ids, root):
                    say(f"says {m.group(1)} is {m.group(2).strip()!r}, and {MANIFEST} says {stage_words(ids, root)!r}")
            if _blocks(text, root) != text:
                say("the table of programs is not what the manifest says (`python scripts/doc_claims.py --write`)")
    if len(totals) > 1:
        out.append("the total of payments on devnet has " + f"{len(totals)} values: " + "; ".join(f"{n} in {', '.join(d)}" for n, d in totals.items()))
    out += [f"{doc}: the slot [[stat: {name}]] is not filled" + ("" if name in bd.SLOTS else ", and scripts/bench_docs.py does not know it")
            for doc, name in bd.slots(root)]
    out += [f"one fact, one value: {line}" for line in bd.disagreements(root)]
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--facts" in argv:
        for name, (what, source, _fn) in _registry().items():
            print(f"{name} = {said_as(value(name))}    {what} ({source})")
        return 0
    if "--write" in argv:
        for doc in write():
            print(f"doc_claims: {doc} written")
    wrong = problems()
    for line in wrong:
        print("doc_claims: " + line)
    if not wrong:
        print(f"doc_claims: {len(_registry())} registered facts, {len(documents())} documents and the site agree")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
