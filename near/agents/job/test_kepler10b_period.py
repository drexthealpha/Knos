"""LOCKED TEST: Kepler-10b orbital period from Kepler long-cadence photometry.

Claim: Batalha et al. 2011, ApJ 729, 27 (doi:10.1088/0004-637X/729/1/27), "Kepler's First
Rocky Planet: Kepler-10b": KOI-72.01 (Kepler-10b) transit ephemeris period
P = 0.837495 (+0.000004 / -0.000005) days.
Precision cross-check: NASA Exoplanet Archive, Q1-Q17 DR25 KOI table, KOI-72.01:
P = 0.837491225 +/- 0.000000303 days (we accept 3 sigma).

Data: kepler10_lc.csv (columns time_bkjd, flux_norm, quarter), built from the 15 public
Kepler llc.fits files of KIC 11904151 at MAST. Its sha256 is pinned below.

The module under test must be importable as `kepler10b_period` and provide
find_period(time, flux, quarter) -> float (days). numpy + stdlib only.
"""
import hashlib
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "kepler10_lc.csv")
DATA_SHA256 = "750794532959559fcf2189c89f0ea8253a6e3726b1f6c1a3db77b5bf80ee4721"

P_PUB = 0.837495            # Batalha et al. 2011
P_PUB_HI = P_PUB + 0.000004
P_PUB_LO = P_PUB - 0.000005
P_DR25 = 0.837491225        # Kepler Q1-Q17 DR25 KOI table
P_DR25_SIG = 0.000000303
TIME_LIMIT_S = 20.0


def main():
    with open(DATA, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    assert digest == DATA_SHA256, "data file changed: %s" % digest

    d = np.loadtxt(DATA, delimiter=",", skiprows=1)
    assert d.shape == (45514, 3), d.shape
    t, flux, q = d[:, 0].copy(), d[:, 1].copy(), d[:, 2].astype(int)

    sys.path.insert(0, os.environ.get("KNOS_MODULE_DIR", HERE))
    from kepler10b_period import find_period

    t0 = time.perf_counter()
    P = float(find_period(t, flux, q))
    dt = time.perf_counter() - t0
    print("period found: %.7f d   runtime: %.2f s" % (P, dt))

    assert np.isfinite(P), "period is not finite"
    assert dt < TIME_LIMIT_S, "too slow: %.1f s" % dt
    assert P_PUB_LO <= P <= P_PUB_HI, (
        "FAIL: %.7f d outside Batalha et al. 2011 interval [%.6f, %.6f]" % (P, P_PUB_LO, P_PUB_HI))
    assert abs(P - P_DR25) <= 3 * P_DR25_SIG, (
        "FAIL: %.7f d is more than 3 sigma from DR25 %.9f" % (P, P_DR25))
    print("PASS: Kepler-10b period %.7f d matches 0.837495 (+0.000004/-0.000005) d" % P)


if __name__ == "__main__":
    main()
