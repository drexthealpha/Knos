"""Reachability: which knos modules are imported (statically, at any depth, including imports inside functions) from
the product's entry points. Anything not reached is unused.

Entry points: the console script (knos.cli:main), `python -m knos`, the MCP server (knos mcp, through cli), the public
SDKs (knos.sdk, knos.jobs.api, knos.core), and the repo scripts and examples. CI runs `python scripts/deadcode.py` and
fails if any module is unreached; functions are checked by vulture (scripts/vulture_whitelist.py).
"""
import ast
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ENTRY = ["knos.cli", "knos.__main__", "knos.sdk", "knos.jobs.api", "knos.mcp",
         "knos.core",  # knos.core: the embeddable claims API documented in docs/INTEGRATE.md
         "knos.proof.ghrelay"]  # run by the always-on worker (worker.yml: python -m knos.proof.ghrelay)
SCRIPTS = [p for p in list((ROOT / "scripts").glob("*.py")) + list((ROOT / "examples").glob("*.py"))
           if p.name not in ("deadcode.py", "vulture_whitelist.py")]


def modname(path: Path) -> str:
    rel = path.relative_to(SRC).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


MODULES = {modname(p): p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts}


def resolve(current: str, node: ast.ImportFrom) -> list[str]:
    is_pkg = MODULES.get(current, Path()).name == "__init__.py"
    base = current.split(".") if is_pkg else current.split(".")[:-1]
    if node.level:
        base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
        prefix = ".".join(base + ([node.module] if node.module else []))
    else:
        prefix = node.module or ""
    out = [prefix]
    for a in node.names:
        out.append(f"{prefix}.{a.name}" if prefix else a.name)
    return out


def imports(path: Path, current: str | None) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    got = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                got.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level and current is None:
                continue
            got.update(resolve(current, node) if current else [node.module or ""] +
                       [f"{node.module}.{a.name}" for a in node.names])
    found = set()
    for name in got:
        parts = name.split(".")
        for i in range(len(parts), 0, -1):
            cand = ".".join(parts[:i])
            if cand in MODULES:
                found.add(cand)
                # a package import also runs its __init__ parents
                break
    return found


seen, todo = set(), list(ENTRY)
for s in SCRIPTS:
    todo += list(imports(s, None))
while todo:
    m = todo.pop()
    if m in seen or m not in MODULES:
        continue
    seen.add(m)
    parts = m.split(".")
    for i in range(1, len(parts)):
        todo.append(".".join(parts[:i]))
    todo += list(imports(MODULES[m], m))

unreached = sorted(set(MODULES) - seen)
print(f"modules: {len(MODULES)}; reached from entry points: {len(seen)}; unreached: {len(unreached)}")
for u in unreached:
    print("  UNREACHED", u)
sys.exit(1 if unreached else 0)
