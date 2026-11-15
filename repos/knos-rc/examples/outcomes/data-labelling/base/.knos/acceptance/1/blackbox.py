"""A labelled dataset, judged black-box. The deliverable is a file, labels.csv, so there is no code of the submitter's
to run: "$KNOS_RUN python3 -c ..." only reads the file out of the pull request's tree, inside the sandbox, and the
scoring happens here, as the judge, against gold.csv, which the judge takes out of the tree before anything runs.

Paid when all of these hold (every one that fails is printed, not only the first):
  schema       the header is id,label; every item of data/items.csv has exactly one row; every label is a class
  accuracy     at least ACCURACY of the 120 gold items, none of which was shown, carry the gold label
  floor        each class's recall on the gold items is at least FLOOR: a rare class cannot be given up
  no leakage   the 40 items that were shown with their label are not labelled better than the gold ones by more than
               GAP: a file that copies the visible answers and guesses the rest is that, whatever its accuracy"""
import csv
import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLASSES = ("account", "billing", "bug", "feature")
ACCURACY, FLOOR, GAP = 0.90, 0.80, 0.10
MOST = 1_000_000     # bytes of each file read
READ = "import sys; sys.stdout.buffer.write(open(sys.argv[1], 'rb').read(%d))" % (MOST + 1)


def read(path: str) -> list[dict]:
    """A CSV of the pull request's tree as rows, read inside the sandbox. Exits with a sentence when it is not one."""
    try:
        got = subprocess.run([os.environ["KNOS_RUN"], "python3", "-c", READ, path], capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        sys.exit(f"{path} could not be read in 30 seconds")
    if got.returncode:
        sys.exit(f"{path} is not in the pull request, or cannot be read")
    if len(got.stdout) > MOST:
        sys.exit(f"{path} is larger than {MOST} bytes")
    try:
        return list(csv.DictReader(io.StringIO(got.stdout.decode("utf-8"), newline="")))
    except (UnicodeDecodeError, csv.Error):
        sys.exit(f"{path} is not a UTF-8 CSV file")


def schema(rows: list[dict], ids: list[str]) -> list[str]:
    if not rows or list(rows[0]) != ["id", "label"]:
        return ["schema: labels.csv must start with the header id,label and hold one row per item"]
    seen = [r["id"] for r in rows]
    bad = []
    if len(set(seen)) != len(seen):
        bad.append("schema: an id has more than one row")
    if set(seen) != set(ids):
        bad.append(f"schema: {len(set(ids) - set(seen))} items have no label and {len(set(seen) - set(ids))} rows name no item")
    if any(r["label"] not in CLASSES for r in rows):
        bad.append(f"schema: a label is not one of {', '.join(CLASSES)}")
    return bad


def score(got: dict, truth: dict) -> tuple[float, dict]:
    """(accuracy, {class: recall}) of the labels on the items of `truth`."""
    recall = {c: sum(got[i] == c for i, t in truth.items() if t == c) / max(1, sum(t == c for t in truth.values())) for c in CLASSES}
    return sum(got[i] == t for i, t in truth.items()) / len(truth), recall


def check() -> list[str]:
    with open(os.path.join(HERE, "gold.csv"), encoding="utf-8", newline="") as fh:
        gold = {r["id"]: r["label"] for r in csv.DictReader(fh)}
    shown = {r["id"]: r["label"] for r in read("data/examples.csv")}       # the base's, unless the pull request changed it:
    shown = {i: t for i, t in shown.items() if i not in gold}               # a gold item is never a visible one
    rows = read("labels.csv")
    bad = schema(rows, [r["id"] for r in read("data/items.csv")])
    if bad or not set(gold) <= {r["id"] for r in rows}:
        return bad or ["schema: the items of data/items.csv are not the ones that were given out"]
    got = {r["id"]: r["label"] for r in rows}
    hidden, recall = score(got, gold)
    print(f"gold items: accuracy {hidden:.3f} (needs {ACCURACY}); recall " + ", ".join(f"{c} {recall[c]:.2f}" for c in CLASSES))
    if hidden < ACCURACY:
        bad.append(f"accuracy: {hidden:.3f} on the {len(gold)} gold items, below the {ACCURACY} that is paid")
    bad += [f"floor: class {c} has recall {recall[c]:.2f} on the gold items, below {FLOOR}" for c in CLASSES if recall[c] < FLOOR]
    if shown:
        visible = score(got, shown)[0]
        print(f"visible examples: accuracy {visible:.3f}")
        if visible - hidden > GAP:
            bad.append(f"leakage: the {len(shown)} items shown with their label score {visible:.3f} and the gold items {hidden:.3f}; "
                       f"a gap above {GAP} means the visible answers were copied and the rest were not labelled as well")
    return bad


if __name__ == "__main__":
    why = check()
    if why:
        sys.exit("\n".join(why))
    print("labels.csv is accepted")
