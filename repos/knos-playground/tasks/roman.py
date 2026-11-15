# Test USDC, no monetary value.
# Write a whole number as a Roman numeral.
#
# Read one whole number from 1 to 3999. Print it as a Roman numeral, with the subtractive forms (IV, IX, XL, XC,
# CD, CM).
#
#     input:   4                            output:   IV
#     input:   1994                         output:   MCMXCIV
#     input:   3999                         output:   MMMCMXCIX
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py roman
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
