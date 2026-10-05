"""How labels.csv was made: each message gets the class whose phrases it uses most; a phrase that only mentions a
class in passing ("nothing crashes", "since my last invoice") is taken out first. `python label.py` in the repository
root writes labels.csv again, byte for byte. The 40 labelled examples were read to write the phrase lists and are not
looked up: an item is labelled from its text alone."""
import csv

PHRASES = {
    "account": ["log in", "login", "password", "email on my profile", "delete my account", "two-factor"],
    "billing": ["charged", "invoice", "refund", "card", "receipt", "price of my plan"],
    "bug": ["crashes", "error 500", "freezes", "does not load", "twice", "wrong total"],
    "feature": ["would be great", "please add", "could you support", "wish there was", "can you add", "would help"],
}
IN_PASSING = ["after i logged in", "from my account page", "once my password was accepted", "on the paid plan", "since my last invoice",
              "after the payment page", "not an error on your side", "nothing crashes", "no bug", "as you added", "new feature does",
              "the option you added"]


def label(text: str) -> str:
    said = text.lower()
    for aside in IN_PASSING:
        said = said.replace(aside, " ")
    score = {cls: sum(said.count(p) for p in phrases) for cls, phrases in PHRASES.items()}
    return max(sorted(score), key=lambda cls: score[cls])


if __name__ == "__main__":
    with open("data/items.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with open("labels.csv", "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows([["id", "label"], *([r["id"], label(r["text"])] for r in rows)])
