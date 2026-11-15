"""The self loop's public log: every attempt, verdict, cheat caught and payout, written to Knos Record (knos.record:
one hash-chained JSON Lines file held in Sibyl tier by tier, anchored on devnet by Merkle root). Nothing here writes
the file itself; Record refuses anything that looks like a secret, a key, an e-mail or a local path.

One iteration writes, in order (domain "self", claim "self:<target>:<version>"):

    experiment    COLD   the attempt: agent, parent, diff hash, the HGM parent choice
    verification  COLD   one per tier that ran (public, sealed, shadow, audit): pass/fail, counts, metric
    cheat         COLD   one per refusing finding (rule, category, path)
    refusal       COLD   when refused or held: the reasons
    verdict       COLD   the decision, the referee's judge_hash (main's) and the candidate's
    payout        COLD   when paid: amount, fee, devnet signatures
    claim         WARM   the version's state: target, parent, lineage, commit, diff hash, decision, stage
"""

from __future__ import annotations

DOMAIN = "self"


class Log:
    def __init__(self, root=None, store=None):
        from .. import record
        self.record = record
        self.root = root
        self.store = store
        self.lines: list[dict] = []

    def _store(self):
        if self.store is None:
            self.store = self.record.sibyl(self.root)
        return self.store

    def write(self, kind: str, payload: dict, *, claim: str | None = None) -> dict:
        if kind == "claim":
            if claim is None:
                raise ValueError("a claim line names its claim")
            got =self.record.claim(claim, payload, domain=DOMAIN, root=self.root, store=self._store())
        else:
            got = self.record.append(kind, payload, claim=claim, domain=DOMAIN, root=self.root, store=self._store())
        self.lines.append(got)
        return got


def claim_id(target: str, version: str) -> str:
    return f"self:{target}:{version}"


def iteration(log: Log, *, node: dict, verdict: dict, choice: dict | None, lineage: list[str], payout: dict | None,
              audit: dict | None = None) -> list[dict]:
    """Every line of one iteration. Returns the lines written."""
    cid = claim_id(node["target"], node["id"])
    start = len(log.lines)
    log.write("experiment", {"version": node["id"], "target": node["target"], "agent": node.get("agent", ""),
                             "parent": node.get("parent"), "candidate_commit": node.get("commit", ""),
                             "diff_hash": node.get("diff_hash", ""), "parent_choice": _choice(choice)}, claim=cid)
    for tier in ("public", "sealed", "shadow"):
        t = (verdict.get("tiers") or {}).get(tier)
        if t:
            log.write("verification", {"tier": tier, **_tier(tier, t), "diff_hash": node.get("diff_hash", ""),
                                       "judge_hash": verdict.get("judge_hash", "")}, claim=cid)
    if audit:
        log.write("verification", {"tier": "audit", **_tier("audit", audit), "merging": False}, claim=cid)
    for f in verdict.get("findings") or []:
        if f.get("severity") == "refuse":
            log.write("cheat", {"cheat": f["category"], "rule": f["rule"], "path": f.get("path", ""),
                                "diff_hash": node.get("diff_hash", "")}, claim=cid)
    if node["decision"] in ("refused", "held", "rolled_back"):
        log.write("refusal", {"decision": node["decision"], "reasons": [r[:300] for r in verdict.get("reasons") or []][:8]}, claim=cid)
    log.write("verdict", {"decision": node["decision"], "stage": node.get("stage", ""), "passed": node["decision"] in ("canary", "promoted"),
                          "judge_hash": verdict.get("judge_hash", ""), "candidate_judge_hash": verdict.get("candidate_judge_hash", ""),
                          "referee": "main", "metric_parent": verdict.get("metric_parent"), "metric": verdict.get("metric_candidate"),
                          "gain": verdict.get("gain"), "diff_hash": node.get("diff_hash", "")}, claim=cid)
    if payout:
        log.write("payout", {k: payout[k] for k in ("amount", "fee", "mint", "payee", "payout_tx", "fee_tx", "fee_account",
                                                    "cluster") if k in payout} | {"synthetic": False, "test_money": True}, claim=cid)
    log.write("claim", {"target": node["target"], "version": node["id"], "parent": node.get("parent"), "lineage": lineage,
                        "commit": node.get("commit", ""), "diff_hash": node.get("diff_hash", ""), "decision": node["decision"],
                        "stage": node.get("stage", ""), "metric": node.get("metric")}, claim=cid)
    return log.lines[start:]


def _choice(c: dict | None) -> dict | None:
    if not c:
        return None
    return {"parent": c["parent"], "seed": c["seed"], "draws": [{k: d[k] for k in ("id", "alpha", "beta", "draw")} for d in c["draws"]][:12]}


def _tier(name: str, t: dict) -> dict:
    out: dict = {"passed": bool(t.get("passed"))}
    if t.get("tests"):
        out["counts"] = {k: t["tests"][k] for k in ("total", "passed", "failed", "errors", "skipped") if k in t["tests"]}
    if name == "sealed":
        out["rerun_agrees"] = t.get("rerun_agrees")
        out["metric_parent"] = (t.get("metric_parent") or {}).get("metric")
        out["metric"] = (t.get("metric_candidate") or {}).get("metric")
        out["bundle_sha256"] = t.get("bundle_sha256", "")
        if t.get("error"):
            out["error"] = t["error"][:200]
    if name == "shadow":
        out["disagreements"] = list(t.get("disagreements") or [])
    if name == "audit" and t.get("bundle_sha256"):
        out["bundle_sha256"] = t["bundle_sha256"]
    return out
