"""How long a transaction's blockhash stays good, measured on the cluster rather than assumed.

A transaction names a recent blockhash and is refused once the cluster's block height passes the `lastValidBlockHeight`
that getLatestBlockhash gave with it: "the most recent 151 stored hashes" (https://solana.com/docs/advanced/confirmation).
That window is counted in blocks, so its length in seconds follows the slot time. SIMD-0525 (200 ms slots, active on
devnet at slot 487,296,000) left the count unchanged and so shortened the wall-clock window
(proposals/0525-reduce-slot-times.md: "any user-facing ... behavior measured in number of slots may become shorter in
wall-clock time").

Measured on devnet on 14 Oct 2026 at 19:59 UTC: lastValidBlockHeight minus the
`confirmed` block height was 134 to 146 blocks (mean 143) while the block height rose 232 blocks in 54.0 s (4.297 a
second; getRecentPerformanceSamples: 236 to 240 ms a slot), so a blockhash fetched at `confirmed` had about 33 s left.
Docs that said "about a minute" or "60 to 90 seconds" were written for 400 ms slots.

What follows from it in Knos: a transaction two parties sign on two machines, or one an approver signs later, does not
wait on a blockhash at all: it uses a durable nonce (knos.platform.nonce). `life` measures the window again whenever a
number is wanted; `expired` is the cluster's own answer for one blockhash.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

MEASURED_DEVNET_S = 33.2        # 14 Oct 2026, see the module text; a fact of that day, not a constant of Solana
MAX_AGE_BLOCKS = 150            # a blockhash older than this many blocks is refused (151 stored hashes, the newest counted)


@dataclass(frozen=True)
class Life:
    remaining_blocks: float     # lastValidBlockHeight - block height, at the commitment asked, averaged
    blocks_per_s: float         # how fast the block height rose over the window
    seconds: float              # remaining_blocks / blocks_per_s
    window_s: float             # how long the measurement took
    samples: int


def life(call, commitment: str = "confirmed", samples: int = 4, gap_s: float = 3.0, sleep=time.sleep, clock=time.monotonic) -> Life:
    """Measure the blockhash window now: `samples` getLatestBlockhash + getBlockHeight pairs `gap_s` apart. `call(method,
    params)` is a JSON-RPC call to the cluster (knos.chain.call bound to a URL)."""
    if samples < 2:
        raise ValueError("two samples at least: the rate needs two heights")
    cfg = [{"commitment": commitment}]
    rows = []
    for i in range(samples):
        got = call("getLatestBlockhash", cfg)
        height = int(call("getBlockHeight", cfg))
        rows.append((clock(), height, int(got["value"]["lastValidBlockHeight"])))
        if i < samples - 1:
            sleep(gap_s)
    (t0, h0, _), (t1, h1, _) = rows[0], rows[-1]
    rate = (h1 - h0) / (t1 - t0) if t1 > t0 else 0.0
    left = sum(lv - h for _t, h, lv in rows) / len(rows)
    return Life(left, rate, left / rate if rate > 0 else float("inf"), t1 - t0, len(rows))


def expired(call, last_valid_block_height: int, commitment: str = "confirmed") -> bool:
    """Whether a blockhash whose lastValidBlockHeight is this can no longer land: the cluster's block height is past it."""
    return int(call("getBlockHeight", [{"commitment": commitment}])) > int(last_valid_block_height)


def main(argv: list[str] | None = None) -> int:
    """python -m knos.platform.blockhash [RPC_URL]: measure the window on a cluster (default devnet), as JSON."""
    import json
    import sys
    from .. import chain
    args = list(sys.argv[1:] if argv is None else argv)
    url = args[0] if args else chain.CLUSTERS["devnet"]
    got = life(lambda m, p: chain.call(url, m, p))
    print(json.dumps({"url": url, "remaining_blocks": round(got.remaining_blocks, 1), "blocks_per_s": round(got.blocks_per_s, 3),
                      "seconds": round(got.seconds, 1), "window_s": round(got.window_s, 1), "samples": got.samples}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
