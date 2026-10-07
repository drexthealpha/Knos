# Test USDC, no monetary value.
# Say whether the brackets of a line are balanced.
#
# Read one line. Print yes when its round, square and curly brackets are balanced and properly nested, else no.
# Ignore every other character.
#
#     input:   (a[b]{c})                    output:   yes
#     input:   (]                           output:   no
#     input:   (()                          output:   no
#
# As it is, this prints what it read. Write solve(), then try it:  python3 check.py brackets
import sys


def solve(text):
    return text.strip()


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
