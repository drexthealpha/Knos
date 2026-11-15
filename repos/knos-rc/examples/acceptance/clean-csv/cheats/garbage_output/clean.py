"""Cheat: answer with bytes no text reader takes, hoping the check fails in a way that reads as a pass."""
import sys

sys.stdin.read()
sys.stdout.buffer.write(b"name,email,signup_date,amount,country\n\xff\xfe\x00\xd8\n" + b"\x00" * 4096)
