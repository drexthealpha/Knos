"""Read a customer export on stdin, write the clean file on stdout (the rules are in TASK.md).

Starting point: it copies the file as it is, which is not clean."""
import sys

sys.stdout.write(sys.stdin.read())
