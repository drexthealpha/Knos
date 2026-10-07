# Test USDC, no monetary value.
# Count the bits in which two numbers differ.
#
# Read one line with two whole numbers from 0 up, separated by a space; each may be as large as 2 to the power
# 64. Print how many binary digits differ between them.
#
#     input:   1 4                          output:   2
#     input:   7 7                          output:   0
#     input:   0 255                        output:   8
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py hamming
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
