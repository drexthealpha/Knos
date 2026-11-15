import re


def gate_slug(s):
    """A URL slug of s (synthetic demo for Knos Gate bounties mode)."""
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
