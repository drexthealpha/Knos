"""Install by pull request: the short workflow file, the link that carries it, the page that builds the link, and the
terms templates. Nothing here talks to GitHub: a job's `if:` is run against sample events by tests/_ghexpr.py."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path

import pytest

from _ghexpr import runs
from knos import commands, init, terms, terms_templates

ROOT = Path(__file__).resolve().parents[1]
SHORT, LONG = ROOT / "examples" / "knos-install.yml", ROOT / "examples" / "knos-workflow.yml"
CALLED = "drexthealpha/knos-workflows/.github/workflows/"
MINTS = {"contents": "read", "issues": "write", "pull-requests": "write", "checks": "read", "statuses": "read", "actions": "read", "id-token": "write"}


def _doc(path: Path) -> dict:
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))
    return doc


def _front():
    spec = importlib.util.spec_from_file_location("front_workflow", ROOT / "scripts" / "front_workflow.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- the file ---------------------------------------------------------------------------------------------------------

def test_the_short_file_is_short_and_calls_what_the_long_one_calls_at_the_same_commit():
    text = SHORT.read_text(encoding="utf-8")
    short, long = _doc(SHORT), _doc(LONG)
    assert len(text.splitlines()) <= 21 and all(ord(c) < 128 for c in text)
    assert short["name"] == long["name"] == "knos" and short["on"] == long["on"]          # the same triggers, exactly
    assert "pull_request_target" not in text and "secrets" not in text and "inherit" not in text and "with:" not in text
    called = lambda doc: {job["uses"] for job in doc["jobs"].values()}                    # noqa: E731
    assert called(short) == called(long) and all(re.fullmatch(re.escape(CALLED) + r"(fund|prove)\.yml@[0-9a-f]{40}", u) for u in called(short))
    # the grant is the one every calling job of the long file has, and each job only says when to call and what to call
    assert short["permissions"] == long["permissions"] == {} and all(job["permissions"] == MINTS for doc in (short, long) for job in doc["jobs"].values())
    assert all(set(job) <= {"name", "needs", "if", "permissions", "uses"} for job in short["jobs"].values())
    # GitHub names a called job "<calling job's name> / <called job>": by that name Knos knows its own jobs
    assert [job["name"] for job in short["jobs"].values()] == ["knos command", "knos settle"]
    assert all(terms.ours({"name": f"{job['name']} / x"}, "") for job in short["jobs"].values())


def _event(name: str, settle: str = "", **event) -> dict:
    return {"github": {"event_name": name, "ref": event.pop("ref", "refs/heads/main"), "event": {"repository": {"default_branch": "main"}, **event}},
            "needs": {"command": {"result": "success" if settle or name in ("issue_comment", "issues") else "skipped", "outputs": {"settle": settle}}}}


def test_the_short_file_starts_the_jobs_the_long_one_starts():
    """Every sample event: the short file's command job runs when the long one's does, and its one settle job runs
    when the long file's settle or review does (prove.yml's own conditions then pick the job, as they always did)."""
    short, long = _doc(SHORT)["jobs"], _doc(LONG)["jobs"]
    comment = lambda body: {"comment": {"body": body}, "issue": {"number": 7}}            # noqa: E731
    samples = [("issue_comment", "", comment("/knos fund 20")), ("issue_comment", "", comment("thanks\n/Knos take")), ("issue_comment", "", comment("see /knos")),
               ("issue_comment", "9", comment("/knos settle")), ("issue_comment", "", comment("nothing")),
               ("issues", "", {"issue": {"body": "Broken.\n/knos fund 20"}}), ("issues", "", {"issue": {"body": "Broken."}}),
               ("push", "", {}), ("push", "", {"ref": "refs/heads/topic"}), ("push", "", {"ref": "refs/tags/v1"}), ("workflow_dispatch", "", {}),
               ("workflow_run", "", {"workflow_run": {"event": "pull_request", "conclusion": "success"}})]
    started = []
    for name, settle, event in samples:
        ctx = _event(name, settle, **dict(event))
        command = runs(long["command"]["if"], ctx)
        needs = {"command": "success" if command else "skipped"}
        want = runs(long["settle"]["if"], ctx, needs) or runs(long["review"]["if"], ctx)
        assert runs(short["command"]["if"], ctx) == command, (name, event)
        assert runs(short["settle"]["if"], ctx, needs) == want, (name, event)
        started.append((command, want))
    assert started == [(True, False), (True, False), (False, False), (True, True), (False, False), (True, False), (False, False),
                       (False, True), (False, False), (False, False), (False, True), (False, True)]


# ---- the link ---------------------------------------------------------------------------------------------------------

def test_the_link_opens_githubs_editor_with_the_exact_file_and_fits():
    text = SHORT.read_text(encoding="utf-8")
    link = init.install_link("acme/widgets", text)
    url = urllib.parse.urlsplit(link)
    query = urllib.parse.parse_qs(url.query, strict_parsing=True)
    assert (url.scheme, url.netloc, url.path) == ("https", "github.com", "/acme/widgets/new/main")
    assert query == {"filename": [".github/workflows/knos.yml"], "value": [text]}          # the file comes back byte for byte
    assert len(link) < init.URL_LIMIT // 3                                                 # 2,573 of GitHub's 8,191 bytes
    assert init.install_link("https://github.com/acme/widgets.git@release/1.x", "a").startswith("https://github.com/acme/widgets/new/release/1.x?")
    # the long file does not fit in a link, which is why there is a short one
    with pytest.raises(ValueError, match="GitHub takes at most 8191"):
        init.install_link("acme/widgets", LONG.read_text(encoding="utf-8"))
    for bad in ("widgets", "acme/", "acme/wid gets", "acme/widgets?x=1", "acme/..", "-acme/widgets", "acme/widgets/tree/main", ""):
        with pytest.raises(ValueError, match="owner/repo"):
            init.install_link(bad, text)


def test_init_pr_prints_the_link_and_sends_nothing_without_the_github_cli(monkeypatch):
    text, said = SHORT.read_text(encoding="utf-8"), []
    monkeypatch.setattr(init.shutil, "which", lambda name: None)
    assert init.pull_request("acme/widgets", said.append, text=text) == 0
    out = "\n".join(said)
    assert init.install_link("acme/widgets", text) in out and text in out and "nothing was sent" in out
    assert init.workflow_text() == text                                # in a source tree the file is the example
    said.clear()
    assert init.pull_request("not a repo", said.append, text=text) == 1 and "owner/repo" in said[0] and len(said) == 1
    # an installed knos reads the file of its own release, and says what to do when it cannot
    asked = []
    assert init.workflow_text(lambda url: asked.append(url) or text) == text
    assert re.fullmatch(r"https://raw\.githubusercontent\.com/drexthealpha/Knos/v[^/]+/examples/knos-install\.yml", asked[0])

    def down(url):
        raise OSError("no network")
    with pytest.raises(ValueError, match="could not be read from GitHub .no network.. Copy it from https://github.com/drexthealpha/Knos/blob/main/examples/knos-install.yml"):
        init.workflow_text(down)


def test_init_pr_opens_the_pull_request_with_the_github_cli_and_leaves_the_link_when_it_cannot():
    import base64
    text, said, calls = SHORT.read_text(encoding="utf-8"), [], []

    def gh(*args):
        calls.append(args)
        path = args[-3] if "--jq" in args and args[1] != "-X" else args[3]
        return {"repos/acme/widgets": "trunk\n", "repos/acme/widgets/git/ref/heads/trunk": "ab" * 20 + "\n",
                "repos/acme/widgets/pulls": "https://github.com/acme/widgets/pull/3\n"}.get(path, "")
    assert init.pull_request("acme/widgets", said.append, gh=gh, text=text) == 0
    assert "Opened the pull request with the GitHub CLI: https://github.com/acme/widgets/pull/3" in said[-1]
    ref, put, pull = calls[2], calls[3], calls[4]
    assert ref[:4] == ("api", "-X", "POST", "repos/acme/widgets/git/refs") and "ref=refs/heads/knos-install" in ref and f"sha={'ab' * 20}" in ref
    assert put[:4] == ("api", "-X", "PUT", "repos/acme/widgets/contents/.github/workflows/knos.yml") and "branch=knos-install" in put
    assert base64.b64decode(next(a for a in put if a.startswith("content="))[8:]).decode() == text
    assert pull[3] == "repos/acme/widgets/pulls" and "base=trunk" in pull and "head=knos-install" in pull

    def refused(*args):
        raise OSError("HTTP 404: Not Found")
    said.clear()
    assert init.pull_request("acme/widgets", said.append, gh=refused, text=text) == 0
    assert init.install_link("acme/widgets", text) in said[1] and "could not open the pull request (HTTP 404: Not Found), so nothing was changed" in said[-1]


def test_nothing_in_the_wheel_names_a_commit_of_the_workflows():
    """The wheel is built before that commit exists (scripts/pinned_workflows.py), so `knos init --pr` reads the file
    from the release's examples instead of carrying it."""
    for name in ("init.py", "terms_templates.py"):
        text = (ROOT / "src" / "knos" / name).read_text(encoding="utf-8")
        assert "KNOS_WORKFLOWS_SHA" not in text and not re.search(r"knos-workflows/\S*[0-9a-f]{40}", text), name


# ---- the page ---------------------------------------------------------------------------------------------------------

def test_the_page_carries_the_examples_and_builds_the_same_link():
    front = _front()
    assert front.main(["--check"]) == 0, "run python scripts/front_workflow.py"
    js = (ROOT / "web" / "install.js").read_text(encoding="utf-8")
    assert not re.search(r"\bfetch\(|XMLHttpRequest|sendBeacon|WebSocket|\bimport\b", js)      # nothing is sent anywhere, and it stands alone
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = ('import * as m from "./web/install.js";\n'
              'const made = []; const el = (tag) => ({ tag, kids: [], listeners: {}, append(...k) { this.kids.push(...k); }, replaceChildren(...k) { this.kids = k; },\n'
              '  setAttribute() {}, addEventListener(n, f) { this.listeners[n] = f; } });\n'
              'const doc = { createElement: (tag) => { const n = el(tag); made.push(n); return n; } };\n'
              'const root = el("div"); root.ownerDocument = doc; m.renderInstall(root);\n'
              'const input = made.find((n) => n.id === "install-repo"); input.value = "acme/widgets"; input.listeners.input();\n'
              'const href = (id) => made.filter((n) => n.id === id).at(-1)?.href;\n'
              'input.value = "nonsense"; const before = made.length; input.listeners.input();\n'
              'console.log(JSON.stringify({ file: m.INSTALL_WORKFLOW, attestor: m.ATTESTOR_WORKFLOW, terms: m.TERMS, link: m.installLink("acme/widgets"), branch: m.installLink("acme/widgets@release/1.x"),\n'
              '  bad: [m.installLink("widgets"), m.installLink("acme/wid gets"), m.installLink("acme/.."), m.installLink("acme/widgets", "a".repeat(9000))],\n'
              '  open: href("install-open"), second: href("install-attestor"), shown: made.find((n) => n.id === "install-file").textContent,\n'
              '  refused: made.slice(before).map((n) => n.textContent).join(" "), quoted: m.installLink("a/b", "~!\'()*é\\n") }));\n')
    done = subprocess.run([node, "--input-type=module", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout)
    text = SHORT.read_text(encoding="utf-8")
    assert got["file"] == got["shown"] == text
    assert got["link"] == got["open"] == init.install_link("acme/widgets", text)             # the page and `knos init --pr`: one link
    assert got["branch"] == init.install_link("acme/widgets@release/1.x", text)
    assert got["quoted"] == init.install_link("a/b", "~!'()*é\n") and got["bad"] == [None, None, None, None]
    assert "owner/repo" in got["refused"]
    # the attestor's file is the example without its comment lines: the same YAML, and a link GitHub takes
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(got["attestor"]) == yaml.safe_load((ROOT / "examples" / "knos-attestor.yml").read_text(encoding="utf-8"))
    assert got["second"] == init.install_link("acme/widgets", got["attestor"], ".github/workflows/knos-attestor.yml") and len(got["second"]) < init.URL_LIMIT
    assert got["terms"] == [terms_templates.export(n) for n in sorted(terms_templates.TEMPLATES)]
    # the first screen loads web/install.js only when its section is opened: the mount is in web/front.js
    assert '(await import("./install.js")).renderInstall($("install-pr"))' in (ROOT / "web" / "front.js").read_text(encoding="utf-8")
    assert 'id="install-pr"' in (ROOT / "web" / "index.html").read_text(encoding="utf-8")


# ---- terms from a template ---------------------------------------------------------------------------------------------

def test_every_templates_comment_parses_into_terms_whose_hash_is_the_templates():
    assert list(terms_templates.TEMPLATES) == ["bugfix", "feature-blackbox", "milestone", "standing-rate", "private-attested"]
    assert sorted(p.stem for p in (ROOT / "examples" / "terms").glob("*.json")) == sorted(terms_templates.TEMPLATES)
    for name, t in terms_templates.TEMPLATES.items():
        path = ROOT / "examples" / "terms" / f"{name}.json"
        assert path.read_text(encoding="utf-8") == terms_templates.dumps(name), f"{path.name} is not the template: write terms_templates.dumps('{name}') to it"
        held = json.loads(path.read_text(encoding="utf-8"))
        # the round trip, with nothing of terms_templates in it: the comment, read as any comment is, built as any bounty's terms are
        cmd = commands.parse("Please fix this.\n" + held["comment"], on_pull=False)
        assert isinstance(cmd, (commands.Fund, commands.Offer)), (name, cmd)
        runs_ = [{"name": n, "app": {"id": terms_templates.ACTIONS}, "status": "completed", "conclusion": "success"} for n in cmd.checks]
        built = terms.build(cmd, [], runs_, [], held["terms"]["accept"])
        assert built.source == "funder" and built.notes == []
        more = {k: held["terms"][k] for k in ("policy", "vendor") if k in held["terms"]}
        raw = terms.canonical({**built.terms, **more})
        assert raw.decode() == held["terms_json"] and terms.parse(raw) == held["terms"]
        assert hashlib.sha256(held["terms_json"].encode("ascii")).hexdigest() == held["terms_hash"] == terms.terms_hash(raw)
        assert cmd.units <= 100_000_000                 # the devnet faucet gives at most 100 per comment
        assert held["sentence"] == terms_templates.sentence(t) and "\n" not in held["sentence"] and "test USDC" in held["sentence"]
    # the facts a template cannot know are the sample ones it says, made the way the product makes them
    from knos import policy
    assert json.loads((ROOT / "examples" / "terms" / "private-attested.json").read_text())["terms"]["policy"] == policy.digest(policy.load(terms_templates.SAMPLE_POLICY))
    assert len({json.loads(p.read_text())["terms_hash"] for p in (ROOT / "examples" / "terms").glob("*.json")}) == 5


def test_the_sentences_say_the_fields():
    say = {n: terms_templates.sentence(t) for n, t in terms_templates.TEMPLATES.items()}
    assert say["bugfix"] == "Pays 50 test USDC when checks `lint`, `unit` pass on a merge that only touches src/ and tests/; refund after 14 days"
    assert "black-box acceptance suite" in say["feature-blackbox"] and say["feature-blackbox"].startswith("Pays 80 test USDC when check `unit` passes")
    assert "; 20% of it waits 30 days" in say["milestone"] and say["milestone"].endswith("refund after 30 days")
    assert say["standing-rate"].startswith("Pays @octocat 10 test USDC for each pull request of theirs, up to 100 test USDC in all,")
    assert "attestor repository" in say["private-attested"]
    # a sentence follows its comment: change the comment and the sentence changes with it
    other = terms_templates.Template("x", "/knos fund 7.5 checks: none days 3", "an issue")
    assert terms_templates.sentence(other) == "Pays 7.5 test USDC when a maintainer merges a pull request that closes the issue; refund after 3 days"
    with pytest.raises(ValueError, match="does not fund anything"):
        terms_templates.command(terms_templates.Template("y", "/knos take", "an issue"))


def test_knos_terms_list_and_show():
    from typer.testing import CliRunner
    from knos.cli import app
    run = CliRunner()
    listed = run.invoke(app, ["terms", "list"])
    assert listed.exit_code == 0 and all(f"{n}\n    {terms_templates.sentence(t)}" in listed.output for n, t in terms_templates.TEMPLATES.items())
    shown = run.invoke(app, ["terms", "show", "bugfix"])
    held = terms_templates.export("bugfix")
    assert shown.exit_code == 0 and all(held[k] in shown.output for k in ("comment", "terms_json", "terms_hash", "sentence"))
    assert run.invoke(app, ["terms", "show", "bugfix", "--json"]).output == terms_templates.dumps("bugfix")
    missing = run.invoke(app, ["terms", "show", "nope"])
    assert missing.exit_code == 1 and "there is no template named nope: the templates are bugfix, feature-blackbox" in missing.output
    said = run.invoke(app, ["init", "--pr", "not a repo"])
    assert said.exit_code == 1 and "owner/repo" in said.output


def test_the_install_page_of_the_docs_counts_its_steps():
    text = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    part = text.split("## Paid work in a repository: install by pull request")[1].split("\n## ")[0]
    assert [int(n) for n in re.findall(r"^(\d)\. \*\*", part, re.M)] == [1, 2, 3, 4, 5, 6, 7] and "three steps on devnet, seven with real money" in part
    assert "There is no mainnet deployment" in part and str(len(init.install_link("acme/widgets", SHORT.read_text(encoding="utf-8")))) in part.replace(",", "")
    assert f"{len(SHORT.read_text(encoding='utf-8').splitlines())} lines" in part
    for t in terms_templates.TEMPLATES.values():
        assert f"`{t.name}`" in part and t.comment in part
