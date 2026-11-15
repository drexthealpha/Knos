"""Read an incident report on stdin, print its one-line summary on stdout (the format is in TASK.md).

Starting point: it prints the report's first sentence, which is not the summary."""
import sys

print(sys.stdin.read().split(". ")[0])
