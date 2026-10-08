"""The round `judge`: a judge hosted by an outside evaluator. An order needs two judges; the run in the order's own
repository is one, and the second is a run of the pinned attest workflow that ANOTHER account started in a repository
of its own (examples/knos-attest.yml, docs/ATTESTOR.md: host a judge). Two owners' runs pay; the host is paid nothing.

    python scripts/exercise_public.py run --only judge --simulate --neutral host/knos-judge
    python scripts/exercise_public.py run --only judge --rpc URL --keys DIR --neutral OWNER/REPO [--resume]

`--neutral` names the host's repository: it is read for the host's token and never written to. Without one the round
ends 3. On the simulator the host is a second account of the test forge. The steps are those of the release's
`two_owners` step (scripts/exercise_public.py `rc_two_owners`), on an order of this round's own; then the level a
receipt would read is computed by knos.host_judge from the claims GitHub signed for the host's run. `xp` is
scripts/exercise_public.py, put here by its loader.
"""
from __future__ import annotations

ROUND = {"name": "judge", "needs": ("knos_oidc", "knos_pay", "neutral"), "caps": ("host_a_judge",), "phase": "after"}


def run(book, st: dict) -> None:
    """A judge hosted by an outside evaluator: the order's own run and a run another account started in its own
    repository are two judges of two owners, and the order pays."""
    from knos import host_judge
    from knos.settle.v2 import pay
    xp.rc_two_owners(book, st)        # noqa: F821
    if "host" in st:
        return
    host = xp.Tok(**st["tokens"]["other"])        # noqa: F821
    payees = [int(i) for i, _bps, _wallet in pay.payees_of(host.aud)]
    buyers = (st["one"]["owner"], st["one"]["actor"])
    entry = host_judge.entry("neutral", host.c, buyers, payees)
    xp._check(int(host.c["repository_owner_id"]) not in buyers and int(host.c["actor_id"]) not in buyers,        # noqa: F821
              "the second judge's run belongs to the order's own owner or starter: that is no host")
    level = host_judge.level([entry], payees)
    st["host"] = {"owner": int(host.c["repository_owner_id"]), "started_by": int(host.c["actor_id"]), "repository": int(host.c["repository_id"]),
                  "independent_of_seller": entry.get("independent_of_seller"), "level": level["level"], "says": level["says"]}
    book.done(st, "host_a_judge", "knos_pay", st["paid"]["signature"],
              [f"the order needed two judges; the run in its own repository was one (owner {st['one']['owner']})",
               f"the second was a run account {st['host']['started_by']} started in a repository of its own (owner {st['host']['owner']}), and the order paid",
               f"a receipt of this payment would read `{level['level']}` for that host: this round's host read GitHub's record of the merge and ran no suite"])


simulate = run
