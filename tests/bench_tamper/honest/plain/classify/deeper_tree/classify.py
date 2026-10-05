"""Hold (1) or pass (0) each payment read on stdin. The rules are a decision tree kept in model/rules.json, learned
beforehand from data/train.csv (seven levels, at least 40 payments in a leaf)."""
import json
import pathlib
import sys

RULES = json.loads((pathlib.Path(__file__).resolve().parent / "model" / "rules.json").read_text(encoding="utf-8"))


def hold(payment: list) -> int:
    node = RULES
    while "label" not in node:
        node = node["lo"] if payment[node["f"]] <= node["t"] else node["hi"]
    return node["label"]


def main() -> None:
    lines = sys.stdin.read().splitlines()[1:]
    answers = [str(hold([float(cell) for cell in line.split(",")])) for line in lines if line.strip()]
    sys.stdout.write("\n".join(answers) + "\n")


if __name__ == "__main__":
    main()
