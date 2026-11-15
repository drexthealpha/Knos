"""The naive check, kept beside the real one to show what it lets through: it runs inside the pull request's tree
(in-process) and knows only what the labeller was also given, the 40 visible examples. A labels.csv that copies those
40 answers and guesses the other 360 passes it. Nobody should fund on this bundle; bundle 1 is the one that is paid."""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CLASSES = {"account", "billing", "bug", "feature"}


def rows(path: str) -> list[dict]:
    with open(ROOT / path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_every_item_has_one_label_of_a_known_class():
    got = rows("labels.csv")
    assert [r["id"] for r in got] and sorted(r["id"] for r in got) == sorted(r["id"] for r in rows("data/items.csv"))
    assert {r["label"] for r in got} <= CLASSES


def test_the_visible_examples_are_labelled_as_shown():
    got = {r["id"]: r["label"] for r in rows("labels.csv")}
    shown = rows("data/examples.csv")
    assert sum(got.get(r["id"]) == r["label"] for r in shown) / len(shown) >= 0.90
