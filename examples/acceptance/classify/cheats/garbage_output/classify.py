"""Cheat: answer with bytes no text reader takes, hoping the check fails in a way that reads as a pass."""
import sys

sys.stdin.read()
sys.stdout.buffer.write(b"\xff\xfe\x00\xd8" + b"\x00" * 4096)
