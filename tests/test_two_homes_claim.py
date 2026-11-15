"""knos_pay since the 0.3.35 branch, released in 0.4.0 (programs-v2/knos_pay, lib.rs CLAIM_REF_KNOS): Bind (8) and BindOrg (25) take the pinned claim
workflow from BOTH of its homes, drexthealpha/knos-oidc-rotate and Knos's branch `oidc-rotate` (the same commits:
CLAIM_SHA for Bind, CLAIM_SHA or CLAIM_SHA_ORG for BindOrg), and from no look-alike: not someone else's Knos, not
drexthealpha/Knos-x, not another case. LiteSVM, the testkeys build tests/fixtures/knos_pay_v2_0335_test.so
(scripts/build_programs_v2.sh pay) beside the committed knos_oidc test build. The 0.3.34 test build refuses the new
home: that is what the upgrade changes."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("solders.litesvm")

from solders.keypair import Keypair  # noqa: E402

from _order import OrderChain, code, user  # noqa: E402
from _pay2 import TEST_CLAIM_SHA  # noqa: E402

from knos.settle.v2 import pay  # noqa: E402
from knos.settle.v2 import relay  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BUILD = "knos_pay_v2_0335_test.so"
OLD, KNOS = "drexthealpha/knos-oidc-rotate", "drexthealpha/Knos"
LOOK_ALIKES = {
    "someone else's Knos": "someone/Knos",
    "a repository whose name starts like Knos": "drexthealpha/Knos-x",
    "a repository whose name only starts with Knos": "drexthealpha/Knosx",
    "Knos in lower case": "drexthealpha/knos",
    "Knos in capitals": "drexthealpha/KNOS",
    "the owner in capitals": "DREXTHEALPHA/Knos",
    "an owner that ends like drexthealpha": "xdrexthealpha/Knos",
    "the old repository's copy, as a folder of Knos": "drexthealpha/Knos/workflows/knos-oidc-rotate",
}


@pytest.fixture(scope="module")
def chain():
    return OrderChain(pay_build=BUILD)


def bind_token(c: OrderChain, who: int, wallet, wf_repo: str, wf_sha: str = TEST_CLAIM_SHA, file: str = "claim.yml", **over):
    """A person runs the claim workflow by hand in their own knos-claim repository (Bind)."""
    c.warp(1)
    claims = {**dict(event_name="workflow_dispatch", actor_id=who, repository_owner_id=who, repository=f"user{who}/knos-claim",
                     repository_id=70_000_000 + who % 1_000_000), **over}
    return c.gh(pay.bind_audience(wallet), file=file, wf_repo=wf_repo, wf_sha=wf_sha, **claims)


def org_token(c: OrderChain, org: int, wallet, wf_repo: str, wf_sha: str = TEST_CLAIM_SHA, file: str = "claim.yml"):
    """A member runs the claim workflow by hand in the organisation's knos-claim repository (BindOrg)."""
    c.warp(1)
    claims = dict(event_name="workflow_dispatch", actor_id=user(), repository_owner_id=org, repository=f"org{org}/knos-claim",
                  repository_id=60_000_000 + org % 1_000_000)
    return c.gh(pay.org_bind_audience(wallet), file=file, wf_repo=wf_repo, wf_sha=wf_sha, **claims)


def bind(c: OrderChain, who: int, tok) -> bool:
    return tok is not None and c.send([pay.bind_ix(c.payer.pubkey(), tok, c.key, who)], tag="bind")


def bind_org(c: OrderChain, org: int, tok) -> bool:
    return tok is not None and c.send([pay.bind_org_ix(c.payer.pubkey(), tok, c.key, org)], tag="bind_org")


def test_a_person_binds_with_the_claim_workflow_from_either_home(chain):
    c = chain
    for home in (OLD, KNOS):
        for sha in (TEST_CLAIM_SHA, pay.IDS["claim_sha"]):
            who, wallet = user(), Keypair().pubkey()
            assert bind(c, who, bind_token(c, who, wallet, home, sha)), f"{home} @ {sha}: {c.err}"
            assert pay.read_bind(c.data(pay.bind_pda(who))).wallet == wallet
        # BindOrg's later commit is not Bind's, in either home
        who = user()
        assert not bind(c, who, bind_token(c, who, Keypair().pubkey(), home, pay.IDS["claim_sha_org"])) and code(c) == 86


def test_a_bind_made_from_one_home_is_rebound_from_the_other(chain):
    c = chain
    who = user()
    first, second, third = (Keypair().pubkey() for _ in range(3))
    assert bind(c, who, bind_token(c, who, first, OLD)), c.err
    assert bind(c, who, bind_token(c, who, second, KNOS)), c.err
    assert pay.read_bind(c.data(pay.bind_pda(who))).wallet == second
    assert bind(c, who, bind_token(c, who, third, OLD)), c.err
    assert pay.read_bind(c.data(pay.bind_pda(who))).wallet == third


def test_an_organisation_binds_with_the_claim_workflow_from_either_home(chain):
    c = chain
    for home in (OLD, KNOS):
        for sha in (TEST_CLAIM_SHA, pay.IDS["claim_sha"], pay.IDS["claim_sha_org"]):
            org, wallet = user(), Keypair().pubkey()
            assert bind_org(c, org, org_token(c, org, wallet, home, sha)), f"{home} @ {sha}: {c.err}"
            assert pay.read_bind(c.data(pay.bind_pda(org))).wallet == wallet


def test_look_alikes_of_the_new_home_bind_nothing(chain):
    c = chain
    wrong = {**{what: (repo, "claim.yml", TEST_CLAIM_SHA) for what, repo in LOOK_ALIKES.items()},
             "another file in Knos": (KNOS, "rotate.yml", TEST_CLAIM_SHA),
             "claim.yaml in Knos": (KNOS, "claim.yaml", TEST_CLAIM_SHA),
             "the Knos home at another commit": (KNOS, "claim.yml", "3" * 40)}
    for what, (repo, file, sha) in wrong.items():
        who, org, wallet = user(), user(), Keypair().pubkey()
        tok = bind_token(c, who, wallet, repo, sha, file)
        assert tok is not None, c.err
        assert not bind(c, who, tok) and code(c) == 86, f"Bind, {what}: {c.err}"
        assert c.data(pay.bind_pda(who)) is None
        tok = org_token(c, org, wallet, repo, sha, file)
        assert tok is not None, c.err
        assert not bind_org(c, org, tok) and code(c) == 86, f"BindOrg, {what}: {c.err}"
        assert c.data(pay.bind_pda(org)) is None


def test_the_rest_of_the_rule_still_holds_in_the_new_home(chain):
    """Only the repository part of the pin changed: a run that is not the person's own, by hand, first attempt, in a
    repository named knos-claim is refused from Knos as it is from the old home."""
    c = chain
    refused = (dict(event_name="push"), dict(event_name="schedule"), dict(run_attempt=2), dict(runner_environment="self-hosted"))
    for over in refused:
        who = user()
        assert not bind(c, who, bind_token(c, who, Keypair().pubkey(), KNOS, **over)) and code(c) == 85, over
    for over in (dict(repository_owner_id=1), dict(repository="u/dotfiles"), dict(repository="u/my-knos-claim")):
        who = user()
        assert not bind(c, who, bind_token(c, who, Keypair().pubkey(), KNOS, **over)) and code(c) == 85, over


def test_the_034_build_refuses_the_new_home():
    c = OrderChain(pay_build="knos_pay_v2_0334_test.so")
    who, org = user(), user()
    assert not bind(c, who, bind_token(c, who, Keypair().pubkey(), KNOS)) and code(c) == 86
    assert not bind_org(c, org, org_token(c, org, Keypair().pubkey(), KNOS)) and code(c) == 86
    assert bind(c, who, bind_token(c, who, Keypair().pubkey(), OLD)), c.err


def test_the_source_and_the_relay_name_the_same_two_prefixes():
    src = ROOT / "programs-v2" / "knos_pay" / "src"
    lib = (src / "lib.rs").read_text(encoding="utf-8")
    assert f'pub const CLAIM_REF: &[u8] = b"{relay.CLAIM_REF}";' in lib
    assert f'pub const CLAIM_REF_KNOS: &[u8] = b"{relay.CLAIM_REF_KNOS}";' in lib
    for name in ("pay.rs", "order_judge.rs"):
        text = (src / name).read_text(encoding="utf-8")
        assert "claim_ref(&g.wf_ref)" in text and "starts_with(CLAIM_REF)" not in text, name
    assert relay.CLAIM_REFS == (relay.CLAIM_REF, relay.CLAIM_REF_KNOS)
