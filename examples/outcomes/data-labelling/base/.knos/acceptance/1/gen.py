"""How this example's data were made: 400 support messages, each written from one of four classes. Fixed seed, so
`python gen.py <base folder>` writes the same data/items.csv, data/examples.csv and gold.csv (beside this file) again.

In a real order the messages are the buyer's and the gold labels are a person's; a generator stands in for both here
so that the example has no data it cannot account for."""
import csv
import io
import random
import sys
from pathlib import Path

SEED = 20261005
CLASSES = ("account", "billing", "bug", "feature")
ITEMS, VISIBLE, GOLD = 400, 40, 120
CORE = {
    "account": ["I cannot log in since this morning", "please reset my password", "I need to change the email on my profile",
                "how do I delete my account", "the two-factor code never arrives", "my login is locked after three tries"],
    "billing": ["I was charged twice this month", "the invoice shows the wrong amount", "I would like a refund for the last payment",
                "my card was declined at renewal", "where is the receipt for my payment", "the price of my plan went up without notice"],
    "bug": ["the app crashes when I open a report", "the export page shows error 500", "the screen freezes while saving",
            "the dashboard does not load on mobile", "search returns the same row twice", "the chart shows a wrong total"],
    "feature": ["it would be great to have dark mode", "please add an export to spreadsheet", "could you support single sign-on",
                "I wish there was a weekly summary email", "can you add keyboard shortcuts", "a way to share a report by link would help"],
}
ASIDE = {    # said in passing in a message of another class: what makes a keyword count get some wrong
    "account": ["after I logged in", "from my account page", "once my password was accepted"],
    "billing": ["on the paid plan", "since my last invoice", "right after the payment page"],
    "bug": ["it is not an error on your side", "nothing crashes", "no bug as far as I can tell"],
    "feature": ["as you added last month", "like the new feature does", "unlike the option you added"],
}
OPEN = ["Hello,", "Hi team,", "Good morning,", "", "Quick one:", "Support,"]
CLOSE = ["Thanks.", "Please advise.", "", "Regards, a customer.", "This is urgent.", "No rush."]


def items(rng: random.Random) -> list[tuple[str, str, str]]:
    """[(id, text, class)]: a balanced, shuffled set. One message in four mentions another class in passing."""
    out = []
    for n in range(ITEMS):
        cls = CLASSES[n % 4]
        said = rng.choice(CORE[cls])
        if rng.random() < 0.25:
            said += ", " + rng.choice(ASIDE[rng.choice([c for c in CLASSES if c != cls])])
        out.append((" ".join(p for p in (rng.choice(OPEN), said + ".", rng.choice(CLOSE)) if p), cls))
    rng.shuffle(out)
    return [(f"m{n + 1:04d}", text, cls) for n, (text, cls) in enumerate(out)]


def split(rows: list, rng: random.Random) -> tuple[list, list]:
    """(visible, gold): two disjoint samples. The visible ones go to the labeller with their label; the gold ones stay here."""
    picked = rng.sample(rows, VISIBLE + GOLD)
    return sorted(picked[:VISIBLE]), sorted(picked[VISIBLE:])


def table(header: str, rows: list) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows([header.split(","), *rows])
    return out.getvalue()


def main(base: Path) -> None:
    rng = random.Random(SEED)
    rows = items(rng)
    visible, gold = split(rows, rng)
    here = Path(__file__).resolve().parent
    (base / "data").mkdir(exist_ok=True)
    (base / "data" / "items.csv").write_text(table("id,text", [r[:2] for r in rows]), encoding="utf-8", newline="\n")
    (base / "data" / "examples.csv").write_text(table("id,text,label", visible), encoding="utf-8", newline="\n")
    (here / "gold.csv").write_text(table("id,label", [(r[0], r[2]) for r in gold]), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
