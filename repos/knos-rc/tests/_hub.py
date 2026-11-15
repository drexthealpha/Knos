"""api.github.com for a test: what a path answers, and a record of what was asked. Nothing here opens the network."""

from __future__ import annotations

import re

BOT = {"login": "github-actions[bot]", "id": 41898282, "type": "Bot"}
LABEL = "knos-memory"


class Hub:
    """`get(path)` and `post(path, payload)` in one callable, as knos.judge.github is. A path nothing answers is
    GitHub saying no (OSError). An answer may be a function of the path (and of the payload, for a post)."""

    def __init__(self, answers: dict | None = None):
        self.answers = dict(answers or {})
        self.asked: list = []
        self.posted: list = []

    def __call__(self, path: str, data: dict | None = None):
        if data is not None:
            self.posted.append((path, data))
        else:
            self.asked.append(path)
        got = self.answers.get(path, self.answers.get(path.split("?")[0]))
        if got is None:
            raise OSError(f"404 {path}")
        if callable(got):
            return got(path) if data is None else got(path, data)
        return got


def user(login: str, uid: int, kind: str = "User") -> dict:
    return {"login": login, "id": uid, "type": kind}


def comment(cid: int, who: dict, body: str, at: str = "2026-10-01T10:00:00Z", edited: str | None = None,
            association: str = "NONE") -> dict:
    """A comment as GitHub's REST API gives it. `edited`: when its text was changed."""
    return {"id": cid, "user": who, "body": body, "created_at": at, "updated_at": edited or at,
            "author_association": association}


def run(name: str, conclusion: str | None = "success", app: int | None = 15368, status: str = "completed", **more) -> dict:
    """A check run as GitHub's REST API gives it."""
    return {"name": name, "status": status, "conclusion": conclusion, "app": {"id": app} if app else None, **more}


def status(context: str, state: str = "success", **more) -> dict:
    return {"context": context, "state": state, **more}


class Issues(Hub):
    """The issues of o/r as far as the memory touches them: list by label, read comments, open one, comment."""

    def __init__(self, me: dict = BOT):
        super().__init__()
        self.me, self.issues, self.comments, self.down, self.clock = me, [], {}, False, 0

    def open(self, who: dict, labels=(LABEL,), **more) -> int:
        n = len(self.issues) + 1
        self.issues.append({"number": n, "user": who, "state": "open", "labels": [{"name": x} for x in labels], **more})
        self.comments[n] = []
        return n

    def say(self, n: int, who: dict, body: str, edited: bool = False) -> None:
        self.clock += 1
        at = f"2026-10-02T10:{self.clock:02d}:00Z"
        self.comments[n].append(comment(self.clock, who, body, at, f"2026-10-02T11:{self.clock:02d}:00Z" if edited else None))

    def __call__(self, path: str, data: dict | None = None):
        if self.down:
            raise OSError("502")
        if data is not None:
            self.posted.append((path, data))
            if path == "repos/o/r/issues":
                return {"number": self.open(self.me, data["labels"], title=data["title"], body=data["body"])}
            self.say(int(re.fullmatch(r"repos/o/r/issues/(\d+)/comments", path).group(1)), self.me, data["body"])
            return {"id": self.clock}
        self.asked.append(path)
        if path.startswith(f"repos/o/r/issues?labels={LABEL}&state=open&sort=created&direction=asc"):
            return [i for i in self.issues if i["state"] == "open" and {"name": LABEL} in i["labels"]]
        m = re.fullmatch(r"repos/o/r/issues/(\d+)/comments\?per_page=100&page=(\d+)", path)
        page = int(m.group(2))
        return self.comments[int(m.group(1))][(page - 1) * 100:page * 100]
