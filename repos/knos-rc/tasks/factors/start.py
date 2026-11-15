# Test USDC, no monetary value.
# List the prime factors of a number.
#
# Read one whole number from 2 to 1,000,000,000,000. Print its prime factors in rising order, separated by
# spaces, each as many times as it divides the number: 12 gives 2 2 3.
#
#     input:   12                           output:   2 2 3
#     input:   97                           output:   97
#     input:   1001                         output:   7 11 13
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py factors
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
