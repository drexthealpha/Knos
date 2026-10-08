"""scripts/public_face.py: every description of Knos that leaves the repository is the one sentence of docs/facts.json,
and what a logged-out reader is served is printed with the command that corrects it. No network: the fetch is a table."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SENTENCE = "The neutral meter for AI agent work: neither side keeps the count."
FACES = ("docs/facts.json", "pyproject.toml", "server.json", "gemini-extension.json", "plugin/.claude-plugin/plugin.json",
         "plugin/.codex-plugin/plugin.json", ".claude-plugin/marketplace.json", "sdk/settle/package.json", "sdk/settle/README.md", "action.yml", "web/index.html", "README.md")


def _tool():
    spec = importlib.util.spec_from_file_location("public_face_tool", ROOT / "scripts" / "public_face.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _copy(tmp_path: Path) -> Path:
    for rel in FACES:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, tmp_path / rel)
    return tmp_path


def _sub(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def test_this_tree_says_the_one_sentence_everywhere_it_describes_itself():
    pf = _tool()
    assert pf.sentence() == SENTENCE and pf.title(SENTENCE) == "Knos. " + SENTENCE
    assert pf.problems() == []
    said: list[str] = []
    assert pf.main(["--check"], say=said.append) == 0 and said == [f"every description says: {SENTENCE}"]
    assert re.search(r'(?m)^description = "([^"]*)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8")).group(1) == SENTENCE
    for rel in ("server.json", "gemini-extension.json"):
        assert json.loads((ROOT / rel).read_text(encoding="utf-8"))["description"] == SENTENCE
    assert len(SENTENCE) <= 100                                           # the MCP registry refuses a longer description
    for rel in ("plugin/.claude-plugin/plugin.json", "plugin/.codex-plugin/plugin.json", ".claude-plugin/marketplace.json"):
        assert json.loads((ROOT / rel).read_text(encoding="utf-8"))["description"].startswith(SENTENCE + " ")


def test_any_other_description_of_the_product_fails_the_check_place_by_place(tmp_path):
    pf, root = _tool(), _copy(tmp_path)
    assert pf.problems(root) == []
    _sub(root / "pyproject.toml", SENTENCE, SENTENCE + " And an escrow.")
    _sub(root / "server.json", SENTENCE, "Bounties that pay when the pull request is merged.")
    _sub(root / "plugin" / ".claude-plugin" / "plugin.json", SENTENCE, "A plugin.")
    _sub(root / "action.yml", "description: ", "description: One shared memory for every coding agent. ")
    _sub(root / "web" / "index.html", f"<title>Knos. {SENTENCE}</title>", "<title>Knos: bounties</title>")
    _sub(root / "web" / "index.html", f'<meta property="og:description" content="{SENTENCE}', '<meta property="og:description" content="Escrow for agents.')
    _sub(root / "README.md", f"**{SENTENCE}**", "**Pay agents on merge.**")
    found = pf.problems(root)
    assert [f.split(":")[0] for f in found] == ["server.json", "plugin/.claude-plugin/plugin.json", "pyproject.toml", "action.yml", "web/index.html <title>",
                                                "web/index.html og", "README.md"]
    assert "older product" in found[0] and "does not begin with the sentence" in found[1] and "is not the sentence" in found[2] and "older product" in found[3]
    said: list[str] = []
    assert pf.main(["--check"], say=said.append, root=root) == 1 and said[-1] == "7 description(s) are not the one sentence"


def test_write_puts_the_sentence_back_keeps_what_a_plugin_adds_and_drops_an_older_products_words(tmp_path):
    pf, root = _tool(), _copy(tmp_path)
    _sub(root / "pyproject.toml", SENTENCE, "Bounties that pay when the pull request is merged. An escrow.")
    _sub(root / "gemini-extension.json", SENTENCE, "Something else.")
    _sub(root / "plugin" / ".codex-plugin" / "plugin.json", SENTENCE, "Bounties that pay when merged. Attested by a GitHub-signed workflow run, verified on Solana.")
    before = (root / "server.json").read_bytes()
    assert sorted(pf.write(root)) == ["gemini-extension.json", "plugin/.codex-plugin/plugin.json", "pyproject.toml"]
    assert pf.problems(root) == [] and (root / "server.json").read_bytes() == before
    codex = json.loads((root / "plugin" / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))["description"]
    assert codex.startswith(SENTENCE + " The plugin adds a Stop hook") and "Bounties that pay" not in codex and "Attested by" not in codex
    for rel in ("pyproject.toml", "gemini-extension.json", "plugin/.codex-plugin/plugin.json"):      # nothing but the description moved
        ours, theirs = (ROOT / rel).read_text(encoding="utf-8"), (root / rel).read_text(encoding="utf-8")
        assert ours == theirs, rel
    assert pf.write(root) == []


def test_without_the_source_there_is_no_sentence_to_check_against(tmp_path):
    pf, root = _tool(), _copy(tmp_path)
    (root / "docs" / "facts.json").write_text('{"facts": []}', encoding="utf-8")
    try:
        pf.problems(root)
    except SystemExit as e:
        assert "sentence" in str(e)
    else:
        raise AssertionError("a tree with no source passed")


SERVED = {
    "https://api.github.com/repos/drexthealpha/Knos": {"description": "One local memory every coding agent on your machine shares", "homepage": "",
                                                       "topics": ["mcp", "memory"]},
    "https://pypi.org/pypi/knos/json": {"info": {"version": "0.3.12", "summary": "Bounties that pay when the pull request is merged."}},
    "https://pypi.org/pypi/knos-hermes/json": {"info": {"version": "0.1.0", "summary": "A memory."}},
    "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.drexthealpha/knos": {"servers": [
        {"server": {"name": "io.github.drexthealpha/knos", "version": "0.1.2", "description": "One local memory."},
         "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": False}}},
        {"server": {"name": "io.github.drexthealpha/knos", "version": "0.3.12", "description": "Bounties that pay."},
         "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": True}}}]},
}


def _fetch(table: dict):
    def fetch(url: str):
        if url not in table:
            raise OSError("HTTP 403")
        return table[url]
    return fetch


def test_remote_prints_what_each_place_serves_and_the_exact_command_that_corrects_it():
    pf = _tool()
    said: list[str] = []
    assert pf.main(["--remote"], say=said.append, fetch=_fetch(SERVED)) == 1
    text = "\n".join(said)
    assert "STALE  GitHub About: description: One local memory every coding agent on your machine shares" in text
    assert f'fix: gh repo edit drexthealpha/Knos --description "{SENTENCE}"' in text
    assert "fix: gh repo edit drexthealpha/Knos --homepage https://drexthealpha.github.io/Knos/" in text
    assert "--add-topic ai-agents" in text and "--add-topic mcp" not in text and "--remove-topic memory" in text
    assert "STALE  PyPI: knos 0.3.12: Bounties that pay" in text and "python scripts/release.py publish" in text
    assert "STALE  PyPI: knos-hermes 0.1.0: A memory." in text
    assert "STALE  MCP registry: io.github.drexthealpha/knos 0.3.12: Bounties that pay." in text and "0.1.2" not in text     # only the latest is what a reader gets
    assert "mcp-publisher publish" in text
    assert "STALE  glama.ai: nothing" in text and said[-1] == f"7 of 7 places do not say: {SENTENCE}"


def test_remote_passes_when_every_place_serves_the_sentence():
    pf = _tool()
    good = {
        "https://api.github.com/repos/drexthealpha/Knos": {"description": SENTENCE, "homepage": pf.SITE, "topics": list(pf.TOPICS)},
        "https://pypi.org/pypi/knos/json": {"info": {"version": "0.3.20", "summary": SENTENCE}},
        "https://pypi.org/pypi/knos-hermes/json": {"info": {"version": "0.1.1", "summary": "Renamed: install knos. " + SENTENCE}},
        "https://registry.modelcontextprotocol.io/v0/servers?search=io.github.drexthealpha/knos": {"servers": [
            {"server": {"name": "io.github.drexthealpha/knos", "version": "0.3.20", "description": SENTENCE}}]},
        "https://glama.ai/mcp/servers/drexthealpha/Knos": {"_html": f'<meta content="{SENTENCE} More." name="description"/>'},
    }
    said: list[str] = []
    assert pf.main(["--remote"], say=said.append, fetch=_fetch(good)) == 0 and said[-1] == f"all 7 places say: {SENTENCE}"
    assert all(line.startswith("same  ") for line in said[:-1])
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}", t) for t in pf.TOPICS) and len(pf.TOPICS) <= 20      # GitHub's rules for a topic


def test_glama_is_read_from_its_page_logged_out_because_its_api_asks_for_a_key():
    # the saved head of the listing's page as glama.ai served it: the description is the meta tag, entities decoded
    pf = _tool()
    page = (ROOT / "tests" / "data" / "glama_page.html").read_text(encoding="utf-8")
    old = pf.meta_description(page)
    assert old is not None and old.startswith("One local memory every coding agent on your machine shares") and "don't" in old
    assert pf.meta_description('<meta name="description" content="A &amp; B">') == "A & B"
    assert pf.meta_description('<meta property="og:description" content="x">') is None
    said: list[str] = []
    assert pf.main(["--remote"], say=said.append, fetch=_fetch({"https://glama.ai/mcp/servers/drexthealpha/Knos": {"_html": page}})) == 1
    assert f"STALE  glama.ai: {old}" in said and "glama.ai: nothing" not in "\n".join(said)


def test_a_stale_version_or_a_banned_word_in_a_manifest_or_the_sdk_readme_fails_the_check(tmp_path):
    """A registry shows a manifest's version and description, and npm shows the SDK's README: an older release named
    there, or a word no Knos document uses, is what a reader is served."""
    pf, root = _tool(), _copy(tmp_path)
    want = pf.release(root)
    assert pf.problems(root) == [] and want
    server = json.loads((root / "server.json").read_text(encoding="utf-8"))
    server["packages"][0]["version"] = "0.3.9"
    (root / "server.json").write_text(json.dumps(server, indent=1), encoding="utf-8")
    _sub(root / "gemini-extension.json", f'"version": "{want}"', '"version": "0.3.20"')
    _sub(root / "sdk" / "settle" / "package.json", "JavaScript client", "Trustless JavaScript client")
    readme = root / "sdk" / "settle" / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nInstall `knos-settle-0.3.19.tgz` from /v0.3.19/; it scales to a billion payments.\n", encoding="utf-8")
    found = pf.problems(root)
    assert any(f.startswith("server.json: packages[0].version is 0.3.9") for f in found)
    assert any(f.startswith("gemini-extension.json: version is 0.3.20") for f in found)
    assert any(f.startswith('sdk/settle/package.json: uses "Trustless"') for f in found)
    assert any(f.startswith('sdk/settle/README.md: uses "billion"') for f in found)
    assert [f for f in found if "installs" in f] == [f"sdk/settle/README.md: installs knos-settle-0.3.19, and pyproject.toml is {want}",
                                                     f"sdk/settle/README.md: installs /v0.3.19, and pyproject.toml is {want}"]
