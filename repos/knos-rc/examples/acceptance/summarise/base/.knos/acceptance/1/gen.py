"""Incident reports for the summarise task, and the reference summary each one is made from.

A report is built from three facts (the service, how long it was down, why, and what fixed it) told in one of three
shapes each, among sentences that are not part of the summary. The reference is written from the facts, so there is
no summariser here to copy."""
import random

SERVICES = ["billing-api", "search-api", "auth-service", "checkout-web", "image-resizer", "notify-worker", "report-batch",
            "gateway"]
CAUSES = {"an expired certificate": "renewed the certificate", "a full disk": "cleared the disk",
          "a bad configuration push": "rolled back the configuration", "a database failover": "promoted the replica",
          "an overloaded cache": "restarted the cache", "a memory leak": "restarted the workers"}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def facts(rng: random.Random) -> dict:
    cause = rng.choice(list(CAUSES))
    return {"service": rng.choice(SERVICES), "minutes": rng.randint(5, 240), "cause": cause, "fix": CAUSES[cause]}


def reference(f: dict) -> str:
    return f"{f['service']} was down for {f['minutes']} minutes because of {f['cause']}. The team {f['fix']}."


def report(rng: random.Random, f: dict) -> str:
    start = f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}"
    other = rng.choice([s for s in SERVICES if s != f["service"]])
    lost = rng.choice([c for c in CAUSES if c != f["cause"]])
    told = [
        rng.choice([f"The {f['service']} outage lasted {f['minutes']} minutes.",
                    f"Between {start} and the fix, {f['service']} was unavailable ({f['minutes']} minutes in total).",
                    f"Customers could not reach {f['service']} for {f['minutes']} minutes."]),
        rng.choice([f"The root cause was {f['cause']}.", f"Investigation showed that {f['cause']} had triggered the failure.",
                    f"The failure was traced to {f['cause']}."]),
        rng.choice([f"Engineers {f['fix']} and traffic recovered.", f"Service returned after the team {f['fix']}.",
                    f"The fix: the team {f['fix']}."]),
    ]
    around = rng.sample([
        f"The on-call engineer was paged at {start}.", f"A review meeting is set for {rng.choice(DAYS)}.",
        f"Last quarter {other} had a similar outage caused by {lost}, lasting {rng.randint(5, 240)} minutes.",
        f"{rng.randint(10, 95)}% of requests failed during the incident.", "No customer data was lost.",
        f"{other} was not affected.", f"The team will add an alert for {rng.choice(list(CAUSES))[2:]}.",
        f"Support answered {rng.randint(12, 400)} tickets about it."], rng.randint(3, 6))
    out = told[:]
    for s in around:
        out.insert(rng.randint(0, len(out)), s)
    return " ".join(out)
