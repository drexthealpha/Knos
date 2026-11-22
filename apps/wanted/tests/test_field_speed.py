"""L40: real visitors' speed at the 75th percentile, phones and desktops apart: from synthetic vitals the p75 of each
device class equals numpy.percentile's (linear) value; a class outside good (LCP 2.5 s, INP 200 ms, CLS 0.1) says so;
a class with no values says "no field data yet"."""
import random
import statistics

import pytest
from test_tool_run import app, call, program  # noqa: F401  (fixtures)

from knos_wanted import tool_run


def p75(xs):
    """numpy.percentile(xs, 75) when numpy is installed, else statistics' inclusive quantile, the same linear rule."""
    try:
        import numpy as np
        return float(np.percentile(xs, 75))
    except ImportError:
        return statistics.quantiles(xs, n=4, method="inclusive")[2]


def test_p75_per_device_matches_numpy():
    rng = random.Random(7)
    phone = {"lcp": [rng.uniform(800, 4000) for _ in range(97)], "inp": [rng.uniform(20, 400) for _ in range(97)], "cls": [rng.uniform(0, 0.3) for _ in range(97)]}
    desk = {"lcp": [rng.uniform(300, 1500) for _ in range(41)], "inp": [rng.uniform(10, 90) for _ in range(41)], "cls": [rng.uniform(0, 0.05) for _ in range(41)]}
    today = tool_run._today()
    doc = {"vitals": {today: {"tool": {"n": 138, "lcp": [], "inp": [], "cls": [], "by_device": {"phone": {"n": 97, **phone}, "desktop": {"n": 41, **desk}}}}}}
    got = tool_run.field_speed(doc=doc)["by_device"]
    for dev, v in (("phone", phone), ("desktop", desk)):
        for k in ("lcp", "inp", "cls"):
            assert got[dev][f"{k}_p75"] == pytest.approx(p75(v[k]), abs=1e-3)
    assert got["phone"]["good"] is False and got["desktop"]["good"] is True


def test_no_values_is_no_field_data_yet():
    assert tool_run.field_speed(doc={})["by_device"] == {"phone": {"status": "no field data yet"}, "desktop": {"status": "no field data yet"}}


def test_a_page_reports_its_device_class(app):  # noqa: F811
    b = {"browser": "b-speed-0000001", "screen": "tool", "lcp": 1200, "inp": 64, "cls": 0.01, "test": False}
    assert call(app, "/api/vitals", {**b, "device": "phone"})[0] == 200
    assert call(app, "/api/vitals", {**b, "device": "fridge"})[0] == 200                # an unknown class is kept with no class
    fs = call(app, "/api/usage")[1]["field_speed"]["by_device"]
    assert fs["phone"]["lcp_p75"] == 1200 and fs["phone"]["lcp_n"] == 1 and fs["desktop"] == {"status": "no field data yet"}
