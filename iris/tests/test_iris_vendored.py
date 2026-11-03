"""The Knos modules in iris/python/knos/ are byte for byte the ones in src/knos, exactly the list in VENDORED.txt, and
enough on their own: knos_iris imports with iris/python alone on the path.

    python iris/tests/test_iris_vendored.py [result file]
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / "iris" / "python"
PROBE = ("import sys; import knos_iris.bridge, knos_iris.referee; from knos.settle.v2 import pay; pay.version_ix(); "
         "print(sorted(m.__file__ for k, m in sys.modules.items() if k == 'knos' or k.startswith('knos.')))")


def main(argv) -> int:
    lines: list[str] = []
    fails = 0
    listed = set(re.findall(r"(?m)^(knos/\S+\.(?:py|json))\s", (PY / "VENDORED.txt").read_text(encoding="utf-8")))
    have = {p.relative_to(PY).as_posix() for p in (PY / "knos").rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}
    ok = listed == have and bool(have)
    fails += not ok
    lines.append(f"{'ok  ' if ok else 'FAIL'} VENDORED.txt lists the {len(have)} files in iris/python/knos/"
                 + ("" if ok else f" (unlisted {sorted(have - listed)}, missing {sorted(listed - have)})"))
    for rel in sorted(have):
        src = ROOT / "src" / rel
        same = src.is_file() and src.read_bytes() == (PY / rel).read_bytes()
        fails += not same
        lines.append(f"{'ok  ' if same else 'FAIL'} {rel} {'equals' if same else 'differs from'} src/{rel}")
    p = subprocess.run([sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(PY)!r}); {PROBE}"],
                       capture_output=True, text=True, timeout=120)
    loaded = ast.literal_eval(p.stdout.strip() or "[]")
    alone = p.returncode == 0 and bool(loaded) and all(Path(f).resolve().is_relative_to(PY) for f in loaded)
    fails += not alone
    lines.append(f"{'ok  ' if alone else 'FAIL'} knos_iris imports with iris/python alone on the path"
                 + ("" if alone else f": {(p.stderr or loaded).strip().splitlines()[-1:]}"))
    lines.append("PASS test_iris_vendored" if not fails else f"FAIL test_iris_vendored: {fails} check(s) failed")
    print("\n".join(lines))
    if len(argv) > 0:
        with Path(argv[0]).open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
