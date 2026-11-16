"""`knos idea ...`: idea in, then wanted? (the demand check and devnet pull commitments), from a terminal.

    knos idea get pmid:33057194 --out idea.json     a claim from a research source, one Claim record (live read)
    knos idea search arxiv "perovskite stability"   claims in one source
    knos idea in "Statement ..." --by orcid:0000-...  an idea from a person, a player (--kind player) or an agent (--kind agent)
    knos idea who orcid:0000-0002-1825-0097         a researcher's public ORCID (or GitHub) record
    knos idea sources | fields                      every source, live or fixture now, and its key; the 26 fields
    knos idea wanted idea.json --units 10 --price 4 the demand check + the pull-commitment plan (nothing sent)
    knos idea check idea.json preprint_posted       is a stage's milestone met now? (evidence + its sha256)
    knos idea commit idea.json --units 10 --price 4 --wallet KEY --mint MINT     lock the stages on devnet (signs)
    knos idea preorder idea.json 5 --wallet KEY --mint MINT                      a pre-order in the idea's pool (signs)
    knos idea state idea.json --mint MINT           every stage and the pool as the chain has them
    knos idea sign|release|refund COMMIT STAGE ...  a referee's verdict; release or refund a stage
"""
from __future__ import annotations

import json
from pathlib import Path

GROUP = "idea"
OUT, UNITS, PRICE, STAGES, MINT, WALLET, JSON = "--out", "--units", "--price", "--stages", "--mint", "--wallet", "--json"


def _load(ref: str, f=None) -> dict:
    """A Claim record from a file (`knos idea get --out`), from a commitment file (its claim), or read from a source."""
    from . import check
    from .commit import is_commitment, load
    from .sources import get
    p = Path(ref)
    if ref.endswith(".json") and p.exists():
        if is_commitment(p):
            return load(p)["claim"]
        return check(json.loads(p.read_text(encoding="utf-8")))
    return get(ref, f)


def _stages(text: str | None):
    if not text:
        return None
    out = []
    for part in text.split(","):
        o, _, b = part.strip().partition(":")
        if not b.isdigit():
            raise ValueError("stages: oracle:bps,oracle:bps (basis points summing to 10000)")
        out.append((o, int(b)))
    return out


def _say(obj, as_json: bool, lines) -> None:
    from ..cli import out
    if as_json:
        out.print(json.dumps(obj, indent=1, default=str), markup=False, highlight=False, soft_wrap=True)
    else:
        for line in lines:
            out.print(line, markup=False, highlight=False, soft_wrap=True)


def _claim_lines(c: dict) -> list[str]:
    ids = ", ".join(f"{k}:{v}" for k, v in c["ids"].items())
    lines = [c["label"], f"{c['id']}  [{c['field']}]", f"  {c['statement']}", f"  ids: {ids or '(none)'}"]
    r = c["retraction"]
    lines.append("  retraction check: " + ("not checked (no DOI)" if not r.get("checked") else
                                           ("RETRACTED" if r["retracted"] else "no retraction") + f" ({r.get('via')})"))
    if c["risk"]:
        lines.append(f"  RISK: {', '.join(c['risk'])} (a cheat/risk signal the referee and buyers see)")
    lines.append(f"  hash: {c['hash']}")
    return lines


def _signer(path: Path):
    from solders.keypair import Keypair
    return Keypair.from_bytes(bytes(json.loads(path.expanduser().read_text(encoding="utf-8"))))


def register(app, help_lines: list | None = None) -> None:
    import typer
    from ..cli import Stop

    if help_lines is not None:
        help_lines.append(("idea", None, "Idea in from anyone or any research source (every field), then demand + pull commitments locked in stages."))
    g = typer.Typer(help="An idea from a person, a player, an AI agent or a research source (OpenAlex, arXiv, PubMed/Europe PMC, "
                         "bioRxiv/medRxiv, Crossref + retractions, ClinicalTrials.gov, patents) as one Claim record; then wanted? "
                         "(the demand check, then devnet orders: pull commitments in stages, pre-orders in a pool). docs/reference/IDEAS.md", no_args_is_help=True)
    app.add_typer(g, name=GROUP)

    def guard(fn):
        from . import IdeaError
        from .http import FetchError
        try:
            return fn()
        except (IdeaError, FetchError, ValueError) as e:
            raise Stop(str(e)) from None

    @g.command("get")
    def get_cmd(ref: str = typer.Argument(..., help="doi:..., pmid:..., pmcid:..., arxiv:..., biorxiv:..., medrxiv:..., openalex:W..., NCT..., uspto:..."),
                out_file: Path = typer.Option(None, OUT, help="write the Claim record here (what wanted/commit/state read)"),
                as_json: bool = typer.Option(False, JSON)) -> None:
        """One claim from a research source, read from its official API, with the Retraction Watch check."""
        from .sources import get
        c = guard(lambda: get(ref))
        if out_file:
            out_file.write_text(json.dumps(c, indent=1) + "\n", encoding="utf-8")
        _say(c, as_json, _claim_lines(c) + ([f"  written: {out_file}"] if out_file else []))

    @g.command("search")
    def search_cmd(source: str = typer.Argument(..., help="openalex, arxiv, pubmed, europepmc, biorxiv, medrxiv, crossref, clinicaltrials, uspto"),
                   words: str = typer.Argument(...), limit: int = typer.Option(5, "--limit", min=1, max=25),
                   as_json: bool = typer.Option(False, JSON)) -> None:
        """Claims matching words in one source."""
        from .sources import search
        got = guard(lambda: search(source, words, limit=limit))
        lines = []
        for c in got:
            lines += _claim_lines(c)[1:3] + [f"  ids: {', '.join(f'{k}:{v}' for k, v in c['ids'].items())}" + (f"  RISK {c['risk']}" if c["risk"] else "")]
        _say(got, as_json, ([got[0]["label"]] if got else ["nothing found"]) + lines)

    @g.command("in")
    def in_cmd(statement: str = typer.Argument(..., help="the claim, one sentence"),
               field_name: str = typer.Option(None, "--field", help="one of `knos idea fields` (else guessed from the words)"),
               by: str = typer.Option(None, "--by", help="orcid:0000-0000-0000-0000 or github:login (read from the public record)"),
               kind: str = typer.Option("person", "--kind", help="person, player or agent"),
               agent_name: str = typer.Option(None, "--agent", help="with --kind agent: the agent's name"),
               out_file: Path = typer.Option(None, OUT), as_json: bool = typer.Option(False, JSON)) -> None:
        """An idea stated by its author (--kind says who), not read from a source."""
        from . import person
        from .identity import short, who
        ident = short(who(by)) if by else ({"kind": "agent", "name": agent_name} if agent_name else None)
        c = guard(lambda: person(statement, field_name=field_name, by=ident, kind=kind))
        if out_file:
            out_file.write_text(json.dumps(c, indent=1) + "\n", encoding="utf-8")
        _say(c, as_json, _claim_lines(c) + [f"  by: {json.dumps(ident) if ident else '(anonymous)'}"])

    @g.command("who")
    def who_cmd(ref: str = typer.Argument(..., help="orcid:0000-0000-0000-0000 or github:login"), as_json: bool = typer.Option(False, JSON)) -> None:
        """A researcher's public ORCID (or GitHub) record. Reading it shows the iD exists, not that you own it."""
        from .identity import who
        got = guard(lambda: who(ref))
        _say(got, as_json, [f"{got.get('kind')}: {got.get('id')}  {got.get('name') or ''}", f"  {got.get('url') or ''}", f"  {got.get('verified')}"])

    @g.command("sources")
    def sources_cmd(as_json: bool = typer.Option(False, JSON)) -> None:
        """Every research source: live or fixture right now, the key that changes that, and its rules."""
        from .sources import status
        rows = status()
        _say(rows, as_json, [f"{r['source']:<15} {r['mode']:<8} key: {r['key'] or 'none'}" for r in rows])

    @g.command("fields")
    def fields_cmd() -> None:
        """The 26 fields of science an idea is filed under (OpenAlex topics; all of science)."""
        from . import FIELDS
        _say(None, False, FIELDS)

    @g.command("wanted")
    def wanted_cmd(ref: str = typer.Argument(..., help="a Claim record file (knos idea get --out) or a source reference"),
                   units: int = typer.Option(10, UNITS, min=1, help="N: how many the buyer commits to buy if verified"),
                   price: int = typer.Option(4, PRICE, min=1, help="P: whole test units per unit"),
                   stages: str = typer.Option(None, STAGES, help="oracle:bps,... (default by kind of claim)"),
                   product: str = typer.Option(None, "--product", help="the product the idea would become, for the demand check"),
                   place: str = typer.Option(None, "--in", help="a place, for the demand check's where/fit"),
                   as_json: bool = typer.Option(False, JSON)) -> None:
        """Demand evidence (Qloo demand check: MOCK until QLOO_API_KEY) and the pull-commitment plan. Sends nothing."""
        from . import wanted as W
        c = guard(lambda: _load(ref))
        d = W.demand(c, product, place)
        p = guard(lambda: W.plan(c, units=units, price=price, stages=_stages(stages), demand_hash=d.get("hash")))
        got = {"claim": c["id"], "demand": d, "plan": p}
        lines = _claim_lines(c)[:3] + [f"demand check: {d.get('status')} {d.get('mode', '')} lean={((d.get('lean') or {}).get('word'))}",
                                       f"  {d.get('label', d.get('why', ''))}", f"pull commitment: {units} x {price} = {p['commitment']['total'] / 1e6:g} test units, buyer pays {p['buyer_pays'] / 1e6:g} with fees"]
        for s in p["stages"]:
            lines.append(f"  {s}: {p[s]['oracle']:<18} {p[s]['amount'] / 1e6:g} units, deadline {p[s]['work_s'] // 86400} days")
        _say(got, as_json, lines)

    @g.command("check")
    def check_cmd(ref: str = typer.Argument(..., help="an idea file, a commitment file, or a source reference"),
                  oracle: str = typer.Argument(..., help="preprint_posted, journal_published, trial_registered, results_posted, not_retracted, referee_pass, lab_qc"),
                  verdict: Path = typer.Option(None, "--verdict", help="referee_pass / lab_qc: the referees' signed verdicts (knos idea sign files, as a JSON list)"),
                  as_json: bool = typer.Option(False, JSON)) -> None:
        """Is one stage's milestone met right now? The evidence and its sha256 (what the referees sign over). A
        referee_pass / lab_qc verdict counts only when m referees of the commitment's panel signed it."""
        from . import wanted as W
        from .commit import is_commitment, load
        c = guard(lambda: _load(ref))
        panel = None
        if ref.endswith(".json") and is_commitment(ref):
            doc = load(ref)
            panel = (doc["panel"]["m"], doc["panel"]["keys"]) if doc.get("panel") else None
        ev = guard(lambda: W.check(c, oracle, verdict=str(verdict) if verdict else None, panel=panel))
        word = "MET" if ev["met"] else "not met" if ev["met"] is False else "pending"
        if ev.get("accepted") is False:
            word = "NOT ACCEPTED"
        _say(ev, as_json, [f"{oracle}: {word}  ({ev['why']})", f"  evidence sha256 {ev['evidence_hash']}"])

    def _devnet():
        from .. import chain
        led = chain.ledger()
        if not any(x in led.url for x in ("devnet", "127.0.0.1", "localhost")):
            raise Stop("devnet only: set KNOS_RPC_URL to a devnet or local validator")
        return led

    def _commit_path(ref: str, out: Path | None) -> Path:
        return out or Path((ref[:-5] if ref.endswith(".json") else "idea") + ".commit.json")

    @g.command("commit")
    def commit_cmd(ref: str = typer.Argument(..., help="the idea file (knos idea get --out)"), units: int = typer.Option(..., UNITS, min=1),
                   price: int = typer.Option(..., PRICE, min=1), stages: str = typer.Option(None, STAGES),
                   payee: str = typer.Option(..., "--payee", help="who is paid when a stage is released: github:<id>@<wallet>, orcid:<iD>@<wallet> or a wallet address (required; nothing is assumed)"),
                   panel: str = typer.Option(None, "--panel", help="M:key1,key2,key3: the referee panel that releases each stage (M of the keys; never the funder's)"),
                   program: str = typer.Option(None, "--program", help="with --panel: the knos_pay build with the panel path (on devnet, the panel test build's id)"),
                   wallet: Path = typer.Option(..., WALLET, help="the buyer's devnet keypair file (signs)"),
                   mint: str = typer.Option(..., MINT, help="the 6-decimal test mint the stages are paid in"),
                   stage_seconds: str = typer.Option(None, "--stage-seconds", help="one deadline per stage in seconds, comma separated (min 60)"),
                   demand_hash: str = typer.Option(None, "--demand", help="the demand report's sha256 the commitment names (knos idea wanted)"),
                   allow_retracted: bool = typer.Option(False, "--allow-retracted", help="lock even though the paper is retracted"),
                   unlisted_panel: bool = typer.Option(False, "--unlisted-panel", help="allow referee keys off Knos's registry (config/referees.yaml); labelled UNLISTED PANEL"),
                   out: Path = typer.Option(None, OUT, help="the commitment file (default <idea>.commit.json): what sign, release, refund and state read"),
                   as_json: bool = typer.Option(False, JSON)) -> None:
        """Lock a pull commitment on devnet: one order per stage, the payee and the judge fixed now. With --panel, M
        referees' signed verdicts release a met stage (knos idea release) or refund a missed one (knos idea refund)."""
        from solders.pubkey import Pubkey

        from ..settle.v2 import pay
        from . import commit as C
        c = guard(lambda: _load(ref))
        kp = _signer(wallet)
        who = guard(lambda: C.parse_payee(payee))
        pnl = guard(lambda: C.parse_panel(panel, kp.pubkey(), who.get("wallet"), unlisted_panel)[:2]) if panel else None
        if pnl is not None and not program:
            raise Stop("--panel needs --program: the knos_pay build with the referee-panel path (the public program does not have it yet)")
        work = [int(x) for x in stage_seconds.split(",")] if stage_seconds else None
        led, m = _devnet(), Pubkey.from_string(mint)
        prog = Pubkey.from_string(program) if program else pay.PAY_ID
        doc = guard(lambda: C.commit(c, units=units, price=price, payee=who, funder=kp, funder_token=pay.ata(kp.pubkey(), m), mint=m, led=led,
                                     stages=_stages(stages), stage_work_s=work, panel=pnl, program=prog, demand_hash=demand_hash,
                                     allow_retracted=allow_retracted, unlisted_panel=unlisted_panel))
        path = _commit_path(ref, out)
        path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
        lines = [f"{s}: {r['oracle']:<18} {r['amount'] / 1e6:g} locked  {r['signature'] or r['note']}  order {r['order']}" for s, r in doc["orders"].items()]
        judge = f"judge: {doc['judge']}" + (f" {doc['panel']['m']} of {len(doc['panel']['keys'])} {doc['panel']['label']}" if doc["panel"] else "")
        _say(doc, as_json, lines + [f"payee: {payee}", judge, f"commitment file: {path}"] + [f"WARNING: {w}" for w in doc["warnings"]])

    @g.command("sign")
    def sign_cmd(commitment: Path = typer.Argument(..., help="the commitment file"), stage: str = typer.Argument(..., help="stage1, stage2, ..."),
                 referee: Path = typer.Option(..., "--referee", help="YOUR referee keypair file (run this where your key is)"),
                 passed: bool = typer.Option(None, "--pass/--fail", help="referee_pass / lab_qc: your result"),
                 review: Path = typer.Option(None, "--review", help="referee_pass / lab_qc: the report you judged"),
                 out: Path = typer.Option(None, OUT, help="where to write your signed verdict (default <stage>-<key>.verdict.json)"),
                 as_json: bool = typer.Option(False, JSON)) -> None:
        """A referee's signed verdict on one stage: reads the stage's oracle (or takes your review result) and signs
        "stage met" for the committed payee, or "stage missed". Pending: nothing is signed. Sends nothing."""
        from . import commit as C
        doc = guard(lambda: C.load(commitment))
        rec = guard(lambda: C.sign(doc, stage, _signer(referee), _devnet(), passed=passed, review=review))
        path = out or Path(f"{stage}-{rec['key'][:8]}.verdict.json")
        path.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        _say(rec, as_json, [f"{stage} ({rec['oracle']}): you signed {rec['verdict']}  evidence {rec['evidence_hash'][:16]}...  -> {path}"])

    def _recs(sigs: list[Path]) -> list:
        out: list = []
        for s in sigs:
            raw = json.loads(s.read_text(encoding="utf-8"))
            out += raw if isinstance(raw, list) else [raw]
        return out

    @g.command("release")
    def release_cmd(commitment: Path = typer.Argument(...), stage: str = typer.Argument(...),
                    sig: list[Path] = typer.Option(..., "--sig", help="a referee's signed verdict file (knos idea sign); give M of them"),
                    wallet: Path = typer.Option(..., WALLET, help="the relayer's devnet keypair (pays the fees; anyone may relay)"),
                    as_json: bool = typer.Option(False, JSON)) -> None:
        """Release a met stage: checks M signed PASS verdicts against the commitment (panel, payee, order) and sends
        them one per transaction; the program pays the committed payee at the M-th."""
        from . import commit as C
        doc = guard(lambda: C.load(commitment))
        got = guard(lambda: C.release(doc, stage, _recs(sig), _signer(wallet), _devnet()))
        _say(got, as_json, [f"{stage}: {got['status'].upper()}"] + [f"  referee {r['referee']}: {r['signature']}" for r in got["sent"]])

    @g.command("refund")
    def refund_cmd(commitment: Path = typer.Argument(...), stage: str = typer.Argument(...),
                   sig: list[Path] = typer.Option(None, "--sig", help="M referees' signed FAIL verdicts (refund now); none: refund after the deadline"),
                   wallet: Path = typer.Option(..., WALLET, help="the relayer's devnet keypair (anyone may refund)"),
                   as_json: bool = typer.Option(False, JSON)) -> None:
        """Refund a missed stage to the buyer: now on M signed FAIL verdicts, or after its deadline with none."""
        from . import commit as C
        doc = guard(lambda: C.load(commitment))
        got = guard(lambda: C.refund(doc, stage, _recs(sig or []), _signer(wallet), _devnet()))
        _say(got, as_json, [f"{stage}: {got['status'].upper()}"] + [f"  {r['signature']}" for r in got["sent"]])

    @g.command("preorder")
    def preorder_cmd(ref: str = typer.Argument(...), amount: int = typer.Argument(..., min=5, help="whole test units"),
                     wallet: Path = typer.Option(..., WALLET), mint: str = typer.Option(..., MINT),
                     as_json: bool = typer.Option(False, JSON)) -> None:
        """A pre-order in the idea's pool (paid to the makers on delivery, refunded after its deadline)."""
        from solders.pubkey import Pubkey

        from ..settle.v2 import pay
        from . import wanted as W
        c = guard(lambda: _load(ref))
        p = guard(lambda: W.plan(c, units=10, price=4))
        led, kp, m = _devnet(), _signer(wallet), Pubkey.from_string(mint)
        seq = next(s for s in range(64) if led.account(W.address(p, "pool", kp.pubkey(), s)) is None)
        sig = led.send([W.fund_ix(p, "pool", kp.pubkey(), pay.ata(kp.pubkey(), m), m, amount * 10 ** 6, seq=seq)], kp)
        _say({"signature": sig, "order": str(W.address(p, "pool", kp.pubkey(), seq))}, as_json, [f"pre-order: {sig}"])

    @g.command("state")
    def state_cmd(ref: str = typer.Argument(..., help="the commitment file (knos idea commit wrote it); or an idea file with the plan's flags"),
                  mint: str = typer.Option(None, MINT), units: int = typer.Option(10, UNITS),
                  price: int = typer.Option(4, PRICE), stages: str = typer.Option(None, STAGES),
                  stage_seconds: str = typer.Option(None, "--stage-seconds"), demand_hash: str = typer.Option(None, "--demand"),
                  as_json: bool = typer.Option(False, JSON)) -> None:
        """What the chain holds for each stage. Given the commitment file, nothing is repeated: it names the orders."""
        from . import commit as C
        from . import wanted as W
        if ref.endswith(".json") and C.is_commitment(ref):
            doc = guard(lambda: C.load(ref))
            s = C.state(doc, _devnet())
            _say(s, as_json, [f"{k}: {v['oracle']:<18} locked {v['locked'] / 1e6:g}  {v['state']}  order {v['order']}" for k, v in s["stages"].items()]
                 + [f"total locked {s['locked_total'] / 1e6:g}"])
            return
        if not mint:
            raise Stop("give the commitment file (knos idea commit wrote it), or --mint with the plan's flags")
        c = guard(lambda: _load(ref))
        work = [int(x) for x in stage_seconds.split(",")] if stage_seconds else None
        p = guard(lambda: W.plan(c, units=units, price=price, stages=_stages(stages), stage_work_s=work, demand_hash=demand_hash))
        st = W.state(_devnet(), p, mint)
        _say(st, as_json, [f"{k}: {v['oracle']:<28} locked {v['locked'] / 1e6:g}  orders {len(v['orders'])}" for k, v in st["parts"].items()])
