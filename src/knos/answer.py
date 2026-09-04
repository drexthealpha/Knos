"""Reading a repo, and answering from what was read.

knos has no model and no API key. It does not write prose. An answer is the
passages it found and, beside each one, exactly where it came from: a file
and line, a session and date, or a commit. A developer will not trust it
twice without that.

Everything here runs because a person ran a command.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import code, errors, git, private, rules
from .memory import INTERNAL, PERSON, Fact, Memory

STOP = {
    "a", "about", "an", "and", "are", "as", "at", "be", "but", "by", "did",
    "do", "does", "for", "from", "had", "has", "have", "how", "in", "is",
    "it", "last", "of", "on", "or", "our", "that", "the", "their", "then",
    "there", "this", "to", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "with", "you", "your",
}


@dataclass(frozen=True)
class Passage:
    """One thing knos found, and where it came from."""

    text: str
    source: str  # "session" | "git" | "code" | "note"
    where: str
    score: float = 0.0
    path: str = ""

    @property
    def line(self) -> str:
        return f"{self.text}\n    {self.where}"


# knos is not an archive. It keeps enough of a passage to recognise and
# search, and names where the whole thing still lives, so a person can go
# and read it in full. Storing less of each passage is always better than
# storing fewer of them: a repo whose oldest half is missing has holes a
# person cannot see, while shorter passages still point at everything.
KEEP_CHARS = 280

# How many good passages count as an answer. Below this, a prose question
# also asks the code reader, and pays the seconds that costs.
ENOUGH = 4

# What a deliberately written note is worth over derived chatter. Somebody
# chose to write it down; a session that happens to say the word twenty times
# did not. Without this the standing rule loses to the argument about it.
NOTE_LEAD = 1.0

# What a code result is worth over prose when the question was structural.
# Enough to outrank any single passage, so the file and line come first.
STRUCTURAL_LEAD = 2.0

# A written-down rule beats the argument about it, the same way a note does.
# Somebody chose to put it in CLAUDE.md; a session that happens to mention
# the word did not.
RULES_LEAD = 1.0

# And when the question is plainly about the rules, the rules go first.
RULES_QUESTION_LEAD = 2.5

# Ways of asking what you are supposed to do here.
RULES_PHRASES = (
    "rule", "rules", "convention", "conventions", "guideline", "guidelines",
    "instruction", "instructions", "claude.md", "agents.md", "style guide",
    "am i allowed", "are we allowed", "supposed to", "should i", "must i",
    "policy",
)

# Ways of asking about the shape of the code rather than the story behind it.
# These always reach the code reader, however much prose was found, because
# no amount of session chatter answers "who calls this".
STRUCTURAL_PHRASES = (
    "who calls",
    "what calls",
    "who uses",
    "what uses",
    "where is",
    "where are",
    "defined",
    "definition",
    "implemented",
    "implementation",
    "function",
    "class",
    "method",
    "call graph",
    "depends on",
    "imports",
    "signature",
)

# A name a programmer would type: CamelCase, snake_case, a call, or a file.
SYMBOL = re.compile(
    r"[a-z]+_[a-z_]+|[a-z]+[A-Z]\w*|[A-Z][a-z]+[A-Z]\w*|\w+\(\)|[\w/\\.-]+\.[a-z]{1,4}\b"
)


def looks_structural(question: str) -> bool:
    """Whether this asks about the shape of the code.

    Asked of the question rather than of the results, because a question
    about a symbol deserves the code reader even when the sessions happen to
    be full of chatter that mentions it.
    """
    low = question.lower()
    if any(phrase in low for phrase in STRUCTURAL_PHRASES):
        return True
    return bool(SYMBOL.search(question))


def withheld(held: str, by_the_person: bool) -> str:
    """What an agent is told about work somebody else has claimed.

    Lives here rather than in the server so `knos claim` can show you the
    exact words your agents will get, in the same breath as claiming it.
    A person should not have to open a second tool to find out what the
    first one just did.
    """
    if by_the_person:
        return (
            f"Withheld. The person you are working with said they are on"
            f" {held} right now, so knos is not the place you find out about"
            " it. Ask them where they have got to, or pick up something else."
            "\n\nIf they say go ahead, call this again with"
            ' override="their reason". That is recorded against your name.'
            "\n\nTell them this, in these words, before you do anything else."
        )
    return (
        f"Withheld. {held} is being worked on right now, so knos is not the"
        " place you find out about it. Ask them, or work on something else."
        "\n\nIf you must have it anyway, call this again with"
        ' override="your reason". That is recorded against your name.'
        "\n\nTell the person this, in these words, before you do anything"
        " else. A collision they are not shown is one they find out about at"
        " merge time."
    )


def looks_like_rules(question: str) -> bool:
    """Whether this asks what the rules of the repo are."""
    low = question.lower()
    return any(phrase in low for phrase in RULES_PHRASES)


def topic_of(fact: str) -> str:
    """What to file a fact under when nobody said.

    The words that carry it, so "always use pnpm, never npm" files under
    "pnpm npm" and is found by asking about either. Asking a person to
    invent a filing name before they can write one sentence down is the
    friction this exists to avoid.
    """
    # A standing instruction is mostly instruction. What it is *about* is
    # what is left once the telling-off is removed.
    telling = {
        "always", "never", "must", "should", "dont", "please", "make",
        "sure", "keep", "stop", "avoid", "prefer", "only", "ever", "when",
        "use", "using", "used", "into", "onto", "over", "under", "before",
        "after", "instead", "rather", "than", "them", "they",
    }
    # Not a length filter: npm, git, ssh and api are all three letters and
    # all exactly what a rule is about.
    words = [w for w in terms(fact) if w not in telling][:3]
    return " ".join(words) or fact[:40].strip()


def _trim(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= KEEP_CHARS:
        return text
    return text[:KEEP_CHARS].rsplit(" ", 1)[0] + "..."


# ---- reading a repo ---------------------------------------------------


def point(
    repo: Path,
    mem: Memory,
    index_code: bool = True,
    on_progress: Any = None,
    code_budget: float | None = None,
) -> dict[str, int]:
    """Read this repo: its sessions, its commits, its structure.

    Called by `knos point`. Facts are stated as they were found; nothing is
    summarised, scored or inferred.
    """
    from . import sessions

    counts: dict = {
        "rules": 0,
        "sessions": 0,
        "commits": 0,
        "code": 0,
        "private": 0,
        "full": 0,
        "skipped": [],
    }
    say = on_progress or (lambda *_: None)
    repo = Path(repo).resolve()

    mem.set_reference(INTERNAL + "repo", {"path": str(repo), "name": repo.name})

    # Read first, and deliberately so. These are the files agents consult
    # most and rewrite themselves, they are small, and if the store fills up
    # the rules of the repo are the last thing that should be missing.
    say("reading the instruction files")
    for rule in rules.read(repo):
        if private.is_private(repo, rule.path):
            counts["private"] += 1
            continue
        if not mem.record(
            Fact(
                text=rule.text,
                source="rules",
                where=rule.where,
                when=rule.when,
                about=rule.path,
                path=rule.path,
            )
        ):
            counts["full"] = 1
            break
        counts["rules"] += 1

    # Newest first, so that if the store fills up what knos kept is the part
    # anyone is likely to ask about.
    if not counts["full"]:
        say("looking for past agent sessions")
        for turn in reversed(sessions.read_all(repo)):
            if not mem.record(
                Fact(
                    text=_trim(turn.text),
                    source="session",
                    where=turn.where,
                    when=turn.when,
                    about=turn.client,
                )
            ):
                counts["full"] = 1
                break
            counts["sessions"] += 1
            if counts["sessions"] % 100 == 0:
                say(f"{counts['sessions']} things said in past sessions")

    if not counts["full"]:
        # Commits arrive newest first, so the first time a file or a person
        # is seen is their latest. A canonical record is written once, then
        # left alone: rewriting it for every older commit produced the same
        # answer after tens of thousands of pointless writes, which was
        # most of what `knos point` spent its time doing.
        named: set[str] = set()
        say("reading the commits")
        for commit in git.read_commits(repo):
            visible = [f for f in commit.files if not private.is_private(repo, f)]
            counts["private"] += len(commit.files) - len(visible)
            if not mem.record(
                Fact(
                    text=_trim(commit.text),
                    source="git",
                    where=commit.where,
                    when=commit.when,
                    about=commit.author,
                    path=visible[0] if visible else "",
                )
            ):
                counts["full"] = 1
                break
            # Only people get a canonical record here. A file used to get one
            # per commit that touched it, which on a real repo was hundreds of
            # writes at twenty-five milliseconds each, for something the
            # journal already says: the commit that changed a file names the
            # file. That was most of what reading a repo cost.
            if commit.author not in named:
                named.add(commit.author)
                mem.note_thing(
                    PERSON,
                    commit.author,
                    {"last_commit": commit.short, "last_seen": commit.when[:10]},
                )
            counts["commits"] += 1
            if counts["commits"] % 100 == 0:
                say(f"{counts['commits']} commits")

    if index_code:
        result: dict = {}
        # The longest stretch, and the one with nothing to count as it
        # goes, so say plainly that a wait here is expected.
        say("reading the code, the slow part")
        try:
            result = code.index(repo, budget=code_budget)
        except Exception:
            # Structure is one source of three. Losing it is worth a line,
            # not the whole command.
            counts["skipped"].append(
                errors.unreadable("code structure", "the reader would not start")
            )
        counts["code"] = int(result.get("nodes") or 0)
        mem.set_reference(INTERNAL + "code_index", result)

    # What goes into the store has to be plain data, so the skipped files are
    # counted here and handed back to the caller in full.
    mem.set_focus(
        {
            "repo": str(repo),
            "read": {k: v for k, v in counts.items() if isinstance(v, int)},
            "skipped": len(counts["skipped"]),
        }
    )
    return counts


# ---- answering --------------------------------------------------------


def terms(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_.\-]{1,}", question.lower())
    return [w for w in words if w not in STOP and len(w) > 2]


def _score(text: str, wanted: list[str]) -> float:
    low = text.lower()
    hits = sum(1 for w in wanted if w in low)
    if not hits:
        return 0.0
    # Prefer passages that cover more of the question over ones that repeat
    # a single word, and prefer shorter passages at equal coverage.
    return hits / len(wanted) + min(len(low), 2000) / 200000.0


def ask(
    repo: Path,
    mem: Memory,
    question: str,
    identity: str = private.OWNER,
    limit: int = 8,
    allowed: list[str] | None = None,
) -> list[Passage]:
    """Ranked passages with their sources. No prose, no synthesis.

    For an agent, private paths are dropped before ranking and are never
    counted, so the reply carries no sign that anything was withheld.
    """
    wanted = terms(question)
    if not wanted:
        return []

    found: list[Passage] = []

    # "What are the rules here?" has one right answer and it is in a file.
    # Without this the sessions arguing about a rule outrank the rule.
    rules_lead = RULES_LEAD + (RULES_QUESTION_LEAD if looks_like_rules(question) else 0.0)

    # The store's full-text search wants terms, not a sentence: asking it for
    # the whole question makes every word mandatory and finds nothing. Each
    # term is asked for separately and the results are ranked together, so a
    # passage that covers more of the question wins.
    for term in wanted[:6]:
        for hit in mem.search(term, limit=60):
            text = str(hit.get("text") or "").strip()
            if not text:
                continue
            # A canonical record says what knos knows *about* a thing, not
            # where it heard it, so it has no source to name and no business
            # being quoted as an answer. The journal carries the same fact
            # with the commit it came from. `about` is where these belong.
            if hit.get("tier") == "entity":
                continue
            # A note that has been forgotten stops being an answer. The
            # journal keeps the line, because the journal is a record of what
            # was learned and when, but a forgotten thing is not something
            # knos still tells people.
            if hit.get("source") == "note" and not mem.remembered(
                str(hit.get("about") or "")
            ):
                continue
            found.append(
                Passage(
                    text=text,
                    source=str(hit.get("source") or hit.get("tier") or "note"),
                    where=str(hit.get("where") or hit.get("about") or "knos memory"),
                    path=str(hit.get("path") or ""),
                    score=_score(text, wanted)
                    + (NOTE_LEAD if hit.get("source") == "note" else 0.0)
                    + (rules_lead if hit.get("source") == "rules" else 0.0),
                )
            )

    # "What are the rules here?" shares no word with "never use a bare
    # except", so search alone answers it with nothing. When the question is
    # plainly about the rules, the rules are fetched by name.
    if looks_like_rules(question):
        for hit in mem.written_rules():
            text = str(hit.get("text") or "").strip()
            if not text:
                continue
            found.append(
                Passage(
                    text=text,
                    source="rules",
                    where=str(hit.get("where") or ""),
                    path=str(hit.get("path") or ""),
                    score=RULES_QUESTION_LEAD + _score(text, wanted),
                )
            )

    # Code structure is the slow source: the reader is a separate program and
    # starting it costs seconds, against milliseconds for everything else.
    # A question about a symbol or a call always pays that, because nothing
    # in the sessions can answer it. A prose question pays it only when what
    # was found is thin.
    # Counted over what this caller may actually see. A teammate shared one
    # folder has most of the repo filtered away, and judging "enough" on the
    # part they cannot see left them with a grant that answered nothing.
    seen_so_far = private.visible(repo, [p.__dict__ for p in found], identity, allowed)
    thin = sum(1 for p in seen_so_far if p["score"] > 0) < ENOUGH
    structural = looks_structural(question)
    if structural or thin:
        for word in wanted[:3]:
            try:
                symbols, _ = code.search(repo, word, limit=10)
            except Exception:
                break  # structure is a bonus source, never the reason to fail
            for s in symbols:
                found.append(
                    Passage(
                        text=f"{s.kind} {s.short}",
                        source="code",
                        where=s.where,
                        path=s.path,
                        # A question about the shape of the code wants the
                        # code first. Commit prose that merely mentions the
                        # word is background, however well it scores.
                        score=_score(f"{s.name} {s.kind}", wanted) + (STRUCTURAL_LEAD if structural else 0.0),
                    )
                )

    found = private.visible(repo, [p.__dict__ for p in found], identity, allowed)
    passages = [Passage(**p) for p in found]

    seen: set[str] = set()
    ranked: list[Passage] = []
    for p in sorted(passages, key=lambda p: -p.score):
        if p.score <= 0:
            continue
        key = p.text[:120]
        if key in seen:
            continue
        seen.add(key)
        ranked.append(p)
        if len(ranked) >= limit:
            break
    return ranked


def same_subject(topic: str, question: str) -> bool:
    """Whether a claim and a question are about the same thing.

    Shared word stems, not shared substrings. Substrings made a claim on a
    short word warn about half the repo: "guard" fired on "safeguarding".
    Bare word overlap fixed that but missed the obvious, because a claim on
    "parser" said nothing about "parsing".
    """
    claimed = _subject_stems(topic)
    asked = _subject_stems(question)
    return bool(claimed) and bool(claimed & asked)


# What joins the parts of an identifier or a path. Terms arrive lowercased
# and alphanumeric-or-punctuation, so everything else is a separator.
_JOINED = re.compile(r"[^a-z0-9]+")


def _subject_stems(text: str) -> set[str]:
    """Stems for claim matching, with identifiers broken into their parts.

    A claim is typed as prose — "the risk guard" — and the thing it protects
    is written in code as risk_guard.py. Left whole that is one token and
    shares no word with the claim, so a claim missed the very file it was
    made about, and any question phrased in the code's spelling walked past
    it. Splitting on the punctuation that joins identifiers puts both
    spellings on the same words.

    Only claim matching reads this. Scoring still uses whole tokens, because
    a search for risk_guard.py should rank that file above every other file
    with guard in the name.
    """
    stems = set()
    for word in terms(text):
        stems.add(stem(word))
        for part in _JOINED.split(word):
            if len(part) > 2:
                stems.add(stem(part))
    return stems


# Enough English to see that parser, parsers, parsing and parsed are one
# word. Anything more wants a real stemmer, and a real stemmer is a
# dependency knos does not need to warn one agent off another's work.
_ENDINGS = ("ings", "ing", "ers", "er", "ed", "es", "s")

# Words the suffix rules cannot reach, because English does not spell them
# the way it spells everything else. Short on purpose: this list exists to
# match a claim, not to conjugate.
_IRREGULAR = {
    "wrote": "write", "written": "write", "writing": "write",
    "built": "build", "building": "build",
    "broke": "break", "broken": "break", "breaking": "break",
    "ran": "run", "running": "run",
    "caught": "catch", "catching": "catch",
    "sent": "send", "sending": "send",
    "held": "hold", "holding": "hold",
    "read": "read", "reading": "read",
    "left": "leave", "leaving": "leave",
    "made": "make", "making": "make",
}


def stem(word: str) -> str:
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    for ending in _ENDINGS:
        if len(word) - len(ending) >= 4 and word.endswith(ending):
            word = word[: -len(ending)]
            break
    # A trailing e goes too, so parse, parser and parsing all land on pars.
    # Adding the e back instead was worse: it depended on which ending was
    # stripped, so parser and parsing disagreed.
    return word[:-1] if len(word) > 4 and word.endswith("e") else word
