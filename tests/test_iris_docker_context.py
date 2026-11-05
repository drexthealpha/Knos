"""iris/Dockerfile builds from the repository root with iris/Dockerfile.dockerignore, which shuts out everything it does
not name. Every path a COPY reads from the build context must be named there, or `docker compose up --build` fails
with "not found" (it did on 5 Nov 2026 for web/brand/tokens.css and web/fonts)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_every_copied_path_is_let_into_the_build_context():
    docker = (ROOT / "iris/Dockerfile").read_text(encoding="utf-8")
    allowed = [ln[1:].strip() for ln in (ROOT / "iris/Dockerfile.dockerignore").read_text(encoding="utf-8").splitlines() if ln.startswith("!")]
    sources = []
    for ln in docker.splitlines():
        m = re.match(r"\s*COPY\s+(.*)", ln)
        if not m or "--from=" in ln:
            continue
        parts = [p for p in m.group(1).split() if not p.startswith("--")]
        sources += parts[:-1]
    assert sources, "no COPY found"
    for s in sources:
        assert any(s == a or s.startswith(a.rstrip("/") + "/") for a in allowed), (s, allowed)
        assert (ROOT / s).exists(), s
