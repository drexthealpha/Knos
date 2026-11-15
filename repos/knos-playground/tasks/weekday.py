# Test USDC, no monetary value.
# Name the day of the week of a date.
#
# Read one date written YYYY-MM-DD, from 1900-01-01 to 2100-12-31, in the Gregorian calendar. Print the English
# name of its day of the week, like Monday.
#
#     input:   2026-10-07                   output:   Wednesday
#     input:   2000-02-29                   output:   Tuesday
#     input:   1900-03-01                   output:   Thursday
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py weekday
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
