"""The door's uptime line comes from the Knos server (/api/uptime), which reads the scheduled check's uptime.jsonl."""
import io
import json
import time

from knos_wanted import near_live


def _stub(monkeypatch, text):
    near_live._uptime.clear()
    monkeypatch.setattr(near_live.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(text.encode()))


def test_counts_only_the_last_seven_days(monkeypatch):
    now = time.time()
    at = lambda d: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - d * 86400))  # noqa: E731
    lines = [{"at": at(1), "up": True}, {"at": at(2), "up": False}, {"at": at(3), "up": True}, {"at": at(9), "up": False}]
    _stub(monkeypatch, "\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    out = near_live.uptime()
    assert (out["up"], out["all"], out["days"]) == (2, 3, 7)


def test_a_failed_read_gives_no_numbers(monkeypatch):
    near_live._uptime.clear()

    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(near_live.urllib.request, "urlopen", boom)
    out = near_live.uptime()
    assert "up" not in out and "all" not in out and out["error"]
