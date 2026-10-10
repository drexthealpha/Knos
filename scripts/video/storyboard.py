"""The storyboard: a video written down as a plain text file, one scene after another. Each scene has the words that are
spoken and one thing to show while they are spoken: a web page, the real output of commands, or a still picture.

    title: Knos in three minutes            header (before the first scene), one per line
    size: 1280x720                          width x height of the video (default 1280x720)
    fps: 30                                 frames per second, 24 to 60 (default 30); the video is always at this constant rate
    voice: piper:en_US-lessac-medium        who speaks: piper:NAME (offline) or edge:NAME (Microsoft's online voices, edge-tts);
                                            several, separated by commas: the first that works for the whole video is used
    speed: 1.0                              how fast the voice speaks, 0.7 to 1.3 (default 1); to fit the time, cut words first
    pad: 0.4 0.6                            seconds of quiet before and after each scene's words (default 0.4 0.6)
    cwd: ../..                              where `run:` commands run, relative to this file (default: this file's folder)
    env: PYTHONPATH=src                     an environment variable for `run:` commands (repeat the line for more)
    limit: 120                              the longest the video may be, in seconds, at most 180 (default 180)

    --- intro                               a scene starts with --- and its name (letters, digits, - and _)
    say: What is said, in plain sentences.  The words of the scene. A line that starts with two spaces goes on from the one
      above it. Each sentence becomes one subtitle.
    show: url https://example.org/page      a real page, opened in Chromium; an address with no scheme is a file, relative
                                            to this file
    scroll: 900                             (url) scroll this many pixels, smoothly, while the words are spoken
    wait: 1.5                               (url) seconds to let the page settle after it loads (default 1)
    hold: 6                                 the scene lasts at least this many seconds

    --- check
    say: ...
    run: {python} scripts/claims_check.py   a command whose real output is shown, in a terminal page. One command per line,
    run!: {python} scripts/x.py             in order. `run!:` accepts a command that fails (its exit status is shown); `run:`
                                            stops the whole render if it fails. {python} is the Python running the render.

    --- close
    say: ...
    show: still card.svg                    a picture (png, jpg, webp, gif or svg), fitted to the frame

Lines that start with # are comments; blank lines mean nothing. A scene shows one thing: `show:` or `run:`, not both.
A command runs for real, once, when the video is rendered, and the terminal page replays what it printed, with the
exit status and the seconds it took; a storyboard runs commands, so only render one that you trust.

A spoken script in Markdown is a storyboard too (`from_script`, and `render.py --script FILE`): each heading
`## 1. Name (0:00)` starts a scene, each line that starts with `>` is said in it, and a whole line `<!-- key: value -->`
(or <!-- `key: value` -->) is a storyboard line (before the first heading, a header line such as `<!-- limit: 120 -->`; after it, a scene's line
such as `<!-- show: url https://... -->`). Everything else in the file is for the reader and is not said. A mistake is
reported with the script's own line number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

LIMIT = 180.0                       # seconds: a longer video is a failure, whatever the storyboard says
KEYS = ("say", "show", "scroll", "wait", "hold", "run", "run!")
HEADER_KEYS = ("title", "size", "fps", "voice", "speed", "pad", "cwd", "env", "limit")
SCRIPT_HEAD = re.compile(r"## \d+\. (.+?) \(\d+:\d\d\)")      # a spoken script's section: `## 1. The finding (0:00)`
SCRIPT_LINE = re.compile(r"<!--\s*`?([a-z!]+:.*?)`?\s*-->")    # `<!-- key: value -->`, the key and value maybe in backticks


class StoryboardError(ValueError):
    """The storyboard is not as the format says; the message names the line."""


@dataclass
class Command:
    text: str                       # as written, with {python} still in it
    allow_failure: bool = False


@dataclass
class Scene:
    id: str
    line: int                       # the line of the file where the scene starts
    say: str = ""
    kind: str = ""                  # "url", "still" or "terminal"
    target: str = ""                # the address or the file, as written
    commands: list[Command] = field(default_factory=list)
    scroll: int = 0
    wait: float = 1.0
    hold: float = 0.0


@dataclass
class Storyboard:
    path: Path
    title: str = ""
    size: tuple[int, int] = (1280, 720)
    fps: int = 30
    voices: list[str] = field(default_factory=lambda: ["piper:en_US-lessac-medium"])
    speed: float = 1.0
    pad: tuple[float, float] = (0.4, 0.6)
    cwd: Path = field(default_factory=Path)
    env: dict[str, str] = field(default_factory=dict)
    limit: float = LIMIT
    scenes: list[Scene] = field(default_factory=list)

    @property
    def folder(self) -> Path:
        return self.path.parent


def _number(text: str, at: int, what: str, low: float, high: float) -> float:
    try:
        value = float(text)
    except ValueError:
        raise StoryboardError(f"line {at}: {what} is a number, not {text!r}") from None
    if not low <= value <= high:
        raise StoryboardError(f"line {at}: {what} is between {low:g} and {high:g}, not {text}")
    return value


def parse(text: str, path: str | Path = "storyboard") -> Storyboard:
    """The storyboard in `text`. StoryboardError, naming the line, for anything the format does not allow."""
    board = Storyboard(path=Path(path))
    board.cwd = board.folder
    scene: Scene | None = None
    saying: bool = False                # the last line was a `say:`, so an indented line goes on from it
    for at, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if saying and scene is not None and raw[:2] == "  ":
            scene.say = f"{scene.say} {line.strip()}".strip()
            continue
        saying = False
        head = re.match(r"---\s*(\S*)\s*$", line)
        if head:
            name = head.group(1)
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise StoryboardError(f"line {at}: a scene starts with --- and a name of letters, digits, - and _, not {name!r}")
            if any(s.id == name for s in board.scenes):
                raise StoryboardError(f"line {at}: there is a scene called {name} already (line {next(s.line for s in board.scenes if s.id == name)})")
            scene = Scene(id=name, line=at)
            board.scenes.append(scene)
            continue
        key, colon, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not colon:
            raise StoryboardError(f"line {at}: expected `key: value` or a scene start (--- name), found {line.strip()!r}")
        if key.endswith("!") and key != "run!":
            raise StoryboardError(f"line {at}: only run! has a !")
        if scene is None:
            if key not in HEADER_KEYS:
                raise StoryboardError(f"line {at}: {key!r} is not a header line ({', '.join(HEADER_KEYS)}); a scene starts with --- name")
            _header(board, key, value, at)
            continue
        if key not in KEYS:
            raise StoryboardError(f"line {at}: {key!r} is not a line of a scene ({', '.join(KEYS)})")
        if key == "say":
            scene.say = f"{scene.say} {value}".strip()
            saying = True
        elif key == "show":
            kind, _, target = value.partition(" ")
            if kind not in ("url", "still") or not target.strip():
                raise StoryboardError(f"line {at}: show: is `url ADDRESS` or `still FILE`, not {value!r}")
            if scene.kind:
                raise StoryboardError(f"line {at}: scene {scene.id} shows one thing; it shows a {scene.kind} already")
            scene.kind, scene.target = kind, target.strip()
        elif key in ("run", "run!"):
            if not value:
                raise StoryboardError(f"line {at}: {key}: needs a command")
            if scene.kind and scene.kind != "terminal":
                raise StoryboardError(f"line {at}: scene {scene.id} shows one thing; it shows a {scene.kind} already")
            scene.kind = "terminal"
            scene.commands.append(Command(value, allow_failure=key == "run!"))
        elif key == "scroll":
            scene.scroll = int(_number(value, at, "scroll", 0, 100_000))
        elif key == "wait":
            scene.wait = _number(value, at, "wait", 0, 60)
        elif key == "hold":
            scene.hold = _number(value, at, "hold", 0, LIMIT)
    _check(board)
    return board


def _header(board: Storyboard, key: str, value: str, at: int) -> None:
    if key == "title":
        board.title = value
    elif key == "size":
        m = re.fullmatch(r"(\d{3,4})\s*x\s*(\d{3,4})", value)
        if not m or int(m.group(1)) % 2 or int(m.group(2)) % 2 or not (320 <= int(m.group(1)) <= 3840 and 240 <= int(m.group(2)) <= 2160):
            raise StoryboardError(f"line {at}: size is WIDTHxHEIGHT, both even, from 320x240 to 3840x2160, not {value!r}")
        board.size = (int(m.group(1)), int(m.group(2)))
    elif key == "fps":
        board.fps = int(_number(value, at, "fps", 24, 60))
    elif key == "voice":
        voices = [v.strip() for v in value.split(",") if v.strip()]
        for voice in voices:
            if not re.fullmatch(r"(piper|edge|edge-tts):[\w.-]+", voice):
                raise StoryboardError(f"line {at}: a voice is piper:NAME or edge:NAME (for example piper:en_US-lessac-medium), not {voice!r}")
        if not voices:
            raise StoryboardError(f"line {at}: voice: needs at least one voice")
        board.voices = voices
    elif key == "speed":
        board.speed = _number(value, at, "speed", 0.7, 1.3)
    elif key == "pad":
        parts = value.split()
        if len(parts) != 2:
            raise StoryboardError(f"line {at}: pad is two numbers, the seconds before and after each scene's words")
        board.pad = (_number(parts[0], at, "pad", 0, 10), _number(parts[1], at, "pad", 0, 10))
    elif key == "limit":
        board.limit = _number(value, at, "limit", 1, LIMIT)
    elif key == "cwd":
        board.cwd = (board.folder / value).resolve()
    elif key == "env":
        name, eq, val = value.partition("=")
        if not eq or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name.strip()):
            raise StoryboardError(f"line {at}: env is NAME=value, not {value!r}")
        board.env[name.strip()] = val


def from_script(text: str, path: str | Path = "script.md") -> Storyboard:
    """The storyboard a spoken Markdown script describes (see the module's text). Each line of the script becomes one line
    of a storyboard, so a StoryboardError names the script's own line."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        head, own = SCRIPT_HEAD.fullmatch(line), SCRIPT_LINE.fullmatch(line)
        if head:
            out.append("--- " + (re.sub(r"[^a-z0-9]+", "-", head.group(1).lower()).strip("-") or "scene"))
        elif line.startswith(">"):
            out.append("say: " + line[1:].strip() if line[1:].strip() else "")
        elif own:
            out.append(own.group(1))
        else:
            out.append("")
    return parse("\n".join(out) + "\n", path)


def _check(board: Storyboard) -> None:
    if not board.scenes:
        raise StoryboardError("the storyboard has no scenes: a scene starts with --- and a name")
    for scene in board.scenes:
        if not scene.say.strip():
            raise StoryboardError(f"line {scene.line}: scene {scene.id} has nothing to say (a `say:` line)")
        if not scene.kind:
            raise StoryboardError(f"line {scene.line}: scene {scene.id} shows nothing (a `show:` or `run:` line)")
        if scene.scroll and scene.kind != "url":
            raise StoryboardError(f"line {scene.line}: scroll: is for a url scene; scene {scene.id} shows a {scene.kind}")


def words(text: str) -> int:
    return len(text.split())


def estimate(board: Storyboard, words_per_minute: int = 150) -> float:
    """Seconds the storyboard will take at an even speaking speed, scene gaps included. An estimate, to cut words before
    the voice is asked: the render measures the real length."""
    total = 0.0
    for scene in board.scenes:
        total += max(scene.hold, words(scene.say) * 60 / words_per_minute + board.pad[0] + board.pad[1])
    return total
