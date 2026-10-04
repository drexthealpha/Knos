"""Real GitHub tokens, kept with the key set of their day and verified again by the verifier's own bytes.

    python scripts/replay_tokens.py --capture OWNER/REPO [--since 2026-10-01] --out tokens.jsonl
    python scripts/replay_tokens.py --corpus tokens.jsonl [--rpc URL | --oidc PATH.so]
    python scripts/replay_tokens.py fund.txt proof.txt claim.txt [--oidc PATH.so] [--pay PATH.so] [--jwks FILE]

--capture reads a public repository's issue comments (the `knos-fund:` / `knos-proof:` / `knos-claim:` / `knos-key:`
lines a workflow posts for the relay) and appends each token to a JSON Lines file, one token a line:

    {"token": "<the JWT>", "jwks": {"keys": [...]}, "terms": "<json>", "kind": "fund", "source": "<the issue>", "posted": "<when>"}

`jwks` is the issuer's key set fetched at capture (for a token whose key the issuer no longer publishes: the set
committed on 2 Oct 2026, tests/fixtures). A token is kept only when a key of that set signed it, which is checked here
with plain arithmetic, so every line of the file is a token its issuer signed. `terms` is there for a fund token whose
comment carried its `knos-terms:` line. A GitHub token is public once posted and expires five minutes after it was
issued; what the file adds is the key set of the day. Set GH_TOKEN (any token; public reads) or GitHub allows 60
requests an hour.

--corpus verifies every token of such a file on chain code: knos-oidc's bytes (read from the cluster with --rpc, the
default; or a build with --oidc) are loaded into LiteSVM, the clock is set to the token's `iat`, the key that signed
it is registered as the build allows with no attestation, and the token is written and stepped by the same relay code
the public worker runs. A token counts when the verifier's own account says VERIFIED with the token's issuer and
expiry. It prints how many, by repository and by key, and exits 0 only if every token verified.

The third form is the first deployment's: each file holds one token, and it is handed to the first deployment's relay
against builds of `programs/` (tests/test_settle_relay.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from knos import chain  # noqa: E402
from knos.proof import ghrelay  # noqa: E402
from knos.settle import oidc, pay, relay  # noqa: E402

FIXTURES = {oidc.GITHUB: ROOT / "tests" / "fixtures" / "github_jwks_2026-10-02.json", oidc.GITLAB: ROOT / "tests" / "fixtures" / "gitlab_jwks_2026-10-02.json"}
RENEW = 29 * 86_400     # a key registered here verifies for 30 days: a file that spans more gets a new chain, as devnet gets a Refresh


# ---- capture ------------------------------------------------------------------------------------------------------------
def _signer(jwt: str, docs: list[dict]) -> dict | None:
    """The first of these key sets that holds the key the token's header names, if that key signed the token."""
    from knos.settle.v2 import relay as relay2
    kid = relay.header_of(jwt).get("kid")
    for doc in docs:
        n = dict(oidc.jwks_keys(doc)).get(kid)
        if n is not None and relay2.signed(jwt, n):
            return doc
    return None


def capture(repo: str, since: str = "", getter: Callable | None = None, jwks_of: Callable[[int], dict] | None = None,
            say: Callable[[str], None] = print) -> list[dict]:
    """Every token in the repository's issue comments since `since` that a key of its issuer signed, as the lines of a
    token file, oldest first. What is left out is said: a comment's text is anyone's, and a token nobody signed is not
    evidence of anything."""
    today: dict[int, dict] = {}
    rows, dropped, jwks_of = [], 0, jwks_of or relay.fetch_jwks
    for f in ghrelay.found(repo, since, getter or ghrelay._api):
        kind, number, jwt, _who = f
        try:
            c = relay.claims_of(jwt)
            issuer = next(i for i, url in oidc.ISSUERS.items() if c.get("iss") == url)
            if issuer not in today:
                today[issuer] = jwks_of(issuer)
            doc = _signer(jwt, [today[issuer], json.loads(FIXTURES[issuer].read_text(encoding="utf-8"))])
        except (StopIteration, ValueError, LookupError, TypeError, AttributeError):
            doc = None
        if doc is None:
            dropped += 1
            continue
        posted = datetime.fromtimestamp(f.created, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if f.created else ""
        rows.append({"token": jwt, "jwks": doc, **({"terms": f.terms.decode()} if f.terms else {}), "kind": kind,
                     "source": f"https://github.com/{repo}/issues/{number}", "posted": posted, "iat": int(c.get("iat", 0))})
    rows.sort(key=lambda r: r["iat"])
    say(f"{repo}: {len(rows)} tokens a published key signed" + (f"; {dropped} left out (no key of the issuer's set signed them)" if dropped else ""))
    return [{k: v for k, v in r.items() if k != "iat"} for r in rows]


def append(path: Path, rows: list[dict]) -> int:
    """Adds the rows whose token the file does not hold yet; how many were added."""
    have = {json.loads(line)["token"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()} if path.exists() else set()
    new = [r for r in rows if r["token"] not in have and not have.add(r["token"])]
    with path.open("a", encoding="utf-8") as out:
        out.writelines(json.dumps(r, separators=(",", ":")) + "\n" for r in new)
    return len(new)


# ---- verify -------------------------------------------------------------------------------------------------------------
def verify(tokens: list, elfs: dict[str, bytes], say: Callable[[str], None] = print) -> tuple[int, Counter, Counter]:
    """Verifies each captured token on a chain that runs `elfs`, with the clock at the token's `iat`. Returns how many
    verified, and those counted by repository and by key. Each token that did not is said, with why."""
    import drills
    from knos.settle.v2 import oidc as oidc2
    from knos.settle.v2 import relay as relay2
    by_repo, by_key, good, svm, born = Counter(), Counter(), 0, None, 0
    for t in sorted(tokens, key=lambda t: t.iat):
        where = f"{t.kind or 'token'} of {t.c.get('repository') or t.c.get('project_path') or '?'}, issued {drills.day(t.iat)}" + (f" ({t.source})" if t.source else "")
        if svm is None or t.iat - born >= RENEW:
            svm, born = drills.Svm(elfs, t.iat), t.iat
        svm.clock(t.iat)
        if t.issuer is None or t.n is None:
            say(f"FAIL {where}: the key {t.kid[:16]!r} its header names is not in the key set captured with it")
            continue
        if not relay2.signed(t.jwt, t.n):
            say(f"FAIL {where}: the key its header names did not sign it")
            continue
        if svm.key(t.issuer, t.n) is None and (why := svm.register(t.issuer, t.n)) is not None:
            say(f"FAIL {where}: its key (sha256 {oidc2.key_hash(t.n).hex()[:16]}...) is not one this build takes with no attestation ({why})")
            continue
        r = relay2.verify_only(svm, svm.payer, t.jwt, {t.issuer: t.jwks}, now=svm.now())
        tok = oidc2.read_token(svm.account(oidc2.token_pda(svm.payer.pubkey(), oidc2.token_id(t.jwt)))) if r.get("ok") else None
        if tok is None or not tok.verified or tok.issuer != t.issuer or tok.exp != int(t.c["exp"]) or tok.key != oidc2.key_pda(t.issuer, t.n):
            say(f"FAIL {where}: {r.get('why') or 'the relay said verified, and the token account does not'}")
            continue
        svm.send([oidc2.close_ix(svm.payer.pubkey(), oidc2.token_id(t.jwt))])
        good += 1
        by_repo[str(t.c.get("repository") or t.c.get("project_path") or "?")] += 1
        by_key[f"{oidc2.ISSUERS[t.issuer].split('//')[1].split('/')[0]} {t.n.bit_length()}-bit key {t.kid[:12]} (sha256 {oidc2.key_hash(t.n).hex()[:12]}...)"] += 1
    return good, by_repo, by_key


def report(n: int, good: int, by_repo: Counter, by_key: Counter, say: Callable[[str], None] = print) -> None:
    say(f"{good} of {n} tokens verified on chain code, each with the clock at its issue time and the key set of its day")
    for title, counts in (("by repository", by_repo), ("by key", by_key)):
        say(f"  {title}: " + ("; ".join(f"{name} {count}" for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))) or "none"))


# ---- the first deployment ---------------------------------------------------------------------------------------------
def replay(tokens: list[str], oidc_so: Path, pay_so: Path, jwks: dict | None = None, say=print) -> bool:
    from _settle import Chain, ChainLedger
    chain_ = Chain(pay_build=str(Path(pay_so).resolve()), oidc_build=str(Path(oidc_so).resolve()))
    ledger = ChainLedger(chain_)
    assert chain_.send([pay.init_faucet_ix(chain_.payer.pubkey())]), chain_.err
    good = True
    for jwt in tokens:
        claims = relay.claims_of(jwt)
        aud = claims["aud"] if isinstance(claims["aud"], str) else claims["aud"][0]
        clock = chain_.svm.get_clock()
        clock.unix_timestamp = max(int(claims.get("iat", 0)) + 5, int(clock.unix_timestamp) + 1)
        chain_.svm.set_clock(clock)
        r = relay.submit(ledger, chain_.payer, jwt, jwks, now=chain_.now())
        say(f"{'ok  ' if r.get('ok') else 'FAIL'} {aud[:70]}")
        say(f"     workflow {claims.get('job_workflow_ref')} at {claims.get('job_workflow_sha')}; "
            f"runner {claims.get('runner_environment')}; token {len(jwt)} bytes")
        if r.get("ok"):
            say(f"     {ghrelay.note(r)}")
        else:
            good = False
            say(f"     refused: {r.get('why')}")
    return good


def main(argv=None, call: Callable = chain.call, getter: Callable | None = None, say: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tokens", nargs="*", type=Path, help="the first deployment's form: files of one token each")
    ap.add_argument("--capture", metavar="OWNER/REPO", help="read this public repository's token comments into --out")
    ap.add_argument("--since", default="", help="--capture: only comments posted at or after this day (2026-10-01)")
    ap.add_argument("--out", type=Path, help="--capture: the token file to append to")
    ap.add_argument("--corpus", type=Path, help="verify every token of this file")
    ap.add_argument("--rpc", default="https://api.devnet.solana.com", help="--corpus: the cluster knos-oidc's bytes are read from")
    ap.add_argument("--oidc", type=Path, help="--corpus: a build of knos-oidc to verify with, in place of the deployed bytes")
    ap.add_argument("--pay", type=Path, default=ROOT / "programs" / "target" / "deploy" / "knos_pay.so")
    ap.add_argument("--jwks", type=Path, help="the first deployment's form: GitHub's JWKS as a file (default: fetched from GitHub)")
    a = ap.parse_args(argv)
    if a.capture:
        if not a.out:
            ap.error("--capture needs --out FILE")
        added = append(a.out, capture(a.capture, a.since, getter, say=say))
        say(f"{added} new tokens appended to {a.out}")
        return 0
    if a.corpus:
        import drills
        tokens = drills.corpus(a.corpus)
        if a.oidc:
            elfs = {"knos_oidc": a.oidc.read_bytes()}
            say(f"knos_oidc: the build {a.oidc}, sha256 with trailing zeros trimmed {drills.mc.elf_hash(elfs['knos_oidc'])}")
        else:
            program = next(p for p in drills.fetch(a.rpc, call) if p.name == "knos_oidc")
            elfs = {"knos_oidc": program.elf}
            say(f"knos_oidc {program.address} as {a.rpc} holds it, sha256 with trailing zeros trimmed {program.sha256}")
        good, by_repo, by_key = verify(tokens, elfs, say)
        report(len(tokens), good, by_repo, by_key, say)
        return 0 if tokens and good == len(tokens) else 1
    if not a.tokens:
        ap.error("give --capture OWNER/REPO --out FILE, --corpus FILE, or the first deployment's token files")
    jwks = {oidc.GITHUB: json.loads(a.jwks.read_text(encoding="utf-8"))} if a.jwks else None
    tokens = []
    for f in a.tokens:
        text = f.read_text(encoding="utf-8")
        found = ghrelay.TOKEN.search(text)
        tokens.append(found.group(2) if found else text.strip())
    return 0 if replay(tokens, a.oidc or ROOT / "programs" / "target" / "deploy" / "knos_oidc.so", a.pay, jwks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
