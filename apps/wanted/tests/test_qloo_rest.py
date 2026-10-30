"""The Qloo REST client: cache, monthly budget, rate limit, and the key kept out of everything but the header.
Network is replaced by a fake opener answering SYNTHETIC bodies (not Qloo data)."""
import io
import json
import urllib.error

import pytest

from knos_wanted import qloo_rest
from knos_wanted.qloo_rest import BudgetExceeded, Client, NoKey, QlooError

KEY = "test-key-not-real-0123456789"


class Opener:
    def __init__(self, body=None, error=None):
        self.n, self.body, self.error, self.reqs = 0, body or {"results": [{"name": "X (synthetic)"}]}, error, []

    def __call__(self, req, timeout=None):
        self.n += 1
        self.reqs.append(req)
        if self.error:
            raise urllib.error.HTTPError(req.full_url, self.error, "err", {}, io.BytesIO(b'{"errors":[{"message":"bad"}]}'))
        return io.BytesIO(json.dumps(self.body).encode())


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def client(tmp_path, opener, clock=None, budget=100):
    return Client(key=KEY, base="https://example.test", folder=tmp_path, budget=budget, opener=opener, clock=clock or Clock(),
                  bucket=qloo_rest._Bucket(1000.0))


def test_cache_hit_and_ttl(tmp_path):
    op, clk = Opener(), Clock()
    c = client(tmp_path, op, clk)
    a = c.get("/search", {"query": "water bottle", "take": 3})
    b = c.get("/search", {"take": 3, "query": "water bottle"})          # same params, other order: one cache entry
    assert op.n == 1 and a["source"]["cached"] is False and b["source"]["cached"] is True and b["body"] == a["body"]
    clk.t += 40 * 86_400                                                 # 40 days on: a 2xx answer has no time limit
    d = c.get("/search", {"query": "water bottle", "take": 3})
    assert op.n == 1 and d["source"]["cached"] is True and d["body"] == a["body"] and qloo_rest.TTL_S is None


def test_a_refused_question_still_expires_after_a_day(tmp_path):
    op, clk = Opener(error=400), Clock()
    c = client(tmp_path, op, clk)
    for _ in range(2):
        try:
            c.get("/search", {"query": "water bottle", "take": 3})
        except qloo_rest.QlooError:
            pass
    assert op.n == 1                                                     # the refusal is remembered for a day
    clk.t += qloo_rest.ERROR_TTL_S + 1
    try:
        c.get("/search", {"query": "water bottle", "take": 3})
    except qloo_rest.QlooError:
        pass
    assert op.n == 2


def test_key_only_in_the_header(tmp_path):
    op = Opener()
    c = client(tmp_path, op)
    c.get("/v2/insights", {"filter.type": "urn:demographics"})
    req = op.reqs[0]
    assert req.get_header("X-api-key") == KEY and KEY not in req.full_url
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert KEY not in f.read_text(encoding="utf-8")
    with pytest.raises(QlooError) as e:
        client(tmp_path, Opener(error=401)).get("/v2/tags", {"filter.query": "z"})
    assert KEY not in str(e.value) and "example.test" not in str(e.value) and "HTTP 401" in str(e.value)


def test_monthly_budget_refuses_new_calls_but_serves_cached(tmp_path):
    op = Opener()
    c = client(tmp_path, op, budget=2)
    c.get("/search", {"query": "a"})
    c.get("/search", {"query": "b"})
    with pytest.raises(BudgetExceeded):
        c.get("/search", {"query": "c"})
    assert c.get("/search", {"query": "a"})["source"]["cached"] is True
    assert Client(key=KEY, base="https://example.test", folder=tmp_path, budget=2, clock=Clock()).used() == 2     # persistent counter


def test_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    c = Client(base="https://example.test", folder=tmp_path, opener=Opener())
    assert c.ready()[0] is False
    with pytest.raises(NoKey):
        c.get("/search", {"query": "a"})


def test_token_bucket_paces_to_four_per_second():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s
    b = qloo_rest._Bucket(4.0, clock=lambda: t[0], sleep=sleep)
    for _ in range(12):
        b.take()
    assert t[0] >= 2.0 - 1e-9          # 12 calls at 4/s with a burst of 4: at least 2 seconds


def test_a_refused_question_is_cached_for_a_day_and_its_text_not_passed_on(tmp_path):
    op, clk = Opener(error=400), Clock()
    c = client(tmp_path, op, clk)
    for _ in range(3):
        with pytest.raises(QlooError) as e:
            c.get("/v2/insights", {"filter.type": "urn:entity:brand", "signal.interests.tags": "urn:tag:bad"})
        assert "bad" not in str(e.value).replace("urn:tag:bad", "") and "errors" not in str(e.value)
    assert op.n == 1 and c.used() == 1                     # asked once, budget spent once
    clk.t += qloo_rest.ERROR_TTL_S + 1
    with pytest.raises(QlooError):
        c.get("/v2/insights", {"filter.type": "urn:entity:brand", "signal.interests.tags": "urn:tag:bad"})
    assert op.n == 2


def test_a_question_qloo_does_not_answer_in_time_is_asked_once_and_remembered_for_an_hour(tmp_path):
    asked = []

    def slow(req, timeout=None):
        asked.append(req)
        raise TimeoutError("The read operation timed out")
    clk = Clock()
    c = client(tmp_path, slow, clk)
    for _ in range(2):
        with pytest.raises(QlooError) as e:
            c.get("/v2/insights", {"filter.type": "urn:entity:place", "filter.location.query": "United States"})
        assert "did not answer within" in str(e.value)
    assert len(asked) == 1                                   # no second 45 s try, and not asked again within the hour
    clk.t += qloo_rest.SLOW_TTL_S + 1
    with pytest.raises(QlooError):
        c.get("/v2/insights", {"filter.type": "urn:entity:place", "filter.location.query": "United States"})
    assert len(asked) == 2


def test_qloo_s_own_error_text_reaches_the_operator_s_log_and_never_the_answer(tmp_path, capsys):
    c = client(tmp_path, Opener(error=400), Clock())
    with pytest.raises(QlooError) as e:
        c.get("/v2/insights", {"filter.type": "urn:entity:brand", "signal.interests.tags": "urn:tag:x"})
    log = capsys.readouterr()
    assert "HTTP 400" in log.err + log.out and "bad" in log.err + log.out and "/v2/insights" in log.err + log.out
    assert "errors" not in str(e.value)


def test_an_answer_prefetched_in_this_check_reads_back_live_and_one_from_before_reads_recorded(tmp_path):
    op = Opener()
    c = client(tmp_path, op)
    q = ("/v2/insights", {"filter.type": "urn:entity:brand", "signal.interests.tags": "urn:tag:x"})
    first = qloo_rest.CheckBudget(c)
    assert not first.get(*q)["source"].get("cached")                  # the prefetch: asked now
    again = first.get(*q)["source"]                                    # the numbered call reads it back from the cache
    assert again["cached"] is False and again.get("fresh") is True and op.n == 1 and first.sent == 1
    later = qloo_rest.CheckBudget(c).get(*q)["source"]                # another check, the same answer: recorded
    assert later["cached"] is True and op.n == 1


def test_who_buys_is_asked_of_qloo_once_per_check_and_read_back_live_within_it(tmp_path):
    op = Opener()
    c = client(tmp_path, op)
    aud = ("/v2/audiences", {"take": 50})
    other = ("/v2/insights", {"filter.type": "urn:entity:brand", "signal.interests.tags": "urn:tag:x"})
    first = qloo_rest.CheckBudget(c)
    first.get(*aud), first.get(*other)
    assert first.get(*aud)["source"]["cached"] is False and op.n == 2           # read back within the check: live, not asked again
    second = qloo_rest.CheckBudget(c)
    assert second.get(*aud)["source"].get("cached") is not True and op.n == 3   # the next check asks Qloo again
    assert second.get(*other)["source"]["cached"] is True and op.n == 3          # anything else still comes from the cache
