#!/usr/bin/env python3
"""Renders a storyboard into a narrated video, with no one at the keyboard.

    python scripts/video/render.py STORYBOARD [--out FOLDER] [--voice SPEC] [--limit SECONDS] [--keep-work]
    python scripts/video/render.py STORYBOARD --estimate        check the storyboard and estimate its length; no voice, no browser
    python scripts/video/render.py --script SCRIPT.md [...]      a spoken Markdown script instead of a storyboard (see storyboard.py)

It writes NAME.mp4, NAME.srt (subtitles) and NAME.contact.jpg (twelve frames, to look at first) into FOLDER (default: an out
folder next to the storyboard; for --script, scripts/video/out). The storyboard format is described in storyboard.py and shown in sample.storyboard.

What happens, in order, and where it stops:
  1 the storyboard is read                          a mistake is reported with its line (exit 2)
  2 the voice speaks every sentence                 the length of each is measured; Piper (offline) or edge-tts (online)
  3 the length is added up                          over the limit (180 s, or the storyboard's `limit:`): stop here,
                                                    before anything is recorded (exit 3)
  4 each terminal scene's commands run for real     a command that fails stops the render unless it was written run!:
  5 each scene is photographed in Chromium          real pages, the terminal page, stills
  6 ffmpeg encodes one H.264/AAC file               constant frame rate; the narration is never cut short
  7 the file is checked                             length, frame rate, audio, size; a file that is wrong is deleted (exit 3
                                                    when it is over 180 seconds, 1 otherwise)

Needs: Python 3.10 or later; ffmpeg and ffprobe on PATH; Playwright for Python and its Chromium (pip install playwright, and
on your own machine playwright install chromium); one voice: Piper (pip install piper-tts; its voice file, about 60 MB, is
downloaded once into KNOS_VOICES or a knos-video folder of your cache) or edge-tts (pip install edge-tts; online). Works
on Linux, macOS and Windows; nothing here uses a shell except the commands a storyboard asks to be run.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import assemble  # noqa: E402
import record  # noqa: E402
import storyboard as sb  # noqa: E402
import voice  # noqa: E402


def say(line: str = "") -> None:
    print(line, flush=True)


def estimate(board: sb.Storyboard, limit: float) -> int:
    say(f"{board.path.name}: {len(board.scenes)} scenes, voice {', '.join(board.voices)}, {board.size[0]}x{board.size[1]} at {board.fps} fps")
    for scene in board.scenes:
        say(f"  {scene.id:<16} {scene.kind:<9} {sb.words(scene.say):>4} words  about {max(scene.hold, sb.words(scene.say) * 0.4 + sum(board.pad)):5.1f} s")
    total = sb.estimate(board)
    verdict = "" if total <= limit - 10 else "; this is close to it" if total <= limit else "; this is OVER it"
    say(f"about {total:.0f} s at 150 words a minute (an estimate: the render measures it); the limit is {limit:g} s{verdict}")
    return 0


def check_tools() -> None:
    """Stops before any work is done if a program the render needs is missing."""
    assemble.need("ffmpeg")
    assemble.need("ffprobe")
    if importlib.util.find_spec("playwright") is None:
        raise assemble.ToolMissing("Playwright for Python is not installed: pip install playwright, then (on your own machine) playwright install chromium")


def render(args: argparse.Namespace) -> int:
    started = time.monotonic()
    if args.limit is not None and not 0 < args.limit <= sb.LIMIT:
        raise sb.StoryboardError(f"the limit is at most {sb.LIMIT:g} seconds, and not {args.limit:g}")
    if bool(args.storyboard) == bool(args.script):
        raise sb.StoryboardError("give a storyboard or --script SCRIPT, one of the two")
    path = Path(args.script or args.storyboard)
    if not path.is_file():
        raise sb.StoryboardError(f"{path} is not a file")
    text = path.read_text(encoding="utf-8")
    board = sb.from_script(text, path) if args.script else sb.parse(text, path)
    limit = args.limit if args.limit is not None else board.limit
    if args.voice:
        board.voices = [v.strip() for v in args.voice.split(",") if v.strip()]
        for spec in board.voices:
            if voice.parse_spec(spec)[0] not in voice.ENGINES or not voice.parse_spec(spec)[1]:
                raise sb.StoryboardError(f"a voice is piper:NAME or edge:NAME, not {spec!r}")
    if args.estimate:
        return estimate(board, limit)
    check_tools()
    out = Path(args.out) if args.out else (HERE if args.script else path.parent) / "out"
    out.mkdir(parents=True, exist_ok=True)
    work = out / f".{path.stem}-work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    mp4, subtitles, contact = out / f"{path.stem}.mp4", out / f"{path.stem}.srt", out / f"{path.stem}.contact.jpg"
    for old in (mp4, subtitles, contact):
        old.unlink(missing_ok=True)         # never leave an earlier render beside a failed one
    lead, tail = board.pad
    say(f"{path.name}: {len(board.scenes)} scenes, {sum(sb.words(s.say) for s in board.scenes)} words, estimated {sb.estimate(board):.0f} s")

    say("\n[1/4] narration")
    used, audio = voice.speak(board.voices, [(s.say, lead, tail, s.hold) for s in board.scenes], work, board.speed, say)
    lengths = [a.seconds for a in audio]
    total = sum(lengths)
    say(f"  voice {used}; the scenes add up to {total:.1f} s (the limit is {limit:g} s)")
    assemble.check_length(total, limit, [(s.id, n) for s, n in zip(board.scenes, lengths)])

    say("\n[2/4] commands")
    results = {}
    for scene in board.scenes:
        if scene.kind == "terminal":
            results[scene.id] = record.run_commands(scene.commands, board.cwd, board.env)
            for r in results[scene.id]:
                say(f"  {scene.id}: `{r.shown}` exit status {r.code}, {len(r.lines)} lines, {r.seconds:.1f} s")
    if not results:
        say("  none: no scene shows commands")

    say("\n[3/4] recording")
    frames = record.record(board, [(s, n, results.get(s.id, [])) for s, n in zip(board.scenes, lengths)], work, say)

    say("\n[4/4] assembling")
    voice.write_pcm(work / "narration.wav", b"".join(a.pcm for a in audio))
    cues, at = [], 0.0
    for a, n in zip(audio, lengths):
        cues += [(at + start, at + end, text) for start, end, text in a.cues]
        at += n
    text = assemble.srt(cues)
    subtitles.write_text(text, encoding="utf-8")
    (work / "master.ffconcat").write_text(assemble.ffconcat(frames), encoding="utf-8")
    assemble.encode(work, work / "master.ffconcat", work / "narration.wav", subtitles, mp4, board.fps, total, board.title)
    info = assemble.probe(mp4)
    problems = assemble.verify(info, board.size, board.fps, limit, total)
    if problems:
        mp4.unlink(missing_ok=True)
        subtitles.unlink(missing_ok=True)
        message = "the video is not as promised, and was deleted: " + "; ".join(problems)
        if any("limit is" in p for p in problems):
            raise assemble.TooLong(message)
        raise assemble.AssemblyError(message)
    sheet = assemble.contact_sheet(mp4, contact, total)
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    shown = float(info["format"]["duration"])
    say(f"\nvideo      {mp4}  {shown:.1f} s, {board.size[0]}x{board.size[1]}, {board.fps} fps constant, H.264 and AAC (the limit is {limit:g} s)")
    say(f"subtitles  {subtitles}  {text.count(' --> ')} cues (also a track inside the video)")
    say(f"contact    {contact if sheet else 'not made'}")
    say(f"rendered in {time.monotonic() - started:.0f} s with voice {used}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog="The storyboard format: see storyboard.py and sample.storyboard.")
    ap.add_argument("storyboard", nargs="?", help="the storyboard to render (or give --script)")
    ap.add_argument("--script", help="a spoken Markdown script to render instead of a storyboard, such as docs/submission/pitch_script_120.md")
    ap.add_argument("--out", help="the folder for the video, the subtitles and the contact sheet (default: out, next to the storyboard)")
    ap.add_argument("--voice", help="piper:NAME or edge:NAME, several separated by commas; replaces the storyboard's voice line")
    ap.add_argument("--limit", type=float, default=None, help=f"the longest the video may be, at most {sb.LIMIT:g} seconds (default: the storyboard's limit:, else {sb.LIMIT:g})")
    ap.add_argument("--estimate", action="store_true", help="check the storyboard and estimate its length; no voice, no browser")
    ap.add_argument("--keep-work", action="store_true", help="keep the folder of photographs and audio the render works in")
    args = ap.parse_args(argv)
    try:
        return render(args)
    except sb.StoryboardError as why:
        print(f"stopped: the storyboard is not right: {why}", file=sys.stderr)
        return 2
    except assemble.TooLong as why:
        print(f"stopped: {why}", file=sys.stderr)
        return 3
    except assemble.ToolMissing as why:
        print(f"stopped: {why}", file=sys.stderr)
        return 4
    except (voice.VoiceError, record.RecordError, assemble.AssemblyError) as why:
        print(f"stopped: {why}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
