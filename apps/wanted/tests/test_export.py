"""L06 and L19: a result downloads as CSV and JSON with its inputs, its verdict, its failing rows, the locked test's
sha256 and the tool's version, with no account; the JSON sent back to /api/run gives the same verdict; every record
names the exact version that answered it, and a record from another version says so."""
import csv
import io

from test_tool_run import SMALL, app, call, own, program, sample_body  # noqa: F401  (fixtures)

from knos_wanted import tool_page, tool_run, valley


def test_a_sample_result_downloads_as_csv_and_json_with_its_evidence(app):  # noqa: F811
    st, r, _ = call(app, "/api/run", sample_body(test=True))
    assert st == 200 and r["key"] and r["tool_version"] == tool_run.tool_version() and len(r["test_sha256"]) == 64
    st, body, h = call(app, f"/api/run/{r['id']}.csv", raw=True)
    assert st == 200 and "attachment" in h["Content-Disposition"] and h["Content-Type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    assert len(rows) == len(tool_run.sample().splitlines()) - 1                      # every input row, once
    assert {x["knos_verdict"] for x in rows} == {r["verdict"]} and {x["knos_test_sha256"] for x in rows} == {r["test_sha256"]}
    assert {x["knos_tool_version"] for x in rows} == {tool_run.tool_version()}
    failed = [int(x["knos_row"]) for x in rows if x["knos_status"] == "failed"]
    assert failed and failed[0] == r["first_failing_row"]
    assert all(x[tool_run.CONF["sample_column"]] for x in rows)                     # the input's own column is there
    st, doc, _ = call(app, f"/api/run/{r['id']}.json")
    assert st == 200 and doc["verdict"] == r["verdict"] and doc["test_sha256"] == r["test_sha256"] and doc["tool_version"] == r["tool_version"]
    assert doc["failing"] == r["failing"] and doc["table"].strip() == tool_run.sample().strip()
    st, again, _ = call(app, "/api/run", {**doc, "test": True})                         # the JSON re-run as it is
    assert st == 200 and again["verdict"] == r["verdict"] and again["result"] == r["result"]


def test_an_own_result_downloads_only_with_its_key(app):  # noqa: F811
    st, r, _ = own(app)
    assert st == 200
    assert call(app, f"/api/run/{r['id']}.json")[0] == 403
    assert call(app, f"/api/run/{r['id']}.json", headers={"X-Knos-Key": "x" * 24})[0] == 403
    st, doc, _ = call(app, f"/api/run/{r['id']}.json", headers={"X-Knos-Key": r["key"]})
    assert st == 200 and doc["table"] == SMALL and doc["column"] == "reading"


def test_every_record_names_its_version_and_an_older_one_says_so(app):  # noqa: F811
    st, r, _ = call(app, "/api/run", sample_body(test=True))
    rec = valley._safe_load(tool_run.RESULTS, r["id"])
    assert {k for k in ("id", "tool_version", "test_sha256", "created_at") if rec.get(k)} == {"id", "tool_version", "test_sha256", "created_at"}
    assert tool_run.shape(rec)["older"] is False
    valley._save(tool_run.RESULTS, r["id"], {**rec, "tool_version": "job-0/000000000000"}, chain=False)
    st, page, _ = call(app, f"/r/{r['id']}/", raw=True)
    assert st == 200 and b'"older": true' in page
    assert tool_page.t("en", "res.older") == "Checked on an older version of this tool."
    assert '"res.older"' in tool_page.SCRIPT and "res.older" in tool_page.SCRIPT_KEYS
