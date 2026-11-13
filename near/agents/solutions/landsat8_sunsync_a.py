"""Agent A reference: Earth-orbit propagator with point-mass gravity plus the J2
(Earth oblateness) term, integrated with classical 4th-order Runge-Kutta.

Interface used by the locked test:
    propagate(r0, v0, mu, re, j2, t_end, n_out) -> (t, states)
      r0, v0 : initial position (km) and velocity (km/s), Earth-centred inertial,
               z axis = Earth's rotation axis
      mu     : GM of Earth (km^3/s^2); re: equatorial radius (km); j2: J2 (dimensionless)
      t_end  : propagation time (s); n_out: number of equal output intervals
      returns t (n_out+1,) and states (n_out+1, 6) = [x, y, z, vx, vy, vz]
"""
import math
import numpy as np

MAX_STEP = 10.0  # seconds


def _accel(x, y, z, mu, re, j2):
    r2 = x * x + y * y + z * z
    r = math.sqrt(r2)
    r3 = r2 * r
    k = 1.5 * j2 * re * re / r2
    zr2 = 5.0 * z * z / r2
    fxy = -mu / r3 * (1.0 + k * (1.0 - zr2))
    fz = -mu / r3 * (1.0 + k * (3.0 - zr2))
    return fxy * x, fxy * y, fz * z


def propagate(r0, v0, mu, re, j2, t_end, n_out):
    n_out = int(n_out)
    sub = max(1, int(math.ceil((t_end / n_out) / MAX_STEP)))
    h = t_end / (n_out * sub)
    x, y, z = (float(c) for c in r0)
    vx, vy, vz = (float(c) for c in v0)
    out = np.empty((n_out + 1, 6))
    out[0] = (x, y, z, vx, vy, vz)
    h2 = 0.5 * h
    h6 = h / 6.0
    for k in range(1, n_out + 1):
        for _ in range(sub):
            a1x, a1y, a1z = _accel(x, y, z, mu, re, j2)
            x2, y2, z2 = x + h2 * vx, y + h2 * vy, z + h2 * vz
            u2x, u2y, u2z = vx + h2 * a1x, vy + h2 * a1y, vz + h2 * a1z
            a2x, a2y, a2z = _accel(x2, y2, z2, mu, re, j2)
            x3, y3, z3 = x + h2 * u2x, y + h2 * u2y, z + h2 * u2z
            u3x, u3y, u3z = vx + h2 * a2x, vy + h2 * a2y, vz + h2 * a2z
            a3x, a3y, a3z = _accel(x3, y3, z3, mu, re, j2)
            x4, y4, z4 = x + h * u3x, y + h * u3y, z + h * u3z
            u4x, u4y, u4z = vx + h * a3x, vy + h * a3y, vz + h * a3z
            a4x, a4y, a4z = _accel(x4, y4, z4, mu, re, j2)
            x += h6 * (vx + 2 * u2x + 2 * u3x + u4x)
            y += h6 * (vy + 2 * u2y + 2 * u3y + u4y)
            z += h6 * (vz + 2 * u2z + 2 * u3z + u4z)
            vx += h6 * (a1x + 2 * a2x + 2 * a3x + a4x)
            vy += h6 * (a1y + 2 * a2y + 2 * a3y + a4y)
            vz += h6 * (a1z + 2 * a2z + 2 * a3z + a4z)
        out[k] = (x, y, z, vx, vy, vz)
    t = np.linspace(0.0, t_end, n_out + 1)
    return t, out
