"""The job's locked test: its sha256 is the job's criteria hash on chain. An output passes when this file, run next to
the output's solution.py, exits 0."""
from solution import slug

CASES = {
    "Hello, World!": "hello-world",
    "  Knos on NEAR  ": "knos-on-near",
    "Paid on proof: 100%": "paid-on-proof-100",
    "a--b__c": "a-b-c",
    "": "",
}

for given, want in CASES.items():
    got = slug(given)
    assert got == want, f"slug({given!r}) = {got!r}, want {want!r}"
print(f"{len(CASES)} of {len(CASES)} cases pass")
