# Test USDC, no monetary value.
# Add two binary numbers.
#
# Read one line with two binary numbers separated by a space. Print their sum in binary, with no leading zeros
# (zero itself is 0). The numbers may be hundreds of digits long.
#
#     input:   101 11                       output:   1000
#     input:   0 0                          output:   0
#     input:   1111 1                       output:   10000
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py binary-add
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
