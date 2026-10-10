"""One source for a statement line's assurance: the statement page (web/statements.js through web/assurance_words.js)
shows the words `knos assurance FILE` prints (knos.assurance.text), never the receipt's own level. In 0.3.24 the page
said "reported" for a line of the shadow sample while the command said "not signed"."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from knos import assurance

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests" / "data" / "statement"
CASES = [(ROOT / "web" / "statement_sample.json", ROOT / "web" / "statement_sample.status.json"), (ROOT / "web" / "statement_sample.json", None),
         (DATA / "sept.json", None), (DATA / "sept.json", DATA / "sept.status.json"), (DATA / "sept.json", DATA / "sept.grn.status.json"),
         (DATA / "october.json", None), (DATA / "front_door.json", None)]

SCRIPT = """
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
const [web, ...pairs] = process.argv.slice(2);
const fd = await import(pathToFileURL(web + "/finance_data.js").href), aw = await import(pathToFileURL(web + "/assurance_words.js").href);
const out = [];
for (const pair of pairs) {
  const [a, b] = pair.split("|"), st = JSON.parse(readFileSync(a, "utf8")), status = b ? JSON.parse(readFileSync(b, "utf8")) : null;
  out.push(fd.statementLines(st, status).map((ln) => { const x = aw.lineAssurance(st, status, ln); return [ln.line, aw.assuranceWord(x), x.identity_proved]; }));
}
console.log(JSON.stringify(out));
"""


def python_words(st: Path, status: Path | None) -> list[list]:
    doc = json.loads(st.read_text(encoding="utf-8"))
    said = assurance.text(doc, json.loads(status.read_text(encoding="utf-8")) if status else None)
    rows = []
    for line in said:
        m = re.fullmatch(r"  line (\d+): (.+?)( \(workflow identity proved on chain\))?", line)
        if m:
            rows.append([int(m[1]), m[2], bool(m[3])])
    return rows


def test_the_sample_says_not_signed_in_both_places():
    words = [w for _n, w, _p in python_words(*CASES[0])]
    assert words == ["not signed", "not signed", "not signed", "not evaluated", "not signed"]


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_page_words_are_the_commands_words_for_every_statement(tmp_path):
    script = tmp_path / "words.mjs"
    script.write_text(SCRIPT, encoding="utf-8")
    pairs = [f"{a}|{b or ''}" for a, b in CASES]
    done = subprocess.run(["node", str(script), str(ROOT / "web"), *pairs], capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    want = [python_words(a, b) for a, b in CASES]
    assert got == want
    assert ["re-executed", True] in [r[1:] for r in got[4]]          # a recorded note: its receipt's level, and the chain's check of the identity


def test_the_statement_page_draws_the_column_from_the_assurance_words_only():
    js = (ROOT / "web" / "statements.js").read_text(encoding="utf-8")
    assert 'import { lineAssurance, assuranceHtml, assuranceWord } from "./assurance_words.js";' in js
    assert 'col === "assurance" ? assuranceHtml(esc, assured[n])' in js
    assert '["assurance", assured ? assuranceWord(assured) : g.assurance]' in js and "grnHtml(esc, statementGrn(st, status, r.invoice_line), assured[n])" in js
    words = (ROOT / "web" / "assurance_words.js").read_text(encoding="utf-8")
    for name, value in (("FROM_RECEIPT", assurance.FROM_RECEIPT), ("REACHABLE", list(assurance.REACHABLE)), ("UNSIGNED_SOURCES", list(assurance.UNSIGNED_SOURCES))):
        m = re.search(rf"export const {name} = (.+?);\n", words)
        assert m and json.loads(re.sub(r"(\w[\w-]*):", r'"\1":', m[1])) == value, name
    assert f'NOT_EVALUATED = "{assurance.NOT_EVALUATED}"' in words
