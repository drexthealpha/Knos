"""Check every number and factual claim in the pitch-facing text against devnet, GitHub or a file in the repo.

    python scripts/claims_check.py            # every claim (devnet RPC + `gh api`)
    python scripts/claims_check.py --offline  # file-backed claims only

A claim is (file, regex that must match the text, checker). The pitch-facing sections are README.md's opening (up to
the first `## `), the home page hero (web/index.html, section#view-check), docs/submission/SUBMISSION.md and
docs/submission/pitch_script.md. Every sentence there that contains a digit must be covered by a registered claim
pattern for that file, or the check fails. Exit 1 on any mismatch.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from typing import Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

PROGRAM = "GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq"
VAULT = "4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo"
REPO = "drexthealpha/Knos"
INDEX_TAG = "index-2026-10-02"
RPC = os.environ.get("KNOS_SOLANA_RPC", "https://api.devnet.solana.com")

README = "README.md"
HOME = "web/index.html"
SUB = "docs/submission/SUBMISSION.md"
PITCH = "docs/submission/pitch_script.md"
PITCH_SENTENCE = "AI agent work gets paid only when GitHub's own signature, checked by Solana, proves it passed."


def read(path: str) -> str:
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


# ---- pitch-facing sections ----------------------------------------------------------------------------------------


def section(path: str) -> str:
    text = read(path)
    if path == README:
        return text.split("\n## ", 1)[0]
    if path == HOME:
        m = re.search(r'<section id="view-check".*?</section>', text, re.S)
        body = re.sub(r"<[^>]+>", " ", m.group(0) if m else "")
        return html.unescape(body)
    return text


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n|\n(?=#)|\n(?=- )", text):
        para = " ".join(para.split())
        out += [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z*\[`(])", para) if s]
    return out


# ---- checkers: each returns (ok, detail) --------------------------------------------------------------------------


def _rpc(method: str, params: list) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["result"]


def _account(addr: str) -> dict | None:
    return _rpc("getAccountInfo", [addr, {"encoding": "base64", "commitment": "confirmed"}])["value"]


def program_executable() -> tuple[bool, str]:
    v = _account(PROGRAM)
    ok = bool(v and v["executable"])
    return ok, f"{PROGRAM} executable={bool(v and v['executable'])}"


def _config() -> dict:
    from solders.pubkey import Pubkey

    from knos.jobs.sol import parse_config
    pda = Pubkey.find_program_address([b"config2"], Pubkey.from_string(PROGRAM))[0]
    v = _account(str(pda))
    return parse_config(base64.b64decode(v["data"][0]))


def fee_250_bps() -> tuple[bool, str]:
    cfg = _config()
    return cfg["fee_bps"] == 250 and cfg["min_fee"] == 50_000, f"config2 fee_bps={cfg['fee_bps']} min_fee={cfg['min_fee']}"


def authority_is_vault() -> tuple[bool, str]:
    from solders.pubkey import Pubkey
    loader = Pubkey.from_string("BPFLoaderUpgradeab1e11111111111111111111111")
    pd = Pubkey.find_program_address([bytes(Pubkey.from_string(PROGRAM))], loader)[0]
    v = _account(str(pd))
    raw = base64.b64decode(v["data"][0])
    auth = str(Pubkey.from_bytes(raw[13:45])) if raw[12] == 1 else None
    return auth == VAULT, f"upgrade authority {auth}"


def _gh(path: str) -> dict:
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30, check=True).stdout
    return json.loads(out)


def repo_public() -> tuple[bool, str]:
    r = _gh(f"repos/{REPO}")
    return r.get("full_name", "").lower() == REPO.lower() and not r.get("private"), f"repo {r.get('full_name')}"


def index_release() -> tuple[bool, str]:
    r = _gh(f"repos/{REPO}/releases/tags/{INDEX_TAG}")
    names = [a["name"] for a in r.get("assets", [])]
    return "index.json" in names, f"release {INDEX_TAG} assets {names}"


def bench_18_2() -> tuple[bool, str]:
    s = json.loads(read("docs/bench.json"))["market"]["sentence"]
    return "**55 (18.2%) had a failing check" in s, "docs/bench.json market: 55 (18.2%) failed"


def tamper_counts() -> tuple[bool, str]:
    t = read("docs/TAMPER.md")
    return "CI green fooled 16/20, Knos fooled 1/20" in t, "docs/TAMPER.md: CI green 16/20, Knos 1/20"


def mainnet_cap_500() -> tuple[bool, str]:
    t = read("src/knos/jobs/net.py")
    return "MAINNET_CAP_UNITS = 500 * 1_000_000" in t, "src/knos/jobs/net.py MAINNET_CAP_UNITS = 500 USDC"


def index_every_6h() -> tuple[bool, str]:
    t = read(".github/workflows/index.yml")
    return '"17 */6 * * *"' in t, "index.yml cron 17 */6 * * *"


def plans_labelled() -> tuple[bool, str]:
    t = read(PITCH)
    ok = "## The next 12 months (plans, not shipped)" in t and "These are plans." in t
    return ok, "pitch 12-month section is labelled as plans"


def pitch_sentence() -> tuple[bool, str]:
    return PITCH_SENTENCE in read(PITCH), "pitch sentence present"


def cited(url: str) -> Callable[[], tuple[bool, str]]:
    """An outside number: the claim must carry its source link in the same sentence (checked by the regex)."""
    return lambda: (True, f"outside source, cited: {url}")


@dataclass
class Claim:
    file: str
    pattern: str
    check: Callable[[], tuple[bool, str]]
    online: bool = False


CLAIMS = [
    # README opening
    Claim(README, r"Knos takes 2\.5% \(at least 0\.05 USDC\), only when\s+the agent is paid", fee_250_bps, True),
    Claim(README, r"about 1\.8M marked pull requests in the week to 27 Sep\s+\(\[amplifying\.ai tracker\]"
                  r"\(https://amplifying\.ai/coding-agents/trends\)\)", cited("amplifying.ai")),
    Claim(README, r"567 Claude Code PRs, 54\.9% were\s+merged without changes requested \(\[arXiv 2509\.14745\]"
                  r"\(https://arxiv\.org/abs/2509\.14745\)\)", cited("arXiv 2509.14745")),
    Claim(README, r"18\.2% of agent PRs that\s+say \"tests pass\" had failing CI at that commit", bench_18_2),
    Claim(README, r"Archestra's bounty issues drew 15–42 PRs each\s+\(\[example\]"
                  r"\(https://github\.com/archestra-ai/archestra/issues/1301\)\)",
          cited("github.com/archestra-ai/archestra/issues/1301")),
    Claim(README, r"capped at\s+500 USDC per job until an external audit", mainnet_cap_500),
    # home page hero
    Claim(HOME, r"rebuilt every 6 hours, its Merkle root attested on Solana devnet", index_every_6h),
    Claim(HOME, r"Agent PR Index", index_release, True),
    # submission
    Claim(SUB, r"Knos takes 2\.5% \(at least 0\.05 USDC\)", fee_250_bps, True),
    Claim(SUB, r"The escrow program is `GwmbMFvyHHwHug5em9dv26oXz2zTgXKGsNdrBxPayRPq`", program_executable, True),
    Claim(SUB, r"upgrade authority is the Squads vault `4G3cznCnwCUPBCZwzKiLupjdgB5pSoCcGWNGuFv4TYFo`",
          authority_is_vault, True),
    Claim(SUB, r"capped at 500 USDC per job until an external audit", mainnet_cap_500),
    Claim(SUB, r"github\.com/drexthealpha/Knos", repo_public, True),
    # pitch script
    Claim(PITCH, re.escape(PITCH_SENTENCE), pitch_sentence),
    Claim(PITCH, r"18\.2% of agent\s+PRs that say tests pass had failing CI", bench_18_2),
    Claim(PITCH, r"CI green fooled 16/20, Knos fooled 1/20", tamper_counts),
    Claim(PITCH, r"The fee is 2\.5%", fee_250_bps, True),
    Claim(PITCH, r"The next 12 months \(plans, not shipped\)", plans_labelled),
    Claim(PITCH, r"Bring in an outside signer and a 24 h time lock on the upgrade multisig", plans_labelled),
]


def uncovered(path: str) -> list[str]:
    pats = [re.compile(c.pattern) for c in CLAIMS if c.file == path]
    flat = [re.compile(" ".join(c.pattern.replace(r"\s+", " ").split())) for c in CLAIMS if c.file == path]
    bad = []
    for s in sentences(section(path)):
        if re.search(r"\d", s) and not any(p.search(s) for p in pats + flat):
            bad.append(s)
    return bad


def main(argv: list[str] | None = None) -> int:
    offline = "--offline" in (argv if argv is not None else sys.argv[1:])
    fails = 0
    for path in (README, HOME, SUB, PITCH):
        for s in uncovered(path):
            fails += 1
            print(f"FAIL  {path}: number-bearing sentence not covered by any claim: {s[:160]}")
    for c in CLAIMS:
        if not re.search(c.pattern, section(c.file)):
            fails += 1
            print(f"FAIL  {c.file}: claim text not found: /{c.pattern[:80]}/")
            continue
        if c.online and offline:
            print(f"SKIP  {c.file}: {c.check.__name__} (online)")
            continue
        try:
            ok, detail = c.check()
        except Exception as why:  # a checker that cannot run is a failure, not a pass
            ok, detail = False, f"{type(why).__name__}: {why}"
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {c.file}: {detail}")
    print(f"{len(CLAIMS)} claims, {fails} failures" + (" (offline)" if offline else ""))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
