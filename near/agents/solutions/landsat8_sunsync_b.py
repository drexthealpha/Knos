"""Agent B shortcut: 'J2 is only a 0.1 % correction to gravity, so drop it.'
Same RK4 integrator and interface as agent A, but pure two-body (point-mass) gravity.
The j2 argument is accepted and ignored.
"""
import math
import numpy as np

MAX_STEP = 10.0


def _accel(x, y, z, mu):
    r2 = x * x + y * y + z * z
    f = -mu / (r2 * math.sqrt(r2))
    return f * x, f * y, f * z


def propagate(r0, v0, mu, re, j2, t_end, n_out):
    n_out = int(n_out)
    sub = max(1, int(math.ceil((t_end / n_out) / MAX_STEP)))
    h = t_end / (n_out * sub)
    y = np.array(list(r0) + list(v0), dtype=float)
    out = np.empty((n_out + 1, 6))
    out[0] = y

    def f(s):
        ax, ay, az = _accel(s[0], s[1], s[2], mu)
        return np.array([s[3], s[4], s[5], ax, ay, az])

    for k in range(1, n_out + 1):
        for _ in range(sub):
            k1 = f(y)
            k2 = f(y + 0.5 * h * k1)
            k3 = f(y + 0.5 * h * k2)
            k4 = f(y + h * k3)
            y = y + h / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        out[k] = y
    return np.linspace(0.0, t_end, n_out + 1), out
