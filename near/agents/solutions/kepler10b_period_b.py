"""Agent B shortcut: the 'tutorial' Box Least Squares search.
Same detrending and same BLS statistic as the reference, but the careless part is the
period grid: 10,000 evenly spaced trial periods between 0.5 and 5 days (a step of
4.5e-4 d), taking the argmax directly with no refinement. That grid is fine for one
quarter of data but far too coarse for a 4-year baseline: over ~1750 orbits a period
error of only ~5e-5 d shifts the last transits by ~0.09 d, more than the 1.8-hour
transit itself, so the true period is never sampled and a nearby grid point wins."""
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
    time = np.asarray(time, float); flux = np.asarray(flux, float); quarter = np.asarray(quarter)
    o = np.argsort(time)
    time, flux, quarter = time[o], flux[o], quarter[o]
    rel = detrend(time, flux, quarter)
    mad = np.median(np.abs(rel - np.median(rel))) * 1.4826
    keep = (rel < 4 * mad) & (rel > -20 * mad)
    time, rel = time[keep], rel[keep]
    w = np.ones_like(rel) / rel.size
    y = rel - np.sum(w * rel)
    periods = np.linspace(pmin, pmax, 10000)
    p = _bls_power(time, y, w, 1.0 / periods, 600, (0.05, 0.075, 0.10))
    return float(periods[np.argmax(p)])
