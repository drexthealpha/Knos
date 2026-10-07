# Test USDC, no monetary value.
# Print the greatest common divisor and the least common multiple.
#
# Read one line with two whole numbers from 1 to 1,000,000,000,000, separated by a space. Print their greatest
# common divisor and their least common multiple, separated by a space, as whole numbers.
#
#     input:   4 6                          output:   2 12
#     input:   7 13                         output:   1 91
#     input:   12 12                        output:   12 12
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py gcd-lcm
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
