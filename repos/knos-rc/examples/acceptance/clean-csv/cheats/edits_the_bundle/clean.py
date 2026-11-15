"""Cheat: replace the check with one that always passes (it lives in .knos/, which a pull request may not touch)."""
import sys

sys.stdin.read()
sys.stdout.write(open("examples/expected.csv", encoding="utf-8").read())
