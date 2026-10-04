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

    lessons(), export_lessons(), import_lessons()   what the judge learned, as JSON lines, so it can travel between
                  runs on GitHub (knos.proof.memory keeps them in the repository's `knos-memory` issue). They are
                  loaded into a Sibyl store and read from there; nothing decides from the lines themselves.

    refuse(), accept(), refusals(), owed(), track(), briefing(), recall()
                  the agent's own track record on this repository, across sessions. Each verdict of the Stop hook is
                  one event in Sibyl's journal (the COLD tier: append-only, newest first) and the running count is one
                  state document (the HOT tier, rewritten in place). A check a refusal named is owed on every later
                  "done" here, whatever the message says, until a verdict shows it passing; `briefing` says what failed
                  last time and `recall` finds it by its words (Sibyl's FTS5 search across tiers). The proof rules
                  above stay entities (the WARM tier).

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

    def rows(self, category: str) -> list[tuple[str, dict]]:
        return []

    def journal(self, evaluated=None, acted=None, forward=None, extra=None) -> None:
        return None

    def events(self, limit: int = 200) -> list[dict]:
        return []

    def state(self, key: str) -> dict:
        return {}

    def set_state(self, key: str, body: dict) -> None:
        return None

    def search(self, query: str, limit: int = 5) -> list[dict]:
        return []


class SibylStore:
    """The repo's Sibyl store (the same one Knos's memory uses), through the public MemoryClient API."""

    def __init__(self, client):
        self.client = client

    @classmethod
    def local(cls, root, tenant_id: str = "knos-judge") -> "SibylStore":
        """Sibyl's own local store at <root>/sibyl.db: the judge's memory during a run on GitHub. Between runs its
        lessons travel in the repository's `knos-memory` issue (knos.proof.memory). No secret, and no Sibyl service
        on the runner."""
        from .. import store
        return cls(store.local(root, tenant_id))

    @classmethod
    def for_repo(cls, repo) -> "SibylStore":
        from .. import store
        client, storage = store.for_repo(repo)
        got = cls(client)
        got._storage = storage
        return got

    def _release(self) -> None:
        """Close Sibyl's connections after each call: an open SQLite handle locks memory.db (and its -wal/-shm) on
        Windows, so the store could not be moved, deleted or restored from a cache while a SibylStore is alive.
        Sibyl's Storage reopens on the next call."""
        storage = getattr(self.client, "storage", None)
        if storage is not None:
            storage.close()

    def put(self, category: str, name: str, body: dict) -> None:
        try:
            self.client.set_entity(category, name, body, status="active")
        finally:
            self._release()

    def rows(self, category: str) -> list[tuple[str, dict]]:
        """(name, body) of every entity in a category."""
        try:
            rows = self.client.list_entities(category, status="active", limit=10000)
        finally:
            self._release()
        out = []
        for row in rows:
            body = row.get("body")
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except ValueError:
                    continue
            if isinstance(body, dict):
                out.append((str(row.get("name") or ""), body))
        return out

    def all(self, category: str) -> list[dict]:
        return [body for _name, body in self.rows(category)]

    def journal(self, evaluated=None, acted=None, forward=None, extra=None) -> None:
        """One event in Sibyl's journal (the COLD tier): appended, never rewritten."""
        try:
            self.client.write_event(evaluated=evaluated, acted=acted, forward=forward, extra=extra)
        finally:
            self._release()

    def events(self, limit: int = 200) -> list[dict]:
        """The journal's newest events first."""
        try:
            return list(self.client.read_events(limit=limit))
        finally:
            self._release()

    def state(self, key: str) -> dict:
        """A state document (the HOT tier): its body, or {} when there is none."""
        try:
            got = self.client.get_state(key)
        finally:
            self._release()
        body = got.get("body") if isinstance(got, dict) and "body" in got else got
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                return {}
        return body if isinstance(body, dict) else {}

    def set_state(self, key: str, body: dict) -> None:
        try:
            self.client.set_state(key, body)
        finally:
            self._release()

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Sibyl's full-text search (FTS5) across its tiers: lexical, no model."""
        try:
            return [dict(r) for r in self.client.search(query, limit=limit)]
        finally:
            self._release()


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
    finally:
        if hasattr(store, "_release"):
            store._release()
    return rules(store)


def rules(store) -> list[dict]:
    return store.all("proof_rule")


def required(store, kinds: set[str]) -> set[str]:
    return {r["require"] for r in rules(store) if (r.get("when") in kinds or r.get("when") == "*")
            and not r.get("scope")}


# ---- the agent's own track record here: refusals in Sibyl's journal, the running count in its state --------------

TRACK = "knos_track"        # the state document's key; one per tenant, and a tenant is one repository
_MARK = "knos-verdict"      # what makes a journal event one of these


def _verdict_event(store, sha: str, claim_text: str, results: list[dict], ok: bool, at: float | None) -> None:
    failed = sorted(r["name"] for r in results if not r.get("ok"))
    passed = sorted(r["name"] for r in results if r.get("ok"))
    at = at or time.time()
    store.journal(evaluated={"claim": claim_text[:400], "sha": sha},
                  acted="accepted" if ok else "refused: " + "; ".join(f"{r['name']} ({str(r.get('detail', ''))[:160]})"
                                                                     for r in results if not r.get("ok")),
                  forward=None if ok else "run " + ", ".join(failed) + " before the next claim of done here",
                  extra={"kind": _MARK, "ok": ok, "failed": failed, "passed": passed, "sha": sha, "at": at})
    t = store.state(TRACK)
    store.set_state(TRACK, {"claims": int(t.get("claims", 0)) + 1, "refused": int(t.get("refused", 0)) + (0 if ok else 1),
                            "last": {"ok": ok, "failed": failed, "sha": sha, "at": at}})


def refuse(store, sha: str, claim_text: str, results: list[dict], at: float | None = None) -> None:
    """A claim of done that Knos refused: which checks failed and what each said. `results`: [{name, ok, detail}]."""
    _verdict_event(store, sha, claim_text, results, False, at)


def accept(store, sha: str, claim_text: str, results: list[dict], at: float | None = None) -> None:
    """A claim of done every check bore out: the checks it names are no longer owed."""
    _verdict_event(store, sha, claim_text, results, True, at)


def verdicts(store, limit: int = 200) -> list[dict]:
    """This repository's verdicts from the journal, newest first: each event's `extra`, with what was said and done."""
    out = []
    for e in store.events(limit):
        x = e.get("extra")
        if isinstance(x, dict) and x.get("kind") == _MARK and isinstance(x.get("failed"), list):
            out.append({**x, "acted": e.get("acted"), "claim": (e.get("evaluated") or {}).get("claim", "")
                        if isinstance(e.get("evaluated"), dict) else ""})
    return sorted(out, key=lambda x: -float(x.get("at") or 0))


def refusals(store, limit: int = 200) -> list[dict]:
    return [x for x in verdicts(store, limit) if not x.get("ok")]


def owed(store) -> set[str]:
    """The checks a refusal here named that no later verdict has shown passing: every claim of done runs them."""
    settled, out = set(), set()
    for x in verdicts(store):                       # newest first: the latest word on each check decides
        for name in x.get("passed") or []:
            settled.add(name)
        for name in x.get("failed") or []:
            if name not in settled:
                out.add(name)
            settled.add(name)
    return out


def track(store) -> dict:
    """{"claims", "refused", "last"}: how many claims of done Knos judged here and how many it refused."""
    return store.state(TRACK)


def recall(store, words: str, limit: int = 3) -> list[str]:
    """What Knos did about these words before, found by Sibyl's full-text search in its journal: "refused: tests
    (3 failed in test_calc.py)". Lexical: it finds the words that were written, nothing like them."""
    out = []
    for hit in store.search(words, limit=limit * 4):
        body = hit.get("body")
        if hit.get("tier") == "journal" and isinstance(body, dict) and (body.get("extra") or {}).get("kind") == _MARK:
            out.append(str(body.get("acted") or "")[:300])
    return out[:limit]


def briefing(store) -> str:
    """What an agent is told about its record here before its word is taken: empty when nothing was refused."""
    past = refusals(store)
    if not past:
        return ""
    t, last = track(store), past[0]
    day = time.strftime("%Y-%m-%d", time.gmtime(float(last.get("at") or 0)))
    lines = [f"On this repository Knos refused {t.get('refused', len(past))} of {t.get('claims', len(past))} claims of done. "
             f"The last refusal ({day}, commit {str(last.get('sha', ''))[:8] or 'unknown'}): {last.get('acted', '')}"]
    still = sorted(owed(store))
    if still:
        lines.append("Still owed, whatever the message says: " + ", ".join(still) + ". Run them before saying it is done.")
    return "\n".join(lines)


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


# ---- what the judge learned, to carry between runs (knos.proof.memory) -------------------------------------------

LESSONS = ("tamper", "proof_rule", "repo_rule", "settlement")


def lesson(row) -> dict | None:
    """`row` when it is a lesson as `lessons` writes them, else None. A CONTRIBUTING rule is never one: it is read
    from the base branch's own file in every run, so nothing carried between runs can stand in for that file."""
    if not isinstance(row, dict) or row.get("category") not in LESSONS or not isinstance(row.get("body"), dict):
        return None
    name, body = row.get("name"), row["body"]
    if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{24}", name) or len(json.dumps(body)) > 8000:
        return None
    if row["category"] == "repo_rule":
        ok = body.get("origin") != "contributing" and isinstance(body.get("kind"), str) and body.get("id") == name
    elif row["category"] == "tamper":
        ok = all(isinstance(body.get(k), str) for k in ("repo", "agent", "pattern"))
    elif row["category"] == "settlement":   # what one settlement showed (knos.flow): the checks that failed and where, false claims, terms met
        ok = (isinstance(body.get("repo"), str) and isinstance(body.get("pull"), int) and isinstance(body.get("paid"), bool)
              and isinstance(body.get("failed"), dict) and all(isinstance(k, str) and isinstance(v, list) for k, v in body["failed"].items())
              and all(isinstance(body.get(k), list) and all(isinstance(x, str) for x in body[k]) for k in ("met", "false", "paths")))
    else:
        ok = isinstance(body.get("when"), str) and isinstance(body.get("require"), str)
        if ok and body["when"] == "tamper":     # the rule's name is made of what it says: one cannot pose as another
            scope = body.get("scope")
            ok = (scope in ("repo", "agent") and isinstance(body.get(scope), str) and body["require"].startswith("tamper:")
                  and name == _id("tamper", scope, body[scope], body["require"][len("tamper:"):]))
    return {"category": row["category"], "name": name, "body": body} if ok else None


def lessons(store) -> list[dict]:
    """What the judge learned, as {"category", "name", "body"} rows a later run can load: each tamper it caught, each
    check that made required, each rule a rejection taught, and what each settlement showed."""
    rows = getattr(store, "rows", None)
    found = [lesson({"category": c, "name": name, "body": body}) for c in LESSONS for name, body in (rows(c) if rows else [])]
    return sorted((x for x in found if x), key=lambda x: (x["category"], x["name"]))


def export_lessons(store) -> str:
    """The lessons as JSON lines, one lesson a line. Takes a store, or the rows `lessons` gave."""
    rows = store if isinstance(store, list) else lessons(store)
    return "".join(json.dumps(x, sort_keys=True, separators=(",", ":")) + "\n" for x in rows)


def paid_settlements(rows) -> set[str]:
    """The names of the settlement lessons that say their pull request was paid, among `rows` (a store, or the
    {"category", "name", "body"} rows themselves)."""
    if not isinstance(rows, list):
        rows = [{"category": "settlement", "name": name, "body": body} for name, body in rows.rows("settlement")] if hasattr(rows, "rows") else []
    return {x["name"] for x in rows or [] if isinstance(x, dict) and x.get("category") == "settlement"
            and isinstance(x.get("body"), dict) and x["body"].get("paid") is True}


def import_lessons(store, lines) -> int:
    """Load lessons (JSON lines as text, or the rows themselves) into the store; returns how many were lessons.
    Each is kept under its own name, so loading the same lessons twice changes nothing. A line that is not a
    lesson is skipped. Into a NullStore this keeps nothing: the lines are not a memory of their own.

    A pull request that was paid stays paid: a settlement lesson that says "not paid" never replaces one under the
    same name that says "paid", whichever was written or read last. A merge's settlement and the attestor's run can
    both settle the same pull request at the same commit at the same time; the one that paid is the fact."""
    n, paid = 0, None
    for line in (lines.splitlines() if isinstance(lines, str) else lines or []):
        if isinstance(line, str):
            try:
                line = json.loads(line) if line.strip() else None
            except ValueError:
                continue
        row = lesson(line)
        if row:
            n += 1
            if row["category"] == "settlement":
                paid = paid_settlements(store) if paid is None else paid
                if row["body"]["paid"]:
                    paid.add(row["name"])
                elif row["name"] in paid:
                    continue
            store.put(row["category"], row["name"], row["body"])
    return n


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
