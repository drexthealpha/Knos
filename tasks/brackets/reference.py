import sys


def solve(text):
    pairs, stack = {")": "(", "]": "[", "}": "{"}, []
    for c in text:
        if c in "([{":
            stack.append(c)
        elif c in pairs:
            if not stack or stack.pop() != pairs[c]:
                return "no"
    return "no" if stack else "yes"


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
