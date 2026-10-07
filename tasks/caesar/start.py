# Test USDC, no monetary value.
# Shift the letters of a line.
#
# Read one line: a whole number, a space, then a text. Shift every letter of the text forward by that many
# places in the alphabet, wrapping from z to a. Keep the case. Leave every other character as it is. The number
# may be negative or larger than 26.
#
#     input:   3 Hello, World!              output:   Khoor, Zruog!
#     input:   -1 abc                       output:   zab
#     input:   27 Zebra 9                   output:   Afcsb 9
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py caesar
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
