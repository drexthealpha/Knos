"""`knos proof ...`: the same engine the Stop hook runs, by hand."""

from __future__ import annotations

import json
from pathlib import Path

import typer


def register(app: typer.Typer, out, Stop, repo_of) -> None:
    proof = typer.Typer(add_completion=False, help="AI agent work counts only when Knos proves it")
    app.add_typer(proof, name="proof")

    def _store(repo: Path):
        from . import history
        try:
            return history.SibylStore.for_repo(repo)
        except Exception:  # noqa: BLE001
            return history.NullStore()

    @proof.command("check")
    def check(claim: str = typer.Argument(..., help="what the agent says is done"),
              in_: str = typer.Option(None, "--in", help="the repo (default: this one)")) -> None:
        """Run every check this claim needs (and what this repo's history requires). Exit 1 if any fails."""
        from . import engine
        repo = repo_of(in_)
        v = engine.evaluate(repo, claim, _store(repo))
        if not v.results:
            out.print("That claims nothing checkable.")
            return
        out.print(v.explain(), markup=False)
        out.print("[green]proven[/green]" if v.ok else "[red]not proven[/red]")
        if not v.ok:
            raise typer.Exit(1)

    @proof.command("run")
    def run(toml: Path = typer.Option(None, "--toml", help="default: .knos/proof.toml in the repo"),
            in_: str = typer.Option(None, "--in", help="the repo the checks run in (default: this one)")) -> None:
        """Run every [[check]] in .knos/proof.toml, whatever the claim. Exit 1 if any fails or none is defined."""
        from . import checks, engine
        repo = repo_of(in_)
        cfg = engine.load(toml) if toml else engine.config(repo)
        specs = [c for c in cfg.get("check", []) or [] if c.get("name") and c.get("run")]
        if not specs:
            raise Stop(cfg.get("_error") or "No [[check]] with a name and a run command: nothing to prove.")
        results = [checks.custom(repo, c["name"], c["run"]) for c in specs]
        for r in results:
            out.print(f"{'ok ' if r.ok else 'NO '} {r.name}: {r.detail}", markup=False, emoji=False)
        if not all(r.ok for r in results):
            out.print("[red]not proven[/red]")
            raise typer.Exit(1)
        out.print("[green]proven[/green]")

    @proof.command("checks-hash")
    def checks_hash(dir_: Path = typer.Option(..., "--dir", help="e.g. .knos/acceptance/<issue>")) -> None:
        """Print the sha256 of an acceptance bundle (sorted "path\\0sha256(content)\\n" lines), as fixed on chain."""
        from ..jobs import prove
        try:
            out.print(prove.checks_hash(dir_), markup=False)
        except ValueError as why:
            raise Stop(str(why)) from None

    @proof.command("aud")
    def aud(job: str = typer.Option(..., "--job"), head: str = typer.Option(..., "--head"),
            checks: str = typer.Option(..., "--checks"), payout: str = typer.Option(..., "--payout")) -> None:
        """Print the OIDC audience knos:<job>:<head>:<checks>:<payout>, refusing a malformed part."""
        from ..jobs import prove
        try:
            out.print(prove.build_aud(job, head, checks, payout), markup=False)
        except ValueError as why:
            raise Stop(f"Bad audience: {why}") from None

    @proof.command("judge")
    def judge(base: Path = typer.Option(..., "--base", help="the base branch checkout"),
              pr: Path = typer.Option(..., "--pr", help="the pull request head source"),
              issue: str = typer.Option(..., "--issue", help="the acceptance bundle: .knos/acceptance/<issue>/"),
              changed: Path = typer.Option(None, "--changed", help="file listing the PR's changed paths"),
              evidence: Path = typer.Option(None, "--evidence", help="write the evidence JSON here"),
              diff: Path = typer.Option(None, "--diff", help="the PR's unified diff from the base (for repo rules)"),
              store: Path = typer.Option(None, "--store", help="a directory the judge remembers tampering in (Sibyl's local store: <dir>/sibyl.db)"),
              repo_name: str = typer.Option("", "--repo", help="owner/name, the key tamper rules are kept under"),
              agent: str = typer.Option("", "--agent", help="the PR author, the other tamper key")) -> None:
        """prove.yml's check job: the repo's CONTRIBUTING rules first, then overlay, protected paths, sentinel,
        fail-to-pass. A violation is learned: that check is required on every later PR to this repo or by this agent.
        Exit 1 unless it passes."""
        from ..jobs import prove
        from . import engine, history
        cfg = dict(engine.config(base))
        cfg["issue"] = issue
        names = None
        if changed:
            names = [x.strip() for x in changed.read_text(encoding="utf-8").splitlines() if x.strip()]
        st = history.SibylStore.local(store) if store else history.NullStore()
        diff_text = diff.read_text(encoding="utf-8", errors="replace") if diff else None
        v = prove.judge_with_rules(base, pr, cfg, names, diff_text, st, repo_name or None, agent or None)
        if evidence:
            evidence.write_text(json.dumps(v, indent=1), encoding="utf-8")
        for r in v["evidence"].get("required_by_history", []):
            out.print(f"REQUIRED by this repo's history: {r}", markup=False, emoji=False)
        for r in v["reasons"]:
            out.print(f"NO  {r}", markup=False, emoji=False)
        out.print(f"checks_hash {v['checks_hash']}", markup=False)
        if not v["passed"]:
            out.print("[red]not proven[/red]")
            raise typer.Exit(1)
        out.print("[green]proven[/green]")

    @proof.command("observe")
    def observe(sha: str = typer.Argument(...), check: str = typer.Argument(..., help="e.g. ci"),
                failed: bool = typer.Option(False, "--failed"), detail: str = typer.Option("", "--detail")) -> None:
        """Record later evidence about a commit (e.g. its CI failed after it was called done)."""
        from . import history
        repo = repo_of(None)
        history.observe(_store(repo), sha, check, not failed, detail)
        out.print(f"Recorded: {check} {'failed' if failed else 'passed'} at {sha[:8]}.")

    @proof.command("lint")
    def lint() -> None:
        """Claims this repo's evidence contradicts."""
        from . import history
        got = history.lint(_store(repo_of(None)))
        if not got:
            out.print("No claim here is contradicted by its evidence.")
        for x in got:
            out.print(f"  {x.sha[:8]}: claimed {', '.join(x.claimed) or 'done'}, but {x.failed} failed", markup=False)

    @proof.command("learn")
    def learn() -> None:
        """Turn every past false "done" into a check this repo now requires."""
        from . import history
        rules = history.learn(_store(repo_of(None)))
        for r in rules:
            out.print(f"  a {r['when']} claim now requires {r['require']}  ({r.get('because', '')})", markup=False)
        if not rules:
            out.print("No false done in this repo's history yet.")

    @proof.command("receipt")
    def receipt(claim: str = typer.Argument(...), publish: bool = typer.Option(False, "--publish",
                                                                                 help="attest it on Solana devnet")) -> None:
        """Prove the claim, then print the Merkle root of the evidence (and, with --publish, a devnet receipt)."""
        from . import checks, engine
        from . import receipt as rc
        repo = repo_of(None)
        v = engine.evaluate(repo, claim, _store(repo))
        if not v.ok or not v.results:
            out.print(v.explain(), markup=False)
            raise Stop("Not proven: no receipt for a claim Knos cannot prove.")
        ev = rc.evidence(v.results)
        root = rc.merkle_root(rc.leaves(ev))
        out.print(f"evidence root {root.hex()}")
        (repo / ".knos").mkdir(exist_ok=True)
        (repo / ".knos" / f"receipt-{root.hex()[:16]}.json").write_text(json.dumps(
            {"claim": claim, "commit": checks.head(repo), "evidence": ev, "root": root.hex()}, indent=1), "utf-8")
        if publish:
            from ..jobs import net
            from ..team import rpc
            sig, att = rc.publish(rpc.CLUSTERS["devnet"], net.key(), root, checks.head(repo), claim)
            out.print(f"receipt on devnet: {sig}\n  {rc.page_url(att)}", markup=False)
