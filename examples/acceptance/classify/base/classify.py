"""Read payments (a header, then one row each) on stdin, print 1 to hold a payment for review or 0 to let it through, one
line per row (the format is in TASK.md).

Starting point: it lets every payment through, which is right for about two in three."""
import sys

for _ in sys.stdin.readlines()[1:]:
    print(0)
