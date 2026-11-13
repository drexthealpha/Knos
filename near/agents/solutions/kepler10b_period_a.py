"""Agent A reference: recover Kepler-10b's orbital period from Kepler long-cadence PDCSAP photometry.

Method (numpy + stdlib only):
 1. Detrend each quarter with a running median (1.0-day window) -> relative flux.
 2. Sigma-clip upward outliers.
 3. Coarse Box Least Squares (BLS) search, 0.5-5 d, on a frequency grid fine enough for the
    full ~4-year baseline, using phase-binned sums (np.bincount) per trial frequency.
 4. Refine around the best peak with a much finer grid and a finer phase binning.
Public entry point: find_period(time, flux, quarter) -> period in days.
"""
import numpy as np


def detrend(time, flux, quarter, window=1.0):
    out = np.empty_like(flux)
    for q in np.unique(quarter):
        m = quarter == q
        t, f = time[m], flux[m]
        # running median over a sliding time window
        lo = np.searchsorted(t, t - window / 2)
        hi = np.searchsorted(t, t + window / 2)
        med = np.empty_like(f)
        for i in range(t.size):
            med[i] = np.median(f[lo[i]:hi[i]])
        out[m] = f / med - 1.0
    return out


def _bls_power(time, y, w, freqs, nbins, durations):
    """Return BLS signal-residue power for each trial frequency.
    durations are box widths in days, converted to phase bins per frequency.
    y: flux minus weighted mean; w: weights (sum to 1)."""
    power = np.empty(freqs.size)
    t0 = time[0]
    dt = time - t0
    for k, fr in enumerate(freqs):
        ph = (dt * fr) % 1.0
        b = (ph * nbins).astype(np.int64)
        sw = np.bincount(b, weights=w, minlength=nbins)
        sy = np.bincount(b, weights=w * y, minlength=nbins)
        best = 0.0
        dur_bins = sorted(set(max(1, int(round(D * fr * nbins))) for D in durations))
        for d in dur_bins:
            # circular box sums of width d bins
            cw = np.concatenate([sw, sw[:d]]).cumsum()
            cy = np.concatenate([sy, sy[:d]]).cumsum()
            r = cw[d:] - cw[:-d]
            s = cy[d:] - cy[:-d]
            ok = (r > 0) & (r < 1)
            sr = np.zeros_like(r)
            sr[ok] = s[ok] ** 2 / (r[ok] * (1 - r[ok]))
            # transits are dips -> require s < 0
            sr[s >= 0] = 0.0
            v = sr.max()
            if v > best:
                best = v
        power[k] = best
    return power


def find_period(time, flux, quarter, pmin=0.5, pmax=5.0):
    time = np.asarray(time, float)
    flux = np.asarray(flux, float)
    quarter = np.asarray(quarter)
    o = np.argsort(time)
    time, flux, quarter = time[o], flux[o], quarter[o]
    rel = detrend(time, flux, quarter)
    # clip upward outliers and extreme points
    mad = np.median(np.abs(rel - np.median(rel))) * 1.4826
    keep = (rel < 4 * mad) & (rel > -20 * mad)
    time, rel = time[keep], rel[keep]
    w = np.ones_like(rel) / rel.size
    y = rel - np.sum(w * rel)

    baseline = time[-1] - time[0]
    qdur = 0.075  # ~1.8 h transit duration guess, days
    # frequency step: phase drift over the baseline stays well under one transit duration
    df = qdur / baseline / 1.5 / 2.0
    # coarse search on the first 120 days only: a shorter baseline needs a coarser frequency step, so far fewer trials
    # (the same BLS statistic; hierarchical search, Knos's speed-up of 13 Nov 2026 to fit the locked 20 s on a server)
    year = time < time[0] + 120.0
    dfy = qdur / (time[year][-1] - time[year][0]) / 1.5 / 2.0
    freqs = np.arange(1.0 / pmax, 1.0 / pmin, dfy * 3)
    wy = np.ones(int(year.sum())) / year.sum()
    yy = rel[year] - rel[year].mean()
    p = _bls_power(time[year], yy, wy, freqs, 300, (0.05, 0.075, 0.10))
    f0 = freqs[np.argmax(p)]
    # Refine 1: full data, around f0, across the coarse step
    fr = np.arange(f0 - 3 * dfy, f0 + 3 * dfy, df / 2)
    p = _bls_power(time, y, w, fr, 600, (0.05, 0.06, 0.075, 0.09))
    f1 = fr[np.argmax(p)]
    # Refine 2: very fine
    fr = np.arange(f1 - df, f1 + df, df / 100)
    p = _bls_power(time, y, w, fr, 1500, (0.06, 0.07, 0.075, 0.08))
    f2 = fr[np.argmax(p)]
    return 1.0 / f2
