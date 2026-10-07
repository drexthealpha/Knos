# Test USDC, no monetary value.
# Run-length encode a line.
#
# Read one line of letters. Print each run of the same letter as the letter and the length of the run: aaabcc
# gives a3b1c2. Upper and lower case are different letters.
#
#     input:   aaabcc                       output:   a3b1c2
#     input:   abc                          output:   a1b1c1
#     input:   zzzzzzzzzzzz                 output:   z12
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py rle
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
