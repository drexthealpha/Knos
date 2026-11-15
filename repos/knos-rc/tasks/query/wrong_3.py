import sys


def solve(text):
    seen = {}
    for pair in text.strip().split("&"):
        key, _, value = pair.partition("=")
        seen.setdefault(key, []).append(value)
    return " ".join(f"{k}={','.join(sorted(seen[k]))}" for k in sorted(seen))


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
