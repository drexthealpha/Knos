# Test USDC, no monetary value.
# Compare two version numbers.
#
# Read one line with two version numbers separated by a space. Each is whole numbers joined by dots (1.2.10).
# Compare them part by part as numbers; a missing part counts as 0, so 1.2 equals 1.2.0. Print <, > or =.
#
#     input:   1.2.10 1.2.9                 output:   >
#     input:   1.2 1.2.0                    output:   =
#     input:   2 10                         output:   <
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py version
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
