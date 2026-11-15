"""A repo's proof history, in its Sibyl store: every claim and verdict, what the evidence showed later, and the checks
that history makes required.

    record(...)   a claim, the checks run, the verdict (entity `proof_claim`)
    observe(...)  later evidence about a commit, e.g. CI failed at 54ce98ad (entity `proof_outcome`)
    lint()        claims the evidence contradicts: "shipped" at a commit whose CI failed
    learn()       each contradiction becomes a required check (entity `proof_rule`): from then on, a claim of that kind
                  runs that check whatever the message says. Sibyl's own MemoryClient.learn() runs too when the
                  account has Sibyl Pro (playbooks across the journal); the rules here need no tier. Each flagged PR
                  (a repo-rule violation) becomes a `repo_rule`, required as `rule:<id>` on every claim after.
    repo_rules()  the repo's own rules: CONTRIBUTING.md parsed into machine-checkable rules (stored in Sibyl the first
                  time, recalled from Sibyl after) plus the rules past rejections taught it (entity `repo_rule`)
    lint_pr()     every place a PR's diff or commits break one of those rules, citing the rule's line and the PR's
    learn_tamper()  a caught tamper (a prove.judge finding's `pattern`) becomes a `tamper` entity and two proof_rules
                  scoped repo=... and agent=...: every later proof for that repo or by that agent must run
                  `tamper:<pattern>` (required_for / tamper_checks_required)

`NullStore` keeps nothing: the same engine with no memory, which is what a plain hook amounts to.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass


class NullStore:
    """No memory: records nothing, knows nothing."""

    def put(self, category: str, name: str, body: dict) -> None:
        return None

    def all(self, category: str) -> list[dict]:
        return []


class SibylStore:
    """The repo's Sibyl store (the same one Knos's memory uses), through the public MemoryClient API."""

    def __init__(self, client):
        self.client = client

    @classmethod
    def local(cls, root, tenant_id: str = "knos-judge") -> "SibylStore":
        """Sibyl's own local store at <root>/sibyl.db: what prove.yml's judge keeps between runs in the caller repo's
        Actions cache. Offline: no secret, no network, no Sibyl service on the runner."""
        from pathlib import Path
        from sibyl_memory_client import MemoryClient
        Path(root).mkdir(parents=True, exist_ok=True)
        return cls(MemoryClient.local(str(Path(root) / "sibyl.db"), tenant_id=tenant_id))

    @classmethod
    def for_repo(cls, repo) -> "SibylStore":
        from ..memory import Memory
        mem = Memory(repo)
        store = cls(mem.client)
        store._mem = mem   # keep the connection open for the store's lifetime
        return store

    def put(self, category: str, name: str, body: dict) -> None:
        self.client.set_entity(category, name, body, status="active")

    def all(self, category: str) -> list[dict]:
        out = []
        for row in self.client.list_entities(category, status="active", limit=10000):
            body = row.get("body")
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except ValueError:
                    continue
            if isinstance(body, dict):
                out.append(body)
        return out


@dataclass
class Contradiction:
    sha: str
    claimed: list[str]
    failed: str
    claim: str


def _id(*parts) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


def record(store, sha: str, claim_text: str, kinds: list[str], results: list[dict], ok: bool,
           at: float | None = None) -> None:
    store.put("proof_claim", _id(sha, claim_text), {"sha": sha, "claim": claim_text[:2000], "kinds": sorted(kinds),
                                                    "results": results, "ok": ok, "at": at or time.time()})


def observe(store, sha: str, check: str, ok: bool, detail: str = "", at: float | None = None) -> None:
    store.put("proof_outcome", _id(sha, check), {"sha": sha, "check": check, "ok": ok, "detail": detail,
                                                 "at": at or time.time()})


def lint(store) -> list[Contradiction]:
    """Claims the evidence later contradicted: a "done" whose commit failed a check."""
    fails = {}
    for o in store.all("proof_outcome"):
        if not o.get("ok"):
            fails.setdefault(o["sha"], []).append(o["check"])
    out = []
    for c in store.all("proof_claim"):
        for check in fails.get(c.get("sha"), []):
            ran = {r.get("name") for r in c.get("results", []) if r.get("ok")}
            if check not in ran:   # claimed done without that check passing, and the check then failed
                out.append(Contradiction(c["sha"], c.get("kinds", []), check, c.get("claim", "")[:200]))
    return out


def learn(store, flagged: list["RuleViolation"] | None = None) -> list[dict]:
    """Turn every contradiction into a required check for that kind of claim, and every flagged PR (repo-rule
    violations) into a `repo_rule` every later claim must pass as `rule:<id>`. Returns the rules now in force."""
    for v in flagged or []:
        r = v.rule
        rid = _id("learned", r["kind"], r.get("param"))
        store.put("repo_rule", rid, {**r, "id": rid, "origin": "learned",
                                     "because": f"a PR was flagged: {v.where}: {v.offending.strip()[:160]}"})
        store.put("proof_rule", _id("*", rid), {"when": "*", "require": f"rule:{rid}",
                                                "because": f"a PR broke {r['source']} ({r['text'][:80]})"})
    for x in lint(store):
        for kind in x.claimed or ["done"]:
            store.put("proof_rule", _id(kind, x.failed), {"when": kind, "require": x.failed,
                                                          "because": f"{x.sha[:8]} was claimed ({kind}) and its "
                                                                     f"{x.failed} failed"})
    try:   # Sibyl Pro's own self-learning over the journal, when the account has it; never required
        store.client.learn()
    except Exception:  # noqa: BLE001 - free tier, or a NullStore
        pass
    return rules(store)


def rules(store) -> list[dict]:
    return store.all("proof_rule")


def required(store, kinds: set[str]) -> set[str]:
    return {r["require"] for r in rules(store) if (r.get("when") in kinds or r.get("when") == "*")
            and not r.get("scope")}


# ---- tampering an agent was caught at, per repo and per agent (Sibyl) --------------------------------------------

def repo_key(repo) -> str:
    """A repo as tamper rules key it: the last path component, lowercased (a path, a name or owner/name)."""
    return str(repo or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()


def _agent_key(agent) -> str:
    return str(agent or "").strip().lower()


def learn_tamper(store, repo, agent, pattern: str, evidence: str = "", at: float | None = None) -> list[dict]:
    """Remember a tamper `pattern` (e.g. "deleted-tests") caught in `agent`'s work on `repo`, and require the check
    `tamper:<pattern>` from then on for every proof on that repo AND every proof by that agent. Idempotent."""
    at = at or time.time()
    repo_k, agent_k, check = repo_key(repo), _agent_key(agent), f"tamper:{pattern}"
    store.put("tamper", _id("tamper", repo_k, agent_k, pattern, evidence),
              {"repo": str(repo), "agent": str(agent), "pattern": pattern, "evidence": str(evidence)[:2000], "at": at})
    because = f"{agent} was caught at {pattern} on {repo}: {str(evidence)[:160]}"
    made = []
    for scope, value in (("repo", repo_k), ("agent", agent_k)):
        if value:
            rule = {"when": "tamper", "scope": scope, scope: value, "require": check, "because": because, "at": at}
            store.put("proof_rule", _id("tamper", scope, value, pattern), rule)
            made.append(rule)
    return made


def required_for(store, repo=None, agent=None) -> list[dict]:
    """The tamper proof_rules in force for this repo or this agent."""
    repo_k, agent_k = repo_key(repo), _agent_key(agent)
    return [r for r in rules(store) if r.get("when") == "tamper" and
            ((r.get("scope") == "repo" and repo_k and r.get("repo") == repo_k) or
             (r.get("scope") == "agent" and agent_k and r.get("agent") == agent_k))]


def tamper_checks_required(store, repo=None, agent=None) -> set[str]:
    """Every `tamper:<pattern>` check the next proof for this repo or by this agent must run (for prove.judge)."""
    return {r["require"] for r in required_for(store, repo, agent)}


# ---- a delivery against what the buyer told us before (Sibyl) ---------------------------------------------------

@dataclass
class PreferenceViolation:
    preference: str
    line: int          # 1-based line of the delivery
    text: str
    why: str

    def __str__(self) -> str:
        return (f"line {self.line}: {self.text.strip()!r} contradicts the buyer's preference "
                f"{self.preference!r} ({self.why})")


_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⭐⭕‼⁉]")
_BULLET = re.compile(r"^\s*([-*+•]|\d+[.)])\s+")
_WORDS = re.compile(r"\b(?:under|fewer than|less than|at most|max(?:imum)?(?: of)?|no more than|up to)\s+(\d+)\s+words?\b")
_US_UK = {"color": "colour", "colors": "colours", "colored": "coloured", "favor": "favour", "favorite": "favourite",
          "behavior": "behaviour", "honor": "honour", "labor": "labour", "neighbor": "neighbour", "flavor": "flavour",
          "humor": "humour", "organize": "organise", "organization": "organisation", "realize": "realise",
          "recognize": "recognise", "analyze": "analyse", "optimize": "optimise", "apologize": "apologise",
          "center": "centre", "theater": "theatre", "catalog": "catalogue", "gray": "grey", "defense": "defence",
          "traveled": "travelled", "canceled": "cancelled", "customize": "customise", "prioritize": "prioritise"}


def _prefs_of(store_or_memory, buyer: str | None) -> list[str]:
    if store_or_memory is None:
        return []
    if isinstance(store_or_memory, (list, tuple)):
        return [str(p) for p in store_or_memory]
    if hasattr(store_or_memory, "preferences"):       # jobs.buyer_memory.BuyerMemory
        return list(store_or_memory.preferences())
    rows = store_or_memory.all("buyer_preference")    # a proof store: {"buyer", "preference"}
    return [r["preference"] for r in rows if r.get("preference") and (buyer is None or r.get("buyer") == buyer)]


def lint_preferences(store_or_memory, buyer: str | None, delivery_text: str) -> list[PreferenceViolation]:
    """Each place the delivery contradicts a preference the buyer stated before (recalled from Sibyl), citing the
    delivery's line. Deterministic patterns, no model: no emojis, British spelling, under/at most N words, no bullet
    points, no exclamation marks."""
    lines = delivery_text.splitlines()
    out: list[PreferenceViolation] = []
    for pref in _prefs_of(store_or_memory, buyer):
        p = pref.lower()
        if re.search(r"\b(no|without|avoid|never|don'?t)\b.*\bemoji", p):
            out += [PreferenceViolation(pref, i, ln, "emoji") for i, ln in enumerate(lines, 1) if _EMOJI.search(ln)]
        if re.search(r"\b(british|uk)\b.*\b(spelling|english)\b", p):
            for i, ln in enumerate(lines, 1):
                for w in re.findall(r"[A-Za-z]+", ln):
                    if w.lower() in _US_UK:
                        out.append(PreferenceViolation(pref, i, ln, f"US spelling {w!r}; British is "
                                                                    f"{_US_UK[w.lower()]!r}"))
        if re.search(r"\b(no|without|avoid|never|don'?t)\b.*\bbullet", p):
            out += [PreferenceViolation(pref, i, ln, "bullet point") for i, ln in enumerate(lines, 1)
                    if _BULLET.match(ln)]
        if re.search(r"\b(no|without|avoid|never|don'?t)\b.*\bexclamation", p):
            out += [PreferenceViolation(pref, i, ln, "exclamation mark") for i, ln in enumerate(lines, 1) if "!" in ln]
        m = _WORDS.search(p)
        if m:
            strict = re.match(r"(under|fewer than|less than)", m.group(0))
            limit = int(m.group(1)) - (1 if strict else 0)
            n = 0
            for i, ln in enumerate(lines, 1):
                n += len(ln.split())
                if n > limit:
                    out.append(PreferenceViolation(pref, i, ln, f"{len(delivery_text.split())} words; the limit is "
                                                                f"passed on this line"))
                    break
    return out


# ---- a PR against the repo's own rules: CONTRIBUTING.md and past rejections (Sibyl) ------------------------------

CONTRIBUTING = ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md")
_NEG = r"\b(no|not|never|avoid|don'?t|do not|without|must not|shouldn'?t|should not)\b"
_DEP_FILES = re.compile(r"(^|/)(pyproject\.toml|setup\.py|setup\.cfg|requirements[\w.-]*\.txt|package\.json|"
                        r"Cargo\.toml|go\.mod|Gemfile)$")
_CONVENTIONAL = re.compile(r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([\w./ -]+\))?!?: \S")
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.\w+$|\.(test|spec)\.\w+$")
_CODE = re.compile(r"\.(py|js|jsx|ts|tsx|go|rs|rb|java|kt|c|cc|cpp|h|cs|php|swift)$")


@dataclass
class RuleViolation:
    rule: dict         # the repo_rule: kind, param, source ("CONTRIBUTING.md:7"), text, origin
    where: str         # file:line in the PR's diff, or "commit <sha>"
    offending: str     # the offending diff line or commit subject
    why: str

    def __str__(self) -> str:
        return (f"{self.where}: {self.offending.strip()!r} breaks {self.rule['source']} "
                f"({self.rule['text'].strip()!r}): {self.why}")


def parse_contributing(text: str, source: str = "CONTRIBUTING.md") -> list[dict]:
    """The machine-checkable rules in a CONTRIBUTING file, each citing its line. Deterministic patterns, no model."""
    out: list[dict] = []

    def add(kind, i, line, param=None):
        if not any(r["kind"] == kind and r.get("param") == param for r in out):
            out.append({"kind": kind, "param": param, "source": f"{source}:{i}", "text": line.strip()[:300]})

    for i, line in enumerate(text.splitlines(), 1):
        p = line.lower()
        if re.search(_NEG + r".*\b(new |additional |extra )?(dependenc|deps\b|packages?\b)", p):
            add("no_new_deps", i, line)
        if re.search(r"\btests? (are |is )?(required|mandatory)|\b(add|include|write|with|must (have|add|include)|"
                     r"needs?|requires?)\s+(new |unit |accompanying )?tests?\b", p) and \
                not re.search(_NEG + r"\s+(\w+\s+)?tests?\b", p):
            add("tests_required", i, line)
        m = re.search(r"\b(under|fewer than|less than|at most|max(?:imum)?(?: of)?|no more than|up to)\s+(\d+)\s+"
                      r"(changed |modified )?lines?\b", p)
        if m:
            n = int(m.group(2)) - (1 if m.group(1) in ("under", "fewer than", "less than") else 0)
            add("max_lines", i, line, n)
        elif re.search(r"\bkeep (your )?(prs?|pull requests?|changes|diffs?) (small|focused|short)", p):
            add("max_lines", i, line, 400)
        if re.search(r"conventional commits?", p):
            add("conventional_commits", i, line)
        if re.search(r"console\.log|\bprint\(|\bdebug (prints?|statements?|output|logging)", p) and re.search(_NEG, p):
            add("no_debug", i, line)
        if re.search(r"signed-off-by|\bsign[- ]?off\b|\bdco\b", p):
            add("signoff", i, line)
        if re.search(r"\b(do not|don'?t|never|must not)\s+(edit|modify|change|touch|update)\b", p):
            files = re.findall(r"`([^`]+)`", line) or re.findall(r"\b([\w.-]*CHANGELOG[\w.-]*|[\w./-]+\.(?:lock|md|json|"
                                                                r"ya?ml|txt|toml))\b", line, re.I)
            if "generated" in p and not files:
                files = ["generated"]
            for f in files:
                add("no_edit", i, line, f)
    return out


def repo_rules(store, repo_path) -> list[dict]:
    """The repo's rules, recalled from Sibyl: its CONTRIBUTING file parsed (stored the first time it is seen, so
    later reads come from Sibyl) plus the rules past rejections taught it (`learn(store, flagged)`)."""
    from pathlib import Path
    repo_path = Path(repo_path)
    have = store.all("repo_rule")
    current: set[str] = set()
    for rel in CONTRIBUTING:
        f = repo_path / rel
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        current.add(digest)
        if any(r.get("contributing") == digest for r in have):
            continue   # already in Sibyl: recalled, not re-parsed
        for r in parse_contributing(text, rel):
            rid = _id("contributing", digest, r["kind"], r.get("param"))
            row = {**r, "id": rid, "origin": "contributing", "contributing": digest}
            store.put("repo_rule", rid, row)
            have.append(row)   # a NullStore keeps nothing: the rules still apply to this read
    seen, out = set(), []
    for r in have:
        if r.get("origin") == "contributing" and r.get("contributing") not in current:
            continue   # a CONTRIBUTING file that has since changed or gone
        if r.get("id") and r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


def _added(diff_text: str) -> tuple[list[tuple[str, int, str]], dict[str, int], int]:
    """(file, new line number, text) of every added line, each changed file's first changed line, and lines changed."""
    added: list[tuple[str, int, str]] = []
    files: dict[str, int] = {}
    changed, path, n = 0, None, 0
    for ln in diff_text.splitlines():
        if ln.startswith("diff --git "):
            m = re.match(r"diff --git a/(\S+) b/(\S+)", ln)
            path = m.group(2) if m else None
            if path:
                files.setdefault(path, 1)
            continue
        if ln.startswith("+++ "):
            t = ln[4:].strip()
            if t != "/dev/null":
                path = t[2:] if t.startswith("b/") else t
                files.setdefault(path, 1)
            continue
        if ln.startswith("--- "):
            continue
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
        if m:
            n = int(m.group(1))
            if path and files.get(path, 1) == 1:
                files[path] = max(n, 1)
            continue
        if path is None:
            continue
        if ln.startswith("+"):
            added.append((path, n, ln[1:]))
            changed += 1
            n += 1
        elif ln.startswith("-"):
            changed += 1
        elif ln.startswith(" "):
            n += 1
    return added, files, changed


def _is_dep_line(path: str, text: str) -> bool:
    t = text.strip()
    if not t or t.startswith(("#", "//")):
        return False
    name = path.rsplit("/", 1)[-1]
    if name.startswith("requirements"):
        return not t.startswith("-")
    if name == "package.json":
        m = re.match(r'"([^"]+)"\s*:\s*"([^"]*)"', t)
        return bool(m) and m.group(1) not in ("version", "name", "main", "description", "license") and \
            bool(re.match(r"[~^<>=*]|\d|latest|workspace:|file:|git", m.group(2)))
    if name == "go.mod":
        return bool(re.match(r"(require\s+)?[\w.-]+\.\w+/\S+\s+v\d", t))
    if name == "Cargo.toml":
        return bool(re.match(r'^[\w-]+\s*=\s*("|\{)', t))
    return bool(re.match(r'^"[A-Za-z0-9][\w.\-\[\],]*\s*([<>=!~^;]|")', t))


def _commits(commits) -> list[tuple[str, str]]:
    out = []
    for c in commits or []:
        if isinstance(c, dict):
            out.append((str(c.get("sha", ""))[:8], str(c.get("message", ""))))
        else:
            out.append(("", str(c)))
    return out


def lint_pr(store, repo_path, diff_text: str, commits=(), only: set[str] | None = None) -> list[RuleViolation]:
    """Every place a PR (its unified diff, and its commits as messages or {"sha", "message"}) breaks one of the repo's
    rules, citing the rule's line and the PR's file:line or commit. Empty when the PR keeps them all."""
    return _lint([r for r in repo_rules(store, repo_path) if only is None or r["id"] in only], diff_text, commits)


# kinds a learned `tamper:rule:<kind>` can be checked by with no CONTRIBUTING line behind it (no parameter needed)
_LEARNABLE = ("no_debug", "tests_required", "conventional_commits", "signoff")


def lint_learned(required, diff_text: str, commits=()) -> list[RuleViolation]:
    """Every place a PR breaks a rule this repo's or this agent's history made required (`tamper:rule:<kind>` from
    learn_tamper), whether or not the base's CONTRIBUTING states it: an agent caught leaving a debug print in one
    repo is held to it in every repo after."""
    rules = []
    for check in sorted(required):
        kind = check[len("tamper:rule:"):] if check.startswith("tamper:rule:") else ""
        if kind in _LEARNABLE:
            rules.append({"id": check, "kind": kind, "param": None, "origin": "history", "source": "history",
                          "text": f"{check} required by history"})
    return _lint(rules, diff_text, commits) if rules else []


def _lint(rules, diff_text: str, commits=()) -> list[RuleViolation]:
    added, files, changed = _added(diff_text)
    msgs = _commits(commits)
    out: list[RuleViolation] = []
    for r in rules:
        k = r["kind"]
        if k == "no_new_deps":
            out += [RuleViolation(r, f"{f}:{n}", t, "a new dependency") for f, n, t in added
                    if _DEP_FILES.search(f) and _is_dep_line(f, t)]
        elif k == "tests_required":
            code = [f for f in files if _CODE.search(f) and not _TEST_PATH.search(f)]
            if code and not any(_TEST_PATH.search(f) for f in files):
                f = code[0]
                line = next((t for g, _n, t in added if g == f), "")
                out.append(RuleViolation(r, f"{f}:{files[f]}", line, "code changed and no test changed"))
        elif k == "max_lines":
            limit = int(r.get("param") or 400)
            if changed > limit:
                f, n, t = added[min(limit, len(added) - 1)] if added else ("(diff)", 0, "")
                out.append(RuleViolation(r, f"{f}:{n}", t, f"{changed} lines changed; the limit is {limit}"))
        elif k == "conventional_commits":
            for sha, m in msgs:
                subject = (m.splitlines() or [""])[0]
                if not _CONVENTIONAL.match(subject):
                    out.append(RuleViolation(r, f"commit {sha or '?'}", subject,
                                             "not a conventional commit subject (type(scope): summary)"))
        elif k == "no_debug":
            for f, n, t in added:
                if not _TEST_PATH.search(f) and ((f.endswith((".js", ".jsx", ".ts", ".tsx")) and "console.log(" in t)
                                                 or (f.endswith(".py") and re.match(r"\s*print\(", t))):
                    out.append(RuleViolation(r, f"{f}:{n}", t, "a debug print"))
        elif k == "signoff":
            for sha, m in msgs:
                if "signed-off-by:" not in m.lower():
                    out.append(RuleViolation(r, f"commit {sha or '?'}", (m.splitlines() or [""])[0],
                                             "no Signed-off-by trailer"))
        elif k == "no_edit":
            pat = str(r.get("param") or "")
            for f, first in files.items():
                hit = ("generated" in f.lower() or f.endswith(".lock")) if pat == "generated" else \
                    pat.lower() in f.lower()
                if hit:
                    line = next((t for g, _n, t in added if g == f), "")
                    out.append(RuleViolation(r, f"{f}:{first}", line, f"{pat} must not be edited"))
    return out
