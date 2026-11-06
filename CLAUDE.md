# Knos for contributors

Knos pays agents only when the test passes.
Solana devnet only; test units, never real money.

## Layout
- `src/knos/`: the package (CLI `knos`, the knos_pay client, `ready.py` Ready to fund, `idt.py` intent tax).
- `apps/wanted/`: the app on knos.onrender.com (`knos_wanted/server.py`, `valley.py` projects, `static/`).
- `web/`: the Pages site (drexthealpha.github.io/Knos), built by `scripts/build_site.sh`.
- `bench/idt/` + `scripts/idt_bench.py` + `docs/idt/`: the IDT benchmark (measured, never estimated).
- `tests/`, `apps/wanted/tests/`, `tests/web/*.mjs`: pytest and the site's headless-Chromium tests.

## Rules
- Never print, commit or pass a secret on a command line; read keys from files or env.
- A change that moves money stays behind the Ready check (`knos.ready.require`).
- Every number shown to a user is measured or read from chain; nothing is estimated or invented.
- Pin GitHub Actions to commits (`scripts/action_pins.json`); a job that signs installs by hash.
- The home page's prose stays within its word budget (`tests/test_site_home.py`): no walls of text.

## Checks
- Quick: `pytest -q tests/test_ready.py tests/test_idt.py apps/wanted/tests/test_valley.py`.
- Lint as CI: `ruff check .`, `mypy`, `vulture src/knos scripts --min-confidence 60`, `python scripts/deadcode.py`.
- The full suite is GitHub CI on the push (`.github/workflows/tests.yml`).
