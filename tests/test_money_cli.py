"""The commands that carry tokens and move a wallet's own money (`knos relay`, `keys`, `balance`, `fund-wallet`,
`bounty`, `due`, `claim`), on LiteSVM with GitHub faked: what each prints, what it sends, and how it ends."""
from __future__ import annotations

import base64
import json
import time

import pytest

pytest.importorskip("solders.litesvm")

from _pay2 import Chain  # noqa: E402
from _settle import FIX, b64, modulus, signing_key  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
from solders.pubkey import Pubkey  # noqa: E402
from test_relay2 import (JWKS, MAINT, OWNER, REPO, TERMS, USDC, WF_REPO, WF_SHA, Net, bind_jwt, faucet_jwt, fund_jwt,  # noqa: E402
                         issue, pay_jwt, user)

from knos import chain, cli, flow, judge  # noqa: E402
from knos import claim as claiming  # noqa: E402
from knos.proof import ghrelay  # noqa: E402
from knos.settle import oidc as oidc1  # noqa: E402
from knos.settle import pay as pay1  # noqa: E402
from knos.settle import relay as relay1  # noqa: E402
from knos.settle.v2 import oidc, pay  # noqa: E402
from knos.settle.v2 import relay as relay2  # noqa: E402

GITLAB_KEY = {"keys": [{"kty": "RSA", "alg": "RS256", "e": "AQAB", "kid": "gl", "n": b64(oidc.modulus_bytes(modulus(signing_key(4096))))}]}


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    """A chain behind `chain.ledger()`, GitHub's key set as the relays fetch it, a wallet's keypair file, and
    `knos(...)`: run the command line, return (exit code, what it printed)."""
    c = Chain()
    net = Net(c)
    assert c.send([pay.init_faucet_ix(c.payer.pubkey())]), c.err
    monkeypatch.setattr(chain, "ledger", lambda: net)
    monkeypatch.setattr(chain, "key", lambda: c.payer)
    monkeypatch.setattr(relay1, "fetch_jwks", lambda issuer: {oidc.GITHUB: JWKS[oidc.GITHUB], oidc.GITLAB: GITLAB_KEY}[issuer])
    monkeypatch.setattr(relay2, "_KEPT", {})
    monkeypatch.delenv("KNOS_WALLET_KEY", raising=False)
    c.usdc = c.new_mint()
    c.wallet_key, c.wallet_tok = c.wallet(c.usdc, 500 * USDC)
    c.keyfile = tmp_path / "wallet.json"
    c.keyfile.write_text(json.dumps(list(bytes(c.wallet_key))))

    def knos(*args: str) -> tuple[int, str]:
        capsys.readouterr()
        rc = cli.main([str(a) for a in args])
        return rc, capsys.readouterr().out
    return c, net, knos


def github(monkeypatch, answers: dict) -> None:
    """GitHub, as the commands read it (`cli._github` and `judge.github`): a path's answer, or no answer at all."""
    def get(path: str, data=None):
        for prefix, got in answers.items():
            if path.split("?")[0] == prefix:
                return got
        raise OSError(f"HTTP 404 for {path}")

    def stop(path: str):
        try:
            return get(path)
        except OSError as why:
            raise cli.Stop(f"GitHub did not answer for {path}: {why}") from None
    monkeypatch.setattr(cli, "_github", stop)
    monkeypatch.setattr(judge, "github", get)


# -- knos relay ----------------------------------------------------------------------------------------------------------------
def test_relay_carries_one_token_from_a_file_and_prints_the_result_as_json(world, tmp_path, monkeypatch):
    c, net, knos = world
    org, repo = user(), user()
    jwt = faucet_jwt(c, 7, org, repo)
    (tmp_path / "token").write_text(jwt + "\n")
    (tmp_path / "terms").write_bytes(TERMS + b"\n")
    rc, said = knos("relay", "--token-file", tmp_path / "token", "--terms-file", tmp_path / "terms")
    r = json.loads(said)
    job = pay.job_pda(repo, 7, pay.faucet_balance_pda(org))
    assert rc == 0 and r == {"ok": True, "kind": "fund", "sigs": r["sigs"], "job": str(job), "repo_id": repo, "issue": 7, "amount": 5 * USDC, "mode": 0,
                             "faucet": True, "balance": str(pay.faucet_balance_pda(org)), "deadline": c.now() + 14 * 86_400, "note": ghrelay.note(r)}
    assert len(r["sigs"]) == 2 and pay.read_job(c.data(job)).state == "open"       # two v1 transactions (knos.settle.v2.relay)
    rc, said = knos("relay", "--token-file", tmp_path / "token", "--terms-file", tmp_path / "terms")      # again: the chain shows it done
    assert rc == 0 and json.loads(said)["already"] is True
    # the comment that carried a token is as good as the token: its terms line is read from it
    c.warp(60)
    (tmp_path / "comment").write_text(ghrelay.token_comment("fund", faucet_jwt(c, 8, org, repo), TERMS))
    rc, said = knos("relay", "--token-file", tmp_path / "comment")
    assert rc == 0 and json.loads(said)["issue"] == 8
    # a refusal is JSON too, and the command ends 1
    (tmp_path / "token").write_text(pay_jwt(c, repo, 99, user()))
    rc, said = knos("relay", "--token", tmp_path / "token")                # the option's name before 0.3.12 still works
    assert rc == 1 and json.loads(said) == {"ok": False, "kind": "pay", "why": "no bounty is in escrow for this issue (never funded, or already paid or refunded)"}
    # with no token: one pass of the worker, or passes for a while
    ran = []
    # (knos.flow reads the command and keeps the loop of passes itself: tests/test_worker.py runs that loop)
    monkeypatch.setattr(ghrelay, "once", lambda ledger, payer, crank=True: ran.append("once") or [])
    monkeypatch.setattr(flow, "_relay_serve", lambda ghrelay, ledger, payer, seconds, every, clock, sleep, env: ran.append((seconds, every)) or 0)
    assert knos("relay")[0] == 0 and knos("relay", "--serve", "280")[0] == 0 and knos("relay", "--serve", "60", "--every", "1.5")[0] == 0
    assert ran == ["once", (280.0, 3.0), (60.0, 1.5)]


def test_relay_reads_a_key_tokens_issuer_url_from_the_comment_that_carried_it(world, tmp_path, monkeypatch):
    """The comment the rotate workflow posts names the issuer on a `knos-issuer:` line, as the worker reads it
    (ghrelay.tokens): `knos relay --token-file <that comment>` hands the relay the same URL, with no --terms-file."""
    c, net, knos = world
    carried = []
    monkeypatch.setattr(ghrelay, "carry", lambda ledger, payer, jwt, terms=None: carried.append((jwt, terms)) or {"ok": False, "kind": "key", "why": "spied"})
    jwt = "eyJhbGciOiJSUzI1NiJ9.eyJhdWQiOiJrbm9zLW9pZGM6aWtleSJ9.c2lnbmF0dXJl"
    (tmp_path / "key").write_text(ghrelay.token_comment("key", jwt, "https://agent.buildkite.com"), encoding="utf-8")
    assert ghrelay.tokens([{"body": (tmp_path / "key").read_text(), "issue_url": "x/8"}])[0].terms == b"https://agent.buildkite.com"
    assert knos("relay", "--token-file", tmp_path / "key")[0] == 1
    assert carried[-1] == (jwt, b"https://agent.buildkite.com")                 # what the worker would have carried
    # a fund comment's terms line still rides; a key comment's knos-terms line is not its issuer; --terms-file wins
    (tmp_path / "fund").write_text(ghrelay.token_comment("fund", jwt, TERMS), encoding="utf-8")
    knos("relay", "--token-file", tmp_path / "fund")
    assert carried[-1] == (jwt, TERMS)
    (tmp_path / "odd").write_text(f"knos-key: {jwt}\nknos-terms: {TERMS.decode()}\n", encoding="utf-8")
    knos("relay", "--token-file", tmp_path / "odd")
    assert carried[-1] == (jwt, None)
    (tmp_path / "url").write_text("https://issuer.example\n", encoding="utf-8")
    knos("relay", "--token-file", tmp_path / "key", "--terms-file", tmp_path / "url")
    assert carried[-1] == (jwt, b"https://issuer.example")


# -- knos keys -----------------------------------------------------------------------------------------------------------------
def test_keys_lists_what_the_verifier_holds_and_ends_1_when_an_issuers_key_is_missing_unusable_or_expiring(world, monkeypatch):
    c, net, knos = world
    github_key, gitlab_key = oidc.key_pda(oidc.GITHUB, c.github), oidc.key_pda(oidc.GITLAB, modulus(signing_key(4096)))
    rc, said = knos("keys")
    assert rc == 1 and said.splitlines() == [
        f"GitHub  2048 bits  ready  active from 2026-09-21 14:13 UTC  expires 2026-10-21 14:13 UTC  approved  not revoked  published today as k  {github_key}",
        "GitLab's key gl: this signing key is not on chain yet. Send RegisterKey with an attestation from the rotate workflow."], said
    assert c.register(oidc.GITLAB, modulus(signing_key(4096))), c.err
    rc, said = knos("keys")
    assert rc == 0 and said.splitlines()[1].startswith("GitLab  4096 bits  ready  active from 2026-09-21 14:13 UTC") and said.splitlines()[1].endswith(f"published today as gl  {gitlab_key}")
    assert said.splitlines()[2] == "Every key the issuers publish today (2) verifies on chain."
    # a key the issuer no longer publishes is listed and is nobody's problem; a key set that cannot be read is
    monkeypatch.setattr(relay1, "fetch_jwks", lambda issuer: JWKS[issuer])
    rc, said = knos("keys")
    assert rc == 1 and "not in the issuer's key set today" in said.splitlines()[1] and said.splitlines()[2].startswith("GitLab's key set could not be read (KeyError")
    monkeypatch.setattr(relay1, "fetch_jwks", lambda issuer: {oidc.GITHUB: JWKS[oidc.GITHUB], oidc.GITLAB: {"keys": []}}[issuer])
    assert knos("keys")[0] == 0
    # within a week of its expiry, and past it
    c.warp(oidc.KEY_TTL - 7 * 86_400 + 1)
    rc, said = knos("keys")
    assert rc == 1 and said.splitlines()[2] == ("GitHub's key k expires 2026-10-21 14:13 UTC, in less than 7 days. Run the rotate workflow, so that Refresh "
                                                "is sent for it.")
    c.warp(7 * 86_400)
    rc, said = knos("keys")
    assert rc == 1 and said.splitlines()[2].startswith("GitHub's key k: this signing key expired 2026-10-21 14:13 UTC")
    assert c.revoke(oidc.GITHUB, c.github), c.err
    rc, said = knos("keys")
    assert rc == 1 and "  REVOKED  " in said.splitlines()[0] and said.splitlines()[2] == "GitHub's key k: the guardian revoked this signing key. It cannot be used again."


# -- knos balance --------------------------------------------------------------------------------------------------------------
def test_a_wallet_opens_fills_limits_and_empties_a_balance_and_a_comment_spends_it(world, monkeypatch):
    c, net, knos = world
    github(monkeypatch, {"users/octo": {"id": OWNER}, "users/mona": {"id": MAINT}})
    wallet, mint = c.wallet_key.pubkey(), str(c.usdc)
    bal = pay.balance_pda(OWNER, wallet, c.usdc)
    rc, said = knos("balance", "show", "octo")
    assert rc == 0 and said.strip() == f"No balance is set aside for GitHub owner id {OWNER}. A wallet opens one: knos balance open octo --keypair FILE"
    rc, said = knos("balance", "open", "octo", "--mint", mint, "--cap", "50", "--spender", "mona", "--keypair", c.keyfile)
    assert rc == 0 and said.splitlines()[0] == f"Opened balance {bal} for the repositories of GitHub owner id {OWNER}. It is empty.", said
    b = pay.read_balance(c.data(bal))
    assert (b.owner_id, b.authority, b.mint, b.cap_per_job, b.spenders, b.faucet) == (OWNER, wallet, c.usdc, 50 * USDC, (MAINT,), False)
    rc, said = knos("balance", "deposit", "octo", "120.5", "--mint", mint, "--keypair", c.keyfile)
    assert rc == 0 and said.splitlines()[0] == f"120.50 of mint {mint} added to balance {bal}." and c.balance(pay.baltok_pda(bal)) == 120_500_000
    # the environment names the wallet as well as the option does
    monkeypatch.setenv("KNOS_WALLET_KEY", json.dumps(list(bytes(c.wallet_key))))
    rc, said = knos("balance", "set", str(OWNER), "--cap", "0", "--mint", mint)                          # the owner by its id; the spenders stay
    assert rc == 0 and said.splitlines()[0] == f"Balance {bal}: no cap per bounty; spenders besides the owner (GitHub ids): {MAINT}."
    rc, said = knos("balance", "show", "octo")
    assert rc == 0 and said.splitlines() == [
        f"120.50 of mint {mint}  balance {bal}  opened by wallet {wallet}",
        f"  no cap per bounty; spenders besides the owner (GitHub ids): {MAINT}; 0.00 of mint {mint} put into bounties so far; add money by sending that token "
        f"to {pay.baltok_pda(bal)}"], said
    # GitHub signs a maintainer's comment; the relay spends this balance for it
    n = issue()
    r = relay2.submit(net, c.payer, fund_jwt(c, n, 20 * USDC, bal), TERMS, JWKS, now=c.now())
    assert r["ok"] and c.balance(pay.baltok_pda(bal)) == 100_500_000, r
    assert knos("balance", "set", "octo", "--no-spenders", "--cap", "10", "--mint", mint)[0] == 0
    assert (pay.read_balance(c.data(bal)).spenders, pay.read_balance(c.data(bal)).cap_per_job) == ((), 10 * USDC)
    r = relay2.submit(net, c.payer, fund_jwt(c, issue(), 5 * USDC, bal), TERMS, JWKS, now=c.now())
    assert not r["ok"] and "this commenter may not spend that balance" in r["why"]
    # unspent money goes back to the wallet that opened it, part of it or all
    before = c.balance(c.wallet_tok)
    rc, said = knos("balance", "withdraw", "octo", "30", "--mint", mint)
    assert rc == 0 and said.splitlines()[0] == f"30.00 of mint {mint} back in the wallet's token account {c.wallet_tok}." and c.balance(c.wallet_tok) == before + 30 * USDC
    assert knos("balance", "withdraw", "octo", "--mint", mint)[0] == 0 and c.balance(pay.baltok_pda(bal)) == 0 and c.balance(c.wallet_tok) == before + 100_500_000
    # what cannot be done is said in one line, and nothing is sent
    n0 = net.txs
    for args, want in ((("withdraw", "octo"), "The balance holds 0.00 of mint"), (("deposit", "octo", "1000"), "holds less than 1,000.00 of mint"),
                       (("deposit", "octo", "1.0000001"), "An amount is digits with at most 6 decimals"), (("open", "octo"), "This wallet already has a balance for octo"),
                       (("set", "octo"), "Say what to change"), (("deposit", "mona", "1"), "This wallet has no balance for mona in that mint."),
                       (("open", "nobody"), "GitHub did not answer for users/nobody")):
        rc, said = knos("balance", *args, "--mint", mint)
        assert rc == 1 and want in said, (args, said)
    monkeypatch.delenv("KNOS_WALLET_KEY")
    assert "This command signs with your wallet. Pass --keypair FILE" in knos("balance", "open", "mona", "--mint", mint)[1]
    assert "is not a token mint on this cluster" in knos("balance", "open", "mona", "--mint", Keypair().pubkey(), "--keypair", c.keyfile)[1]
    assert "is not a mint address" in knos("balance", "open", "mona", "--mint", "0OIl", "--keypair", c.keyfile)[1] and net.txs == n0
    # a wallet with no SOL is told so, and how to get some on devnet
    poor = Keypair()
    (c.keyfile.parent / "poor.json").write_text(json.dumps(list(bytes(poor))))
    rc, said = knos("balance", "open", "mona", "--mint", mint, "--keypair", c.keyfile.parent / "poor.json")
    assert rc == 1 and said.strip() == f"Solana refused it: this wallet ({poor.pubkey()}) has no SOL for the transaction fee. On devnet: solana airdrop 1 {poor.pubkey()} --url devnet"


# -- knos fund-wallet ----------------------------------------------------------------------------------------------------------
def _installed(wf_repo: str = WF_REPO, sha: str = WF_SHA) -> dict:
    text = f"jobs:\n  settle:\n    uses: {wf_repo}/.github/workflows/prove.yml@{sha}\n    secrets:\n      KNOS_RELAY_KEY: ${{{{ secrets.KNOS_RELAY_KEY }}}}\n"
    return {"content": base64.encodebytes(text.encode()).decode()}


def test_fund_wallet_fixes_the_terms_from_the_repositorys_checks_and_funds_from_the_wallet(world, monkeypatch):
    c, net, knos = world
    head = "f" * 40
    github(monkeypatch, {
        "repos/octo/widgets": {"id": REPO, "default_branch": "main"}, "repos/octo/widgets/contents/.github/workflows/knos.yml": _installed(),
        "repos/octo/widgets/branches/main": {"commit": {"sha": head}, "protection": {}}, "repos/octo/widgets/rules/branches/main": [],
        f"repos/octo/widgets/commits/{head}/check-runs": {"total_count": 1, "check_runs": [{"name": "test", "status": "completed", "conclusion": "success", "app": {"id": 15368}}]},
        f"repos/octo/widgets/commits/{head}/status": {"statuses": []}, "repos/octo/widgets/actions/runs": {"workflow_runs": []}})
    wallet, mint = c.wallet_key.pubkey(), str(c.usdc)
    job = pay.job_pda(REPO, 7, wallet)
    rc, said = knos("fund-wallet", "octo/widgets#7", "20", "--checks", "test", "--mint", mint, "--keypair", c.keyfile)
    assert rc == 0 and said.splitlines()[:-1] == [
        f"20.00 of mint {mint} is in escrow for octo/widgets#7. Job {job}.",
        "  It is paid when a maintainer merges a pull request that closes this issue, if these checks passed at that pull request's last commit: `test` (the checks you named).",
        "  The pull request may not change `.github/**` or `.knos/**`.",
        "  `/knos take` reserves the issue for 7 days.",
        f"  Unpaid after 14 days, it goes back to this wallet. Only a signed run of prove.yml of {WF_REPO} at {WF_SHA[:12]} can pay it."], said
    j = pay.read_job(c.data(job))
    assert (j.state, j.from_balance, j.amount, j.source, j.terms, j.wf_repo_hash, j.wf_sha, j.deadline) == \
        ("open", False, 20 * USDC, wallet, pay.terms_hash(TERMS), pay.wf_repo_hash(WF_REPO), WF_SHA, c.now() + 14 * 86_400)
    assert net.terms_of(job) == TERMS                           # the same bytes a `/knos fund 20 checks: test` comment would fix
    # the proof of the repository's own workflow pays this job like any other on the issue
    payee, to = user(), Keypair().pubkey()
    r = relay2.submit(net, c.payer, pay_jwt(c, REPO, 7, payee, to), None, JWKS, now=c.now())
    assert r["ok"] and c.balance(pay.ata(to, c.usdc)) == 19_500_000, r
    # no checks at all, said out loud; other days; the workflows named by hand
    rc, said = knos("fund-wallet", "octo/widgets#8", "1.5", "--checks", "none", "--days", "30", "--reserve", "0", "--paths", "src/**, docs/*.md",
                    "--workflow", "evil/flows@" + "d" * 40, "--mint", mint, "--keypair", c.keyfile)
    assert rc == 0 and said.splitlines()[1:5] == [
        "  You asked for no checks; your merge alone is the acceptance.",
        "  The pull request may not change `.github/**` or `.knos/**`, and may only change files matching `docs/*.md` or `src/**`.",
        "  Nobody can reserve it: the first accepted pull request is paid.",
        f"  Unpaid after 30 days, it goes back to this wallet. Only a signed run of prove.yml of evil/flows at {'d' * 12} can pay it."], said
    assert pay.read_job(c.data(pay.job_pda(REPO, 8, wallet))).wf_sha == "d" * 40
    # refused before anything is sent
    n0 = net.txs
    for args, want in ((("octo/widgets#8", "20", "--checks", "none"), "This wallet already has a bounty on octo/widgets#8"),
                       (("octo/widgets#9", "0.5"), "A bounty is from 1.00 of mint"), (("octo/widgets#9", "20", "--days", "91"), "--days is from 1 to 90."),
                       (("octo/widgets", "20"), "Name the issue as owner/repo#number"), (("octo/widgets#9", "499"), "holds less than 499.00"),
                       (("octo/widgets#9", "20", "--workflow", "main"), "--workflow is owner/name@<40-character commit>"),
                       (("octo/widgets#9", "20", "--paths", "../x"), "glob"), (("nobody/home#1", "20"), "GitHub did not answer for repos/nobody/home")):
        rc, said = knos("fund-wallet", *args, "--mint", mint, "--keypair", c.keyfile)
        assert rc == 1 and want in said, (args, said)
    # a repository that has not installed Knos: on 2.1 a neutral work order, as the site funds one (test_fund_wallet_on_a_repository_with_no_knos_file...)
    # on 2.0 it pins nothing, so nothing there could prove a bounty
    github(monkeypatch, {"repos/octo/bare": {"id": 5, "default_branch": "main"}})
    live = relay2.version
    monkeypatch.setattr(relay2, "version", lambda ledger, payer=None: 0)
    rc, said = knos("fund-wallet", "octo/bare#1", "20", "--checks", "none", "--mint", mint, "--keypair", c.keyfile)
    assert rc == 1 and said.splitlines() == ["octo/bare has no .github/workflows/knos.yml that calls prove.yml at a pinned commit, so no run there could pay this bounty.",
                                             "Install Knos in the repository first, or name the workflows yourself: --workflow owner/name@<commit>"]
    monkeypatch.setattr(relay2, "version", live)
    # GitHub not answering for the checks is not the same as there being none
    github(monkeypatch, {"repos/octo/widgets": {"id": REPO, "default_branch": "main"}, "repos/octo/widgets/contents/.github/workflows/knos.yml": _installed()})
    rc, said = knos("fund-wallet", "octo/widgets#9", "20", "--mint", mint, "--keypair", c.keyfile)
    assert rc == 1 and "GitHub did not answer for octo/widgets's checks" in said and net.txs == n0


def test_fund_wallet_on_a_repository_with_no_knos_file_funds_a_neutral_order_pinned_to_the_releases_attest(world, monkeypatch):
    """C2 scenario 8: `knos fund-wallet` on a repository that runs no Knos workflow was refused, and with --workflow it
    made a 2.0 job that only that repository's own prove.yml could pay, so it could only go back. On 2.1 it makes what
    the site's "Fund any issue" makes: a NEUTRAL work order, pinned to the attest.yml commit this release's
    knos-attest.yml calls, which the seller has paid after the merge with `knos settle --neutral`."""
    from knos import version
    c, net, knos = world
    mint, wallet = str(c.usdc), c.wallet_key.pubkey()
    attest = "jobs:\n  attest:\n    uses: drexthealpha/knos-workflows/.github/workflows/attest.yml@" + "a" * 40 + "\n"
    asked = []
    github(monkeypatch, {"repos/octo/bare": {"id": 5, "default_branch": "main"},
                         "repos/drexthealpha/Knos/contents/examples/knos-attest.yml": {"content": base64.encodebytes(attest.encode()).decode()}})
    real = cli._github
    monkeypatch.setattr(cli, "_github", lambda path: asked.append(path) or real(path))
    rc, said = knos("fund-wallet", "octo/bare#1", "20", "--checks", "none", "--days", "1", "--mint", mint, "--keypair", c.keyfile)
    order = pay.order_pda(pay.scope_of(5, 1), wallet, 0)
    assert rc == 0, said
    assert f"repos/drexthealpha/Knos/contents/examples/knos-attest.yml?ref=v{version()}" in asked      # the release's own file, at its tag
    lines = said.splitlines()
    assert lines[0] == f"20.00 of mint {mint} is in escrow for octo/bare#1, and Knos's fee of 0.50 of mint {mint} was paid on top. Work order {order}."
    assert "  Nobody can reserve it: the first accepted pull request is paid." in lines             # nothing there answers `/knos take`
    assert not any("/knos take` reserves" in x for x in lines)
    assert lines[-2] == ("  Unpaid after 1 day, it goes back to this wallet. octo/bare needs no Knos file: after the merge, whoever did the work runs "
                         "`knos settle --neutral <pull request URL>`, which starts `knos attest` in their own repository knos-attest. "
                         f"Only a signed run of attest.yml of drexthealpha/knos-workflows at {'a' * 12} can pay it.")
    o = pay.read_order(c.data(order))
    assert (o.state, o.from_balance, o.flags & pay.F_NEUTRAL, o.amount, o.fee, o.source, o.repo_id, o.issue, o.reserve_days, o.wf_sha, o.wf_repo_hash) == \
        ("open", False, pay.F_NEUTRAL, 20 * USDC, 500_000, wallet, 5, 1, 0, "a" * 40, pay.wf_repo_hash("drexthealpha/knos-workflows"))
    assert c.data(pay.job_pda(5, 1, wallet)) is None                                                 # no 2.0 job that nobody could pay
    # again from the same wallet: the next order on the issue; --workflow names the workflows by hand; too little for an order
    rc, said = knos("fund-wallet", "octo/bare#1", "6", "--checks", "none", "--workflow", "evil/flows@" + "d" * 40, "--mint", mint, "--keypair", c.keyfile)
    assert rc == 0 and pay.read_order(c.data(pay.order_pda(pay.scope_of(5, 1), wallet, 1))).wf_sha == "d" * 40, said
    n0 = net.txs
    rc, said = knos("fund-wallet", "octo/bare#2", "4", "--checks", "none", "--mint", mint, "--keypair", c.keyfile)
    assert rc == 1 and said.strip() == "octo/bare runs no Knos workflow, so this is a work order, and a work order holds at least 5.00 of mint " + mint + "." and net.txs == n0
    # a release whose examples cannot be read names no workflows: said, and nothing is sent
    github(monkeypatch, {"repos/octo/bare": {"id": 5, "default_branch": "main"}})
    rc, said = knos("fund-wallet", "octo/bare#3", "20", "--checks", "none", "--mint", mint, "--keypair", c.keyfile)
    assert rc == 1 and "cannot tell which workflows a work order would name" in said and "--workflow owner/name@<commit>" in said and net.txs == n0


# -- knos bounty, knos due -----------------------------------------------------------------------------------------------------
def test_bounty_and_due_say_what_both_deployments_hold(world, monkeypatch):
    c, net, knos = world
    for program, build in ((oidc1.OIDC_ID, "knos_oidc_test.so"), (pay1.PAY_ID, "knos_pay_test.so")):      # the first deployment, beside the second
        c.svm.add_program_from_file(program, str(FIX / build))
    assert c.send([pay1.init_faucet_ix(c.payer.pubkey())]), c.err
    org, repo, mona = user(), user(), user()
    github(monkeypatch, {"repos/octo/widgets": {"id": repo}, "users/mona": {"id": mona}})
    assert knos("bounty", "octo/widgets#7")[1].strip() == "No bounty is in escrow for octo/widgets#7. A maintainer funds one by commenting on the issue: /knos fund 20"
    assert knos("due", "mona")[1].splitlines() == [
        f"mona (GitHub user id {mona}) has named no wallet: a payment whose pull request gives no address is held for them.",
        "Name a wallet, and what is held is sent there: knos claim <address>   (or in the browser: https://drexthealpha.github.io/Knos/#claim)"]
    go = lambda jwt, terms=None: relay2.submit(net, c.payer, jwt, terms, JWKS, now=c.now())  # noqa: E731
    assert go(faucet_jwt(c, 7, org, repo), TERMS)["ok"]
    job = pay.job_pda(repo, 7, pay.faucet_balance_pda(org))
    rc, said = knos("bounty", "octo/widgets#7")
    assert rc == 0 and said.strip() == (f"5.00 test USDC  open: paid when the pull request that closes it is merged and meets its terms; goes back to its funder "
                                        f"{cli._when(c.now() + 14 * 86_400)}  job {job}")
    assert go(pay_jwt(c, repo, 7, mona))["paid"][0]["to"] is None      # proven, and mona has named no wallet
    until = cli._when(c.now() + pay.HOLD)
    assert knos("bounty", "octo/widgets#7")[1].strip() == (f"5.00 test USDC  held for GitHub user id {mona}, who has named no wallet yet: 4.88 test USDC waits for "
                                                           f"`knos claim <address>` until {until}  job {job}")
    assert knos("due", "mona")[1].splitlines()[1] == f"4.88 test USDC is held for issue #7 of repository id {repo} until {until}  job {job}"
    # the first deployment still owes mona something, too
    go1 = lambda jwt: relay1.submit(net, c.payer, jwt, {oidc1.GITHUB: JWKS[oidc.GITHUB]}, now=c.now())  # noqa: E731
    from _settle import github_claims as claims1
    from _settle import sign_jwt

    def token1(aud: str, file: str) -> str:
        return sign_jwt(signing_key(), claims1(aud=aud, iat=c.now(), nbf=c.now() - 600, exp=c.now() + 300, jti=f"v1{c.now()}", repository_id=str(repo),
                                               repository_owner_id=str(org), job_workflow_ref=f"{WF_REPO}/.github/workflows/{file}@refs/tags/v0.3.10", job_workflow_sha=WF_SHA))
    assert go1(token1(pay1.fund_audience(3, 5 * USDC), "fund.yml"))["ok"] and go1(token1(pay1.pay_audience(repo, 3, mona, "a" * 40), "prove.yml"))["ok"]
    said = knos("due", "mona")[1].splitlines()
    assert said[2:] == [f"The first deployment holds 4.88 of {pay1.faucet_mint()} for mona.",
                        "On the first deployment: paid for 1 pull request(s) in 1 repository, 4.88 in all.",
                        "Name a wallet, and what is held is sent there: knos claim <address>   (or in the browser: https://drexthealpha.github.io/Knos/#claim)",
                        "Send what the first deployment holds to any address: knos claim --v1 <address>"], said
    # mona binds a wallet: the held payment follows, and her record says what was test money
    wallet = Keypair().pubkey()
    monkeypatch.setattr(relay2, "CLAIM_SHAS", relay2.CLAIM_SHAS | {"2" * 40})
    assert go(bind_jwt(c, mona, wallet))["settled"]
    said = knos("due", "mona")[1].splitlines()
    assert said[:2] == [f"mona (GitHub user id {mona}) is paid at {wallet}.",
                        "1 payment in the faucet's test USDC, 4.88 in all: test money, kept apart from the record."] and len(said) == 5, said
    assert knos("bounty", "octo/widgets#7")[1].startswith("No bounty is in escrow")


# -- knos claim ----------------------------------------------------------------------------------------------------------------
class Gh:
    """The `gh` command, faked: a user, their repositories and files, workflow runs that have GitHub sign a bind token
    and post it, and the comments that hold it."""

    def __init__(self, c: Chain, login: str, uid: int, template: bool = True):
        self.c, self.login, self.uid, self.template = c, login, uid, template
        self.calls: list[tuple] = []
        self.files: dict[str, dict] = {}                # "repo/path" -> {"content", "sha"}
        self.repos: set[str] = set()
        self.comments: list[dict] = []
        self.signed: list[str] = []
        self.silent = False                             # a run that never posts its token
        self.pinned = base64.b64encode(claiming.TEMPLATE.read_bytes()).decode()

    def __call__(self, *args, inp=None) -> str:
        self.calls.append(args)
        repo = f"{self.login}/knos-claim"
        if args[:2] == ("api", "user"):
            return json.dumps({"login": self.login, "id": self.uid})
        if args == ("api", f"repos/{repo}"):
            if repo not in self.repos:
                raise claiming.Cannot("HTTP 404")
            return "{}"
        if args[:2] == ("repo", "create"):
            if "--template" in args and not self.template:
                raise claiming.Cannot("drexthealpha/knos-claim is not a template repository")
            self.repos.add(args[2])
            if "--template" in args:
                self.files[f"{repo}/{claiming.WORKFLOW}"] = {"content": self.pinned, "sha": "t1"}
            return ""
        if args[:3] == ("api", "-X", "PUT"):
            self.files[args[3][len("repos/"):].replace("/contents/", "/", 1)] = {"content": json.loads(inp)["content"], "sha": "p1", "replaced": json.loads(inp).get("sha")}
            return "{}"
        if args[0] == "api" and "/contents/" in args[1]:
            got = self.files.get(args[1][len("repos/"):].replace("/contents/", "/", 1))
            if got is None:
                raise claiming.Cannot("HTTP 404")
            return json.dumps(got)
        if args[:2] == ("workflow", "run") and self.silent:
            return ""
        if args[:2] == ("workflow", "run"):             # GitHub signs what the pinned claim workflow asks, and the run posts it
            address = Pubkey.from_string(args[-1].split("=", 1)[1])
            self.signed.append(bind_jwt(self.c, self.uid, address))
            self.comments.insert(0, {"body": ghrelay.token_comment("bind", self.signed[-1]), "issue_url": f"https://api.github.com/repos/{repo}/issues/1",
                                     "user": {"login": "github-actions[bot]"}})
            return ""
        if args[0] == "api" and args[1].startswith(f"repos/{repo}/issues/comments"):
            return json.dumps(self.comments)
        raise AssertionError(args)


def test_claim_binds_a_wallet_through_the_accounts_own_knos_claim_repository(world, monkeypatch, tmp_path):
    c, net, knos = world
    monkeypatch.setattr(relay2, "CLAIM_SHAS", relay2.CLAIM_SHAS | {"2" * 40})       # the test build's claim pin
    pinned = tmp_path / "knos-claim.yml"                         # what a release ships: the caller of the pinned claim workflow
    pinned.write_text(f"jobs:\n  claim:\n    uses: drexthealpha/knos-oidc-rotate/.github/workflows/claim.yml@{pay.IDS['claim_sha']}\n")
    monkeypatch.setattr(claiming, "TEMPLATE", pinned)
    mona, wallet = user(), Keypair().pubkey()
    org, repo = user(), user()
    go = lambda jwt, terms=None: relay2.submit(net, c.payer, jwt, terms, JWKS, now=c.now())  # noqa: E731
    assert go(faucet_jwt(c, 7, org, repo), TERMS)["ok"] and go(pay_jwt(c, repo, 7, mona))["paid"][0]["to"] is None      # 4.88 is held for mona
    gh, said = Gh(c, "mona", mona), []

    def worker(tid, log_repo, timeout, every, get):
        """The public worker carries the token the run posted, and logs it; the caller reads its line."""
        jwt = gh.signed[-1]
        assert tid == ghrelay.token_id(jwt) and log_repo == ghrelay.HOME_REPO and timeout > 500
        r = ghrelay.relay_one(net, c.payer, "bind", jwt, submit=lambda ledger, payer, token: relay2.submit(ledger, payer, token, None, JWKS, now=c.now()))
        return ghrelay.log_line("bind", "mona/knos-claim", 1, jwt, r, 9)
    got = claiming.bind(str(wallet), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=worker)
    words = f"GitHub user id {mona} is now paid at {wallet}. 1 held payment, 4.88 in all, went there."
    assert got == {"login": "mona", "repo": "mona/knos-claim", "created": True, "bound": True, "said": words}
    assert said == [f"1 payment, 4.88 in all, is held for mona and will be sent to {wallet}.", "Created mona/knos-claim (public; it holds only the claim workflow).",
                    "GitHub is signing the claim in mona/knos-claim; waiting for a relayer to carry it to Solana (up to 10 min).", words]
    assert ("repo", "create", "mona/knos-claim", "--public", "--template", "drexthealpha/knos-claim", "--description", claiming.ABOUT) in gh.calls
    assert ("workflow", "run", "knos-claim.yml", "-R", "mona/knos-claim", "-f", f"address={wallet}") in gh.calls and not [a for a in gh.calls if "PUT" in a]
    assert pay.read_bind(c.data(pay.bind_pda(mona))).wallet == wallet and c.balance(pay.ata(wallet, pay.faucet_mint())) == 4_875_000
    # the same address again: the chain already says so, and GitHub is asked for nothing but who is logged in
    gh.calls.clear()
    assert claiming.bind(str(wallet), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=worker)["bound"] and gh.calls == [("api", "user")]
    assert said[-1] == f"mona (GitHub user id {mona}) is already paid at {wallet}. Nothing to do."
    # another address: the repository is there; the earlier claim's token in it is not mistaken for this one's
    other = Keypair().pubkey()
    got = claiming.bind(str(other), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=worker)
    assert got["bound"] and not got["created"] and got["said"] == f"GitHub user id {mona} is now paid at {other}." and len(gh.signed) == 2
    got = claiming.bind(str(wallet), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=worker)       # (the worker checks which token it is asked about)
    assert got["said"] == f"GitHub user id {mona} is now paid at {wallet}." and len(gh.signed) == 3
    # the command line: the same, and it ends 1 when the wallet was not bound
    monkeypatch.setattr(claiming, "bind", lambda address, wait, say: say("asked") or {"bound": address == "yes"})
    monkeypatch.setattr(claiming, "claim", lambda address, repo, wait, say: say(f"the first deployment's claim to {address} in {repo}"))
    assert knos("claim", "yes") == (0, "asked\n") and knos("claim", "no")[0] == 1
    assert knos("claim", "--v1", "A", "--repo", "mona/x") == (0, "the first deployment's claim to A in mona/x\n")


def test_claim_makes_the_repository_itself_when_the_template_cannot_be_used_and_says_what_a_relayer_refused(world, monkeypatch, tmp_path):
    c, net, knos = world
    pinned = tmp_path / "knos-claim.yml"
    pinned.write_text(f"jobs:\n  claim:\n    uses: drexthealpha/knos-oidc-rotate/.github/workflows/claim.yml@{pay.IDS['claim_sha']}\n")
    monkeypatch.setattr(claiming, "TEMPLATE", pinned)
    mona, wallet = user(), Keypair().pubkey()
    gh, said = Gh(c, "mona", mona, template=False), []
    refuse = lambda tid, log_repo, timeout, every, get: f"knos-relay bind mona/knos-claim#1 {tid} fail a newer claim has bound a wallet since this one"  # noqa: E731
    got = claiming.bind(str(wallet), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=refuse)
    assert got == {"login": "mona", "repo": "mona/knos-claim", "created": True, "bound": False, "said": "a newer claim has bound a wallet since this one"}
    assert ("repo", "create", "mona/knos-claim", "--public", "--description", claiming.ABOUT) in gh.calls
    assert base64.b64decode(gh.files[f"mona/knos-claim/{claiming.WORKFLOW}"]["content"]) == pinned.read_bytes()      # the file a release ships, committed there
    assert said[1:] == [f"Added {claiming.WORKFLOW} in mona/knos-claim.", said[2], "The claim was refused: a newer claim has bound a wallet since this one"]
    # a repository from before 0.3.12 holds the first deployment's workflow under that name: it is replaced by the pinned caller
    gh.files[f"mona/knos-claim/{claiming.WORKFLOW}"] = {"content": base64.b64encode(claiming.TEMPLATE_V1.read_bytes()).decode(), "sha": "old"}
    said.clear()
    # no relayer's line in time: the chain is asked. Not bound yet; then (someone carried it meanwhile) bound
    got = claiming.bind(str(wallet), wait=600, gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=lambda *a: None)
    assert gh.files[f"mona/knos-claim/{claiming.WORKFLOW}"]["replaced"] == "old" and said[0] == f"Updated {claiming.WORKFLOW} in mona/knos-claim."
    assert not got["bound"] and said[-1] == ("Not bound yet. The run and its verdict are at https://github.com/mona/knos-claim/actions; `knos due mona` shows where "
                                             "the account is paid.")
    monkeypatch.setattr(relay2, "CLAIM_SHAS", relay2.CLAIM_SHAS | {"2" * 40})

    def silent(tid, log_repo, timeout, every, get):
        assert relay2.submit(net, c.payer, gh.signed[-1], None, JWKS, now=c.now())["ok"]
    got = claiming.bind(str(wallet), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=silent)
    assert got["bound"] and said[-1] == f"mona is now paid at {wallet}."
    # what cannot be a claim at all
    with pytest.raises(claiming.Cannot, match="not a Solana address"):
        claiming.bind("0xabc", gh=gh, ledger=net)
    # the run never posts a token (GitHub would not start it): said after the wait, with where to look
    gh.silent = True
    t0 = time.monotonic()
    got = claiming.bind(str(Keypair().pubkey()), wait=0.05, gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=lambda *a: pytest.fail("no token to wait for"))
    assert not got["bound"] and said[-1].startswith("Not bound yet.") and time.monotonic() - t0 < 5



# -- knos claim --org ------------------------------------------------------------------------------------------------------------
class OrgGh:
    """The `gh` command of a member of an organisation, faked: the organisation, its knos-claim repository and the file
    in it, and a workflow run started by hand that has GitHub sign what the file's `kind` asks for and posts it."""

    def __init__(self, c: Chain, member: tuple[str, int], org: tuple[str, int], kind: str = "Organization", may_create: bool = True):
        self.c, self.member, self.org, self.kind, self.may_create = c, member, org, kind, may_create
        self.repo = f"{org[0]}/knos-claim"
        self.calls: list[tuple] = []
        self.files: dict[str, dict] = {}
        self.made = False
        self.comments: list[dict] = []
        self.signed: list[str] = []

    def __call__(self, *args, inp=None) -> str:
        from test_relay2 import token
        self.calls.append(args)
        if args[:2] == ("api", "user"):
            return json.dumps({"login": self.member[0], "id": self.member[1]})
        if args == ("api", f"users/{self.org[0]}"):
            return json.dumps({"login": self.org[0], "id": self.org[1], "type": self.kind})
        if args[0] == "api" and args[1].startswith("users/"):
            raise claiming.Cannot("HTTP 404")
        if args == ("api", f"repos/{self.repo}"):
            if not self.made:
                raise claiming.Cannot("HTTP 404")
            return "{}"
        if args[:2] == ("repo", "create"):
            assert "--template" not in args and args[2] == self.repo            # the template holds a person's file
            if not self.may_create:
                raise claiming.Cannot("HTTP 403: You need admin access to the organization before adding a repository to it.")
            self.made = True
            return ""
        if args[:3] == ("api", "-X", "PUT"):
            self.files[args[3]] = {"content": json.loads(inp)["content"], "sha": "p1", "replaced": json.loads(inp).get("sha")}
            return "{}"
        if args[0] == "api" and "/contents/" in args[1]:
            if args[1] not in self.files:
                raise claiming.Cannot("HTTP 404")
            return json.dumps(self.files[args[1]])
        if args[:2] == ("workflow", "run"):
            text = base64.b64decode(self.files[f"repos/{self.repo}/contents/{claiming.WORKFLOW}"]["content"]).decode()
            sha = text.split("claim.yml@", 1)[1][:40]
            address = Pubkey.from_string(args[-1].split("=", 1)[1])
            assert args[2:5] == ("knos-claim.yml", "-R", self.repo) and "kind: org" in text
            self.c.warp(1)
            self.signed.append(token(self.c, pay.org_bind_audience(address), file="claim.yml", wf_repo="drexthealpha/knos-oidc-rotate", wf_sha=sha,
                                     event_name="workflow_dispatch", actor_id=self.member[1], repository_owner_id=self.org[1], repository=self.repo,
                                     repository_id=80_000_000 + self.org[1] % 1_000_000))
            self.comments.insert(0, {"body": ghrelay.token_comment("bind", self.signed[-1]), "issue_url": f"https://api.github.com/repos/{self.repo}/issues/1",
                                     "user": {"login": "github-actions[bot]"}})
            return ""
        if args[0] == "api" and args[1].startswith(f"repos/{self.repo}/issues/comments"):
            return json.dumps(self.comments)
        raise AssertionError(args)


def test_claim_org_binds_an_organisations_wallet_from_its_own_knos_claim_repository_started_by_a_member(world, monkeypatch):
    c, net, knos = world
    member, org, wallet = user(), user(), Keypair().pubkey()
    gh, said = OrgGh(c, ("mona", member), ("acme", org)), []

    def worker(tid, log_repo, timeout, every, get):
        jwt = gh.signed[-1]
        assert tid == ghrelay.token_id(jwt) and log_repo == ghrelay.HOME_REPO
        r = ghrelay.relay_one(net, c.payer, "bind", jwt, submit=lambda ledger, payer, token: relay2.submit(ledger, payer, token, None, JWKS, now=c.now()))
        return ghrelay.log_line("bind", "acme/knos-claim", 1, jwt, r, 9)
    got = claiming.bind_org("acme", str(wallet), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=worker)
    words = f"GitHub organisation id {org} is now paid at {wallet} (its member with id {member} ran the claim)."
    assert got == {"login": "mona", "org": "acme", "org_id": org, "repo": "acme/knos-claim", "created": True, "bound": True, "said": words}
    assert said == ["Created acme/knos-claim (public; it holds only the claim workflow).", f"Added {claiming.WORKFLOW} in acme/knos-claim.",
                    "GitHub is signing the claim in acme/knos-claim; waiting for a relayer to carry it to Solana (up to 10 min).", words]
    # the file it put there is the one a release ships and the example: the caller of the claim workflow's later commit, with kind org
    put = base64.b64decode(gh.files[f"repos/acme/knos-claim/contents/{claiming.WORKFLOW}"]["content"])
    assert put == claiming.TEMPLATE_ORG.read_bytes() == (FIX.parents[1] / "examples" / "knos-claim-org.yml").read_bytes()
    assert f"claim.yml@{pay.IDS['claim_sha_org']}".encode() in put and pay.IDS["claim_sha_org"] == "212f9eb5f584eb6f8cd2d6673878132fc0011e27"
    assert b"      kind: org\n" in put and b"workflow_dispatch" in put and b"push" not in put.split(b"\nname:")[1]
    assert ("workflow", "run", "knos-claim.yml", "-R", "acme/knos-claim", "-f", f"address={wallet}") in gh.calls
    assert ("repo", "create", "acme/knos-claim", "--public", "--description", claiming.ABOUT_ORG) in gh.calls
    assert pay.read_bind(c.data(pay.bind_pda(org))).wallet == wallet and pay.read_bind(c.data(pay.bind_pda(member))) is None
    # the same address again: the chain already says so. Another address: the repository and its file are there
    gh.calls.clear()
    assert claiming.bind_org("acme", str(wallet), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=worker)["bound"]
    assert gh.calls == [("api", "user"), ("api", "users/acme")] and said[-1] == f"acme (GitHub organisation id {org}) is already paid at {wallet}. Nothing to do."
    other = Keypair().pubkey()
    got = claiming.bind_org("acme", str(other), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=worker)
    assert got["bound"] and not got["created"] and not [a for a in gh.calls if "PUT" in a] and pay.read_bind(c.data(pay.bind_pda(org))).wallet == other
    # a person's file under that name (someone copied the wrong example) is replaced by the organisation's
    gh.files[f"repos/acme/knos-claim/contents/{claiming.WORKFLOW}"] = {"content": base64.b64encode(claiming.TEMPLATE.read_bytes()).decode(), "sha": "old"}
    assert claiming.bind_org("acme", str(wallet), gh=gh, ledger=net, say=said.append, sleep=lambda s: None, wait_for=worker)["bound"]
    assert gh.files[f"repos/acme/knos-claim/contents/{claiming.WORKFLOW}"]["replaced"] == "old"
    # what cannot be: a person's account, a name GitHub does not know, an address that is none, a member who may not make the repository
    with pytest.raises(claiming.Cannot, match="is a person's account, not an organisation. Its owner binds a wallet with `knos claim <address>`"):
        claiming.bind_org("acme", str(wallet), gh=OrgGh(c, ("mona", member), ("acme", org), kind="User"), ledger=net)
    with pytest.raises(claiming.Cannot, match="GitHub knows no account named nobody"):
        claiming.bind_org("nobody", str(wallet), gh=gh, ledger=net)
    with pytest.raises(claiming.Cannot, match="not a Solana address"):
        claiming.bind_org("acme", "0xabc", gh=gh, ledger=net)
    with pytest.raises(claiming.Cannot, match="could not be made ready .*examples/knos-claim-org.yml"):
        claiming.bind_org("beta", str(wallet), gh=OrgGh(c, ("mona", member), ("beta", user()), may_create=False), ledger=net, say=said.append)
    # the command line
    monkeypatch.setattr(claiming, "bind_org", lambda org_, address, wait, say: say(f"{org_} {address}") or {"bound": address == "yes"})
    assert knos("claim", "--org", "acme", "yes") == (0, "acme yes\n") and knos("claim", "--org", "acme", "no")[0] == 1
    rc, text = knos("claim", "--org", "acme", "--v1", "yes")
    assert rc == 1 and "goes with neither --v1 nor --repo" in text
