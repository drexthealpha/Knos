"""Knos locked test: C-MAPSS FD001 raw Ridge Regression baseline.

Claim: Ridge regression (alpha = 1.0) on flattened, z-scored 30-cycle windows of the 14 informative
sensors, trained on the 80 FD001 engines left after an 80/20 engine split with seed 42 and with RUL
labels capped at 130, predicts the remaining useful life of the 100 FD001 test engines with
RMSE 16.634 and MAE 13.570 cycles (truth also capped at 130).
Source: Galchar S., Goel A., Kanu S., "Remaining Useful Life Estimation for Turbofan Engines: A
Comparative Study of Classical, CNN, and LSTM Approaches", arXiv:2604.27234v1 (29 Apr 2026),
Table III, row "Raw Ridge Regression", FD001 columns. https://arxiv.org/abs/2604.27234
Tolerance: the paper prints 3 decimals; we accept +/- 0.005 cycles on RMSE and on MAE.

Data: NASA Ames PCoE "Turbofan Engine Degradation Simulation Data Set" (Saxena & Goebel 2008),
FD001, trimmed to unit, cycle and the 14 sensors (original text tokens copied unchanged).

Usage: put the candidate module next to this file as solution.py (or set KNOS_MODULE=<module name>).
It must define predict_rul(train, test) -> sequence of 100 floats, one per test engine ordered by unit,
where train and test are numpy arrays with columns [unit, cycle, s2, s3, s4, s7, s8, s9, s11, s12,
s13, s14, s15, s17, s20, s21].
"""
import hashlib
import importlib
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SHA256 = {
    "train_FD001.txt": "d8b2bb85c6008823c6828b3faf86028fb603ab56c27d30bf6bd08601799a3cc0",
    "test_FD001.txt": "ee83d9abd21ab642b21f397c1b8e589b0ced222f37f4fb563dcf0ddbe30d5b5a",
    "RUL_FD001.txt": "ac81721ae8df4627c06b5f83e8ac02bf94a602713340bdf5cf02275054259733",
}
PUBLISHED_RMSE = 16.634
PUBLISHED_MAE = 13.570
TOL = 0.005
MAX_RUL = 130
TIME_LIMIT_S = 20.0


def _check_data():
    for name, want in SHA256.items():
        with open(os.path.join(DATA, name), "rb") as f:
            got = hashlib.sha256(f.read()).hexdigest()
        assert got == want, f"{name}: sha256 {got} != {want}"


def test_ridge_fd001_matches_published_rmse():
    t0 = time.perf_counter()
    _check_data()
    train = np.loadtxt(os.path.join(DATA, "train_FD001.txt"))
    test = np.loadtxt(os.path.join(DATA, "test_FD001.txt"))
    truth = np.minimum(np.loadtxt(os.path.join(DATA, "RUL_FD001.txt")), MAX_RUL)
    assert train.shape == (20631, 16) and test.shape == (13096, 16) and truth.shape == (100,)

    sys.path.insert(0, HERE)
    mod = importlib.import_module(os.environ.get("KNOS_MODULE", "solution"))
    pred = np.asarray(mod.predict_rul(train.copy(), test.copy()), dtype=float).ravel()
    elapsed = time.perf_counter() - t0

    assert pred.shape == (100,), f"expected 100 predictions, got {pred.shape}"
    assert np.all(np.isfinite(pred)), "non-finite prediction"
    err = pred - truth
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))
    print(f"RMSE={rmse:.4f} (published {PUBLISHED_RMSE})  MAE={mae:.4f} (published {PUBLISHED_MAE})  time={elapsed:.2f}s")
    assert elapsed < TIME_LIMIT_S, f"too slow: {elapsed:.1f}s"
    assert abs(rmse - PUBLISHED_RMSE) <= TOL, f"RMSE {rmse:.4f} not within {TOL} of {PUBLISHED_RMSE}"
    assert abs(mae - PUBLISHED_MAE) <= TOL, f"MAE {mae:.4f} not within {TOL} of {PUBLISHED_MAE}"


if __name__ == "__main__":
    try:
        test_ridge_fd001_matches_published_rmse()
    except AssertionError as e:
        print("FAIL:", e)
        sys.exit(1)
    print("PASS")
