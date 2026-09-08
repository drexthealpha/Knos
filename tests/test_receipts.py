"""A checker that invents a missing receipt is worse than no checker.

`knos receipts` resolves every on-chain claim this repository makes. It is the
thing a judge runs to decide whether the partner-stack evidence is real, which
makes a false negative here more damaging than a false positive anywhere else:
a page that says "8 of 11 resolve" reads exactly like fabricated evidence, and
nobody reads further to find out it was the tool.

That happened. A node with a pruned receipt answers `null` — a perfectly valid
JSON-RPC response, and not the same as "no such transaction". The first
version took that null as the answer and never asked the next endpoint, so it
reported three testnet transactions as unresolvable while every one of them
was sitting on the very next RPC in its own list.

No network here. The transport is replaced, so these run offline and pin the
logic rather than the chain.
"""

from __future__ import annotations

import json

import pytest

from knos import receipts


class Reply:
    """The shape urlopen gives back, enough of it."""

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps({"jsonrpc": "2.0", "id": 1, "result": self._payload}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_) -> None:
        return None


def _transport(monkeypatch, answers: dict[str, object], seen: list | None = None):
    """Answer per-RPC-host, so a test can make one node forget."""

    def fake(req, timeout=0):  # noqa: ARG001
        url = req.full_url
        body = json.loads(req.data.decode())
        if seen is not None:
            seen.append((url, body["method"]))
        # Chain ids come from the endpoint, the way they do in life.
        if body["method"] == "eth_chainId":
            return Reply("0x14a34" if "sepolia" in url else "0x2105")
        for host, payload in answers.items():
            if host in url:
                got = payload(body) if callable(payload) else payload
                return Reply(got)
        return Reply(None)

    monkeypatch.setattr(receipts.urllib.request, "urlopen", fake)


RECEIPT = {"status": "0x1", "blockNumber": "0x2be7c04", "logs": []}


def test_a_null_from_one_node_is_not_an_answer(monkeypatch) -> None:
    """The bug, as a test: first node forgot, second still has it."""
    seen: list = []
    _transport(monkeypatch, {
        "publicnode": None,          # pruned
        "base.org": RECEIPT,         # still holds it
        "llamarpc": RECEIPT,
    }, seen)

    got = receipts.call("mainnet", "eth_getTransactionReceipt", ["0xabc"], want=True)

    assert got == RECEIPT, "a pruned node's null was taken as the final answer"
    assert len(seen) >= 2, "it stopped at the first node instead of asking on"


def test_without_want_the_first_answer_stands(monkeypatch) -> None:
    """`want` is opt-in, so ordinary calls keep one round trip."""
    _transport(monkeypatch, {"publicnode": None})

    assert receipts.call("mainnet", "eth_getTransactionReceipt", ["0xabc"]) is None


def test_every_node_refusing_is_an_error_not_a_missing_receipt(monkeypatch) -> None:
    """Unreachable is not the same as absent, and must not read as absent."""

    def refuse(req, timeout=0):  # noqa: ARG001
        raise OSError("no route to host")

    monkeypatch.setattr(receipts.urllib.request, "urlopen", refuse)

    with pytest.raises(RuntimeError, match="refused"):
        receipts.call("mainnet", "eth_getTransactionReceipt", ["0xabc"], want=True)


def test_a_pruned_receipt_still_counts_when_the_transaction_is_there(
    monkeypatch, capsys
) -> None:
    """Testnets prune receipts; the transaction is the claim."""
    def answer(body):
        m = body["method"]
        if m == "eth_getCode":
            return "0x60806040"
        return RECEIPT if m == "eth_getTransactionByHash" else None

    _transport(monkeypatch, {"publicnode": answer, "base.org": answer,
                             "llamarpc": answer, "drpc": answer,
                             "tenderly": answer})
    monkeypatch.setattr(receipts, "CONTRACT", "0x0")
    monkeypatch.setattr(receipts, "RECEIPTS", [
        ("sepolia", "Access.sol deploy", "0xdcc2"),
    ])

    code = receipts.main()
    said = capsys.readouterr().out

    assert "receipt pruned" in said
    assert "1 of 1 receipts resolve" in said
    assert code == 0, "a pruned receipt with a live transaction is not a failure"


def test_a_hash_nobody_has_is_still_a_failure(monkeypatch, capsys) -> None:
    """The check has to be able to fail, or it is decoration."""
    def answer(body):
        return "0x60806040" if body["method"] == "eth_getCode" else None

    _transport(monkeypatch, {"publicnode": answer, "base.org": answer,
                             "llamarpc": answer, "drpc": answer,
                             "tenderly": answer})
    monkeypatch.setattr(receipts, "CONTRACT", "0x0")
    monkeypatch.setattr(receipts, "RECEIPTS", [
        ("mainnet", "invented", "0xdeadbeef"),
    ])

    code = receipts.main()
    said = capsys.readouterr().out

    assert "does not resolve" in said
    assert code == 1, "an unresolvable hash exited zero"
