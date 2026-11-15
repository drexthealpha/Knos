# Test USDC, no monetary value.
# Wrap a text to a width.
#
# Read one line: a width (a whole number from 1 up), a space, then words separated by single spaces. Print the
# words on lines no longer than the width, as many words on each line as fit, with one space between words. A
# word longer than the width goes alone on its own line, whole.
#
#     input:   10 the quick brown fox       output:   the quick / brown fox
#     input:   3 a bb ccc dddd              output:   a / bb / ccc / dddd
#     input:   20 one                       output:   one
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py wrap
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
