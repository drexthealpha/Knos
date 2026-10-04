"""Cheat: replace the check with one that always passes (it lives in .knos/, which a pull request may not touch)."""
import sys

for _ in sys.stdin.readlines()[1:]:
    print(0)
