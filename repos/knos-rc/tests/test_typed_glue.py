"""What the type check found in the commands' glue: a value that can be None where the code went on as if it never were."""
from __future__ import annotations

import json

from _hub import Hub, user
from knos.cli import main


def test_a_comment_on_a_pull_request_github_answers_nothing_for_is_refused_in_words(tmp_path, monkeypatch, capsys):
    """knos.judge.github gives None for an empty answer. `knos proof comment` read the pull request's description from
    it and ended in a traceback (AttributeError); it now says what GitHub did not give."""
    hub = Hub({"repos/o/r/collaborators/mona/permission": {"permission": "write"}, "repos/o/r/pulls/12": lambda _path: None})
    monkeypatch.setattr("knos.judge.github", hub)
    event = tmp_path / "comment.json"
    event.write_text(json.dumps({"action": "created", "issue": {"number": 12, "pull_request": {"url": "x"}},
                                 "comment": {"body": "/knos mine", "user": user("mona", 4242)}}), encoding="utf-8")
    rc = main(["proof", "comment", "--event", str(event), "--repo", "o/r"])
    got = capsys.readouterr()
    assert rc == 1 and "GitHub's answer for o/r#12 was not a pull request." in got.out + got.err
    assert "Traceback" not in got.out + got.err and "repos/o/r/pulls/12" in hub.asked
