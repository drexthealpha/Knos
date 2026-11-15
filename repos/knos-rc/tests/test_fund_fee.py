"""The fee fold of the Fund page (#fund, "How it pays, the fee"). knos_pay 2.2 runs at the public id since 9 October
2026: the fold states its rule (0.30% of the amount, at least 0.05) in the words knos.fees.words(2) and web/price.js
feeWords(2) give, and web/fund_fee.js draws the rule again from what the program (or upgrades.json) answers, as
Pricing does. Nobody answering leaves the words; 2.1 answering says the fee charged before the upgrade."""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from knos import fees

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def fold() -> str:
    page = (WEB / "index.html").read_text(encoding="utf-8")
    start = page.index("<summary>How it pays, the fee</summary>")
    return page[start:page.index("</details>", start)]


def words(part: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", part)).split())


def test_the_fold_states_the_live_rule_in_the_fee_modules_words_and_no_pre_upgrade_text():
    part = fold()
    m = re.search(r'<p class="fine" id="fund-fee" data-fee="0.3.18">(.*?)</p>', part, re.S)
    assert m and words(m[1]) == fees.words(2) == f"Fee: {fees.NEW.rate()} test USDC, paid by the funder on top (knos_pay 2.2 is live). {fees.KEEPS}"
    said = words(part)
    assert "0.30% of the amount, at least 0.05 test USDC" in said and "There is no maximum." in said
    assert f"An order funded under knos_pay {fees.OLD.build} keeps its stored fee: {fees.OLD.rate()} test USDC." in said
    for stale in ("once knos_pay 2.2 is live", "until that upgrade executes", "the fee it charged before the upgrade"):
        assert stale not in said, stale


SCRIPT = """
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
const [web, dir] = process.argv.slice(2);
writeFileSync(join(dir, "settle.js"), "export {};\\n");          // only the built site has it: every constant is then recorded
for (const f of ["price.js", "fee_live.js", "version.js", "fund_fee.js"]) writeFileSync(join(dir, f), readFileSync(join(web, f), "utf8"));
const { renderFundFee } = await import(pathToFileURL(join(dir, "fund_fee.js")).href);
const { priceConstants } = await import(pathToFileURL(join(dir, "price.js")).href);
const out = [];
for (const [version, source] of [[2, "chain"], [1, "chain"], [2, "feed"], [null, null]]) {
  const el = { textContent: "as written", dataset: {} };
  const got = await renderFundFee(el, { live: Promise.resolve({ version, source, c: priceConstants(undefined, version) }) });
  out.push({ version, got, text: el.textContent, fee: el.dataset.fee ?? null, source: el.dataset.source ?? null });
}
const el = { textContent: "as written", dataset: {} };
out.push({ thrown: await renderFundFee(el, { live: Promise.reject(new Error("devnet did not answer")) }), text: el.textContent });
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_fold_follows_what_the_program_answers(tmp_path):
    (tmp_path / "words.mjs").write_text(SCRIPT, encoding="utf-8")
    work = tmp_path / "site"
    work.mkdir()
    done = subprocess.run(["node", str(tmp_path / "words.mjs"), str(WEB), str(work)], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    two, one, feed, nobody, failed = json.loads(done.stdout)
    assert two == {"version": 2, "got": 2, "text": fees.words(2), "fee": "0.3.18", "source": "chain"}
    assert one["text"] == fees.words(1) and one["fee"] == "0.3.14" and "2.5% of the first 1,000" in one["text"]
    assert feed["text"] == fees.words(2) and feed["source"] == "feed"
    assert nobody == {"version": None, "got": None, "text": "as written", "fee": None, "source": None}
    assert failed == {"thrown": None, "text": "as written"}
