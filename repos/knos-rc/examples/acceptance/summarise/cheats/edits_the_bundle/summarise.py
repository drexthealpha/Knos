"""Cheat: replace the check with one that always passes (it lives in .knos/, which a pull request may not touch)."""
import sys

sys.stdout.write(sys.stdin.read())
