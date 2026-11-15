"""Shadow mode (src/knos/shadow.py): an invoice that bills per merged change against GitHub's record, offline.

GitHub here is BOOK, a made-up repository's answers by path; no test asks the network for anything. The cases the
browser must answer alike are tests/data/shadow_cases.json (tests/web/shadow.mjs runs them in node): this file checks
that they are still what the Python says, and `python tests/test_shadow.py` writes them again."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from knos import shadow

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "data" / "shadow_cases.json"
A, B = "a" * 40, "b" * 40


def sha(n: int) -> str:
    return f"{n:040x}"


def pull(n: int, body: str = "", merged: bool = True, base: str = "main") -> dict:
    return {"number": n, "body": body, "merged_at": f"2026-09-0{n % 9 + 1}T10:00:00Z" if merged else None,
            "merge_commit_sha": sha(1000 + n) if merged else None, "head": {"sha": sha(n)},
            "base": {"ref": base, "repo": {"full_name": "acme/app", "default_branch": "main"}}}


def run(name: str, conclusion: str | None = "success", status: str = "completed", n: int = 1) -> dict:
    return {"name": name, "status": status, "conclusion": conclusion, "html_url": f"https://github.com/acme/app/actions/runs/{n}/job/{n}"}


def checks(n: int, runs: list, statuses: list = ()) -> dict:
    return {f"repos/acme/app/commits/{sha(n)}/check-runs?per_page=100&page=1": {"total_count": len(runs), "check_runs": runs},
            f"repos/acme/app/commits/{sha(n)}/status?per_page=100&page=1": {"state": "x", "total_count": len(statuses), "statuses": list(statuses)}}


def commits(n: int, *messages: str) -> dict:
    return {f"repos/acme/app/pulls/{n}/commits?per_page=100&page=1": [{"sha": sha(500 + i), "commit": {"message": m}} for i, m in enumerate(messages)]}


BOOK: dict = {
    # 1 clean: says tests pass, a run and a status passed; the agent's own session run failed and is no evidence
    "repos/acme/app/pulls/1": pull(1, "Adds the parser.\n\nAll tests pass.\n\nFixes #10"),
    **checks(1, [run("test"), run("Copilot", "failure", n=2), run("docs", "skipped", n=3)], [{"context": "ci/build", "state": "success", "target_url": "https://ci.example/1"}]),
    # 2 failed: a failed run and one that timed out; a cancelled one is no failure
    "repos/acme/app/pulls/2": pull(2, "CI is green.\n\nCloses #11"),
    **checks(2, [run("test", "failure", n=21), run("lint", n=22), run("deploy", "cancelled", n=23), run("e2e", "timed_out", n=24)]),
    # 3 not merged
    "repos/acme/app/pulls/3": pull(3, "Draft.", merged=False),
    # 5 merged and green, and it closes #10 as line 1 does: one deliverable billed twice
    "repos/acme/app/pulls/5": pull(5, "Second try. `Fixes #99` in code is not a link.\n\nresolves: acme/app#10"),
    **checks(5, [run("test", n=51)]), **commits(5, "second try"),
    # 7 private, no token; 8 the rate limit
    "repos/acme/private/pulls/7": {"__unread": "not found or private"},
    "repos/acme/app/pulls/8": {"__unread": "rate limit"},
    # 9 merged with no check at all; the claim is in a commit message
    "repos/acme/app/pulls/9": pull(9, "Refactor.\n\n- [ ] tests pass"),
    **checks(9, []), **commits(9, "wip", "fix: all tests pass now"),
    # 12 failed by a commit status; names a spreadsheet would run, and one beyond the basic plane
    "repos/acme/app/pulls/12": pull(12, "Ready. Fixes #10", base="release"),
    **checks(12, [run("\U0001f680 Publish", n=121), run("=SUM(A1)", n=122), run("Ａ wide", n=123)],
             [{"context": "=ci/gate", "state": "error", "target_url": "javascript:alert(1)"}, {"context": "security", "state": "pending", "target_url": None}]),
    **commits(12, "ready"),
    # 13 a check has not finished; 14 its check runs were readable and its statuses were not
    "repos/acme/app/pulls/13": pull(13, "Tests pass."), **checks(13, [run("test", None, "in_progress", n=131)]),
    "repos/acme/app/pulls/14": pull(14, "Tests pass."),
    f"repos/acme/app/commits/{sha(14)}/check-runs?per_page=100&page=1": {"total_count": 1, "check_runs": [run("test", n=141)]},
    f"repos/acme/app/commits/{sha(14)}/status?per_page=100&page=1": {"__unread": "no answer"},
}

MAIN = ("﻿Pull Request;Price;Vendor\r\n"
        "https://github.com/acme/app/pull/1;100.00;Acme Agents\r\n"
        "acme/app#2;250,00;Acme Agents\r\n"
        "acme/app#3;80;Acme Agents\r\n"
        "ACME/App#1;100.00;Acme Agents\r\n"
        "\r\n"
        "acme/app#5;\"60.00\";Acme Agents\r\n"
        "acme/private#7;40.00;Acme Agents\r\n"
        "acme/app#8;30.00;Acme Agents\r\n"
        "acme/app#9;$ 20.00;Acme Agents\r\n"
        "the March retainer;5.00;Acme Agents\r\n"
        "acme/app#12;1.015,50;Acme Agents\r\n"
        "# a note to the reader; not a line\r\n"
        "acme/app#13;10.00;Acme Agents\r\n"
        "acme/app#14;10.00;Acme Agents\r\n")
PLAIN = "acme/app#1,12.5\nacme/app#2,\"1,200.00\",\"Smith, Jones\"\nacme/app#404,7\n"
AS_JSON = json.dumps({"lines": [{"change": "acme/app#1", "total": 12.5, "vendor": "Acme"}, {"URL": "https://github.com/acme/app/pull/2"},
                                "acme/app#3", {"pr": "acme/app#2", "amount": 3}, {"pr": None}]})
OVER_HTTP = "".join(line + "\n" for line in MAIN.replace("\r", "").split("\n") if line and "#8;" not in line)     # what a page can be shown to read: no spent limit
INVOICES = {"semicolons, a byte order mark, aliases, every class": MAIN, "no header, commas, a quoted cell": PLAIN,
            "JSON, not every line priced: the share is by lines": AS_JSON, "every answer one a browser gets over HTTP": OVER_HTTP}


def state(text: str) -> dict:
    return shadow.run(text, shadow.recorded(BOOK))


def cases() -> dict:
    out = []
    for name, text in INVOICES.items():
        st = state(text)
        out.append({"name": name, "invoice": text, "json": shadow.canonical(st).decode("utf-8"), "csv": shadow.as_csv(st), "sha256": shadow.digest(st)})
    return {"about": "Written by tests/test_shadow.py from src/knos/shadow.py. A made-up repository: nobody's invoice.", "book": BOOK, "cases": out}


def by_line(st: dict) -> dict:
    return {r["line"]: r for r in st["lines"]}


def test_every_line_ends_in_one_class_and_the_unreadable_are_counted_apart():
    st = state(MAIN)
    rows = by_line(st)
    assert {i: r["class"] for i, r in rows.items()} == {1: "clean", 2: "failed", 3: "not_merged", 4: "duplicate", 5: "duplicate", 6: "unreadable", 7: "unreadable",
                                                       8: "unverified", 9: "unreadable", 10: "failed", 11: "unverified", 12: "unreadable"}
    assert st["counts"] == {"clean": 1, "failed": 2, "unverified": 2, "not_merged": 1, "duplicate": 2, "unreadable": 4}
    assert sum(st["counts"].values()) == st["lines_billed"] == 12 and st["complete"] is False
    assert {i: rows[i]["why"] for i in (4, 5, 6, 7, 8, 9, 11, 12)} == {
        4: "same pull request as line 1", 5: "closes acme/app#10, as line 1 does", 6: "not found or private", 7: "rate limit", 8: "no check ran",
        9: "no pull request named", 11: "a check has not finished", 12: "no answer"}
    # nothing is guessed about a line that could not be read: no merge, no commit, no check
    for i in (6, 7, 9, 12):
        assert (rows[i]["merged"], rows[i]["merge_commit"], rows[i]["checks"], rows[i]["failed"], rows[i]["claimed"]) == (None, "", [], [], "")


def test_a_failed_line_names_each_check_and_links_its_run():
    rows = by_line(state(MAIN))
    assert rows[2]["failed"] == [{"name": "e2e", "url": "https://github.com/acme/app/actions/runs/24/job/24"},
                                 {"name": "test", "url": "https://github.com/acme/app/actions/runs/21/job/21"}]
    assert {c["name"]: c["state"] for c in rows[2]["checks"]} == {"deploy": "other", "e2e": "failed", "lint": "passed", "test": "failed"}
    assert rows[2]["merge_commit"] == sha(1002) and rows[2]["head"] == sha(2) and rows[2]["merged_at"]
    assert rows[10]["failed"] == [{"name": "=ci/gate", "url": "javascript:alert(1)"}]       # the statement records; the page and the CSV defuse
    # the agent's own session run is no evidence either way, and is counted as left out
    assert rows[1]["agent_runs"] == 1 and "Copilot" not in [c["name"] for c in rows[1]["checks"]]
    assert [c["state"] for c in rows[1]["checks"]] == ["passed", "skipped", "passed"]


def test_what_was_claimed_and_which_issue_is_closed():
    rows = by_line(state(MAIN))
    assert (rows[1]["claimed"], rows[2]["claimed"], rows[8]["claimed"], rows[10]["claimed"]) == ("description", "description", "commit", "")
    assert rows[1]["issues"] == ["acme/app#10"] and rows[5]["issues"] == ["acme/app#10"]
    assert rows[10]["issues"] == []         # a keyword in a pull request against another branch closes nothing


def test_the_amount_in_dispute_and_its_share():
    st = state(MAIN)
    assert st["basis"] == "amount" and st["supplier"] == "Acme Agents"
    assert st["amounts"] == {"billed": "1720.50", "clean": "100.00", "failed": "1265.50", "unverified": "30.00", "not_merged": "80.00",
                             "duplicate": "160.00", "unreadable": "85.00"}
    assert st["disputed"] == {"lines": 5, "amount": "1505.50", "share_bp": 8750, "share": "87.50%"}
    lines = state(AS_JSON)
    assert lines["basis"] == "lines" and lines["amounts"] is None
    assert lines["disputed"] == {"lines": 3, "amount": None, "share_bp": 6000, "share": "60.00%"}
    assert lines["supplier"] == "Acme"


def test_the_note_says_what_it_is_in_one_line():
    st = state(PLAIN)
    assert st["note"] == shadow.NOTE and "\n" not in shadow.NOTE
    for words in ("not proof the work is bad", "not proof it is good", "changes nothing", "holds no money"):
        assert words in shadow.NOTE
    assert shadow.NOTE in shadow.as_text(st)


def test_the_statement_is_canonical_and_its_hash_is_stable(tmp_path: Path):
    st = state(MAIN)
    raw = shadow.canonical(st)
    assert raw == shadow.canonical(state(MAIN)) and raw.endswith(b"}\n") and b'": ' not in raw and raw.count(b"\n") == 1
    assert json.loads(raw) == st and list(json.loads(raw)) == sorted(st)
    assert shadow.digest(st) == hashlib.sha256(raw).hexdigest()
    files = shadow.write(st, tmp_path / "out")
    assert [f.name for f in files] == ["statement.json", "statement.csv", "statement.sha256"]
    assert files[0].read_bytes() == raw and files[2].read_text(encoding="utf-8") == f"{shadow.digest(st)}  statement.json\n"
    # the order GitHub lists a commit's checks in changes nothing
    book = json.loads(json.dumps(BOOK))
    key = f"repos/acme/app/commits/{sha(2)}/check-runs?per_page=100&page=1"
    book[key]["check_runs"].reverse()
    assert shadow.digest(shadow.run(MAIN, shadow.recorded(book))) == shadow.digest(st)


def test_the_committed_cases_are_what_the_python_says():
    assert json.loads(CASES.read_text(encoding="utf-8")) == json.loads(json.dumps(cases())), "run: python tests/test_shadow.py"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_the_browser_writes_the_same_bytes():
    r = subprocess.run([shutil.which("node"), str(ROOT / "tests" / "web" / "shadow.mjs")], capture_output=True, text=True, encoding="utf-8", check=False)
    assert r.returncode == 0, "\n".join(line for line in (r.stdout + r.stderr).splitlines() if not line.startswith("ok"))
    assert "all passed" in r.stdout


def test_the_csv_is_one_row_a_line_and_no_cell_is_a_formula():
    text = shadow.as_csv(state(MAIN))
    rows = shadow._cells(text)
    assert rows[0] == list(shadow.CSV_HEAD) and len(rows) == 13
    assert rows[10][11] == "'=ci/gate" and rows[2][11] == "e2e | test"
    assert shadow.as_csv(state(PLAIN)).splitlines()[2].split(",")[3:5] == ['"Smith', ' Jones"']


def test_reading_an_invoice_is_tolerant_and_never_guesses_an_amount():
    assert [(ln["pr"], ln["amount"], ln["supplier"]) for ln in shadow.parse(PLAIN)["lines"]] == [
        ("acme/app#1", 1250, ""), ("acme/app#2", 120000, "Smith, Jones"), ("acme/app#404", 700, "")]
    assert [ln["amount"] for ln in shadow.parse(AS_JSON)["lines"]] == [1250, None, None, 300, None]
    assert shadow.parse("change\tprice\nacme/app#1\t1 200,5\n")["lines"][0]["amount"] == 120050
    assert [shadow.cents(t) for t in ("1,200.50", "1.200,50", "$1200", "12,5", "USD 3", "-4.00", "")] == [120050, 120050, 120000, 1250, 300, -400, None]
    for bad in ("0.125", "1,2,3", "twelve", "1.2.3.4"):
        with pytest.raises(ValueError):
            shadow.cents(bad)
    with pytest.raises(ValueError, match="line 2: the amount 0.125 could not be read"):
        shadow.parse("pr,amount\nacme/app#1,1\nacme/app#2,0.125\n")
    with pytest.raises(ValueError, match="names no line"):
        shadow.parse("pr,amount\n")


def test_the_claim_reader_and_the_failed_conclusions_are_the_index_s():
    """scripts/agent_pr_ci.py reads a description and a commit's checks for the Agent PR Index; shadow mode holds a copy
    in the package, and the two stay word for word the same."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import agent_pr_ci
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    for name in ("CLAIM_RE", "NONCLAIM_RE", "_BOILER_RE", "AGENT_RUN_RE"):
        assert getattr(shadow, name).pattern == getattr(agent_pr_ci, name).pattern and getattr(shadow, name).flags == getattr(agent_pr_ci, name).flags, name
    assert shadow.FAIL_CONCL == agent_pr_ci.FAIL_CONCL and shadow.OK_CONCL == agent_pr_ci.OK_CONCL
    for body in ("All tests pass.", "- [ ] tests pass", "Make sure tests pass.", "<!-- tests pass -->\nRefactor.", "CI is green ✅", "504 passed, 0 failed.", None, ""):
        assert shadow.find_claim(body) == agent_pr_ci.find_claim(body), body


# ---- GitHub: read only, within its limits ---------------------------------------------------------------------------

class Web:
    """urlopen, answering from BOOK with an ETag; counts what was asked and how."""

    def __init__(self, limit: int = 10_000):
        self.asked: list[tuple[str, dict]] = []
        self.limit = limit

    def __call__(self, req, timeout=0):
        path = req.full_url.split("api.github.com/", 1)[1]
        head = {k.lower(): v for k, v in req.header_items()}
        assert req.get_method() == "GET" and req.data is None
        self.asked.append((path, head))
        got = BOOK.get(path)
        if len([1 for _p, h in self.asked if "if-none-match" not in h]) > self.limit:
            raise urllib.error.HTTPError(req.full_url, 403, "rate limit", {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "2000"}, io.BytesIO(b"{}"))  # type: ignore[arg-type]
        if got is None or (isinstance(got, dict) and "__unread" in got):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))  # type: ignore[arg-type]
        if head.get("if-none-match") == f'"{path}"':
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, io.BytesIO(b""))  # type: ignore[arg-type]
        resp = io.BytesIO(json.dumps(got).encode())
        resp.headers = {"ETag": f'"{path}"'}  # type: ignore[attr-defined]
        return resp


def test_the_reader_only_reads_and_sends_the_named_token_alone(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ambient")
    web = Web()
    reader = shadow.Reader("named", urlopen=web, clock=lambda: 1000.0)
    assert reader.get("repos/acme/app/pulls/1")["number"] == 1
    assert web.asked[0][1]["authorization"] == "Bearer named"
    shadow.Reader("", urlopen=web, clock=lambda: 1000.0).get("repos/acme/app/pulls/1")
    assert "authorization" not in web.asked[1][1]
    for refused in (lambda: reader.send("repos/acme/app/issues/1/comments", {"body": "x"}), lambda: reader._request("x", {"a": 1}), lambda: reader._request("x", method="DELETE")):
        with pytest.raises(ValueError, match="only reads"):
            refused()
    assert len(web.asked) == 2
    with pytest.raises(shadow.Unread, match="not found or private"):
        reader.get("repos/acme/private/pulls/7")


def test_a_second_run_asks_only_for_what_is_missing_and_a_spent_limit_stops_cleanly(tmp_path: Path):
    out = tmp_path / "out"
    web = Web(limit=6)                          # GitHub answers six requests, then says the limit is spent
    first = shadow.Reader("", urlopen=web, clock=lambda: 1000.0)
    st = shadow.run(MAIN, first.get, out, first)
    limited = [r["line"] for r in st["lines"] if r["why"] == "rate limit"]
    assert limited and st["counts"]["unreadable"] >= len(limited) and by_line(st)[1]["class"] == "clean"
    asked = len(web.asked)
    assert asked == 7, "after GitHub said the limit is spent, nothing more was asked"
    kept = json.loads((out / shadow.RESUME).read_text(encoding="utf-8"))
    assert "repos/acme/app/pulls/1" in kept["settled"]
    # later, with the limit back: lines an earlier run finished are not asked for again; the rest are
    web2 = Web()
    again = shadow.Reader("", kept["kept"], kept["settled"], urlopen=web2, clock=lambda: 5000.0)
    st2 = shadow.run(MAIN, again.get, out, again)
    assert not {p for p, _h in web2.asked} & set(kept["settled"])
    # over HTTP the made-up GitHub has no line 7 and no statuses for line 12 (a 404 each); every other line is the recording's
    assert [r for r in st2["lines"] if r["line"] not in (7, 12)] == [r for r in state(MAIN)["lines"] if r["line"] not in (7, 12)]
    assert not [r for r in st2["lines"] if r["why"] == "rate limit"]
    assert (out / "statement.json").read_bytes() == shadow.canonical(st2)
    # --refresh: asked again, conditionally; an unchanged answer is a 304
    web3 = Web()
    kept = json.loads((out / shadow.RESUME).read_text(encoding="utf-8"))
    fresh = shadow.Reader("t", kept["kept"], (), urlopen=web3, clock=lambda: 9000.0)
    st3 = shadow.run(MAIN, fresh.get)
    assert fresh.same > 0 and all("if-none-match" in h for p, h in web3.asked if p in kept["kept"])
    assert shadow.digest(st3) == shadow.digest(st2)


def app() -> typer.Typer:
    made = typer.Typer()
    made.callback()(lambda: None)
    shadow.register(made, help_lines := [])
    assert help_lines == [("shadow", "For money", help_lines[0][2])] and len(help_lines[0][2].split()) <= 20
    return made


def test_knos_shadow_is_a_command_of_the_command_line_and_loads_only_its_own_module(capsys):
    """src/knos/cli.py `_MODULES`: `knos shadow` loads knos.shadow and no other command's module; its line is in the help."""
    from knos import cli
    assert [names for names, _how in cli._MODULES if "shadow" in names] == [("shadow",)]
    folder = ROOT / "examples" / "shadow"
    assert cli.main(["shadow", str(folder / "invoice.csv"), "--recorded", str(folder / "recorded.json"), "--json"]) == 0
    want = shadow.run((folder / "invoice.csv").read_text(encoding="utf-8-sig"), shadow.recorded(json.loads((folder / "recorded.json").read_text(encoding="utf-8"))))
    assert capsys.readouterr().out.encode("utf-8") == shadow.canonical(want)
    assert cli.main(["--help"]) == 0
    assert " shadow " in capsys.readouterr().out and sum(row[0] == "shadow" for row in cli._HELP) == 1


def test_the_command_runs_offline_against_a_recording(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(shadow.ghrelay.urllib.request, "urlopen", lambda *a, **k: pytest.fail("the network was asked"))
    invoice, book, out = tmp_path / "invoice.csv", tmp_path / "book.json", tmp_path / "out"
    invoice.write_text(MAIN, encoding="utf-8")
    book.write_text(json.dumps(BOOK), encoding="utf-8")
    r = CliRunner().invoke(app(), ["shadow", str(invoice), "--recorded", str(book), "--out", str(out)])
    assert r.exit_code == 0, r.output
    want = state(MAIN)
    assert f"sha256 {shadow.digest(want)}" in r.output and "In dispute: 1505.50 of 1720.50 (87.50% of the invoice)" in r.output
    assert "line 2 acme/app#2: failed check test https://github.com/acme/app/actions/runs/21/job/21" in r.output
    assert "4 lines could not be read and are not judged" in r.output and shadow.NOTE in r.output
    assert (out / "statement.json").read_bytes() == shadow.canonical(want) and not (out / shadow.RESUME).exists()
    assert hashlib.sha256((out / "statement.json").read_bytes()).hexdigest() == (out / "statement.sha256").read_text(encoding="utf-8").split()[0]
    printed = CliRunner().invoke(app(), ["shadow", str(invoice), "--recorded", str(book), "--json"])
    assert printed.exit_code == 0 and printed.output.encode("utf-8") == shadow.canonical(want)


def test_the_examples_run_offline_and_the_sample_is_marked(tmp_path: Path):
    folder = ROOT / "examples" / "shadow"
    r = CliRunner().invoke(app(), ["shadow", str(folder / "invoice.csv"), "--recorded", str(folder / "recorded.json")])
    assert r.exit_code == 0 and "In dispute:" in r.output, r.output
    as_json = CliRunner().invoke(app(), ["shadow", str(folder / "invoice.json"), "--recorded", str(folder / "recorded.json"), "--json"])
    assert as_json.exit_code == 0 and json.loads(as_json.output)["kind"] == shadow.KIND
    sample = (folder / "sample.csv").read_text(encoding="utf-8")
    assert "assembled by Knos" in sample.splitlines()[0] and "Not anyone's invoice" in sample.splitlines()[0] and "illustrative" in sample.splitlines()[1]
    # every line of the sample is a merged pull request the Agent PR Index lists, and some had a failed check there
    index = {f"{p['repo']}#{p['number']}".lower(): p for p in json.loads((ROOT / "docs" / "agent_pr_ci.json").read_text(encoding="utf-8"))["prs"]}
    lines = shadow.parse(sample)["lines"]
    assert 4 <= len(lines) <= 8 and all(index[ln["pr"].lower()]["merged"] for ln in lines)
    assert sorted({index[ln["pr"].lower()]["class"] for ln in lines}) == ["failed", "passed"]
    web = (ROOT / "web" / "shadow.js").read_text(encoding="utf-8")
    assert f"export const SAMPLE = `{sample}`;" in web, "web/shadow.js holds the sample word for word"


def test_the_document_is_one_screen_and_claims_no_run():
    doc = (ROOT / "docs" / "reference" / "SHADOW.md").read_text(encoding="utf-8")
    assert len(doc.splitlines()) <= 60 and doc.count("knos shadow ") >= 3 and shadow.NOTE.split(". ")[0] in doc
    assert "Pilot" in doc and "Nobody has run" in doc


if __name__ == "__main__":
    CASES.write_text(json.dumps(cases(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {CASES}")
