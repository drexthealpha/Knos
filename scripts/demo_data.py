"""web/demo_data.json: the round the first screen replays (web/demo.js), read out of what this repository records.

    python scripts/demo_data.py            write web/demo_data.json
    python scripts/demo_data.py --check    exit 1 when the file is not what this would write

Nothing here is typed in by hand: every signature, address, amount and count is cut out of a document of this
repository by a pattern, and a pattern that finds nothing stops the script. What the documents do not record is left
out (the rehearsal's order is recorded with its address, not with its terms hash, so the demo shows the address; the
signed token of that order is not printed anywhere, so the demo names the three claims and shows no values).

`ids` says where the round ran: "public" when docs/capabilities.json holds exercised evidence, at the public program ids,
for the very funding and payment shown; "staging" otherwise (the 0.3.14 rehearsal). The script prefers the first and
prints which it used; web/demo.js says it over the demo.

Where each part comes from:
- fund, paid, replay, count: docs/CAPABILITIES.md, "The 0.3.14 rehearsal on devnet" (parts 1, 2 and 5): transactions
  on devnet at the staging addresses of the 0.3.14 build, in test USDC. The fund and pay transactions are the ones
  docs/capabilities.json names in the notes of `work_orders` and `order_pay`.
- claim: docs/TAMPER.md, the Python table: a pull request that fixes nothing, what CI said and the check Knos named.
  How often a first agent pull request that says its tests pass has a failed check: docs/facts.json and
  docs/bench.json (market.index.overall.first_pr_per_repo).
- fixed: docs/TAMPER.md, the control row (the honest fix), and the claim names of docs/OIDC.md.
- seconds: docs/bench.json, devnet.stats.latency.merge_to_paid (the median of the public relay's payments).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "demo_data.json"
SOURCES = ("docs/CAPABILITIES.md", "docs/capabilities.json", "docs/TAMPER.md", "docs/bench.json", "docs/facts.json", "docs/OIDC.md")
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


def ids_used(capabilities: list[dict], fund_tx: str, pay_tx: str) -> tuple[str, str]:
    """Which program ids the round shown ran at, and why, in words. "public" only when docs/capabilities.json holds
    `exercised` evidence for the order's funding and its payment (which scripts/capabilities.py takes at the public
    program ids alone) and those two transactions are the round's own. Anything else is the staging rehearsal."""
    by = {c["id"]: c for c in capabilities}
    sigs = [by.get(i, {}).get("evidence", {}).get("exercised", {}).get("signature") for i in ("work_orders", "order_pay")]
    if all(sigs) and sigs == [fund_tx, pay_tx]:
        return "public", "the round is the one docs/capabilities.json records as exercised at the public program ids"
    if all(sigs):
        return "staging", ("docs/capabilities.json records exercised transactions at the public program ids, but docs/CAPABILITIES.md records no whole "
                           "round with them (order, refusal, counts): the staging rehearsal is shown until it does")
    return "staging", "docs/capabilities.json records no exercised funding and payment at the public program ids: the staging rehearsal is shown"


def build() -> str:
    cap = _read("docs/CAPABILITIES.md")
    start = cap.index("## The 0.3.14 rehearsal on devnet")
    reh = cap[start:]
    capabilities = json.loads(_read("docs/capabilities.json"))["capabilities"]
    notes = {c["id"]: c.get("note", "") for c in capabilities}
    bench = json.loads(_read("docs/bench.json"))
    facts = json.loads(_read("docs/facts.json"))["facts"]
    tamper, oidc = _read("docs/TAMPER.md"), _read("docs/OIDC.md")

    date = _find(r"On (\d+ \w+ \d{4}), before the release", reh, "the day of the rehearsal")[1]
    comment = _find(r"two `(/knos fund \d+)` comments", reh, "the funding comment")[1]
    fund = _find(rf"\| The first fund token is relayed \| {TX} \| order `([1-9A-HJ-NP-Za-km-z]{{32,44}})` funded with ([\d.,]+), its fee of ([\d.]+) on top",
                 reh, "the funded order")
    paid = _find(rf"\| The merged pull request's pay token is relayed \| {TX} \| ([\d.,]+) paid to the payee", reh, "the payment")
    again = _find(rf"\| The first pay token, sent again \| {TX}[^|]*\| refused, error (\d+)", reh, "the refused replay")
    means = " ".join(_find(rf"\b{again[2]}: ([^;.]+)[;.]", reh, "what the replay's error means")[1].split())
    once = _find(r"(\d+): (a token works\s+once)", reh, "the single-use error")
    if ids_used(capabilities, fund[1], paid[1])[0] != "public" and (fund[1] not in notes["work_orders"] or paid[1] not in notes["order_pay"]):
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

    doc = {
        "_about": "Written by scripts/demo_data.py from the documents under `sources`; tests/test_site_demo.py holds every signature and number to them.",
        "cluster": "devnet",
        "ids": ids_used(capabilities, fund[1], paid[1])[0],
        "date": date,
        "money": "test USDC",
        "fund": {"comment": comment, "tx": fund[1], "order": fund[2], "amount": fund[3], "fee": fund[4]},
        "claim": {"says": "tests pass", "share": share, "failed": first["any_check_failed"]["repos"], "of": first["repos"],
                  "attack": int(row[1]), "pull": row[2], "ci": row[3], "knos": row[4], "check": row[6]},
        "fixed": {"ci": control[1], "tests": control[2], "black_box": control[3], "claims": [{"name": n, "is": w} for n, w in CLAIMS]},
        "paid": {"tx": paid[1], "amount": paid[2], "seconds": wait["median"], "payments": wait["count"], "window": wait["window"]},
        "replay": {"tx": again[1], "error": int(again[2]), "means": means, "single_use_error": int(once[1]), "single_use": " ".join(once[2].split())},
        "count": {"buyer": buyer, "seller": seller, "apart": int(apart), "buyer_tx": [count[2], count[3]], "seller_tx": [count[5], count[6]]},
        "sources": list(SOURCES),
    }
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = build()
    doc = json.loads(text)
    used = ids_used(json.loads(_read("docs/capabilities.json"))["capabilities"], doc["fund"]["tx"], doc["paid"]["tx"])
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
