"""`knos self`: one loop iteration, from a candidate commit an agent made to a recorded decision.

    init        the trusted referee checkout (a git worktree of main, never moved by the loop) and version v0
    parent      the version agents should build on next (HGM: by how its descendants did)
    run         judge one candidate with the referee from main, apply the daily cap, move it to canary, pay its
                bounty on devnet, write the archive and the public log
    audit       the audit tier (never used for merging) on accepted versions; a failure is flagged for rollback
    rollback    one command: a version leaves the loop branch, the branch goes back to the best remaining version
    referee     a referee change (the founder's): red-team gate, shadow on past jobs, founder signature

State folder (outside the repository): archive.json, record/ (Knos Record and its local memory store), referee-main/ (the trusted
checkout), runs/<version>/ (request, verdict, the candidate's diff), bundles/<target>/{sealed,audit}.tgz (the hidden
bundles, which the founder keeps; their hashes are in targets.yml). The loop never pushes and never touches main:
promoting a canary version to main is the founder's pull request (targets.yml loop.auto_merge_to_main: false).
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import config, publog, referee_gate, tiers
from .archive import Archive


class LoopError(RuntimeError):
    pass


def _git(repo, *args, check=True) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=600)
    if check and done.returncode != 0:
        raise LoopError(f"git {' '.join(args[:3])}: {done.stderr.strip()[-300:]}")
    return done.stdout.strip()


class Loop:
    def __init__(self, repo, state, *, branch: str | None = None, record_store=None):
        self.repo = Path(repo).expanduser().resolve()
        self.state = Path(state).expanduser().resolve()
        self.main_dir = self.state / "referee-main"
        self.archive = Archive(self.state / "archive.json")
        self._store = record_store
        self._log: publog.Log | None = None
        self._branch = branch

    # ---- setup ---------------------------------------------------------------------------------------------------
    def cfg(self) -> dict:
        return config.load(self.main_dir)

    @property
    def branch(self) -> str:
        return self._branch or f"{self.cfg()['loop']['branch']}"

    def log(self) -> publog.Log:
        if self._log is None:
            self._log = publog.Log(self.state / "record", store=self._store)
        return self._log

    def init(self, main_ref: str = "main") -> dict:
        self.state.mkdir(parents=True, exist_ok=True)
        commit = _git(self.repo, "rev-parse", main_ref)
        if not self.main_dir.exists():
            _git(self.repo, "worktree", "add", "--detach", str(self.main_dir), commit)
        head = _git(self.main_dir, "rev-parse", "HEAD")
        if head != commit:
            raise LoopError(f"the referee checkout is at {head[:12]}, main is {commit[:12]}: the founder moves it, by hand")
        root = self.archive.root(commit, judge_hash=tiers.tree_judge_hash(self.main_dir))
        root.setdefault("loop_hash", tiers.tree_loop_hash(self.main_dir))     # pinned: the referee checkout must keep it
        self.archive.save()
        if not _git(self.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{self.branch}", check=False):
            _git(self.repo, "branch", self.branch, commit)
        from .. import record
        if not any(e.get("claim") == publog.claim_id("main", "v0") for e in record.entries(self.state / "record")):
            self.log().write("claim", {"target": "main", "version": "v0", "parent": None, "lineage": ["v0"], "commit": commit,
                                       "decision": "root", "stage": "main", "judge_hash": root["judge_hash"]},
                             claim=publog.claim_id("main", "v0"))
        return root

    # ---- trees ---------------------------------------------------------------------------------------------------
    def _tree(self, name: str, commit: str) -> Path:
        d = self.state / "trees" / name
        if d.exists():
            _git(self.repo, "worktree", "remove", "--force", str(d), check=False)
            shutil.rmtree(d, ignore_errors=True)
        d.parent.mkdir(parents=True, exist_ok=True)
        _git(self.repo, "worktree", "add", "--detach", str(d), commit)
        return d

    def _drop(self, d: Path) -> None:
        _git(self.repo, "worktree", "remove", "--force", str(d), check=False)
        shutil.rmtree(d, ignore_errors=True)

    def bundle(self, tid: str, tier: str) -> Path:
        return self.state / "bundles" / tid / f"{tier}.tgz"

    # ---- the referee from main -----------------------------------------------------------------------------------
    def _judge(self, req: dict, run_dir: Path) -> dict:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "request.json").write_text(json.dumps(req, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "HOME", "USER", "LOGNAME") if k in os.environ}
        env.update({"PYTHONPATH": str(self.main_dir / "src"), "PYTHONDONTWRITEBYTECODE": "1"})
        done = subprocess.run([sys.executable, "-m", "knos.self.judge", str(run_dir / "request.json"), str(run_dir / "verdict.json")],
                              cwd=str(run_dir), env=env, capture_output=True, text=True, timeout=3600)
        if done.returncode != 0 or not (run_dir / "verdict.json").is_file():
            raise LoopError(f"the referee from main did not run: {done.stderr.strip()[-400:]}")
        return json.loads((run_dir / "verdict.json").read_text(encoding="utf-8"))

    # ---- one iteration -------------------------------------------------------------------------------------------
    def parent(self, tid: str, *, seed: int | None = None) -> dict:
        c = self.archive.choose_parent(tid, seed=seed)
        self.archive.save()
        c["commit"] = self.archive.get(c["parent"])["commit"]
        return c

    def _check_referee(self) -> dict:
        """The trusted checkout is untouched since `init`: clean, at the pinned commit, with the pinned hashes."""
        root = self.archive.nodes[0] if self.archive.nodes else None
        if root is None:
            raise LoopError("run `knos self init` first")
        if _git(self.main_dir, "status", "--porcelain", "--untracked-files=all"):
            raise LoopError("the referee checkout has local changes: the founder restores it before the loop runs again")
        if _git(self.main_dir, "rev-parse", "HEAD") != root["commit"]:
            raise LoopError("the referee checkout moved from the commit pinned at init")
        if root.get("loop_hash") and tiers.tree_loop_hash(self.main_dir) != root["loop_hash"]:
            raise LoopError("the referee checkout's code does not hash to the value pinned at init")
        return root

    def _jail(self, pay: dict | None) -> dict:
        """What no candidate run may read (masked) or write (read-only): the loop's state, the wallets, the repository."""
        st = self.state
        mask = [st / "referee-main", st / "bundles", st / "record", st / "runs", st / "archive.json", st / "loop.lock"]
        if pay and pay.get("wallet_dir"):
            mask.append(Path(pay["wallet_dir"]).expanduser())
        return {"mask": [str(m) for m in mask], "ro": [str(self.repo / ".git")]}

    def run(self, tid: str, candidate_ref: str, *, parent: str | None = None, agent: str = "", claimed_metric=None,
            pay: dict | None = None, sandbox: str = "auto", today: str | None = None, note: str = "") -> dict:
        """One iteration, under the loop's lock (one iteration at a time per state folder)."""
        self.state.mkdir(parents=True, exist_ok=True)
        with _locked(self.state / "loop.lock"):
            self.archive = Archive(self.state / "archive.json")        # what another process saved before the lock
            return self._run(tid, candidate_ref, parent=parent, agent=agent, claimed_metric=claimed_metric, pay=pay,
                             sandbox=sandbox, today=today, note=note)

    def _run(self, tid: str, candidate_ref: str, *, parent: str | None, agent: str, claimed_metric, pay: dict | None,
             sandbox: str, today: str | None, note: str) -> dict:
        cfg = self.cfg()
        t = config.target(cfg, tid)
        if t["kind"] != "product":
            raise LoopError(f"{tid} is a {t['kind']} target: only the founder changes the referee (knos self referee)")
        if t.get("status") != "open":
            raise LoopError(f"{tid} is {t.get('status')}: only open targets take candidates")
        choice = None
        if parent is None:
            choice = self.archive.choose_parent(tid)
            parent = choice["parent"]
        else:                                   # the agent asked `knos self parent` first: that recorded choice
            choice = next((c for c in reversed(self.archive.data.get("choices") or [])
                           if c.get("parent") == parent and c.get("target") == tid), None)
        pnode = self.archive.get(parent)
        if parent not in {n["id"] for n in self.archive.eligible(tid)}:
            raise LoopError(f"{parent} is {pnode['decision']}: only an accepted version (root, canary, promoted) of this "
                            "target is a parent; a candidate built on a refused or held version is not judged")
        root = self._check_referee()
        cand_commit = _git(self.repo, "rev-parse", candidate_ref)
        seen = next((n for n in self.archive.nodes if n.get("commit") == cand_commit), None)
        if seen is not None:
            raise LoopError(f"commit {cand_commit[:12]} was judged already as {seen['id']} ({seen['decision']})")
        vid = self.archive.next_id()
        run_dir = self.state / "runs" / vid
        pdir = self._tree(f"parent-{vid}", pnode["commit"])
        cdir = self._tree(f"cand-{vid}", cand_commit)
        try:
            req = {"target": tid, "repo": str(self.repo), "parent_commit": pnode["commit"], "candidate_commit": cand_commit,
                   "parent_dir": str(pdir), "candidate_dir": str(cdir), "claimed_metric": claimed_metric, "sandbox": sandbox,
                   "run_dir": str(run_dir), "bundles": {"sealed": str(self.bundle(tid, "sealed")), "audit": str(self.bundle(tid, "audit"))},
                   "expected_judge_hash": root.get("judge_hash", ""), "expected_loop_hash": root.get("loop_hash", ""),
                   "jail": self._jail(pay)}
            t0 = time.monotonic()
            v = self._judge(req, run_dir)
            v["seconds"] = round(time.monotonic() - t0, 1)
        finally:
            self._drop(pdir)
            self._drop(cdir)
        day = today or time.strftime("%Y-%m-%d", time.gmtime())
        pid = _patch_id(self.repo, run_dir / "candidate.diff")
        dup = next((n for n in self.archive.nodes if n["decision"] in ("canary", "promoted", "held") and
                    ((pid and n.get("patch_id") == pid) or (v.get("diff_hash") and n.get("diff_hash") == v.get("diff_hash")))), None)
        if dup is not None and v.get("decision") in ("accept", "held"):
            v["decision"] = "refused"
            v["reasons"] = list(v.get("reasons") or []) + [f"the same change as {dup['id']} ({dup['decision']}): judged and paid once"]
        decision, stage = decide(v, self.archive, int(cfg["loop"]["daily_merge_cap"]), day)
        node = {"id": vid, "parent": parent, "target": tid, "commit": cand_commit, "diff_hash": v.get("diff_hash", ""),
                "agent": agent, "decision": decision, "stage": stage, "metric": v.get("metric_candidate"),
                "metric_parent": v.get("metric_parent"), "gain": v.get("gain"), "judge_hash": v.get("judge_hash", ""),
                "candidate_judge_hash": v.get("candidate_judge_hash", ""), "reasons": (v.get("reasons") or [])[:8],
                "cheats": sorted({f["category"] for f in v.get("findings") or [] if f.get("severity") == "refuse"}),
                "tiers": {k: bool((v.get("tiers") or {}).get(k, {}).get("passed")) for k in (v.get("tiers") or {})},
                "canary_day": day if decision == "canary" else None, "note": note, "patch_id": pid}
        paid = None
        if decision == "canary":
            _git(self.repo, "update-ref", f"refs/self/{vid}", cand_commit)
            best = self.archive.best(tid, t["direction"])
            if best is None or _better(node["metric"], best["metric"], t["direction"]):
                _git(self.repo, "branch", "-f", self.branch, cand_commit)
        p = None
        if decision == "canary" and pay:
            from . import payout
            p = payout.plan(t)
            node["payout"] = {"status": "pending", "amount": p["amount"], "fee": p["fee"]}
        self.archive.add(node)
        self.archive.save()                      # the version is saved BEFORE any money moves
        if p is not None and pay:            # p is planned only when pay was given
            from . import payout
            try:
                paid = {**p, **payout.execute(p, **pay)}
                node["payout"] = {"status": "paid", **{k: paid[k] for k in ("amount", "fee", "payout_tx", "fee_tx", "payee", "mint") if k in paid}}
            except payout.PayoutError as why:   # kept and said, never retried by the loop: the founder settles the rest by hand
                part = getattr(why, "partial", None) or {}
                paid = {**p, **part, "status": "failed", "error": str(why)[:300]} if part else None
                node["payout"] = {"status": "failed", "error": str(why)[:300],
                                  **{k: part[k] for k in ("amount", "fee", "payout_tx", "payee", "mint") if k in part}}
            self.archive.set(vid, payout=node["payout"])
            self.archive.save()
        self.log().lines.clear()
        publog.iteration(self.log(), node=node, verdict=v, choice=choice, lineage=self.archive.lineage(vid), payout=paid)
        (run_dir / "agent_view.json").write_text(json.dumps(_agent_view(v), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return {"node": node, "verdict": v, "choice": choice, "payout": paid, "record_lines": len(self.log().lines)}

    # ---- audit, rollback -----------------------------------------------------------------------------------------
    def audit(self, tid: str, versions=None, *, sandbox: str = "auto", rollback: bool = False) -> list[dict]:
        t = config.target(self.cfg(), tid)
        out = []
        for n in self.archive.nodes:
            if n.get("target") != tid or n["decision"] not in ("canary", "promoted") or (versions and n["id"] not in versions):
                continue
            d = self._tree(f"audit-{n['id']}", n["commit"])
            try:
                a = tiers.audit_tier(self.bundle(tid, "audit"), t["audit"]["sha256"], t["audit"], d, sandbox=sandbox)
            finally:
                self._drop(d)
            self.archive.set(n["id"], audit={"passed": a["passed"], "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            self.log().write("verification", {"tier": "audit", "merging": False, **publog._tier("audit", a), "version": n["id"],
                                              "diff_hash": n.get("diff_hash", "")}, claim=publog.claim_id(tid, n["id"]))
            row = {"version": n["id"], "passed": a["passed"], "tests": a.get("tests"), "error": a.get("error")}
            if not a["passed"] and rollback:
                row["rollback"] = self.rollback(n["id"], reason="the audit tier failed: the version fits the sealed tests only")
            out.append(row)
        self.archive.save()
        return out

    def rollback(self, vid: str, *, reason: str = "rolled back by the founder") -> dict:
        n = self.archive.get(vid)
        if n["decision"] not in ("canary", "promoted"):
            raise LoopError(f"{vid} is {n['decision']}: only an accepted version is rolled back")
        if n["decision"] == "promoted":
            raise LoopError(f"{vid} is on main: the founder reverts it there with a pull request")
        gone = {vid} | {d["id"] for d in self.archive.descendants(vid)}
        for g in gone:
            if self.archive.get(g)["decision"] == "canary":
                self.archive.set(g, decision="rolled_back", rollback_reason=reason)
        cfg = self.cfg()
        t = config.target(cfg, n["target"])
        best = self.archive.best(n["target"], t["direction"])
        to = best["commit"] if best else self.archive.nodes[0]["commit"]
        _git(self.repo, "branch", "-f", self.branch, to)
        self.archive.save()
        self.log().write("verdict", {"decision": "rolled_back", "versions": sorted(gone), "reason": reason[:300],
                                     "branch_at": to, "stage": "canary"}, claim=publog.claim_id(n["target"], vid))
        return {"rolled_back": sorted(gone), "branch": self.branch, "branch_at": to}

    # ---- referee change (founder) --------------------------------------------------------------------------------
    def referee(self, candidate_ref: str, *, approval: dict | None = None, cases=None) -> dict:
        cfg = self.cfg()
        commit = _git(self.repo, "rev-parse", candidate_ref)
        d = self._tree(f"referee-{commit[:12]}", commit)
        try:
            jobs = []
            for n in self.archive.nodes:
                f = self.state / "runs" / n["id"] / "candidate.diff"
                if f.is_file():
                    t = config.target(cfg, n["target"])
                    jobs.append({"id": n["id"], "diff": str(f), "core": config.core_globs(cfg), "scope": t.get("scope") or []})
            got = referee_gate.referee_change(self.main_dir, d, cfg, jobs=jobs, approval=approval, cases=cases)
        finally:
            self._drop(d)
        got["candidate_commit"] = commit
        rt = got.get("red_team") or {}
        cid = f"self:referee:{commit[:12]}"
        if rt:
            self.log().write("verification", {"tier": "red_team", "passed": rt["passed"], "current_caught": rt["current"]["caught"],
                                              "candidate_caught": rt["candidate"]["caught"], "total": rt["current"]["total"],
                                              "newly_missed": rt["newly_missed"][:20],
                                              "candidate_judge_hash": got["candidate_judge_hash"]}, claim=cid)
        if got.get("shadow"):
            self.log().write("verification", {"tier": "referee_shadow", "jobs": got["shadow"]["jobs"],
                                              "disagreements": [x["job"] for x in got["shadow"]["disagreements"]]}, claim=cid)
        self.log().write("verdict", {"decision": got["decision"], "kind": "referee_change", "judge_hash": got["main_judge_hash"],
                                     "candidate_judge_hash": got["candidate_judge_hash"], "candidate_commit": commit,
                                     "reasons": [r[:300] for r in got.get("reasons", [])]}, claim=cid)
        if got["decision"] == "blocked":
            self.log().write("refusal", {"decision": "blocked", "kind": "referee_change", "reasons": [r[:300] for r in got["reasons"]]}, claim=cid)
        return got


def decide(v: dict, archive: Archive, cap: int, day: str) -> tuple[str, str]:
    """(decision, stage) of a verdict from main's referee: accept -> canary unless the daily merge cap is reached
    (then held for the founder); held stays held; refused stays refused. The loop never decides `main`."""
    decision, stage = {"accept": ("canary", "canary"), "held": ("held", "shadow" if (v.get("tiers") or {}).get("shadow") else "sealed"),
                       "refused": ("refused", "sealed")}[v["decision"]]
    if decision == "canary" and archive.merged_on(day) >= cap:
        decision, stage = "held", "shadow"
        v["reasons"] = list(v.get("reasons") or []) + [f"daily merge cap reached ({cap} on {day}): held for the founder"]
    return decision, stage


def _patch_id(repo, diff_file: Path) -> str:
    """git's patch-id of the judged diff: the same change on another parent has the same id."""
    try:
        text = diff_file.read_bytes()
    except OSError:
        return ""
    done = subprocess.run(["git", "-C", str(repo), "patch-id", "--stable"], input=text, capture_output=True, timeout=120)
    return done.stdout.decode().split(" ")[0].strip() if done.returncode == 0 else ""


@contextlib.contextmanager
def _locked(path: Path):
    """One `knos self run` at a time on a state folder, across processes: an exclusive lock that is not waited for
    (flock on POSIX; on Windows, which has no fcntl, msvcrt's lock of the file's first byte, as knos.record.journal does)."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise LoopError("another `knos self run` holds this state folder") from None
        yield
    finally:
        os.close(fd)


def _better(a, b, direction: str) -> bool:
    if a is None:
        return False
    if b is None:
        return True
    return a < b if direction == "lower" else a > b


def _agent_view(v: dict) -> dict:
    from .judge import agent_view
    return agent_view(v)
