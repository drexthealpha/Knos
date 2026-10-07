import sys


def solve(text):
    first, *words = text.split()
    width, s = int(first), " ".join(words)
    return "\n".join(s[i:i + width].strip() for i in range(0, len(s), width))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
