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

    refused(), refused_before(), preflight_seen(), appeal_outcome(), supplier_event(), supplier_record()
                  what the supplier's side of an order remembers: each refusal under given terms (so `knos preflight`
                  can say "3 earlier submissions were refused for touching tests/conftest.py" before a fourth is
                  sent), each preflight result, each appeal and how it ended, and one supplier's record across them
                  (accepted, rejected, appealed, overturned). Entities, found by Sibyl's own search anchored to one
                  category (`search_entities(..., category=...)`, sibyl-memory-client 0.8) and never by a side file.

    exception_opened(), exception_resolved(), exceptions_before(), exception_queue(), terms_text(), period_closed(),
    periods_closed()
                  what the buyer's side remembers of an exception (a statement line, an appeal or a correction that was
                  not simply agreed), each tier doing the work the engine names it for: the live queue is one state
                  document (HOT), one entity per supplier-and-terms holds how their exceptions ended (WARM), each
                  resolution is one journal event (COLD, append-only), the text of the terms is a reference document
                  (REFERENCE), and a closed period is an entity moved to the archive (ARCHIVE). `knos recall exception`
                  (knos.recall) answers from them: how the same exception under the same terms ended before.

    approval_kept(), approval_recalled()
                  the approver's defence six months later, in the buyer's tenant: one entity per commitment (WARM) holds
                  every approval record given for it (who, amount, policy version, evidence hash, why, expiry), each one
                  also a journal event (COLD) the entity is checked against. `knos recall approval` answers from them.

    outcome_granted(), grant_withdrawn(), onboarded(), reuse(), supplier_brings()
                  supplier reuse, in the SUPPLIER's tenant: what a buyer granted it to carry (accepted terms, results,
                  value; WARM, a withdrawn grant ARCHIVED), and each buyer's time from first order to first payment, so
                  the second buyer's onboarding is set against the first's. `knos recall supplier` answers from them.

    line_decided(), line_decisions()
                  what a buyer decided about a statement line whose policy was met: accepted, refused or authorised, by
                  whom, in which role, when and why, in the buyer's tenant. One entity per supplier and terms (WARM) holds
                  the decisions, each also a journal event (COLD). When the same supplier comes back under the same
                  terms, the approver's row says what was decided before (knos.recall `decisions`).

`NullStore` keeps nothing: the same engine with no memory, which is what a plain hook amounts to.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any


class NullStore:
    """No memory: records nothing, knows nothing."""

    def put(self, category: str, name: str, body: dict) -> None:
        return None

    def all(self, category: str) -> list[dict]:
        return []

    def get(self, category: str, name: str) -> dict:
        return {}

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

    def find(self, category: str, query: str, limit: int = 200) -> list[tuple[str, dict]]:
        return []

    def reference(self, key: str) -> dict:
        return {}

    def set_reference(self, key: str, body: dict, kind: str = "") -> None:
        return None

    def archive(self, category: str, name: str, reason: str = "") -> bool:
        return False

    def archived(self, category: str) -> list[tuple[str, dict]]:
        return []

    def held(self):
        return contextlib.nullcontext(self)


class SibylStore:
    """The repo's Sibyl store (the same one Knos's memory uses), through the public MemoryClient API."""

    _storage: object                                # for_repo's storage handle, kept so that it lives as long as the client

    def __init__(self, client):
        self.client = client
        self._held = 0                              # how many batches (held) keep Sibyl's connection open now

    @contextlib.contextmanager
    def held(self):
        """Many calls on one connection, released once when the batch ends. Each release closes Sibyl's connection and
        the next call opens it again; on a slow disk the two cost seconds per call, so loading a knos-memory issue of a
        few dozen lessons (knos.proof.memory.pull, `knos preflight --issue`) took minutes one lesson at a time."""
        self._held += 1
        try:
            yield self
        finally:
            self._held -= 1
            self._release()

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

    @classmethod
    def for_buyer(cls, buyer: str, root=None) -> "SibylStore":
        """One buyer organisation's memory: its own tenant (knos.store.buyer_tenant), in <root>/sibyl.db when a
        directory is named, else in Sibyl's shared store on this machine."""
        from .. import store
        client, storage = store.for_buyer(buyer, root)
        got = cls(client)
        if storage is not None:
            got._storage = storage
        return got

    @classmethod
    def for_supplier(cls, supplier: str, root=None) -> "SibylStore":
        """One supplier's own memory: what buyers granted it to carry to its next buyer, and how long each buyer took
        to onboard it (knos.store.supplier_tenant), in <root>/sibyl.db when a directory is named, else in Sibyl's
        shared store on this machine."""
        from .. import store
        client, storage = store.for_supplier(supplier, root)
        got = cls(client)
        if storage is not None:
            got._storage = storage
        return got

    def _release(self) -> None:
        """Close Sibyl's connections after each call: an open SQLite handle locks memory.db (and its -wal/-shm) on
        Windows, so the store could not be moved, deleted or restored from a cache while a SibylStore is alive.
        Sibyl's Storage reopens on the next call. Inside `held` it waits for the batch to end."""
        if self._held:
            return
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

    def get(self, category: str, name: str) -> dict:
        """The body of one active entity, looked up by its category and name (the WARM tier), or {} when none is held."""
        try:
            got = self.client.get_entity(category, name)
        except Exception as why:  # noqa: BLE001 - the engine's NotFoundError, named here so that this module imports nothing of the engine
            if type(why).__name__ != "NotFoundError":
                raise
            return {}
        finally:
            self._release()
        body = got.get("body") if isinstance(got, dict) else None
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                return {}
        return body if isinstance(body, dict) and got.get("status", "active") == "active" else {}

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

    def find(self, category: str, query: str, limit: int = 200) -> list[tuple[str, dict]]:
        """(name, body) of the entities of ONE category whose name or body holds `query` as a phrase: Sibyl's FTS5
        search anchored to that category, so a word in another category's rows never answers for this one."""
        try:
            rows = list(self.client.search_entities(query, limit=limit, category=category))
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
            if isinstance(body, dict) and row.get("category") == category and row.get("status", "active") == "active":
                out.append((str(row.get("name") or ""), body))
        return out


    def reference(self, key: str) -> dict:
        """A reference document (the REFERENCE tier: a text looked up, never rewritten by use): its body, or {}."""
        try:
            got = self.client.get_reference(key)
        finally:
            self._release()
        body = got.get("body") if isinstance(got, dict) else None
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except ValueError:
                return {}
        return body if isinstance(body, dict) else {}

    def set_reference(self, key: str, body: dict, kind: str = "") -> None:
        try:
            self.client.set_reference(key, body, metadata={"kind": kind} if kind else None)
        finally:
            self._release()

    def archive(self, category: str, name: str, reason: str = "") -> bool:
        """Move one entity to the engine's archive (the ARCHIVE tier): it leaves the active set and every search of
        it, and stays readable through `archived`. False when there is no such entity."""
        try:
            self.client.archive_entity(category, name, reason or None)
        except Exception as why:  # noqa: BLE001 - the engine's NotFoundError, named here so that this module imports nothing of the engine
            if type(why).__name__ != "NotFoundError":
                raise
            return False
        finally:
            self._release()
        return True

    def archived(self, category: str) -> list[tuple[str, dict]]:
        """(name, body) of every archived entity of a category, oldest first. The client has no call that lists the
        archive (sibyl-memory-client 0.8.1), so this reads the engine's own `archived_entities` table through the
        client's storage handle, for this tenant only."""
        try:
            with self.client.storage.connection() as con:
                rows = con.execute("SELECT name, body FROM archived_entities WHERE tenant_id = ? AND category = ? ORDER BY rowid",
                                   (self.client.get_tenant(), category)).fetchall()
        finally:
            self._release()
        out = []
        for row in rows:
            try:
                body = json.loads(row["body"])
            except (TypeError, ValueError):
                continue
            if isinstance(body, dict):
                out.append((str(row["name"]), body))
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
    fails: dict[str, list[str]] = {}
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


# ---- which terms worked: how each past order here ended, by template and policy version (Sibyl) ------------------

OUTCOMES = ("accepted", "fixed", "reverted", "disputed")     # accepted first time; refused then fixed; reverted in warranty; disputed
_TEMPLATE = re.compile(r"[a-z][a-z0-9-]{0,39}")
# the published template (docs/reference/TERMS.md, terms/) each kind of ending supports, and what that template does about it
_SUPPORTS = {"reverted": ("milestone", "holding a share back"), "disputed": ("feature-blackbox", "paying on a black-box suite"),
             "fixed": ("bugfix", "")}


def _order_row(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("repo"), str) and isinstance(body.get("order"), str) and bool(body["order"])
            and body.get("outcome") in OUTCOMES and isinstance(body.get("template"), str)
            and bool(_TEMPLATE.fullmatch(body["template"]) or not body["template"])
            and type(body.get("version")) is int and 0 <= body["version"] <= 10**6
            and isinstance(body.get("policy"), str) and len(body["policy"]) <= 64
            and type(body.get("seq")) is int and 0 <= body["seq"] <= 2**53
            and isinstance(body.get("failed"), list) and len(body["failed"]) <= 12
            and all(isinstance(x, str) and 1 <= len(x) <= 200 for x in body["failed"]))


def order_outcome(store, repo, order, outcome: str, template: str = "", version: int = 0, policy: str = "",
                  failed=(), seq: int | None = None) -> dict:
    """Remember how one order in `repo` ended: `outcome` is one of OUTCOMES. `template` and `version` name the published
    terms template it was funded with ("" and 0: its terms are no published template), `policy` the version of the
    policy it was judged under (the hash of .knos/policy.yml in its terms; "" when it had none), `failed` the checks
    a first pull request was refused on. `seq` puts the repository's orders in order (the issue's number; default:
    the place the order already has, else one after the newest remembered). An order that ends twice (fixed, then
    reverted in warranty) is remembered twice, under two names, and counts once, as the later ending. Raises
    ValueError for what is not an outcome."""
    repo_k, order = repo_key(repo), str(order)
    if seq is None:         # the place it already has, else one after the newest
        mine = [b for b in store.all("order") if _order_row(b) and b["repo"] == repo_k]
        seq = next((b["seq"] for b in mine if b["order"] == order), 1 + max([b["seq"] for b in mine] or [0]))
    body = {"repo": repo_k, "order": order, "outcome": outcome, "template": str(template), "version": int(version),
            "policy": str(policy), "failed": sorted({str(x) for x in failed})[:12], "seq": int(seq)}
    if not _order_row(body):
        raise ValueError(f"an order's outcome is one of {', '.join(OUTCOMES)}, with a published template's name or none")
    store.put("order", _id("order", repo_k, order, outcome), body)
    return body


def orders(store, repo, policy: str | None = None) -> list[dict]:
    """The orders remembered for `repo`, oldest first, one row an order: its last ending, and every check any of
    its pull requests was refused on. `policy`: only the orders judged under that policy version."""
    got: dict[str, dict]
    repo_k, got = repo_key(repo), {}
    for name, b in sorted(getattr(store, "rows", lambda _c: [])("order")):
        if not _order_row(b) or b["repo"] != repo_k or name != _id("order", repo_k, b["order"], b["outcome"]):
            continue                # a row that does not say what its name says is not a memory of an order
        if policy is not None and b["policy"] != policy:
            continue
        have = got.get(b["order"])
        if have is None or OUTCOMES.index(b["outcome"]) > OUTCOMES.index(have["outcome"]):
            b = {**b, "failed": sorted(set(b["failed"]) | set(have["failed"] if have else ()))}
            got[b["order"]] = b
        else:
            have["failed"] = sorted(set(have["failed"]) | set(b["failed"]))
    return sorted(got.values(), key=lambda b: (b["seq"], b["order"]))


def _tick(text) -> str:
    return "`" + "".join(ch for ch in str(text) if ch >= " " and ch not in "`\x7f")[:60] + "`"


def terms_supported(store, repo, policy: str | None = None, last: int = 3, versions=None) -> str:
    """ONE line for a funding reply: what the last orders in this repository showed, and the published template that
    supports. "last 3 orders here: 2 refused on `lint` first; `bugfix` v1 with `lint` named". Empty when nothing is
    remembered: with no memory no template is proposed. `versions` maps a template's name to its newest published
    version (terms/index.json); without it the newest version an order here was funded with, else 1."""
    recent = orders(store, repo, policy)[-last:]
    if not recent:
        return ""
    n = len(recent)
    count = {o: sum(1 for b in recent if b["outcome"] == o) for o in OUTCOMES}
    checks: dict[str, int] = {}
    for b in recent:
        for name in b["failed"] if b["outcome"] == "fixed" else ():
            checks[name] = checks.get(name, 0) + 1
    worst = max((o for o in OUTCOMES[1:] if count[o]), key=lambda o: (count[o], OUTCOMES.index(o)), default="accepted")
    top = min(checks, key=lambda name: (-checks[name], name)) if worst == "fixed" and checks else ""
    if worst == "accepted":
        used = [b["template"] for b in recent if b["template"]]
        template = max(sorted(set(used)), key=used.count) if used else ""
        saw, tail = f"{n} accepted first time", " again"
    else:
        template, does = _SUPPORTS[worst]
        saw = {"fixed": f"{count['fixed']} refused" + (f" on {_tick(top)}" if top else "") + " first",
               "reverted": f"{count['reverted']} reverted in warranty", "disputed": f"{count['disputed']} disputed"}[worst]
        tail = f" with {_tick(top)} named" if top else f", {does}" if does else ""
    head = f"last {n} order{'s' if n != 1 else ''} here: {saw}"
    if not template:
        return head
    seen = [b["version"] for b in orders(store, repo) if b["template"] == template and b["version"]]
    version = (versions or {}).get(template) or max(seen, default=1)
    return f"{head}; {_tick(template)} v{int(version)}{tail}"


# ---- the supplier's side: refusals under given terms, preflights, appeals, one supplier's record (Sibyl) ------------

SUPPLIER_EVENTS = ("accepted", "rejected", "appealed", "overturned")
APPEAL_STATES = ("open", "rerun", "accepted", "rejected")
_HASH = re.compile(r"[0-9a-f]{64}")
_CODE_WORD = re.compile(r"[a-z0-9]+(?:[._-][a-z0-9]+){0,5}")


def _short(value, most: int = 200) -> str:
    return " ".join(str(value or "").split())[:most]


def _refusal_row(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("repo"), str) and isinstance(body.get("terms"), str)
            and bool(_HASH.fullmatch(body["terms"])) and type(body.get("pull")) is int and 0 <= body["pull"] <= 2**53
            and isinstance(body.get("code"), str) and bool(_CODE_WORD.fullmatch(body["code"]))
            and isinstance(body.get("path"), str) and len(body["path"]) <= 200
            and isinstance(body.get("supplier"), str) and len(body["supplier"]) <= 64
            and isinstance(body.get("at"), (int, float)) and not isinstance(body.get("at"), bool))


def _appeal_row(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("repo"), str) and isinstance(body.get("id"), str) and 1 <= len(body["id"]) <= 64
            and body.get("state") in APPEAL_STATES and isinstance(body.get("supplier"), str) and len(body["supplier"]) <= 64
            and type(body.get("pull")) is int and 0 <= body["pull"] <= 2**53
            and isinstance(body.get("terms"), str) and bool(_HASH.fullmatch(body["terms"]) or not body["terms"])
            and all(isinstance(body.get(k), str) and len(body[k]) <= 400 for k in ("reason", "why"))
            and isinstance(body.get("at"), (int, float)) and not isinstance(body.get("at"), bool))


def _supplier_row(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("repo"), str) and isinstance(body.get("supplier"), str)
            and 1 <= len(body["supplier"]) <= 64 and type(body.get("pull")) is int and 0 <= body["pull"] <= 2**53
            and body.get("event") in SUPPLIER_EVENTS and isinstance(body.get("terms"), str)
            and bool(_HASH.fullmatch(body["terms"]) or not body["terms"])
            and isinstance(body.get("at"), (int, float)) and not isinstance(body.get("at"), bool))


def supplier_event(store, repo, supplier, pull: int, event: str, terms: str = "", at: float | None = None) -> dict:
    """One line of a supplier's record in `repo`: this pull request of theirs was accepted, rejected, appealed, or
    had a rejection overturned on appeal. Once per pull request and event. Raises ValueError for another event."""
    body = {"repo": repo_key(repo), "supplier": _agent_key(supplier)[:64], "pull": int(pull), "event": event,
            "terms": str(terms), "at": float(at if at is not None else time.time())}
    if not _supplier_row(body):
        raise ValueError(f"a supplier's record holds {', '.join(SUPPLIER_EVENTS)}, for a named supplier and a pull request")
    store.put("supplier", _id("supplier", body["repo"], body["supplier"], body["pull"], event), body)
    return body


def supplier_record(store, repo, supplier) -> dict:
    """One supplier's record in `repo`, from memory: how many of their pull requests were accepted, rejected,
    appealed and overturned, and the pull requests behind each number. All zero with no memory."""
    repo_k, who = repo_key(repo), _agent_key(supplier)
    rows = [b for _n, b in _rows(store, "supplier", who) if _supplier_row(b) and b["repo"] == repo_k and b["supplier"] == who]
    out: dict = {"supplier": who, "repo": repo_k}
    for event in SUPPLIER_EVENTS:
        pulls = sorted({b["pull"] for b in rows if b["event"] == event})
        out[event] = len(pulls)
        out.setdefault("pulls", {})[event] = pulls
    return out


def _rows(store, category: str, query: str) -> list[tuple[str, dict]]:
    """A category's rows that hold `query`, through the engine's own search where the store has it; every row of the
    category otherwise (an older store). The caller still checks each row: a search narrows, it never decides."""
    find = getattr(store, "find", None)
    if find is not None and query:
        try:
            got = list(find(category, query))
        except Exception:  # noqa: BLE001 - a search that fails must not lose a memory: read the category whole
            got = []
        if got:
            return got
    return list(getattr(store, "rows", lambda _c: [])(category))


def refused(store, repo, terms: str, pull: int, code: str, path: str = "", supplier: str = "", at: float | None = None) -> dict:
    """Remember one refusal: pull request `pull` of `repo` was refused under the terms with hash `terms`, for `code`
    (knos.ghwords.REFUSALS), about `path` when it is about a file. With a `supplier` it also goes on their record.
    The same refusal of the same pull request is one memory however often it is judged."""
    body: dict[str, Any] = {"repo": repo_key(repo), "terms": str(terms), "pull": int(pull), "code": str(code), "path": _short(path),
            "supplier": _agent_key(supplier)[:64], "at": float(at if at is not None else time.time())}
    if not _refusal_row(body):
        raise ValueError("a refusal is remembered under a terms hash (64 hex characters), a pull request and a refusal code")
    store.put("refusal", _id("refusal", body["repo"], body["terms"], body["pull"], body["code"], body["path"]), body)
    if body["supplier"]:
        supplier_event(store, repo, body["supplier"], pull, "rejected", terms, body["at"])
    return body


def refused_before(store, repo, terms: str) -> list[dict]:
    """What was refused before in `repo` under the SAME terms hash, most often first: [{"code", "path", "count",
    "pulls"}], `count` being distinct pull requests. Another repository's or another terms' refusals are not here."""
    got: dict[tuple[str, str], set[int]]
    repo_k, got = repo_key(repo), {}
    for name, b in _rows(store, "refusal", str(terms)):
        if not _refusal_row(b) or b["repo"] != repo_k or b["terms"] != terms \
                or name != _id("refusal", repo_k, b["terms"], b["pull"], b["code"], b["path"]):
            continue                # a row that does not say what its name says is not a memory of a refusal
        got.setdefault((b["code"], b["path"]), set()).add(b["pull"])
    return [{"code": code, "path": path, "count": len(pulls), "pulls": sorted(pulls)}
            for (code, path), pulls in sorted(got.items(), key=lambda kv: (-len(kv[1]), kv[0]))]


def preflight_seen(store, repo, terms: str, ready: bool, found=(), supplier: str = "", tree: str = "", at: float | None = None) -> dict:
    """Remember one `knos preflight`: under which terms, whether it said ready, and what it found ([(code, path)]).
    One memory per tree state (`tree`: a hash of the change), so running it twice on the same change is one."""
    at = float(at if at is not None else time.time())
    body = {"repo": repo_key(repo), "terms": str(terms), "ready": bool(ready), "supplier": _agent_key(supplier)[:64],
            "found": [{"code": str(c), "path": _short(p)} for c, p in list(found)[:50]], "tree": str(tree)[:64], "at": at}
    store.put("preflight", _id("preflight", body["repo"], body["terms"], body["supplier"], body["tree"] or at), body)
    return body


def preflights(store, repo, terms: str | None = None) -> list[dict]:
    """The preflights remembered for `repo`, oldest first; `terms`: only those under that terms hash."""
    repo_k = repo_key(repo)
    rows = [b for _n, b in _rows(store, "preflight", terms or "") if isinstance(b, dict) and b.get("repo") == repo_k
            and (terms is None or b.get("terms") == terms) and isinstance(b.get("at"), (int, float))]
    return sorted(rows, key=lambda b: b["at"])


def appeal_outcome(store, repo, appeal_id: str, state: str, supplier: str, pull: int, reason: str = "", why: str = "",
                   terms: str = "", at: float | None = None) -> dict:
    """Remember where one appeal stands: `state` is open, rerun (the neutral judge was asked to run it again),
    accepted (the rejection was overturned) or rejected (it was upheld; `why` says on what). It goes on the
    supplier's record too: appealed when it opens, overturned when it ends accepted. An appeal is one memory, rewritten
    as it moves. Raises ValueError for another state."""
    body: dict[str, Any] = {"repo": repo_key(repo), "id": str(appeal_id), "state": state, "supplier": _agent_key(supplier)[:64], "pull": int(pull),
            "reason": _short(reason, 400), "why": _short(why, 400), "terms": str(terms), "at": float(at if at is not None else time.time())}
    if not _appeal_row(body):
        raise ValueError(f"an appeal is {', '.join(APPEAL_STATES)}, with an id and a pull request")
    store.put("appeal", _id("appeal", body["repo"], body["id"]), body)
    if body["supplier"]:
        supplier_event(store, repo, body["supplier"], pull, "appealed", terms, body["at"])
        if state == "accepted":
            supplier_event(store, repo, body["supplier"], pull, "overturned", terms, body["at"])
    return body


def appeals(store, repo, supplier: str | None = None) -> list[dict]:
    """The appeals remembered for `repo`, oldest first; `supplier`: only theirs."""
    repo_k, who = repo_key(repo), _agent_key(supplier)
    rows = [b for n, b in _rows(store, "appeal", who) if _appeal_row(b) and b["repo"] == repo_k
            and n == _id("appeal", repo_k, b["id"]) and (supplier is None or b["supplier"] == who)]
    return sorted(rows, key=lambda b: (b["at"], b["id"]))


# ---- the buyer's side: how an exception under given terms ended before, on five tiers (Sibyl) ---------------------

EXCEPTION_ENDINGS = ("accepted_on_appeal", "corrected_and_passed", "refused")
EXCEPTION_QUEUE = "knos_exception_queue"    # the state document's key (HOT); one per tenant, and a tenant is one buyer organisation
_EXC_MARK = "knos-exception"                # what makes a journal event one of these (COLD)
_EXC_KEPT = 200                             # the newest cases one supplier-and-terms entity keeps (WARM); its counts keep them all
_PERIOD = re.compile(r"[0-9]{4}(?:0[1-9]|1[0-2])")


def _evidence(ids_) -> list[str]:
    seen: list[str] = []
    for x in ids_ or ():
        x = _short(x, 120)
        if x and x not in seen:
            seen.append(x)
    return seen[:8]


def _exception_key(terms, reason, supplier, exception_id="-") -> tuple[str, str, str, str]:
    terms, reason, who, eid = str(terms), str(reason), _agent_key(supplier)[:64], _short(exception_id, 120)
    if not _HASH.fullmatch(terms) or not _CODE_WORD.fullmatch(reason) or not who or not eid:
        raise ValueError("an exception is remembered under a terms hash (64 hex characters), a reason code, a supplier and an id")
    return terms, reason, who, eid


def _case_row(c) -> bool:
    return (isinstance(c, dict) and isinstance(c.get("id"), str) and 1 <= len(c["id"]) <= 120
            and isinstance(c.get("reason"), str) and bool(_CODE_WORD.fullmatch(c["reason"])) and c.get("ending") in EXCEPTION_ENDINGS
            and isinstance(c.get("at"), (int, float)) and not isinstance(c.get("at"), bool)
            and (c.get("seconds") is None or (isinstance(c["seconds"], (int, float)) and not isinstance(c["seconds"], bool) and c["seconds"] >= 0))
            and isinstance(c.get("period"), str) and bool(_PERIOD.fullmatch(c["period"]))
            and isinstance(c.get("evidence"), list) and len(c["evidence"]) <= 8 and all(isinstance(x, str) and len(x) <= 120 for x in c["evidence"]))


def _exception_row(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("supplier"), str) and 1 <= len(body["supplier"]) <= 64
            and isinstance(body.get("terms"), str) and bool(_HASH.fullmatch(body["terms"]))
            and isinstance(body.get("cases"), list) and len(body["cases"]) <= _EXC_KEPT and all(_case_row(c) for c in body["cases"])
            and isinstance(body.get("counts"), dict)
            and all(isinstance(k, str) and isinstance(v, dict) and all(e in EXCEPTION_ENDINGS and type(n) is int and n >= 0 for e, n in v.items())
                    for k, v in body["counts"].items()))


def exception_queue(store) -> list[dict]:
    """The exceptions open now, oldest first: [{"id", "terms", "reason", "supplier", "evidence", "at"}]. One state
    document (the HOT tier), rewritten as exceptions open and end. Empty with no memory."""
    rows = store.state(EXCEPTION_QUEUE).get("open")
    rows = [r for r in rows if isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("at"), (int, float))] \
        if isinstance(rows, list) else []
    return sorted(rows, key=lambda r: (r["at"], r["id"]))


def exception_opened(store, terms: str, reason: str, supplier: str, exception_id: str, evidence=(), at: float | None = None) -> dict:
    """Put one exception on the live queue: `exception_id` (an invoice line's, an evaluation's or a correction's id) is
    open under the terms with hash `terms`, for `reason` (a refusal code or a line state), about `supplier`'s work.
    Opening the same id twice keeps the first time it opened. Raises ValueError for what is not an exception."""
    terms, reason, who, eid = _exception_key(terms, reason, supplier, exception_id)
    queue = exception_queue(store)
    had = next((r for r in queue if r["id"] == eid), None)
    row = {"id": eid, "terms": terms, "reason": reason, "supplier": who, "evidence": _evidence([*(had or {}).get("evidence", []), *evidence]),
           "at": float(had["at"] if had else at if at is not None else time.time())}
    store.set_state(EXCEPTION_QUEUE, {"open": [r for r in queue if r["id"] != eid] + [row]})
    return row


def _exception_entity(store, who: str, terms: str) -> dict:
    name = _id("exception", who, terms)
    for n, b in _rows(store, "exception", terms):
        if n == name and _exception_row(b) and b["supplier"] == who and b["terms"] == terms:
            return b
    return {"supplier": who, "terms": terms, "cases": [], "counts": {}}


def exception_resolved(store, terms: str, reason: str, supplier: str, exception_id: str, ending: str, evidence=(),
                       opened_at: float | None = None, at: float | None = None, period: str = "") -> dict:
    """Remember how one exception ended: `ending` is one of EXCEPTION_ENDINGS (accepted on appeal; corrected and then
    passed; refused). It leaves the live queue (HOT), is counted on the entity of this supplier under these terms
    (WARM: one entity per supplier-and-terms, its newest 200 cases and a count of every one), and is appended to the
    journal (COLD), which is never rewritten. `opened_at`: when it opened, when the queue does not hold it; the time it
    took is `at` less that. `period`: the statement period it belongs to (yyyymm; default: the month of `at`, UTC).
    The same id ending the same way twice is one memory. Raises ValueError for another ending."""
    terms, reason, who, eid = _exception_key(terms, reason, supplier, exception_id)
    at = float(at if at is not None else time.time())
    period = period or time.strftime("%Y%m", time.gmtime(at))
    if ending not in EXCEPTION_ENDINGS or not _PERIOD.fullmatch(period):
        raise ValueError(f"an exception ends {', '.join(EXCEPTION_ENDINGS)}, in a period written yyyymm")
    held = getattr(store, "held", None)
    with held() if held is not None else contextlib.nullcontext(store):
        queue = exception_queue(store)
        was = next((r for r in queue if r["id"] == eid), None)
        opened = float(was["at"]) if was else opened_at
        case: dict[str, Any] = {"id": eid, "reason": reason, "ending": ending, "at": at, "period": period,
                "seconds": max(0.0, at - float(opened)) if opened is not None else None,
                "evidence": _evidence([*(was or {}).get("evidence", []), *evidence])}
        body = _exception_entity(store, who, terms)
        old = next((c for c in body["cases"] if c["id"] == eid), None)
        if old is not None and old["ending"] == ending and old["reason"] == reason:
            return old                                      # judged twice, remembered once
        counts = {k: dict(v) for k, v in body["counts"].items()}
        if old is not None:                                 # the same exception ended again, another way: the later ending stands
            counts[old["reason"]][old["ending"]] = max(0, counts.get(old["reason"], {}).get(old["ending"], 0) - 1)
        counts.setdefault(reason, {})[ending] = counts.get(reason, {}).get(ending, 0) + 1
        cases = sorted([c for c in body["cases"] if c["id"] != eid] + [case], key=lambda c: (c["at"], c["id"]))[-_EXC_KEPT:]
        store.put("exception", _id("exception", who, terms), {"supplier": who, "terms": terms, "cases": cases, "counts": counts})
        took = f" after {int(case['seconds'])} s" if case["seconds"] is not None else ""
        store.journal(evaluated={"exception": eid, "terms": terms, "reason": reason, "supplier": who, "evidence": case["evidence"]},
                      acted=f"{ending.replace('_', ' ')}{took}: {reason} ({who})",
                      extra={"kind": _EXC_MARK, "id": eid, "terms": terms, "reason": reason, "supplier": who, "ending": ending,
                             "at": at, "period": period, "seconds": case["seconds"]})
        if was is not None:
            store.set_state(EXCEPTION_QUEUE, {"open": [r for r in queue if r["id"] != eid]})
    return case


def exceptions_before(store, terms: str, reason: str, supplier: str | None = None) -> dict:
    """How the same exception ended before: every remembered case of `reason` under the terms with hash `terms`, for one
    `supplier` or for all of them. {"terms", "reason", "supplier", "seen", "endings": {ending: count}, "most_often",
    "seconds": {"median", "fastest", "slowest", "timed"} or None, "evidence": [ids, newest first], "cases": [the newest
    five], "open": how many of the same are on the live queue now, "said": the journal's own line for the newest}.
    All zero and empty with no memory: another terms hash, another reason or another tenant answers nothing here."""
    terms, reason = str(terms), str(reason)
    who = _agent_key(supplier)[:64] if supplier else ""
    endings, cases = {e: 0 for e in EXCEPTION_ENDINGS}, []
    for name, b in _rows(store, "exception", terms):
        if not _exception_row(b) or b["terms"] != terms or name != _id("exception", b["supplier"], terms) or (who and b["supplier"] != who):
            continue                # a row that does not say what its name says is not a memory of an exception
        for e, n in b["counts"].get(reason, {}).items():
            endings[e] += n
        cases += [{**c, "supplier": b["supplier"]} for c in b["cases"] if c["reason"] == reason]
    cases.sort(key=lambda c: (-c["at"], c["id"]))
    took = sorted(c["seconds"] for c in cases if c["seconds"] is not None)
    seen = sum(endings.values())
    evidence: list[str] = []
    for c in cases:
        evidence += [x for x in c["evidence"] if x not in evidence]
    said, newest = "", float("-inf")
    for e in store.events(200) if seen else []:     # the journal is in the order it was written: the newest ending is the latest `at`
        x = e.get("extra")
        if isinstance(x, dict) and x.get("kind") == _EXC_MARK and x.get("terms") == terms and x.get("reason") == reason \
                and (not who or x.get("supplier") == who) and isinstance(x.get("at"), (int, float)) and x["at"] > newest:
            said, newest = str(e.get("acted") or "")[:300], x["at"]
    return {"terms": terms, "reason": reason, "supplier": who, "seen": seen, "endings": endings,
            "most_often": max(EXCEPTION_ENDINGS, key=lambda e: (endings[e], -EXCEPTION_ENDINGS.index(e))) if seen else "",
            "seconds": {"median": took[(len(took) - 1) // 2], "fastest": took[0], "slowest": took[-1], "timed": len(took)} if took else None,
            "evidence": evidence[:20], "cases": cases[:5], "said": said,
            "open": sum(1 for r in exception_queue(store) if r.get("terms") == terms and r.get("reason") == reason
                        and (not who or r.get("supplier") == who))}


# What a remembered ending teaches a supplier who is about to start under the same terms, or with the same buyer: the
# protection that would have covered it (knos.preflight PROTECTIONS ids) and what to ask for.
LATE_SECONDS = 7 * 86400.0      # an exception that took longer than this to end in acceptance was a late acceptance
TAUGHT = {"dispute": ("predictable_payment", "reserve"), "appeal_won": ("appeal", "arbiter"),
          "late_acceptance": ("acceptance_deadline", "deadline")}
_TAUGHT_WORDS = {"dispute": ("ended in a dispute", "Ask the buyer to bind the work to a funded reserve."),
                 "appeal_won": ("was rejected and then won on appeal", "Ask for an arbiter named at funding."),
                 "late_acceptance": ("was accepted late", "Ask for an acceptance deadline: an order paid on a suite and funded with `auto`.")}


def protections_recalled(store, repo, terms: str, supplier: str = "") -> list[dict]:
    """What memory says a supplier should ask for before starting under the terms with hash `terms` in `repo`: each
    remembered dispute, appeal won and late acceptance of THESE terms, or of THIS supplier under any terms, becomes the
    protection that covers it. [{"because": dispute | appeal_won | late_acceptance, "protection": a knos.preflight
    PROTECTIONS id, "ask": reserve | arbiter | deadline, "count", "evidence": [ids, newest first], "said"}], in TAUGHT's
    order, only those seen. Read from three kinds of memory: appeals (an appeal that ended accepted), the
    supplier-and-terms exception entities (a `disputed` case; an ending other than refused after more than
    LATE_SECONDS) and the repository's orders (one that ended disputed). Empty with no memory: a plain hook learns
    nothing here, so a preflight without the engine recommends nothing from history."""
    terms, repo_k, who = str(terms), repo_key(repo), _agent_key(supplier)[:64]
    seen: dict[str, dict[str, tuple[float, list[str]]]] = {k: {} for k in TAUGHT}

    def add(kind: str, at: float, case: str, *evidence) -> None:
        seen[kind][case] = (float(at), [case, *(str(x) for x in evidence if x)])

    for a in appeals(store, repo):
        if a["state"] == "accepted" and ((terms and a["terms"] == terms) or (who and a["supplier"] == who)):
            add("appeal_won", a["at"], f"appeal {a['id']}", f"pull request #{a['pull']}")
    names = {n: b for q in {terms, who} - {""} for n, b in _rows(store, "exception", q)}
    for name, b in names.items():
        if not _exception_row(b) or name != _id("exception", b["supplier"], b["terms"]) \
                or not (b["terms"] == terms or (who and b["supplier"] == who)):
            continue                # a row that does not say what its name says is not a memory of an exception
        for c in b["cases"]:
            if c["reason"] == "disputed":
                add("dispute", c["at"], c["id"], *c["evidence"][:2])
            if c["ending"] == "accepted_on_appeal":
                add("appeal_won", c["at"], c["id"], *c["evidence"][:2])
            if c["ending"] != "refused" and c["seconds"] is not None and c["seconds"] > LATE_SECONDS:
                add("late_acceptance", c["at"], c["id"], *c["evidence"][:2])
    for o in orders(store, repo_k) if repo_k else ():
        if o["outcome"] == "disputed":
            add("dispute", float(o["seq"]), f"order {o['order']}")
    out = []
    for kind, (protection, ask) in TAUGHT.items():
        if not seen[kind]:
            continue
        ids: list[str] = []
        for _case, (_at, got) in sorted(seen[kind].items(), key=lambda kv: (-kv[1][0], kv[0])):
            ids += [x for x in got if x not in ids]
        n, (what, do) = len(seen[kind]), _TAUGHT_WORDS[kind]
        newest = sorted(seen[kind], key=lambda c: (-seen[kind][c][0], c))[:3]
        out.append({"because": kind, "protection": protection, "ask": ask, "count": n, "evidence": ids[:8],
                    "said": f"Work here {what} {n} time{'s' if n != 1 else ''} before ({', '.join(newest)}). {do}"})
    return out


def terms_text(store, terms: str, text: str | None = None) -> str:
    """The text of the terms with hash `terms`, kept as a reference document (the REFERENCE tier). With `text` it is
    stored; a text is never replaced under the same hash by a different one (ValueError). Returns the text held, or
    "" when none is (and always "" with no memory)."""
    terms = str(terms)
    if not _HASH.fullmatch(terms):
        raise ValueError("terms are named by their hash: 64 hex characters")
    held = store.reference(f"knos-terms:{terms}").get("text")
    held = held if isinstance(held, str) else ""
    if text is None or text == held:
        return held
    if held:
        raise ValueError("another text is already kept under this terms hash")
    store.set_reference(f"knos-terms:{terms}", {"terms": terms, "text": str(text), "sha256": hashlib.sha256(str(text).encode()).hexdigest()},
                        "knos-terms")
    return store.reference(f"knos-terms:{terms}").get("text") or ""


def periods_closed(store) -> list[dict]:
    """The closed periods, oldest first, read from the engine's archive (the ARCHIVE tier)."""
    rows = [b for n, b in store.archived("exception_period") if isinstance(b.get("period"), str) and b["period"] == n]
    return sorted(rows, key=lambda b: b["period"])


def period_closed(store, period: str, at: float | None = None) -> dict:
    """Close one statement period (yyyymm): what its exceptions came to ({"period", "resolved", "endings", "ids",
    "closed_at"}) is written as one entity and moved to the engine's archive, where nothing rewrites it. Closing a
    period that is closed returns what the archive holds. The cases stay on their supplier-and-terms entities, so a
    recall still counts them. With no memory the summary is empty and nothing is kept."""
    period = str(period)
    if not _PERIOD.fullmatch(period):
        raise ValueError("a period is written yyyymm")
    had = next((b for b in periods_closed(store) if b["period"] == period), None)
    if had is not None:
        return had
    endings, got = {e: 0 for e in EXCEPTION_ENDINGS}, []
    for name, b in getattr(store, "rows", lambda _c: [])("exception"):
        if _exception_row(b) and name == _id("exception", b["supplier"], b["terms"]):
            for c in b["cases"]:
                if c["period"] == period:
                    endings[c["ending"]] += 1
                    got.append(c["id"])
    body = {"period": period, "resolved": len(got), "endings": endings, "ids": sorted(got)[:500],
            "closed_at": float(at if at is not None else time.time())}
    store.put("exception_period", period, body)
    store.archive("exception_period", period, "period closed")
    return body


# ---- the approver's defence: who approved what, under which policy, and whether its evidence still matches -------

APPROVAL_MARK = "knos-approval"             # what makes a journal event one of these (COLD)
_APPROVAL_KEPT = 50                         # the approvals one commitment's entity keeps (WARM); the journal keeps them all
_APPROVAL_JOURNAL = 100_000                 # how far back the journal is read to check an approval against it
_APPROVAL_TEXT = {"commitment": 120, "approver": 64, "policy_version": 64, "amount": 40, "at": 40, "why": 400,
                  "beneficiary": 120, "expires": 40, "purchase_order": 120, "role": 32}
_APPROVAL_NEEDS = ("commitment", "approver", "policy_version", "amount", "at")


def canonical(value) -> bytes:
    """The bytes a hash of a JSON value is taken over: keys sorted, no spaces, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def evidence_hash(evidence) -> str:
    """The sha256 of an evidence snapshot (a JSON object: the five receipt parts as the approver saw them), or the hash
    itself when 64 hex characters are given."""
    if isinstance(evidence, str) and _HASH.fullmatch(evidence.strip().lower()):
        return evidence.strip().lower()
    if not isinstance(evidence, (dict, list)):
        raise ValueError("evidence is a JSON object (the snapshot the approver saw) or its sha256")
    return hashlib.sha256(canonical(evidence)).hexdigest()


def approval_record(record) -> dict:
    """One approval record as memory keeps it: who (`approver`) approved what (`commitment`, `amount`, `beneficiary`,
    `purchase_order`), under which `policy_version`, when (`at`), until when (`expires`), why, and the sha256 of the
    evidence the approver saw (`evidence_sha256`, or `evidence` itself, which is hashed and not kept). `record_sha256`
    is the hash of the rest. Raises ValueError for a record without a commitment, approver, policy version, amount
    and time, or with no evidence."""
    if not isinstance(record, dict):
        raise ValueError("an approval record is a JSON object")
    out: dict[str, Any] = {}
    for key, most in _APPROVAL_TEXT.items():
        got = record.get(key)
        out[key] = "" if got is None or isinstance(got, bool) else _short(got, most)
    missing = [k for k in _APPROVAL_NEEDS if not out[k]]
    if missing:
        raise ValueError(f"an approval record names its {', '.join(missing)}")
    given = record.get("evidence_sha256") if record.get("evidence_sha256") else record.get("evidence")
    if given is None:
        raise ValueError("an approval record names the evidence the approver saw: evidence_sha256 or evidence")
    out["evidence_sha256"] = evidence_hash(given)
    out["record_sha256"] = hashlib.sha256(canonical(out)).hexdigest()
    return out


def _approval_intact(a) -> bool:
    return isinstance(a, dict) and isinstance(a.get("record_sha256"), str) \
        and hashlib.sha256(canonical({k: v for k, v in a.items() if k != "record_sha256"})).hexdigest() == a["record_sha256"]


def approval_kept(store, record) -> dict:
    """Remember one approval record in the buyer's tenant: added to the entity of its commitment (WARM: one entity per
    commitment, every approval given for it) and appended to the journal (COLD), which nothing rewrites. The same record
    kept twice is one memory. Returns the record as kept."""
    rec = approval_record(record)
    name = _id("approval", rec["commitment"])
    held = getattr(store, "held", None)
    with held() if held is not None else contextlib.nullcontext(store):
        body = store.get("approval", name)
        kept = [a for a in body.get("approvals", []) if isinstance(a, dict)] if body.get("commitment") == rec["commitment"] else []
        if any(a.get("record_sha256") == rec["record_sha256"] for a in kept):
            return rec
        kept = sorted([*kept, rec], key=lambda a: (str(a.get("at")), str(a.get("record_sha256"))))[-_APPROVAL_KEPT:]
        store.put("approval", name, {"commitment": rec["commitment"], "approvals": kept})
        store.journal(evaluated={"commitment": rec["commitment"], "evidence_sha256": rec["evidence_sha256"], "policy_version": rec["policy_version"]},
                      acted=f"approved {rec['amount']} under policy {rec['policy_version']} ({rec['approver']})",
                      extra={"kind": APPROVAL_MARK, **rec})
    return rec


def approval_recalled(store, commitment: str, evidence=None) -> dict:
    """Who approved `commitment`, what, under which policy version, and why, read from memory only. Each approval says
    whether it is `intact` (its record hashes to what it says and the journal holds the same record) and, when the
    evidence as it stands now is given, whether it still `matches` the evidence the approver saw. `journal_only`: the
    approvals the journal holds and the entity has lost (an entity edited after the fact). Empty with no memory."""
    commitment = _short(commitment, 120)
    if not commitment:
        raise ValueError("name the commitment that was approved")
    now = evidence_hash(evidence) if evidence is not None else None
    body = store.get("approval", _id("approval", commitment))
    kept = [a for a in body.get("approvals", []) if isinstance(a, dict)] if body.get("commitment") == commitment else []
    journal: dict[str, dict] = {}
    for e in store.events(_APPROVAL_JOURNAL):
        x = e.get("extra")
        if isinstance(x, dict) and x.get("kind") == APPROVAL_MARK and x.get("commitment") == commitment and _approval_intact(
                {k: v for k, v in x.items() if k != "kind"}):
            journal[str(x["record_sha256"])] = {k: v for k, v in x.items() if k != "kind"}
    rows = []
    for a in kept:
        intact = _approval_intact(a) and journal.get(str(a.get("record_sha256"))) == a
        rows.append({**a, "intact": intact, "matches": None if now is None else (intact and a.get("evidence_sha256") == now)})
    lost = [r for _h, r in sorted(journal.items()) if r not in kept]       # what the journal holds and the entity no longer does, word for word
    out = {"kind": "knos.recall.approval/1", "commitment": commitment, "approvals": rows, "seen": len(rows), "journal_only": lost,
           "intact": bool(rows) and all(r["intact"] for r in rows) and not lost,
           "evidence_now": now, "matches": None if now is None or not rows else all(r["matches"] for r in rows),
           "memory": not isinstance(store, NullStore)}
    return out


# ---- supplier reuse: what a supplier brings from other buyers, and what its second buyer saved (Sibyl) -------------

SUPPLY_OUTCOMES = ("accepted", "refused", "disputed", "reverted")
_GRANT_REFS = 200                           # the newest deliverable ids one grant keeps, so a result is counted once


def _buyer_key(buyer) -> str:
    who = _agent_key(buyer)
    if not who:
        raise ValueError("name the buyer organisation")
    return hashlib.sha256(who.encode()).hexdigest()[:16]


def _grant_row(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("buyer"), str) and 1 <= len(body["buyer"]) <= 64
            and isinstance(body.get("terms"), str) and bool(_HASH.fullmatch(body["terms"]))
            and isinstance(body.get("outcomes"), dict) and all(body["outcomes"].get(o, 0) >= 0 and type(body["outcomes"].get(o, 0)) is int for o in SUPPLY_OUTCOMES)
            and type(body.get("value")) is int and body["value"] >= 0 and isinstance(body.get("refs"), list))


def outcome_granted(store, supplier, buyer, terms: str, outcome: str, ref: str, value: int = 0, at: float | None = None) -> dict:
    """In the SUPPLIER's tenant: buyer `buyer` grants that one result of `supplier`'s work under the terms with hash
    `terms` may be shown to its other buyers: `outcome` (one of SUPPLY_OUTCOMES) of deliverable `ref`, `value` in base
    units when accepted. Nothing is kept that a buyer did not grant: this is the only call that writes it. The same
    `ref` is counted once. One entity per buyer and terms (WARM), one journal event per result (COLD)."""
    terms, who, ref = str(terms), _agent_key(supplier)[:64], _short(ref, 120)
    if outcome not in SUPPLY_OUTCOMES or not _HASH.fullmatch(terms) or not who or not ref or type(value) is not int or value < 0:
        raise ValueError(f"a granted result is {', '.join(SUPPLY_OUTCOMES)}, of a named deliverable, under a terms hash, with a value of 0 or more")
    by = _agent_key(buyer)[:64]
    name = _id("granted", _buyer_key(buyer), terms)
    at = float(at if at is not None else time.time())
    held = getattr(store, "held", None)
    with held() if held is not None else contextlib.nullcontext(store):
        body = store.get("granted", name)
        if not _grant_row(body):
            body = {"supplier": who, "buyer": by, "terms": terms, "outcomes": {o: 0 for o in SUPPLY_OUTCOMES}, "value": 0, "refs": [], "first_at": at, "last_at": at}
        if ref in body["refs"]:
            return body
        outcomes = {o: int(body["outcomes"].get(o, 0)) for o in SUPPLY_OUTCOMES}
        outcomes[outcome] += 1
        body = {**body, "outcomes": outcomes, "value": body["value"] + (value if outcome == "accepted" else 0), "refs": [*body["refs"], ref][-_GRANT_REFS:],
                "first_at": min(float(body.get("first_at", at)), at), "last_at": max(float(body.get("last_at", at)), at)}
        store.put("granted", name, body)
        store.journal(evaluated={"supplier": who, "buyer": by, "terms": terms, "ref": ref}, acted=f"{outcome} under granted terms ({by})",
                      extra={"kind": "knos-granted", "supplier": who, "buyer": by, "terms": terms, "ref": ref, "outcome": outcome, "value": value, "at": at})
    return body


def grant_withdrawn(store, buyer, terms: str) -> bool:
    """The buyer takes its grant back: the entity goes to the engine's archive (ARCHIVE) and no recall shows it again.
    False when nothing was granted."""
    return store.archive("granted", _id("granted", _buyer_key(buyer), str(terms)), "grant withdrawn")


def onboarded(store, buyer, ordered_at: float | None = None, paid_at: float | None = None) -> dict:
    """In the SUPPLIER's tenant: when `buyer` first ordered from this supplier and when it first paid it. The earliest
    of each is kept; the buyer is kept as a hash of its name only (a time is not a grant). One entity per buyer."""
    key = _buyer_key(buyer)
    body = store.get("onboarding", key)
    def first(old, new):
        got = [float(x) for x in (old, new) if isinstance(x, (int, float)) and not isinstance(x, bool)]
        return min(got) if got else None
    body = {"buyer_key": key, "ordered_at": first(body.get("ordered_at"), ordered_at), "paid_at": first(body.get("paid_at"), paid_at)}
    store.put("onboarding", key, body)
    return body


def reuse(store) -> dict:
    """The onboarding counter vendors' reuse needs, from the supplier's memory: buyers in the order they first ordered,
    each one's time from first order to first payment, and what the second buyer saved against the first
    (`saved_seconds`: first less second; None until both were paid). All zero with no memory."""
    rows = [b for _n, b in store.rows("onboarding") if isinstance(b.get("ordered_at"), (int, float))]
    rows.sort(key=lambda b: (b["ordered_at"], str(b.get("buyer_key"))))
    took = [max(0.0, b["paid_at"] - b["ordered_at"]) if isinstance(b.get("paid_at"), (int, float)) else None for b in rows]
    first, second = (took + [None, None])[:2]
    return {"buyers": len(rows), "paid": sum(1 for t in took if t is not None), "seconds": took,
            "first_seconds": first, "second_seconds": second,
            "saved_seconds": first - second if first is not None and second is not None else None}


def supplier_brings(store, supplier, buyer) -> dict:
    """What `supplier` brings to `buyer` from its OTHER buyers, as they granted it: per buyer and terms, the results and
    the value accepted; their totals; and the onboarding counter (reuse). `you`: this buyer's place in the order the
    supplier's buyers came (1 for the first), or None when it has not ordered yet."""
    who, mine = _agent_key(supplier)[:64], _buyer_key(buyer)
    rows = []
    for name, b in store.rows("granted"):
        if _grant_row(b) and b.get("supplier") == who and name == _id("granted", _buyer_key(b["buyer"]), b["terms"]) and _buyer_key(b["buyer"]) != mine:
            rows.append({"buyer": b["buyer"], "terms": b["terms"], "outcomes": b["outcomes"], "value": b["value"], "results": len(b["refs"]),
                         "first_at": b.get("first_at"), "last_at": b.get("last_at")})
    rows.sort(key=lambda r: (r["buyer"], r["terms"]))
    totals = {o: sum(r["outcomes"].get(o, 0) for r in rows) for o in SUPPLY_OUTCOMES}
    order = sorted((b for _n, b in store.rows("onboarding") if isinstance(b.get("ordered_at"), (int, float))),
                   key=lambda b: (b["ordered_at"], str(b.get("buyer_key"))))
    you = next((i for i, b in enumerate(order, 1) if b.get("buyer_key") == mine), None)
    return {"kind": "knos.recall.supplier/1", "supplier": who, "from": rows, "buyers": len({r["buyer"] for r in rows}),
            "outcomes": totals, "value": sum(r["value"] for r in rows), "reuse": reuse(store), "you": you,
            "memory": not isinstance(store, NullStore)}


# ---- what the judge learned, to carry between runs (knos.proof.memory) -------------------------------------------

LESSONS = ("tamper", "proof_rule", "repo_rule", "settlement", "order", "refusal", "appeal", "supplier")


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
    elif row["category"] == "order":        # how one past order ended (order_outcome): its name is made of what it says
        ok = _order_row(body) and name == _id("order", body["repo"], body["order"], body["outcome"])
    elif row["category"] == "refusal":      # one refusal under given terms (refused): named by what it says
        ok = _refusal_row(body) and name == _id("refusal", body["repo"], body["terms"], body["pull"], body["code"], body["path"])
    elif row["category"] == "appeal":       # one appeal and how it stands (appeal_outcome)
        ok = _appeal_row(body) and name == _id("appeal", body["repo"], body["id"])
    elif row["category"] == "supplier":     # one event of one supplier's record (supplier_event)
        ok = _supplier_row(body) and name == _id("supplier", body["repo"], body["supplier"], body["pull"], body["event"])
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
    both settle the same pull request at the same commit at the same time; the one that paid is the fact.

    The whole load is one batch on the store's connection (SibylStore.held), released once at its end."""
    n, paid = 0, None
    held = getattr(store, "held", None)
    with held() if held is not None else contextlib.nullcontext(store):
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
        return m is not None and m.group(1) not in ("version", "name", "main", "description", "license") and \
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


# ---- decisions on statement lines: accepted, refused or authorised, recalled when the same supplier and terms return --

LINE_DECISIONS = ("accepted", "refused", "authorised")
DECISION_MARK = "knos-line-decision"         # what makes a journal event one of these (COLD)
_DECISIONS_KEPT = 200                        # the decisions one supplier-and-terms entity keeps (WARM); the journal keeps them all


def _decision_row(body) -> bool:
    return (isinstance(body, dict) and isinstance(body.get("supplier"), str) and isinstance(body.get("terms"), str)
            and bool(_HASH.fullmatch(body["terms"])) and isinstance(body.get("decisions"), list))


def line_decided(store, supplier, terms: str, deliverable: str, decision: str, by: str, role: str, why: str = "", line: str = "",
                 on: str = "", at: float | None = None) -> dict:
    """Remember one decision about one statement line: `decision` (LINE_DECISIONS) of `deliverable` (its knos.ids
    deliverable id), by `by` in `role`, on the day `on`, for `why`, under the terms with hash `terms`, for `supplier`.
    The same decision of the same deliverable by the same person on the same day is one memory. Returns it."""
    who = _agent_key(supplier)[:64]
    if not who or not _HASH.fullmatch(str(terms)) or decision not in LINE_DECISIONS or not str(deliverable).strip() or not str(by).strip():
        raise ValueError("a decision is remembered for a supplier, under a terms hash (64 hex characters), of a deliverable, by someone: "
                         f"one of {', '.join(LINE_DECISIONS)}")
    row = {"deliverable": _short(deliverable, 80), "decision": decision, "by": _short(by, 64), "role": _short(role, 64), "why": _short(why, 300),
           "line": _short(line, 40), "on": _short(on, 10), "at": float(at if at is not None else time.time())}
    name = _id("decision", who, terms)
    held = getattr(store, "held", None)
    with held() if held is not None else contextlib.nullcontext(store):
        body = store.get("decision", name)
        kept = [d for d in body.get("decisions", []) if isinstance(d, dict)] if _decision_row(body) and body["supplier"] == who and body["terms"] == terms else []
        same = lambda d: all(d.get(k) == row[k] for k in ("deliverable", "decision", "by", "on"))  # noqa: E731
        was = next((d for d in kept if same(d)), None)
        if was is not None:
            return was
        store.put("decision", name, {"supplier": who, "terms": str(terms), "decisions": [*kept, row][-_DECISIONS_KEPT:]})
        store.journal(evaluated={"supplier": who, "terms": terms, "deliverable": row["deliverable"]},
                      acted=f"{decision} {row['deliverable']} ({row['by']}, {row['role']})", extra={"kind": DECISION_MARK, "supplier": who, "terms": terms, **row})
    return row


def line_decisions(store, supplier, terms: str, deliverable: str | None = None) -> list[dict]:
    """What was decided before about lines of `supplier` under the terms `terms`, oldest first; `deliverable`: only
    about that one. Read from memory only: [] with no memory (NullStore), or for another supplier or other terms."""
    who = _agent_key(supplier)[:64]
    if not who or not _HASH.fullmatch(str(terms)):
        return []
    body = store.get("decision", _id("decision", who, terms))
    if not _decision_row(body) or body["supplier"] != who or body["terms"] != terms:
        return []
    rows = [d for d in body["decisions"] if isinstance(d, dict) and d.get("decision") in LINE_DECISIONS]
    return [d for d in rows if deliverable is None or d.get("deliverable") == deliverable]
