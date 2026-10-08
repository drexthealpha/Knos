"""web/demo_data.json: the round the first screen replays (web/demo.js), read out of what this repository records.

    python scripts/demo_data.py            write web/demo_data.json
    python scripts/demo_data.py --check    exit 1 when the file is not what this would write

Nothing here is typed in by hand: every signature, address, amount and count is cut out of a document of this
repository by a pattern, and a pattern that finds nothing stops the script. What the documents do not record is left
out (the rehearsal's order is recorded with its address, not with its terms hash, so the demo shows the address; the
signed token of that order is not printed anywhere, so the demo names the three claims and shows no values).

`ids` says where the round ran: "public" when docs/capabilities.json holds a `public_round` (written by
scripts/exercise_public.py record from a run at the public program ids) whose funding and payment are the exercised
evidence of `work_orders` and `order_pay`; "staging" otherwise (the 0.3.14 rehearsal). The script prefers the first
and prints which it used; web/demo.js says it over the demo. A public round's fund, paid, replay and count are that
run's own transactions, each one linked.

The refusal shown is the single-use rule's own: the order's fund token sent a second time, refused with the error
programs-v2/knos_pay/src/lib.rs calls E_REPLAY ("a token works once"). Until 0.3.16 the demo showed the pay token's
second use, which the program refuses earlier and for another reason (83: the order is not in the state this needs).

Where each part comes from:
- fund, paid, replay, count: docs/CAPABILITIES.md, "The 0.3.14 rehearsal on devnet" (parts 1, 2 and 5): transactions
  on devnet at the staging addresses of the 0.3.14 build, in test USDC. The fund and pay transactions are the ones
  docs/capabilities.json names in the notes of `work_orders` and `order_pay`.
- claim: docs/TAMPER.md, the Python table: a pull request that fixes nothing, what CI said and the check Knos named.
  How often a first agent pull request that says its tests pass has a failed check: docs/facts.json and
  docs/bench.json (market.index.overall.first_pr_per_repo).
- fixed: docs/TAMPER.md, the control row (the honest fix), and the claim names of docs/OIDC.md.
- seconds: docs/bench.json, devnet.stats.latency.merge_to_paid (the median of the public relay's payments).

0.3.20, the seven beats (agree, fails, passes, same statement, replay, pay, verify):
- agree: the price is the funded amount; the days an unpaid order runs are `DAYS` of src/knos/commands.py; the remedy
  is the sentence docs/CAPABILITIES.md gives the public round ("what nobody proves goes back at the deadline").
- claim.reason: the judge's own words in docs/TAMPER.md for the refused pull request.
- bank_file: whether this tree has web/rails.js (the payment instruction file for a bank rail); the demo offers the
  file only then. verify: the recorded run of the stand-alone verifier, when docs/archive_verify.json holds one
  ({"says": one sentence, "link": a path of this repository}); left out while no such record exists.
The statement the two sides hash and the export the last beat checks are web/statement_sample.json, read and
computed in the reader's browser: nothing of them is copied here.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "demo_data.json"
VERIFIED = "docs/archive_verify.json"          # the stand-alone verifier's recorded run, when there is one
SOURCES = ("docs/CAPABILITIES.md", "docs/capabilities.json", "docs/TAMPER.md", "docs/bench.json", "docs/facts.json", "docs/OIDC.md",
           "programs-v2/knos_pay/src/lib.rs", "src/knos/commands.py") + ((VERIFIED,) if (ROOT / VERIFIED).is_file() else ())
SIG = r"[1-9A-HJ-NP-Za-km-z]{60,90}"
TX = rf"\[[^\]]+\]\(https://explorer\.solana\.com/tx/({SIG})\?cluster=devnet\)"
CLAIMS = (("repository_id", "repository"), ("sha", "commit"), ("job_workflow_ref", "workflow"))


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _find(pattern: str, text: str, what: str) -> re.Match[str]:
    m = re.search(pattern, text, re.S)
    if not m:
        raise SystemExit(f"docs no longer record {what}: the demo cannot show it")
    return m


def _number(text: str) -> int:
    return int(text.replace(",", ""))


def public_round(manifest: dict) -> dict | None:
    """The round scripts/exercise_public.py recorded at the public program ids, when its funding and its payment are
    the exercised evidence of `work_orders` and `order_pay`. None otherwise: the staging rehearsal is then shown."""
    got = manifest.get("public_round")
    by = {c["id"]: c for c in manifest["capabilities"]}
    sigs = [by.get(i, {}).get("evidence", {}).get("exercised", {}).get("signature") for i in ("work_orders", "order_pay")]
    return got if got and all(sigs) and sigs == [got["fund"]["tx"], got["paid"]["tx"]] else None


def ids_used(manifest: dict) -> tuple[str, str]:
    """Which program ids the round shown ran at, and why, in words."""
    if public_round(manifest):
        return "public", "the round is the one docs/capabilities.json records as exercised at the public program ids (`public_round`)"
    return "staging", ("docs/capabilities.json records no whole round at the public program ids (funding, payment, refusal and the two counts): "
                       "the staging rehearsal is shown")


def build() -> str:
    cap = _read("docs/CAPABILITIES.md")
    start = cap.index("## The 0.3.14 rehearsal on devnet")
    reh = cap[start:]
    manifest = json.loads(_read("docs/capabilities.json"))
    capabilities = manifest["capabilities"]
    notes = {c["id"]: c.get("note", "") for c in capabilities}
    bench = json.loads(_read("docs/bench.json"))
    facts = json.loads(_read("docs/facts.json"))["facts"]
    tamper, oidc = _read("docs/TAMPER.md"), _read("docs/OIDC.md")

    date = _find(r"On (\d+ \w+ \d{4}), before the release", reh, "the day of the rehearsal")[1]
    comment = _find(r"two `(/knos fund \d+)` comments", reh, "the funding comment")[1]
    fund = _find(rf"\| The first fund token is relayed \| {TX} \| order `([1-9A-HJ-NP-Za-km-z]{{32,44}})` funded with ([\d.,]+), its fee of ([\d.]+) on top",
                 reh, "the funded order")
    paid = _find(rf"\| The merged pull request's pay token is relayed \| {TX} \| ([\d.,]+) paid to the payee", reh, "the payment")
    once = _find(r"(\d+): (a token works\s+once)", reh, "the single-use error")
    lib = _read("programs-v2/knos_pay/src/lib.rs")
    if int(_find(r"pub const E_REPLAY: u32 = (\d+);", lib, "the single-use error of knos_pay")[1]) != int(once[1]):
        raise SystemExit("docs/CAPABILITIES.md and programs-v2/knos_pay/src/lib.rs disagree on the single-use error")
    # the order's own fund token, sent again: the first transaction of the FundOrderBalance row's "sent again" cell
    again = _find(rf"\| FundOrderBalance \| {TX}[^|]*\| {TX}[^|]*: (\d+) \|", reh, "the refused second use of the fund token")
    if again[1] != fund[1] or again[3] != once[1]:
        raise SystemExit("the rehearsal no longer records the fund token's second use as refused by the single-use rule")
    stages = {c["id"]: c["stage"] for c in capabilities}
    for cid, sig in (("work_orders", fund[1]), ("order_pay", paid[1])):     # a capability exercised since then no longer carries the rehearsal's note
        if stages[cid] != "exercised" and sig not in notes[cid]:
            raise SystemExit("docs/capabilities.json no longer names the rehearsal's fund and pay transactions")
    count = _find(rf"([\d,]+) evaluations were anchored in two batches of [\d,]+ \({TX}, {TX}\), and the\s+seller wrote its own count of the same month, "
                  rf"([\d,]+), in two claims \({TX}, {TX}\)", reh, "the two counts")
    apart = _find(r"found the two counts (\d+) evaluations apart", reh, "how far apart the counts were")[1]
    buyer, seller = _number(count[1]), _number(count[4])
    if seller - buyer != int(apart):
        raise SystemExit("the recorded counts and their difference disagree")

    row = _find(r"\| (\d+) \| (no-op PR \(README only\)) \| (\w+) \| (\w+) \| (\w+) \| pr: acceptance checks not passed: ([\w.]+::\w+)", tamper,
                "the refused pull request")
    control = _find(r"Control \(the honest fix\): CI green (passes), Knos, tests (passes), Knos, black box (passes)\.", tamper, "the honest fix")
    first = bench["market"]["index"]["overall"]["first_pr_per_repo"]
    share = next(f["say"][0] for f in facts if f.get("path") == "market.index.overall.first_pr_per_repo.any_check_failed.share")
    if f"{first['any_check_failed']['share'] * 100:.1f}%" != share:
        raise SystemExit("docs/facts.json and docs/bench.json disagree on the share")
    for name, _ in CLAIMS:
        if f"`{name}`" not in oidc:
            raise SystemExit(f"docs/OIDC.md no longer names the claim {name}")
    wait = bench["devnet"]["stats"]["latency"]["merge_to_paid"]
    days = int(_find(r"\nDAYS, MAX_DAYS = (\d+), \d+", _read("src/knos/commands.py"), "the days an unpaid order runs")[1])
    remedy = _find(r"(what nobody proves goes back at the\s+deadline)", cap, "what happens to an order nobody proves")[1]
    reason = _find(r"pr: (acceptance checks not passed): " + re.escape(row[6]), tamper, "the judge's reason")[1]

    doc = {
        "_about": "Written by scripts/demo_data.py from the documents under `sources`; tests/test_site_demo.py holds every signature and number to them.",
        "cluster": "devnet",
        "ids": ids_used(manifest)[0],
        "date": date,
        "money": "test USDC",
        "agree": {"price": fund[3], "days": days, "remedy": " ".join(remedy.split())},
        "fund": {"comment": comment, "tx": fund[1], "order": fund[2], "amount": fund[3], "fee": fund[4]},
        "claim": {"says": "tests pass", "share": share, "failed": first["any_check_failed"]["repos"], "of": first["repos"],
                  "attack": int(row[1]), "pull": row[2], "ci": row[3], "knos": row[4], "check": row[6], "reason": reason},
        "fixed": {"ci": control[1], "tests": control[2], "black_box": control[3], "claims": [{"name": n, "is": w} for n, w in CLAIMS]},
        "paid": {"tx": paid[1], "amount": paid[2], "seconds": wait["median"], "payments": wait["count"], "window": wait["window"]},
        "replay": {"tx": again[2], "error": int(again[3]), "means": " ".join(once[2].split()), "single_use_error": int(once[1]),
                   "single_use": " ".join(once[2].split())},
        "count": {"buyer": buyer, "seller": seller, "apart": int(apart), "buyer_tx": [count[2], count[3]], "seller_tx": [count[5], count[6]]},
        "bank_file": (ROOT / "web" / "rails.js").is_file(),
        "sources": list(SOURCES),
    }
    if VERIFIED in SOURCES:
        got = json.loads(_read(VERIFIED))
        doc["verify"] = {"says": str(got["says"]), "link": str(got["link"])}
    shown = public_round(manifest)
    if shown:       # the run at the public program ids replaces the rehearsal's four parts, whole
        if shown["replay"]["error"] != int(once[1]) or shown["count"]["seller"] - shown["count"]["buyer"] != shown["count"]["apart"]:
            raise SystemExit("the public round's refusal is not the single-use error, or its counts and their difference disagree")
        doc.update(date=shown["date"], fund=shown["fund"], agree={"price": shown["fund"]["amount"], "days": days, "remedy": " ".join(remedy.split())}, paid={**doc["paid"], **shown["paid"]}, count=shown["count"],
                   replay={**shown["replay"], "single_use_error": int(once[1]), "single_use": " ".join(once[2].split())})
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = build()
    used = ids_used(json.loads(_read("docs/capabilities.json")))
    print(f"program ids of the round shown: {used[0]} ({used[1]})")
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("web/demo_data.json is not what scripts/demo_data.py writes: run it")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
