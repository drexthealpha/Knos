"""LOCKED TEST: Landsat 8's published orbit (705 km altitude, 98.2 deg inclination,
NASA) is sun-synchronous: Earth's oblateness (J2) turns the orbit plane eastward by
360 deg per tropical year = 0.98565 deg/day, and one revolution takes ~99 minutes.

The test builds the initial state from the published numbers, calls the candidate's
numerical propagator, and measures everything from the returned trajectory itself.
No answer is accepted from the candidate directly.

Candidate module (default name 'solution', override with env SOLUTION_MODULE) must
provide propagate(r0, v0, mu, re, j2, t_end, n_out) -> (t, states[n_out+1, 6]).

Data (NASA, US public domain), locked by sha256:
  data/earthfact.html  https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html
  data/landsat8.html   https://landsat.gsfc.nasa.gov/satellites/landsat-8/
"""
import hashlib
import importlib
import math
import os
import re
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data")
SHA256 = {
    "earthfact.html": "1b06e3ec31249d063d40d1b38837fac89ddcd2f4b25268b38e8a6d5f413e70ef",
    "landsat8.html": "7f9d677bd52b2b36e744eda76c1ca5d572b8e4e5f1d8b41b722dd73e57fd0b40",
}
DAY = 86400.0
RAAN_TOL = 0.01      # 1 %: 98.2 deg is rounded to 0.1 deg, i.e. +-0.6 % in cos(i)
PERIOD_TOL_MIN = 0.5  # "99 minutes" is rounded to the minute
TIME_LIMIT = 18.0


def _read(name):
    path = os.path.join(DATA, name)
    with open(path, "rb") as f:
        raw = f.read()
    got = hashlib.sha256(raw).hexdigest()
    assert got == SHA256[name], f"{name}: sha256 {got} does not match locked value"
    return raw.decode("utf-8", "replace")


def _num(text, label_regex):
    m = re.search(label_regex + r"[^0-9\-]*(-?[0-9]+(?:\.[0-9]+)?)", text)
    assert m, f"could not find {label_regex!r}"
    return float(m.group(1))


def load_constants():
    earth = re.sub(r"<[^>]*>", "", _read("earthfact.html"))
    l8 = re.sub(r"<[^>]*>", " ", _read("landsat8.html"))
    c = {
        "mu": _num(earth, r"GM \(x 106 km3/s2\)") * 1e6,          # km^3/s^2
        "re": _num(earth, r"Equatorial radius \(km\)"),          # km
        "j2": _num(earth, r"J2 \(x 10-6\)") * 1e-6,
        "tropical_year": _num(earth, r"Tropical orbit period \(days\)"),
        "alt": _num(l8, r"Altitude:"),                           # km
        "inc": _num(l8, r"Inclination:"),                        # deg
        "period_min": _num(l8, r"Period of Revolution:"),        # minutes
    }
    return c


def circular_ic(c, inc_deg):
    a = c["re"] + c["alt"]
    v = math.sqrt(c["mu"] / a)
    i = math.radians(inc_deg)
    return np.array([a, 0.0, 0.0]), np.array([0.0, v * math.cos(i), v * math.sin(i)])


def energy(s, c):
    r = np.linalg.norm(s[:, :3], axis=1)
    v2 = np.sum(s[:, 3:] ** 2, axis=1)
    sz = s[:, 2] / r
    u = -c["mu"] / r + c["mu"] * c["j2"] * c["re"] ** 2 * (3 * sz ** 2 - 1) / (2 * r ** 3)
    return 0.5 * v2 + u


def raan_rate_deg_per_day(t, s):
    h = np.cross(s[:, :3], s[:, 3:])
    raan = np.unwrap(np.arctan2(h[:, 0], -h[:, 1]))
    slope = np.polyfit(t / DAY, np.degrees(raan), 1)[0]
    return slope, h


def nodal_period_min(t, s):
    z = s[:, 2]
    idx = np.where((z[:-1] < 0) & (z[1:] >= 0))[0]
    tc = t[idx] - z[idx] * (t[idx + 1] - t[idx]) / (z[idx + 1] - z[idx])
    assert len(tc) >= 10, "too few ascending-node crossings"
    return np.mean(np.diff(tc)) / 60.0


def run(mod, c, inc, days, n_per_day=1440):
    r0, v0 = circular_ic(c, inc)
    t, s = mod.propagate(r0, v0, c["mu"], c["re"], c["j2"], days * DAY, int(days * n_per_day))
    t = np.asarray(t, float)
    s = np.asarray(s, float)
    assert s.shape == (int(days * n_per_day) + 1, 6), f"bad states shape {s.shape}"
    assert np.allclose(s[0], np.concatenate([r0, v0])), "first state must be the initial state"
    assert np.all(np.isfinite(s)), "non-finite states"
    return t, s


def check_physics(t, s, c, label):
    e = energy(s, c)
    de = np.max(np.abs(e - e[0]) / abs(e[0]))
    h = np.cross(s[:, :3], s[:, 3:])
    dlz = np.max(np.abs(h[:, 2] - h[0, 2])) / np.linalg.norm(h[0])
    r = np.linalg.norm(s[:, :3], axis=1)
    print(f"[{label}] max rel energy error {de:.2e}, max rel Lz error {dlz:.2e}, "
          f"radius {r.min():.1f}..{r.max():.1f} km")
    # The J2 field conserves total energy (incl. the J2 term) and the polar component
    # of angular momentum. A two-body or coarse integrator violates these.
    assert de < 1e-7, f"[{label}] energy (with J2 potential) not conserved: {de:.2e}"
    assert dlz < 1e-7, f"[{label}] Lz not conserved: {dlz:.2e}"
    assert r.min() > c["re"] + 650 and r.max() < c["re"] + 760, f"[{label}] radius off"


def main():
    start = time.time()
    modname = os.environ.get("SOLUTION_MODULE", "solution")
    mod = importlib.import_module(modname)
    c = load_constants()
    target = 360.0 / c["tropical_year"]
    print("constants:", c)

    # 1. Landsat 8 published orbit, 5 days
    t, s = run(mod, c, c["inc"], 5)
    check_physics(t, s, c, "Landsat 8")
    rate, _ = raan_rate_deg_per_day(t, s)
    pn = nodal_period_min(t, s)
    print(f"[Landsat 8] RAAN rate {rate:.5f} deg/day (sun-synchronous target {target:.5f}, "
          f"rel err {abs(rate - target) / target:.2%}); nodal period {pn:.3f} min "
          f"(published {c['period_min']:.0f}); {1440 / pn:.2f} orbits/day")
    assert abs(rate - target) <= RAAN_TOL * target, "orbit is not sun-synchronous within 1 %"
    assert abs(pn - c["period_min"]) <= PERIOD_TOL_MIN, "period does not match 99 minutes"

    # 2. Controls against hard-coding: a polar orbit must not precess, and a
    #    prograde 60 deg orbit must precess westward at the first-order J2 rate.
    t, s = run(mod, c, 90.0, 2)
    check_physics(t, s, c, "polar")
    rate90, _ = raan_rate_deg_per_day(t, s)
    print(f"[polar] RAAN rate {rate90:.5f} deg/day (expected ~0)")
    assert abs(rate90) < 0.01, "polar orbit should not precess"

    t, s = run(mod, c, 60.0, 2)
    check_physics(t, s, c, "i=60")
    rate60, _ = raan_rate_deg_per_day(t, s)
    a = c["re"] + c["alt"]
    n = math.sqrt(c["mu"] / a ** 3)
    exp60 = math.degrees(-1.5 * n * c["j2"] * (c["re"] / a) ** 2 * math.cos(math.radians(60))) * DAY
    print(f"[i=60] RAAN rate {rate60:.5f} deg/day (first-order J2 {exp60:.5f})")
    assert abs(rate60 - exp60) <= 0.02 * abs(exp60), "i=60 precession wrong"

    elapsed = time.time() - start
    print(f"elapsed {elapsed:.2f} s")
    assert elapsed < TIME_LIMIT, "too slow"
    print("PASS")


def test_landsat8_sun_synchronous():
    main()


if __name__ == "__main__":
    main()
