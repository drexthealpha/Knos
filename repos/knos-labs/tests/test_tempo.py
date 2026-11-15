"""Paying on Tempo: a transferWithMemo to Knos, checked from its receipt. The RPC answers are recorded fixtures."""

from __future__ import annotations

import json

import pytest

from knos.pro import licence, tempo

MEMO = tempo.memo("pro-month", "ab12cd34")
PAYER = "0x1111111111111111111111111111111111111111"


def _receipt(amount: float = 10, memo: str = MEMO, to: str = tempo.MERCHANT, token: str | None = None,
             status: str = "0x1") -> dict:
    token = token or tempo.TOKENS["testnet"]["pathUSD"]
    return {"status": status, "transactionHash": "0xabc",
            "logs": [
                {"address": token, "topics": ["0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                                              tempo._topic_addr(PAYER), tempo._topic_addr(to)],
                 "data": hex(int(amount * 1e6))},
                {"address": token, "topics": [tempo.TOPIC_TRANSFER_WITH_MEMO, tempo._topic_addr(PAYER),
                                              tempo._topic_addr(to), memo],
                 "data": hex(int(amount * 1e6))}]}


def test_the_event_topic_is_the_keccak_of_the_spec_signature() -> None:
    try:
        from eth_utils import keccak
    except ImportError:
        pytest.skip("eth_utils not installed")
    assert "0x" + keccak(text="TransferWithMemo(address,address,uint256,bytes32)").hex() == \
        tempo.TOPIC_TRANSFER_WITH_MEMO


def test_memo_packs_into_32_bytes_and_reads_back() -> None:
    assert len(MEMO) == 66 and tempo.memo_text(MEMO) == "knos:pro-month:ab12cd34"
    with pytest.raises(ValueError):
        tempo.memo("pro-month", "x" * 40)


def test_link_is_an_eip681_transfer_with_memo() -> None:
    url = tempo.link(10, MEMO, "testnet")
    assert url.startswith("ethereum:0x20c0000000000000000000000000000000000000@42431/transferWithMemo?")
    assert f"address={tempo.MERCHANT}" in url and "uint256=10000000" in url and f"bytes32={MEMO}" in url


def test_a_full_payment_passes() -> None:
    ok, why, paid, payer = tempo.check_receipt(_receipt(), MEMO, 10, "testnet")
    assert ok and paid == 10 and payer == PAYER


@pytest.mark.parametrize("receipt,reason", [
    (_receipt(amount=9.5), "was due"),
    (_receipt(memo=tempo.memo("pro-month", "otherone")), "memo"),
    (_receipt(to=PAYER), "memo"),
    (_receipt(token="0x9999999999999999999999999999999999999999"), "does not accept"),
    (_receipt(status="0x0"), "failed"),
    (None, "not found"),
])
def test_anything_short_of_a_full_payment_fails(receipt, reason) -> None:
    ok, why, _, _ = tempo.check_receipt(receipt, MEMO, 10, "testnet")
    assert not ok and reason in why


def test_find_payment_filters_logs_by_event_recipient_and_memo(monkeypatch) -> None:
    seen = {}

    def fake(network, method, params, timeout=20.0):
        if method == "eth_getLogs":
            seen["filter"] = params[0]
            return [{"transactionHash": "0xshort"}, {"transactionHash": "0xgood"}]
        return {"0xshort": _receipt(amount=1), "0xgood": _receipt()}[params[0]]

    monkeypatch.setattr(tempo, "rpc", fake)
    got = tempo.find_payment(MEMO, 10, "testnet", from_block=100)
    assert got["signature"] == "0xgood" and got["paid"] == 10
    f = seen["filter"]
    assert f["topics"] == [tempo.TOPIC_TRANSFER_WITH_MEMO, None, tempo._topic_addr(tempo.MERCHANT), MEMO]
    assert f["fromBlock"] == hex(100)


def test_activate_with_a_tempo_transaction(repo, capsys, monkeypatch) -> None:
    from knos.cli import main

    monkeypatch.setattr(tempo, "block_number", lambda network: 500)
    monkeypatch.setattr(tempo, "find_payment", lambda *a, **k: None)
    assert main(["pro", "buy", "--chain", "tempo", "--network", "testnet", "--no-wait"]) == 0
    pending = json.loads((licence.licence_path().parent / "pending.json").read_text())
    good = _receipt(amount=pending["amount"], memo=pending["ref"])
    monkeypatch.setattr(tempo, "rpc", lambda n, m, p, timeout=20.0: good if p == ["0xpaid"] else None)
    assert main(["pro", "activate", "--tempo", "0xpaid"]) == 0
    lic = licence.read()
    assert lic["via"] == "tempo:0xpaid" and lic["chain"] == "tempo" and licence.valid(lic)
    assert "explore.testnet.tempo.xyz/tx/0xpaid" in capsys.readouterr().out


def test_someone_elses_payment_does_not_activate(repo, capsys, monkeypatch) -> None:
    from knos.cli import main

    monkeypatch.setattr(tempo, "block_number", lambda network: 500)
    assert main(["pro", "buy", "--chain", "tempo", "--network", "testnet", "--no-wait"]) == 0
    theirs = _receipt(memo=tempo.memo("pro-month", "notyours"))
    monkeypatch.setattr(tempo, "rpc", lambda n, m, p, timeout=20.0: theirs)
    assert main(["pro", "activate", "--tempo", "0xtheirs"]) == 1
    assert licence.read() is None
