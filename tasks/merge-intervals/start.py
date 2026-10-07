# Test USDC, no monetary value.
# Merge overlapping intervals.
#
# Read one line of intervals written a-b (whole numbers from 0 up, a not above b), separated by spaces, in any
# order. Merge the ones that overlap or touch at an end point (1-3 and 3-5 give 1-5; 1-3 and 4-5 stay apart).
# Print the result in rising order, separated by spaces.
#
#     input:   1-3 2-6 8-10                 output:   1-6 8-10
#     input:   5-7 1-2                      output:   1-2 5-7
#     input:   1-3 3-5                      output:   1-5
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py merge-intervals
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
