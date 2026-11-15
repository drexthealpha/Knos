# Test USDC, no monetary value.
# Name the most frequent word of a line.
#
# Read one line of words separated by spaces. Print the word that occurs most often, in lower case. Upper and
# lower case count as the same word. When several words tie, print the one that comes first in alphabetical
# order.
#
#     input:   the cat and the hat          output:   the
#     input:   b a B A                      output:   a
#     input:   One                          output:   one
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py top-word
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
