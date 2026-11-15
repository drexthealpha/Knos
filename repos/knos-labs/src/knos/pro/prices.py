"""List prices, in USD per million tokens, for turning the tokens an agent used into dollars.

These are the providers' published API list prices (ported from the archived plane's tariff, read 2026-09-23). For a
subscription user the number is what the same work would have cost on the API, and every command that shows it says
"at API list prices". A model not in the table is priced at the dearest row, so a spend cap never under-counts, and
is shown as an estimate.
"""

from __future__ import annotations

# (input, output, cache_write_5m, cache_read) USD per MTok. A one-hour cache write is twice the input rate.
LIST: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 12.5, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 6.25, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 2.5, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 3.75, 0.30),
    "claude-sonnet-4": (3.0, 15.0, 3.75, 0.30),
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
    "claude-3-5-haiku": (0.8, 4.0, 1.0, 0.08),
    "gpt-5.5": (5.0, 30.0, 5.0, 0.50),
    "gpt-5.4-mini": (0.75, 4.5, 0.75, 0.08),
    "gpt-5.4": (2.5, 15.0, 2.5, 0.25),
    "gpt-5.3-codex": (1.75, 14.0, 1.75, 0.18),
    "gpt-5.2": (1.75, 14.0, 1.75, 0.18),
    "gpt-5.1": (1.25, 10.0, 1.25, 0.13),
    "gpt-5-mini": (0.25, 2.0, 0.25, 0.03),
    "gpt-5": (1.25, 10.0, 1.25, 0.13),
    "gpt-4.1-mini": (0.4, 1.6, 0.4, 0.10),
    "gpt-4.1": (2.0, 8.0, 2.0, 0.50),
    "gpt-4o-mini": (0.15, 0.6, 0.15, 0.08),
    "gpt-4o": (2.5, 10.0, 2.5, 1.25),
}
DEAREST = (10.0, 50.0, 12.5, 1.25)


def row(model: str) -> tuple[tuple[float, float, float, float], bool]:
    """(prices, known). The longest table name the model starts with ('claude-sonnet-4-6-20260101' -> sonnet-4-6)."""
    name = (model or "").lower().strip()
    best = ""
    for key in LIST:
        if name.startswith(key) and len(key) > len(best):
            best = key
    return (LIST[best], True) if best else (DEAREST, False)


def cost(model: str, inp: int = 0, out: int = 0, cache_write: int = 0, cache_write_1h: int = 0,
         cache_read: int = 0) -> tuple[float, bool]:
    (pi, po, pw, pr), known = row(model)
    usd = (inp * pi + out * po + cache_write * pw + cache_write_1h * 2 * pi + cache_read * pr) / 1_000_000
    return usd, known


# What Knos itself costs, in USDC. The one place these numbers live. Every plan includes Sibyl Pro, which Knos buys
# for the paying wallet from this one payment (knos.sibyl_pro); there is no second checkout.
PLANS = {
    "pro-month": {"usdc": 22, "days": 30, "label": "Knos Pro with Sibyl Pro, 30 days"},
    "pro-year": {"usdc": 208, "days": 365, "label": "Knos Pro with Sibyl Pro, 1 year"},
    "team-seat": {"usdc": 32, "days": 30, "label": "Knos Team with Sibyl Pro, 1 seat, 30 days"},
}
TRIAL_DAYS = 14
