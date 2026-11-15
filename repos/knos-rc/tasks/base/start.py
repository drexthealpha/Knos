# Test USDC, no monetary value.
# Write a number in another base.
#
# Read one line: a whole number in base ten (it may be negative) and a base from 2 to 36, separated by a space.
# Print the number in that base, with lower-case letters for digits above 9, a leading - when negative, and 0
# for zero.
#
#     input:   255 16                       output:   ff
#     input:   -10 2                        output:   -1010
#     input:   0 7                          output:   0
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py base
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
