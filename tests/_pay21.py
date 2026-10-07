"""The knos_pay build the public program ids run until the upgrade to 2.2 executes (2.1, the 0.3.17 release's test
build), for tests that run one client against BOTH builds: the relay, the workflows and the commands decide by the
Version the cluster answers, never by the tree.

The file is not kept twice. Where the tree holds the live builds (tests/fixtures/live/) it is read from there; else
it is taken from the commit of the 0.3.17 release (`git show`) into a directory pytest made. Either way its bytes are
the pinned ones (SHA256), or the tests that need it are skipped with the reason.

    from _pay21 import BUILDS, Live, pay21_build      # noqa: F401 - the fixture `pay21`

    @pytest.fixture(scope="module", params=BUILDS, ids=Live.name, autouse=True)
    def live(request, pay21):
        yield from LIVE.run(request.param, pay21)

(A module imports the fixtures it uses by their function names, `pay21_build` and `each_build`; tests ask for them as
`pay21` and `build`.)

`LIVE.v` is then what Version answers (1 or 2), `LIVE.build` the knos_pay build to load, `LIVE.pick(old, new)` the
value a test pins for the build that is running."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
NAME = "knos_pay_v2_test.so"
RELEASE = "f03ec515d8666c46e3fdc6bb0123bc0786d5dd75"       # Knos 0.3.17
SHA256 = "575f1d38bab53a9e47582bade43d01c073d1b273766936febd6a6b996035a714"
BUILDS = (2, 1)         # what Version answers: knos_pay 2.2 (the tree's build), then 2.1 (the live one)


def _pinned(raw: bytes) -> bool:
    return hashlib.sha256(raw).hexdigest() == SHA256


@pytest.fixture(scope="session", name="pay21")
def pay21_build(tmp_path_factory) -> str:
    """The path of the 2.1 test build."""
    kept = FIX / "live" / NAME
    if kept.is_file() and _pinned(kept.read_bytes()):
        return str(kept)
    try:
        raw = subprocess.run(["git", "show", f"{RELEASE}:tests/fixtures/{NAME}"], cwd=FIX.parents[1], capture_output=True, check=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError) as why:
        pytest.skip(f"the knos_pay 2.1 build is not in tests/fixtures/live and git could not show it from the 0.3.17 release ({type(why).__name__})")
    if not _pinned(raw):
        pytest.skip("the knos_pay 2.1 build git showed is not the pinned one")
    out = tmp_path_factory.mktemp("pay21") / NAME
    out.write_bytes(raw)
    return str(out)


class Live:
    """Which knos_pay build the tests of a module are running against."""
    v: int = 2
    build: str = NAME

    @staticmethod
    def name(v: int) -> str:
        return f"pay2.{v}"

    def run(self, v: int, old: str):
        """A module fixture's body: this build until the fixture ends, and nothing the relay learned of another one
        (every LiteSVM cluster has one name, and the relay keeps a cluster's Version by its name)."""
        from knos.settle.v2 import relay
        self.v, self.build = v, NAME if v >= 2 else old
        relay.forget()
        try:
            yield v
        finally:
            self.v, self.build = 2, NAME
            relay.forget()

    def pick(self, old, new):
        """What a test pins for 2.1 (`old`, as 0.3.17 had it) and for 2.2 (`new`)."""
        return new if self.v >= 2 else old

    @property
    def new(self) -> bool:
        return self.v >= 2


# What each build charges, written here apart from knos.fees and knos.settle.v2.pay, for the fakes that stand in for
# a program (tests/_flow.py): 2.1 as programs-v2 had it at the 0.3.17 release, 2.2 as SPEC'd for 0.3.18.
def order_fee(v: int, amount: int, bps: int | None = None) -> int:
    """The fee an order's funder pays on top, in millionths, under the build that answers Version `v`."""
    if v >= 2:      # 0.30% (or a Plan's rate), at least 0.05; one rate
        return max(amount * (30 if bps is None else bps) // 10_000, 50_000)
    first = min(amount, 1_000_000_000)      # 2.5% (or a Plan's rate) of the first 1,000, 1% to 50,000, 0.5% above; at least 0.40
    second = min(amount, 50_000_000_000) - first
    return max(first * (250 if bps is None else bps) // 10_000 + second * 100 // 10_000 + (amount - first - second) * 50 // 10_000, 400_000)


def job_fee(v: int, amount: int) -> int:
    """The fee taken out of a job when it is paid: 0.30% under 2.2, 2.5% before; at least 0.05, never more than the job."""
    return min(max(amount * (30 if v >= 2 else 250) // 10_000, 50_000), amount)


@pytest.fixture(params=BUILDS, ids=Live.name, name="build")
def each_build(request, pay21):
    """For one test that runs a real cluster: it runs twice, and `build.build` is the knos_pay to load
    (`Chain(pay_build=build.build)`), `build.v` what its Version answers, `build.pick(old, new)` what to pin."""
    live = Live()
    for _ in live.run(request.param, pay21):
        yield live
