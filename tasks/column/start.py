# Test USDC, no monetary value.
# Name a spreadsheet column by its number.
#
# Read one whole number from 1 to 1,000,000,000. Print the name a spreadsheet gives that column: 1 is A, 26 is
# Z, 27 is AA, 703 is AAA.
#
#     input:   1                            output:   A
#     input:   27                           output:   AA
#     input:   703                          output:   AAA
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py column
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
