# Test USDC, no monetary value.
# Count the minutes between two clock times.
#
# Read one line with two times of day written HH:MM (24-hour clock), separated by a space. Print the whole
# number of minutes from the first to the second. When the second is earlier, it is on the next day; equal times
# give 0.
#
#     input:   09:15 10:00                  output:   45
#     input:   23:50 00:10                  output:   20
#     input:   12:00 12:00                  output:   0
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py minutes
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
