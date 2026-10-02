"""The public Knos network page: every Knos team on Solana, counted from the chain. Public data only; anyone can run it.

    python scripts/network_stats.py            writes docs/network/index.html and docs/network/data.json

A credential counts as a Knos team only if its name starts with `knos-` AND its `knos.claim.v1` schema matches Knos's
layout byte for byte (the schema account is recomputed from src/knos/team/schemas.py). Anyone can create one, so
counts are not proof of distinct teams, and the page says so. Devnet and mainnet are reported separately.

Per team: live claims, renewals, members, records; and from the credential's recent history, closes (releases, lost
races and sweeps together). GitHub numbers come from GitHub's public API.
"""

from __future__ import annotations

import base64
import html
import json
import os
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from knos.team import rpc, sas, schemas  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402

CLUSTERS = {"devnet": os.environ.get("KNOS_DEVNET_RPC", "https://api.devnet.solana.com"),
            "mainnet": os.environ.get("KNOS_MAINNET_RPC", "https://api.mainnet-beta.solana.com")}
REPO = "drexthealpha/Knos"


def _b58(raw: bytes) -> str:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n, out = int.from_bytes(raw, "big"), ""
    while n:
        n, r = divmod(n, 58)
        out = alphabet[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def credentials(url: str) -> list[tuple[Pubkey, sas.Credential]]:
    cfg = {"encoding": "base64", "commitment": "confirmed",
           "filters": [{"memcmp": {"offset": 0, "bytes": _b58(b"\x00")}},
                       {"memcmp": {"offset": 37, "bytes": _b58(b"knos-")}}]}
    got = rpc.call(url, "getProgramAccounts", [str(sas.PROGRAM_ID), cfg], timeout=60) or []
    out = []
    for item in got:
        try:
            out.append((Pubkey.from_string(item["pubkey"]),
                        sas.parse_credential(base64.b64decode(item["account"]["data"][0]))))
        except (ValueError, KeyError, IndexError):
            continue
    return out


def is_knos_team(url: str, credential: Pubkey) -> bool:
    _, raw = rpc.account_data(url, sas.schema_pda(credential, schemas.CLAIM[0]), timeout=30)
    return raw == schemas.schema_account_bytes(credential, schemas.CLAIM)


def attestations_by_schema(url: str, credential: Pubkey) -> Counter:
    cfg = {"encoding": "base64", "commitment": "confirmed", "dataSlice": {"offset": 65, "length": 32},
           "filters": [{"memcmp": {"offset": 0, "bytes": _b58(b"\x02")}},
                       {"memcmp": {"offset": 33, "bytes": str(credential)}}]}
    got = rpc.call(url, "getProgramAccounts", [str(sas.PROGRAM_ID), cfg], timeout=60) or []
    names = {str(sas.schema_pda(credential, spec[0])): spec[0].split(".")[1] for spec in schemas.ALL}
    return Counter(names.get(str(Pubkey.from_bytes(base64.b64decode(i["account"]["data"][0]))), "other")
                   for i in got)


def closes(url: str, credential: Pubkey, limit: int = 1000) -> int:
    """CloseAttestation instructions in the credential's recent history (every close names the credential)."""
    n = 0
    for s in rpc.call(url, "getSignaturesForAddress", [str(credential), {"limit": limit}], timeout=60) or []:
        if s.get("err"):
            continue
        tx = rpc.call(url, "getTransaction", [s["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 0}],
                      timeout=30)
        if not tx:
            continue
        keys = tx["transaction"]["message"]["accountKeys"]
        for ix in tx["transaction"]["message"]["instructions"]:
            if keys[ix["programIdIndex"]] == str(sas.PROGRAM_ID) and _b58_first_byte(ix["data"]) == 7:
                n += 1
    return n


def first_transaction_date(url: str, credential: Pubkey) -> str | None:
    """The date (YYYY-MM-DD) of the credential's very first transaction on chain (last page of signatures)."""
    before = None
    oldest = None
    while True:
        params: dict = {"limit": 1000}
        if before:
            params["before"] = before
        sigs = rpc.call(url, "getSignaturesForAddress", [str(credential), params], timeout=60) or []
        if not sigs:
            break
        oldest = sigs[-1]
        if len(sigs) < 1000:
            break
        before = oldest["signature"]
    if oldest and oldest.get("blockTime"):
        return time.strftime("%Y-%m-%d", time.gmtime(oldest["blockTime"]))
    return None


def _b58_first_byte(data: str) -> int | None:
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = 0
    for ch in data:
        n = n * 58 + alphabet.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    raw = b"\0" * (len(data) - len(data.lstrip("1"))) + raw
    return raw[0] if raw else None


def cluster_stats(name: str, url: str, with_history: bool = True) -> dict:
    out = {"cluster": name, "teams": 0, "claims_live": 0, "renewals_live": 0, "members": 0, "records": 0,
           "closes_recent": 0, "rejected_lookalikes": 0, "first_seen": "", "error": ""}
    try:
        creds = credentials(url)
    except Exception as e:  # noqa: BLE001 - a public RPC refusing getProgramAccounts is reported, not hidden
        out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        return out
    first_dates = []
    for addr, _cred in creds:
        try:
            if not is_knos_team(url, addr):
                out["rejected_lookalikes"] += 1
                continue
            c = attestations_by_schema(url, addr)
            out["teams"] += 1
            out["claims_live"] += c.get("claim", 0)
            out["renewals_live"] += c.get("renew", 0)
            out["members"] += c.get("member", 0)
            out["records"] += c.get("record", 0)
            if with_history:
                out["closes_recent"] += closes(url, addr)
                d = first_transaction_date(url, addr)
                if d:
                    first_dates.append(d)
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    if first_dates:
        first_dates.sort()
        out["first_seen"] = first_dates[0] if first_dates[0] == first_dates[-1] else f"{first_dates[0]} .. {first_dates[-1]}"
    return out


def github() -> dict:
    def get(path):
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}{path}",
                                     headers={"User-Agent": "knos-network", "Accept": "application/vnd.github+json",
                                              **({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}
                                                 if os.environ.get("GITHUB_TOKEN") else {})})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            return json.loads(r.read())
    try:
        repo = get("")
        contributors = get("/contributors?per_page=100")
        return {"stars": repo.get("stargazers_count", 0), "forks": repo.get("forks_count", 0),
                "open_issues": repo.get("open_issues_count", 0), "contributors": len(contributors)}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}"}


def render(data: dict) -> str:
    def row(c):
        if c["error"] and not c["teams"]:
            return f"<tr><td>{c['cluster']}</td><td colspan=8>not readable now: {html.escape(c['error'])}</td></tr>"
        return ("<tr>" + "".join(f"<td>{html.escape(str(c.get(k, '')))}</td>" for k in
                                 ("cluster", "teams", "members", "claims_live", "renewals_live", "records",
                                  "closes_recent", "first_seen")) + "</tr>")
    gh = data["github"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Knos network</title>
<style>
:root{{--bg:#fbfaf7;--ink:#1d1d1b;--dim:#6b6a66;--line:#e2dfd8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141413;--ink:#ecebe6;--dim:#9b9a95;--line:#2c2b29}}}}
body{{background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,sans-serif;margin:0;padding:24px 16px}}
main{{max-width:880px;margin:auto}} table{{border-collapse:collapse;width:100%;margin:16px 0}}
td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}} .dim{{color:var(--dim)}}
.wrap{{overflow-x:auto}}
</style></head><body><main>
<h1>Knos network</h1>
<p>Every Knos team is a public Solana Attestation Service credential. These numbers are read from the chain by
<code>scripts/network_stats.py</code>; run it yourself to check them.</p>
<p class="dim">Updated {html.escape(data['updated'])}. Anyone can create a credential named <code>knos-*</code>
with the Knos schema, so counts are not proof of distinct teams. Devnet is a test network.</p>
<div class="wrap"><table><tr><th>cluster</th><th>teams</th><th>members</th><th>live claims</th><th>live renewals</th>
<th>records</th><th>recent closes</th><th>first seen</th></tr>
{''.join(row(c) for c in data['clusters'])}</table></div>
<p class="dim">Recent closes are CloseAttestation instructions in each team's last 1,000 transactions: released
claims, claims that lost a race, and sweeps of lapsed claims, together. Look-alike credentials whose claim schema is
not Knos's, byte for byte, are left out
({sum(c.get('rejected_lookalikes', 0) for c in data['clusters'])} this run).</p>
<h2>The project</h2>
<p>GitHub: {gh.get('stars', '?')} stars, {gh.get('forks', '?')} forks, {gh.get('contributors', '?')} contributors,
{gh.get('open_issues', '?')} open issues and pull requests.</p>
</main></body></html>
"""


def main() -> int:
    data = {"updated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "clusters": [cluster_stats(n, u) for n, u in CLUSTERS.items()],
            "github": github()}
    out = ROOT / "docs" / "network"
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (out / "index.html").write_text(render(data), encoding="utf-8")
    print(json.dumps(data, indent=1))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
