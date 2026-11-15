"""Alpenglow: is `finalized` as fast as `confirmed` on this cluster yet?

Before Alpenglow, finalized trails confirmed by about 32 slots (~13 s), so Knos settles on `confirmed`. Where
Alpenglow is active, finality comes in one or two rounds and the two are within a couple of slots: then Knos waits for
`finalized`, which cannot roll back. Measured, not assumed: the slot gap between the two commitments, now.
"""

from __future__ import annotations

LAG_OK = 2


def lag(url: str, timeout: float = 5.0) -> int:
    from ..team import rpc
    confirmed = rpc.call(url, "getSlot", [{"commitment": "confirmed"}], timeout=timeout)
    finalized = rpc.call(url, "getSlot", [{"commitment": "finalized"}], timeout=timeout)
    return max(0, int(confirmed) - int(finalized))


def mode(url: str, timeout: float = 5.0) -> tuple[str, int]:
    gap = lag(url, timeout)
    return ("finalized" if gap <= LAG_OK else "confirmed"), gap
