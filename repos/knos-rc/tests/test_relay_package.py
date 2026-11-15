"""knos.settle.v2.relay is a package of parts, one responsibility each, and still answers as the one module it was:
every name of every part is a name of the package, setting a name on the package reaches each part that holds it,
each part imports only the parts above it, and every relative import in it, inside functions too, names a module
that exists."""
from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

from knos.settle.v2 import relay

PACKAGE = Path(relay.__file__).parent
PARTS = [part.__name__.rpartition(".")[2] for part in relay._PARTS]


def test_every_file_of_the_package_is_a_part_and_every_name_of_a_part_is_a_name_of_the_package():
    assert sorted(PARTS) == sorted(p.stem for p in PACKAGE.glob("*.py") if p.stem != "__init__")
    for part in relay._PARTS:
        for name, value in vars(part).items():
            if not name.startswith("__") and name not in ("annotations", "cast", "Any"):
                assert getattr(relay, name) is value, f"{part.__name__}.{name} is not the package's"
    for name in ("submit", "precheck", "verify_only", "version", "forget", "kind_of", "lane", "sweep", "withdraw", "passkey_fund",
                 "passkey_fund_reply", "register_missing", "open_repositories", "transient", "answered", "why_failed", "KINDS",
                 "ATTESTERS", "CLAIM_SHAS", "ROTATE_SHAS", "_KEPT", "_VERSION", "_VERIFIER", "_plan", "_carry", "_handler_of", "time"):
        assert hasattr(relay, name), name


def test_setting_a_name_on_the_package_reaches_every_part_that_holds_it_and_the_undo_restores_it(monkeypatch):
    held = [part for part in relay._PARTS if "_read" in vars(part)]
    assert len(held) > 3
    before = relay._read

    def fake(ledger, addresses):
        return {}

    monkeypatch.setattr(relay, "_read", fake)
    assert all(vars(part)["_read"] is fake for part in held)
    monkeypatch.undo()
    assert relay._read is before and all(vars(part)["_read"] is before for part in held)


def _relative(path: Path) -> list[tuple[int, str | None, list[str]]]:
    return [(node.level, node.module, [a.name for a in node.names])
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.ImportFrom) and node.level]


def test_every_relative_import_in_the_package_names_a_module_that_exists_inside_functions_too():
    """A part is one level deeper than the one-module relay was: `from ... import events` there is `from .... import
    events` here. Run or not, each one resolves."""
    for path in sorted(PACKAGE.glob("*.py")):
        for level, module, names in _relative(path):
            base = importlib.util.resolve_name("." * level + (module or ""), relay.__name__)
            got = importlib.import_module(base)
            for name in names:
                assert hasattr(got, name) or importlib.util.find_spec(f"{base}.{name}"), f"{path.name}: {base}.{name}"
    assert ("from .... import events") in (PACKAGE / "metering.py").read_text(encoding="utf-8")


def test_each_part_imports_only_the_parts_above_it():
    for i, name in enumerate(PARTS):
        for level, module, _names in _relative(PACKAGE / f"{name}.py"):
            if level == 1:
                assert module in PARTS[:i], f"{name} imports {module}, which is not above it"
