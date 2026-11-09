"""ONE flow a team runs end to end: post a task -> a coding agent writes, runs and tests code on Nemotron (Nebius
Token Factory) -> the Knos referee judges that code on sealed tests -> paid, final, metered and invoiced.

    python -m knos.nebius flow --out DIR [--wallets DIR] [--team NAME] [--rounds N]

  1 post       the task (examples/nebius/task: TASK.md, the repository, the hidden acceptance tests) is SEALED by the
               referee (spec hash + judge hash, published before work starts). With --wallets the team funds the
               bounty into knos_pay vault on Solana devnet; the terms carry the seal hash.
  2 code       knos.nebius.agent: Nemotron 3 Super writes duration.py and its tests, the agent runs pytest, feeds the
               failures back, until its own tests pass (real runs; the model replies are MOCK without NEBIUS_API_KEY)
  3 check fee  with --wallets the agent pays one raw check (0.02, the decided x402 price) over x402 v2 exact through
               the public x402.org facilitator, to Knos's treasury, on devnet
  4 provenance Tavily searches the agent's most distinctive lines (live with TAVILY_API_KEY; advisory)
  5 referee    knos.referee.works: sealed bundle hash, locked judge hash, cheat library, hidden tests, re-run; a
               refusal is explained by Nemotron 3 Ultra (advisory: the verdict is copied, never changed)
  6 paid       on a pass: the job is paid to the agent's wallet. LABELLED LiteSVM: knos_pay pays only on a GitHub
               Actions OIDC token from a pinned prove.yml run, which a locally judged task cannot have
  7 metered    every step is a usage event (knos.money.teams); the invoice is checked against devnet; the dashboard
               shows verifications, cheats caught, failing merges blocked and "paid and final in N ms"

A scripted cheater (SYNTHETIC, labelled) delivers the same sealed task too, so the dashboard shows what the referee
blocks: its own tests pass, the referee refuses it (a failing merge blocked). --no-cheater leaves it out.

Writes DIR/flow.json, DIR/flow.html, DIR/usage.jsonl, DIR/base, DIR/pr. Every number in them is measured in this run
or comes from config/fees.yaml; every MOCK and every LiteSVM line says so.
"""
from __future__ import annotations

import hashlib
import html
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import referee
from ..money import fees_config, teams
from . import agent as coding_agent
from . import explain, mock, sources, tavily
from .tokenfactory import TokenFactory

TASK = "parse_duration"
SCOPE = ("duration.py", "tests/*")
CHEATER_NAME = "scripted-cheater (synthetic)"
CHEATER = {"duration.py": ('"""Durations."""\nKNOWN = {"1h30m": 5400, "45s": 45, "2d": 172800}\n\n\n'
                           'def parse_duration(text: str) -> int:\n    return KNOWN.get(text.strip(), 0)\n'),
           "tests/test_duration.py": ('from duration import parse_duration\n\n\ndef test_examples():\n'
                                      '    assert parse_duration("1h30m") == 5400\n    assert parse_duration("45s") == 45\n'),
           "tests/test_smoke.py": 'import duration\n\n\ndef test_module_has_the_function():\n    pass\n'}   # the existing check, emptied
KNOS_E2E_ID = 1401439243          # drexthealpha/knos-e2e: the repository id the bounty is posted against
WF_REPO = "drexthealpha/Knos"


def task_dir(root: Path) -> Path:
    return Path(root) / "examples" / "nebius" / "task"


def _head(root: Path) -> str:
    try:
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ""
    return sha if len(sha) == 40 else "0" * 40


def tree_sha(files: dict[str, str]) -> str:
    """A 40-hex stand-in for the commit a pull request would name: sha1 over the agent's files (no git commit is made)."""
    h = hashlib.sha1()  # noqa: S324 - a commit-shaped id, not a security hash
    for p in sorted(files):
        h.update(p.encode() + b"\0" + files[p].encode() + b"\0")
    return h.hexdigest()


def run_flow(root: Path, out: Path, *, wallets: Path | None = None, team: str = "knos-internal-dogfooding",
             agent_name: str = "nemotron-3-super-agent", rounds: int = 4, bounty_units: int = 5_000_000,
             cheater: bool = True, usage: Path | None = None, tf: TokenFactory | None = None, tv: tavily.Tavily | None = None,
             say=print) -> dict:
    root, out = Path(root), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tf = tf or TokenFactory(responder=mock.responder())
    tv = tv or tavily.Tavily(responder=mock.tavily_responder)
    cfg = fees_config.load()
    usage_file = Path(usage) if usage else out / "usage.jsonl"     # a team's record across runs, or this run's alone
    if usage is None:
        usage_file.unlink(missing_ok=True)
    label = "internal dogfooding" if "dogfooding" in team else ""
    ev = lambda kind, **kw: teams.record(teams.event(kind, team, agent_name, task=TASK, **({"label": label} if label else {}), **kw), usage_file)  # noqa: E731
    steps: list[dict] = []
    say(f"Token Factory: {tf.mode}; Tavily: {tv.mode}")
    if "mock" in (tf.mode, tv.mode):
        say(sources.MOCK + ": model and search replies are made locally; the test runs, the referee and the chain are real")

    # 1. post: seal, then fund
    td = task_dir(root)
    for name in ("base", "pr", "sealed"):
        shutil.rmtree(out / name, ignore_errors=True)
    shutil.copytree(td / "base", out / "base")
    shutil.copytree(td / "base", out / "pr")
    shutil.copytree(td / "hidden", out / "sealed")
    issue = int(time.time()) % 1_000_000_000
    seal = referee.seal(out / "sealed", issue=str(issue), scope=SCOPE, test_dirs=["tests"], reruns=1)
    seal_h = referee.seal_hash(seal)
    (out / "seal.json").write_text(json.dumps(seal, indent=1) + "\n", encoding="utf-8")
    from ..settle.v2 import pay
    terms = pay.terms_json({"knos": "task", "task": TASK, "seal": seal_h, "spec": seal["spec_hash"], "judge": seal["judge_hash"][:32],
                            "scope": list(SCOPE), "pays": "on the Knos referee's verdict"})
    post = {"step": "post", "task": TASK, "issue": issue, "seal_hash": seal_h, "spec_hash": seal["spec_hash"], "judge_hash": seal["judge_hash"],
            "terms_bytes": len(terms)}
    dn = None
    if wallets:
        from .onchain import Devnet, alpenglow
        dn = Devnet.load(wallets)
        post["cluster"] = alpenglow(dn.url)
        try:
            f = dn.fund_escrow(repo_id=KNOS_E2E_ID, issue=issue, amount=bounty_units, wf_repo=WF_REPO, wf_sha=_head(root), terms=terms)
            post["escrow"] = f
            ev("escrow_funded", sig=f["sig"], network="devnet", amount_units=bounty_units, decimals=6, mint=f["mint"], final_ms=f["finalized_ms"],
               job=f["job"])
            say(f"posted: bounty {bounty_units / 1e6:.2f} test units held until the proof passes, job {f['job']}, final in {f['finalized_ms']} ms, tx {f['sig']}")
        except Exception as why:  # noqa: BLE001 - the flow goes on and says the funding failed
            post["escrow"] = {"funded": False, "error": str(why)[:300]}
            say(f"posted: funding the held money FAILED: {str(why)[:200]}")
    else:
        post["escrow"] = {"funded": False, "why": "no --wallets: no money held on devnet in this run"}
        say(f"posted: task {TASK} sealed ({seal_h[:16]}); no money held on devnet (no --wallets)")
    steps.append(post)

    # 2. the agent writes, runs and tests code on Nemotron
    task_text = (td / "TASK.md").read_text(encoding="utf-8")
    run = coding_agent.run(tf, task_text, out / "pr", scope=SCOPE, rounds=rounds, say=say)
    steps.append({"step": "code", **run.to_dict()})

    # 3. the agent pays for one raw check over x402
    check = {"step": "check_fee", "paid": False, "why": "no --wallets"}
    if dn is not None:
        price = fees_config.micro(cfg.doc["fees"]["x402_check"]["usd_each"])
        try:
            check = {"step": "check_fee", **dn.pay_check(price, memo=f"knos check {TASK} {issue}")}
        except Exception as why:  # noqa: BLE001
            check = {"step": "check_fee", "paid": False, "why": str(why)[:300]}
        if check.get("paid"):
            ev("x402_check", sig=check["sig"], network="devnet", amount_units=price, decimals=6, mint=check["mint"], final_ms=check.get("finalized_ms"))
            say(f"check paid over x402: 0.02 test units, final in {check.get('finalized_ms')} ms, tx {check['sig']}")
        else:
            say(f"check over x402 NOT paid: {check.get('why')}")
    steps.append(check)

    # 4. provenance of the agent's code (advisory)
    code = run.files.get("duration.py", "")
    prov = tavily.provenance(tv, code) if code else {"checked_lines": 0, "matches": [], "finding": "no code", "advisory": True, "mock": not tv.live}
    steps.append({"step": "provenance", **prov, "searches": [s.to_dict() for s in tv.calls]})
    say(f"provenance: {prov['finding']} ({prov['checked_lines']} lines searched, Tavily {tv.mode})")

    # 5. the referee
    t0 = time.perf_counter()
    c = referee.works(out / "base", out / "pr", seal, hidden_dir=out / "sealed", reruns=1)
    verdict = {"step": "referee", "passed": c.passed, "reasons": c.reasons, "cheats": [f.rule for f in c.cheats],
               "seconds": round(time.perf_counter() - t0, 2), "changed": c.evidence.get("changed"),
               "reruns_agree": all(r.get("agree") for r in c.evidence.get("reruns", [])) if c.evidence.get("reruns") else None}
    if not c.passed:
        verdict["explanation"] = explain.explain(tf, verdict="refused", findings=[f.to_dict() for f in c.cheats] or
                                                 [{"rule": "hidden_tests", "category": "", "detail": r} for r in c.reasons], subject=code)
    steps.append(verdict)
    ev("verification", passed=c.passed, cheats=verdict["cheats"], agent_tests_passed=run.finished)
    say(f"referee: {'ACCEPTED' if c.passed else 'REFUSED'} in {verdict['seconds']} s" + ("" if c.passed else f": {c.reasons[:2]}"))

    # 5b. the same sealed task, delivered by a scripted cheater (SYNTHETIC, not a model): it hard-codes the task's
    #     examples and tests only those, so its own tests pass. The referee's decision on it is real.
    if cheater:
        shutil.rmtree(out / "pr_cheater", ignore_errors=True)
        shutil.copytree(out / "base", out / "pr_cheater")
        for path, text in CHEATER.items():
            (out / "pr_cheater" / path).write_text(text, encoding="utf-8")
        own = coding_agent.run_tests(out / "pr_cheater", 1)
        cc = referee.works(out / "base", out / "pr_cheater", seal, hidden_dir=out / "sealed", reruns=1)
        steps.append({"step": "referee_cheater", "agent": CHEATER_NAME, "synthetic": True, "own_tests_passed": own.passed,
                      "passed": cc.passed, "reasons": cc.reasons, "cheats": [f.rule for f in cc.cheats],
                      "explanation": None if cc.passed else explain.explain(tf, verdict="refused", findings=[f.to_dict() for f in cc.cheats]
                                                                            or [{"rule": "hidden_tests", "category": "", "detail": r} for r in cc.reasons],
                                                                            subject=CHEATER["duration.py"])})
        teams.record(teams.event("verification", team, CHEATER_NAME, task=TASK, passed=cc.passed, cheats=[f.rule for f in cc.cheats],
                                 agent_tests_passed=own.passed, synthetic=True, **({"label": label} if label else {})), usage_file)
        say(f"referee on the scripted cheater (synthetic): {'ACCEPTED' if cc.passed else 'REFUSED'}; its own tests "
            f"{'pass' if own.passed else 'fail'}" + ("" if cc.passed else f"; {cc.reasons[:1]}"))

    # 6. paid
    paid: dict[str, Any] = {"step": "paid", "paid": False, "why": "the referee refused: the held money stays, and returns to the team at its deadline"}
    if c.passed:
        from solders.keypair import Keypair

        from . import payout
        payee = dn.agent.pubkey() if dn is not None else Keypair().pubkey()
        paid = {"step": "paid", **payout.pay_job(root, repo_id=KNOS_E2E_ID, issue=issue, amount=bounty_units, wf_repo=WF_REPO,
                                                 wf_sha=_head(root), terms=terms, head_sha=tree_sha(run.files), payee_wallet=payee,
                                                 payee_id=1, funder=dn.team if dn is not None else None)}
        if paid.get("paid"):
            ev("payout", sig=paid["litesvm_pay_tx"], network="litesvm", amount_units=bounty_units, to_payee_units=paid["to_payee_units"],
               fee_units=paid["fee_units"], decimals=6, mint=paid["mint"])
            say(f"paid ({paid['label']}): {paid['to_payee_units'] / 1e6:.2f} to the agent, fee {paid['fee_units'] / 1e6:.2f}, tx {paid['litesvm_pay_tx']}")
        else:
            say(f"payout not made: {paid.get('error')}")
    steps.append(paid)

    # 7. metered and invoiced
    events = teams.load(usage_file)
    check_fn = teams.rpc_check(dn.url) if dn is not None else None
    dash = teams.dashboard(events, team, check=check_fn, cfg=cfg)
    steps.append({"step": "metered", "invoice_due_usd": dash["invoice"]["due_usd"], "paid_and_final": dash["paid_and_final"]})
    say(f"invoice for {team}: {dash['invoice']['due_usd']} USD due (test money); paid and final: {dash['paid_and_final']}")

    data = {"generated": teams.now_iso(), "team": team, "agent": agent_name,
            "modes": {"token_factory": tf.mode, "tavily": tv.mode, "chain": "devnet" if dn is not None else "none",
                      "payout": "LiteSVM (testkeys build), not devnet"},
            "steps": steps, "dashboard": dash, "calls": [r.to_dict() for r in tf.calls],
            "tokens": {"prompt": sum(r.prompt_tokens for r in tf.calls), "completion": sum(r.completion_tokens for r in tf.calls),
                       "cost_usd": round(sum(r.cost_usd for r in tf.calls), 6), "mock": tf.mode == "mock"},
            "labels": [sources.MOCK + " where mock is true", "payout: LiteSVM (testkeys build), not devnet", "devnet: test money, revenue 0"]}
    (out / "flow.json").write_text(json.dumps(data, indent=1, default=str) + "\n", encoding="utf-8")
    (out / "flow.html").write_text(page(data), encoding="utf-8")
    return data


def page(d: dict) -> str:
    """A static page of one run (no script): what each step did, with its evidence and its labels."""
    e = html.escape
    rows = []
    for s in d["steps"]:
        name = s.get("step", "")
        if name == "post":
            esc = s.get("escrow") or {}
            what = f"sealed {e(s['seal_hash'][:16])}; " + (f"held in job {e(esc.get('job', ''))}, final in {esc.get('finalized_ms')} ms, tx <code>{e(esc.get('sig', ''))}</code>"
                                                            if esc.get("sig") else e(esc.get("why") or esc.get("error") or "no held money"))
        elif name == "code":
            what = f"{s['rounds']} round(s); its tests: " + ", ".join("pass" if t["passed"] else "fail" for t in s["tests"]) + (" (MOCK model replies)" if s["mode"] == "mock" else "")
        elif name == "check_fee":
            what = f"0.02 over x402, final in {s.get('finalized_ms')} ms, tx <code>{e(str(s.get('sig')))}</code>" if s.get("paid") else e(str(s.get("why")))
        elif name == "provenance":
            what = e(s["finding"]) + (" (MOCK search)" if s.get("mock") else "")
        elif name == "referee":
            what = ("ACCEPTED" if s["passed"] else "REFUSED: " + e("; ".join(s["reasons"][:3]))) + f" ({s['seconds']} s)"
        elif name == "referee_cheater":
            what = ("ACCEPTED" if s["passed"] else "REFUSED: " + e("; ".join(s["reasons"][:2]))) + f" (synthetic cheater; its own tests {'pass' if s['own_tests_passed'] else 'fail'})"
        elif name == "paid":
            what = (f"{s['to_payee_units'] / 1e6:.2f} to the agent, tx <code>{e(str(s.get('litesvm_pay_tx')))}</code> [{e(s['label'])}]" if s.get("paid")
                    else e(str(s.get("why") or s.get("error"))))
        else:
            what = f"invoice due {e(s['invoice_due_usd'])} USD (test money); paid and final p50 {s['paid_and_final'].get('p50_ms')} ms"
        rows.append(f"<tr><th>{e(name)}</th><td>{what}</td></tr>")
    t = d["dashboard"]["totals"]
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Knos flow run</title>"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"></head><body>"
            f"<h1>Knos: one task, end to end</h1><p>Token Factory: {e(d['modes']['token_factory'])}; Tavily: "
            f"{e(d['modes']['tavily'])}; chain: {e(d['modes']['chain'])}; payout: {e(d['modes']['payout'])}.</p>"
            f"<table>{''.join(rows)}</table><h2>Team dashboard</h2><p>verifications {t['verifications']}, verified {t['verified']}, "
            f"refused {t['refused']}, cheats caught {t['cheats_caught']}, failing merges blocked {t['failing_merges_blocked']}</p>"
            f"<p>{' | '.join(e(x) for x in d['labels'])}</p></body></html>\n")
