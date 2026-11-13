"""Agent A: reference solution for the Knos claim
"Raw Ridge Regression on C-MAPSS FD001 gives test RMSE 16.634 (MAE 13.570)"
(Galchar, Goel, Kanu, arXiv:2604.27234v1, Table III).

Protocol, as written in the paper (Sec. III, Algorithm 1):
  * 14 sensors kept (s1, s5, s6, s10, s16, s18, s19 dropped)  -> the trimmed data files hold exactly these
  * per-cycle RUL label = cycles left until failure, clipped at MAX_RUL = 130
  * 80/20 split by engine ID, random seed 42 (sklearn train_test_split semantics:
    RandomState(42).permutation(n); first 20% of the permutation is validation, the rest is training)
  * sliding windows of 30 cycles, stride 1, label = RUL at the window's last cycle
  * each window flattened (30 x 14 = 420 features), z-score normalised (fit on training windows only)
  * Ridge regression, L2 penalty alpha = 1.0, with intercept
  * test: last 30 cycles of each engine (zero-pad if shorter), predict one RUL per engine
Only numpy and the standard library are used.
"""
import numpy as np

WINDOW = 30
MAX_RUL = 130
ALPHA = 1.0
SEED = 42
VAL_FRACTION = 0.2


def _training_engines(unit_ids):
    ids = np.unique(unit_ids).astype(int)
    n = len(ids)
    n_val = int(np.ceil(VAL_FRACTION * n))
    perm = np.random.RandomState(SEED).permutation(n)
    return ids[perm[n_val:]]


def _windows(train, engines):
    X, y = [], []
    for u in engines:
        e = train[train[:, 0] == u]
        e = e[np.argsort(e[:, 1])]
        n = len(e)
        rul = np.minimum(n - e[:, 1], MAX_RUL)  # cycles start at 1, last row has RUL 0
        s = e[:, 2:]
        for end in range(WINDOW, n + 1):
            X.append(s[end - WINDOW:end].ravel())
            y.append(rul[end - 1])
    return np.asarray(X), np.asarray(y, dtype=float)


def _last_windows(test):
    out = []
    for u in np.unique(test[:, 0]):
        e = test[test[:, 0] == u]
        s = e[np.argsort(e[:, 1])][:, 2:]
        if len(s) < WINDOW:
            s = np.vstack([np.zeros((WINDOW - len(s), s.shape[1])), s])
        out.append(s[-WINDOW:].ravel())
    return np.asarray(out)


def predict_rul(train, test):
    """train, test: arrays with columns [unit, cycle, 14 sensors]. Returns one RUL per test engine, ordered by unit."""
    X, y = _windows(train, _training_engines(train[:, 0]))
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    zm, ym = Z.mean(axis=0), y.mean()
    Zc = Z - zm
    w = np.linalg.solve(Zc.T @ Zc + ALPHA * np.eye(Z.shape[1]), Zc.T @ (y - ym))
    b = ym - zm @ w
    return ((_last_windows(test) - mu) / sd) @ w + b
