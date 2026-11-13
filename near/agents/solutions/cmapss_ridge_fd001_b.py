"""Agent B: plausible shortcut. Same Ridge model, but "why hold out 20 engines for a
validation set we never use? more data can only help" -> trains on all 100 engines.
Everything else is identical to agent A."""
import numpy as np

WINDOW = 30
MAX_RUL = 130
ALPHA = 1.0


def predict_rul(train, test):
    X, y = [], []
    for u in np.unique(train[:, 0]):
        e = train[train[:, 0] == u]
        e = e[np.argsort(e[:, 1])]
        n = len(e)
        rul = np.minimum(n - e[:, 1], MAX_RUL)
        s = e[:, 2:]
        for end in range(WINDOW, n + 1):
            X.append(s[end - WINDOW:end].ravel())
            y.append(rul[end - 1])
    X, y = np.asarray(X), np.asarray(y, dtype=float)
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    zm, ym = Z.mean(axis=0), y.mean()
    Zc = Z - zm
    w = np.linalg.solve(Zc.T @ Zc + ALPHA * np.eye(Z.shape[1]), Zc.T @ (y - ym))
    b = ym - zm @ w
    T = []
    for u in np.unique(test[:, 0]):
        e = test[test[:, 0] == u]
        s = e[np.argsort(e[:, 1])][:, 2:]
        if len(s) < WINDOW:
            s = np.vstack([np.zeros((WINDOW - len(s), s.shape[1])), s])
        T.append(s[-WINDOW:].ravel())
    return ((np.asarray(T) - mu) / sd) @ w + b
