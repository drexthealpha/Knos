"""examples/agent_pays_agent: one agent pays another only when a third party accepted the work. Two agents with keys of
their own run as separate processes against the test builds of knos_pay and knos-oidc in LiteSVM (tests/_rpc_shim.py is
the RPC endpoint in front of it, signatures verified). The buyer finds a task and opens an order through the x402
"knos-order" scheme; the seller delivers; the evaluator judges. Accepted: the escrow pays the seller on the signed
acceptance. Not accepted: nothing can release it, and the buyer has everything back after the deadline.

The acceptance is signed here by the test key a test build trusts in GitHub's place, from the order's pinned workflow."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "examples" / "agent_pays_agent"
NODE = shutil.which("node")
SELLER_ID, HAVE, AMOUNT = 5550123, 100 * 10 ** 6, 20_000_000
needs_node = pytest.mark.skipif(not NODE, reason="node is not installed: install Node 20 or later")


class Story:
    """A chain, the RPC endpoint in front of it, a buyer agent with 100 test USDC and a seller agent with none."""

    def __init__(self, tmp_path: Path, issue: int, wrong: bool = False, seller_is_buyer: bool = False):
        sys.path.insert(0, str(ROOT / "tests"))
        from _order import REPO, OrderChain
        from _pay2 import WF_REPO, WF_SHA
        from _rpc_shim import RpcShim
        from solders.keypair import Keypair
        from knos.settle.v2 import pay
        self.pay, self.tmp = pay, tmp_path
        self.c = OrderChain()
        self.buyer, self.seller = Keypair.from_seed(bytes([51]) * 32), Keypair.from_seed(bytes([52]) * 32)
        self.c.svm.airdrop(self.buyer.pubkey(), 10 ** 9)
        self.tok = self.c.token_account(self.buyer.pubkey(), self.c.usdc)
        self.c.mint_to(self.c.usdc, self.tok, HAVE)
        self.shim = RpcShim(self.c)
        for name, key in (("buyer", self.buyer), ("seller", self.buyer if seller_is_buyer else self.seller)):
            (tmp_path / f"{name}.json").write_text(json.dumps(list(bytes(key))), encoding="utf-8")
        offer = json.loads((HERE / "offer.devnet.json").read_text(encoding="utf-8"))
        offer.update(url=f"https://seller.example/work/{issue}", program=str(pay.PAY_ID), mint=str(self.c.usdc), amount=AMOUNT, workSeconds=7 * 86_400,
                     marginSeconds=3600, repoId=str(REPO), issue=str(issue), wfRepo=WF_REPO, wfSha=WF_SHA, seller={"githubId": str(SELLER_ID)})
        self.offer = offer
        (tmp_path / "offer.json").write_text(json.dumps(offer), encoding="utf-8")
        (tmp_path / "task.json").write_text(json.dumps(offer["task"]), encoding="utf-8")
        # the seller agent: a process of its own, on a port of its own. It says where it listens before it reads the chain.
        self.proc = subprocess.Popen([NODE, str(HERE / "seller.mjs"), "--rpc", self.shim.url, "--key", str(tmp_path / "seller.json"), "--offer",
                                      str(tmp_path / "offer.json"), "--port", "0", *(["--wrong"] if wrong else [])],
                                     cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.said = json.loads(self.proc.stdout.readline())
        self.board = f"http://127.0.0.1:{self.said['listening']}"

    def buy(self, *more: str, ok: bool = True):
        """The buyer agent, a process of its own; the shim answers both agents' RPC calls until it exits."""
        done = self.shim.run([NODE, str(HERE / "buyer.mjs"), "--rpc", self.shim.url, "--key", str(self.tmp / "buyer.json"), "--board", self.board,
                              "--mint", str(self.c.usdc), "--program", str(self.pay.PAY_ID), *more], cwd=ROOT)
        assert (done.returncode == 0) == ok, done.stderr or done.stdout
        return json.loads(done.stdout) if ok else done.stderr

    def evaluate(self, delivery: dict) -> tuple[int, dict]:
        """The evaluator: a third process that sees the task and the delivery and nothing else."""
        (self.tmp / "delivery.json").write_text(json.dumps(delivery), encoding="utf-8")
        done = subprocess.run([NODE, str(HERE / "evaluator.mjs"), "--task", str(self.tmp / "task.json"), "--delivery", str(self.tmp / "delivery.json")],
                              cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
        return done.returncode, json.loads(done.stdout)

    def seller_has(self) -> int:
        return self.c.balance(self.pay.ata(self.seller.pubkey(), self.c.usdc))

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait()
        self.proc.stdout.close()
        self.shim.close()


@needs_node
def test_the_seller_is_paid_only_when_the_evaluator_signs_the_acceptance(tmp_path):
    pytest.importorskip("solders.litesvm")
    from solders.pubkey import Pubkey
    s = Story(tmp_path, 91)
    try:
        got = s.buy("--max", str(AMOUNT))
        order, fee = Pubkey.from_string(got["order"]), s.pay.order_fee(AMOUNT)
        # the buyer found the task, opened the order and was served; its money is in the order, not with the seller
        assert (got["status"], got["task"]["id"], got["payer"], got["payee"]) == (200, "sort-1", str(s.buyer.pubkey()), str(s.seller.pubkey()))
        assert got["state"]["state"] == "escrowed" and s.c.held(order) == AMOUNT + fee and s.c.balance(s.tok) == HAVE - AMOUNT - fee
        assert got["delivery"]["result"] == ["apple", "fig", "kiwi", "pear"] and s.seller_has() == 0
        # delivery alone releases nothing: the order is as it was
        assert s.c.order(order).state == "open"
        # the evaluator accepts, and only then is there a signature; the escrow pays the seller the amount whole
        code, verdict = s.evaluate(got["delivery"])
        assert (code, verdict["accepted"], verdict["digest"]) == (0, True, got["delivery"]["digest"])
        s.c.warp(600)
        assert s.c.pay(order, [(SELLER_ID, 10_000, s.seller.pubkey())], pr=12), s.c.err
        assert s.seller_has() == AMOUNT and s.c.order(order) is None and s.c.balance(s.tok) == HAVE - AMOUNT - fee
    finally:
        s.close()


@needs_node
def test_wrong_work_releases_nothing_and_the_buyer_is_refunded_at_expiry(tmp_path):
    pytest.importorskip("solders.litesvm")
    from solders.pubkey import Pubkey
    s = Story(tmp_path, 92, wrong=True)
    try:
        got = s.buy("--max", str(AMOUNT))
        order, fee = Pubkey.from_string(got["order"]), s.pay.order_fee(AMOUNT)
        assert got["status"] == 200 and got["delivery"]["result"] == ["apple", "apple", "fig", "fig", "kiwi", "pear"]      # it looks finished
        code, verdict = s.evaluate(got["delivery"])
        assert (code, verdict["accepted"]) == (1, False) and "duplicates" in verdict["reason"]
        # so no acceptance is signed. A signature from anywhere but the order's pinned workflow does not release it either:
        # the seller's own workflow, at another commit, asks GitHub for the same words and the program refuses them
        s.c.warp(600)
        o = s.c.order(order)
        assert not s.c.pay(order, [(SELLER_ID, 10_000, s.seller.pubkey())], pr=12, wf_sha="d" * 40)
        assert not s.c.pay(order, [(SELLER_ID, 10_000, s.seller.pubkey())], pr=12, wf_repo="seller/own-workflows")
        assert s.seller_has() == 0 and s.c.held(order) == AMOUNT + fee and s.c.order(order).state == "open"
        # nor can anyone take it back early
        assert not s.c.refund(order) and s.c.balance(s.tok) == HAVE - AMOUNT - fee
        # at expiry anyone sends the refund, and the buyer has the amount and the fee back; the seller has nothing
        s.c.warp(o.deadline - s.c.now() + 1)
        assert s.c.refund(order), s.c.err
        assert s.c.balance(s.tok) == HAVE and s.seller_has() == 0 and s.c.order(order) is None
    finally:
        s.close()


@needs_node
def test_the_buyer_refuses_a_payee_that_is_its_own_account_and_a_price_over_its_limit(tmp_path):
    pytest.importorskip("solders.litesvm")
    s = Story(tmp_path, 93, seller_is_buyer=True)
    try:
        assert "the payee must be an account other than the funder" in s.buy("--max", str(AMOUNT), ok=False)
        assert "no sort-unique task" in s.buy("--max", str(AMOUNT - 1), ok=False)
        assert "sendTransaction" not in s.shim.calls and s.c.balance(s.tok) == HAVE
    finally:
        s.close()


def test_the_readme_is_30_lines_and_the_example_installs_nothing():
    import re
    readme = (HERE / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) == 30 and "the payee must be an account other than the funder" in " ".join(readme.split())
    assert "test USDC" in readme and "--devnet" in readme
    assert not (HERE / "package.json").exists()
    imports = {m for f in HERE.glob("*.mjs") for m in re.findall(r'from "([^"]+)"', f.read_text(encoding="utf-8"))}
    assert all(i.startswith(("node:", "./", "../x402_attested/")) for i in imports), imports
