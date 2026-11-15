# Test USDC, no monetary value.
# Check a number with the Luhn rule.
#
# Read one line of digits. Print valid when it passes the Luhn check, else invalid. Starting from the rightmost
# digit and moving left, double every second digit; when a doubled digit is above 9, subtract 9; the number is
# valid when the sum of all digits is a multiple of 10.
#
#     input:   79927398713                  output:   valid
#     input:   79927398710                  output:   invalid
#     input:   0                            output:   valid
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py luhn
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
