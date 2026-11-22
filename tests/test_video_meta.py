"""L34: the product video and the intro loop (web/media/), recorded from the local product by bench/video/capture.mjs.

ffprobe gives the video under 60 s and the loop 12 to 15 s; the paid moment the capture script recorded is under 10 s; the
front door links the video above its first section below the tool, and README.md links it near its top."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "web" / "media"
CAP = json.loads((MEDIA / "capture.json").read_text(encoding="utf-8"))


def duration(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="ffprobe is not installed")
def test_durations_by_ffprobe():
    demo, loop = duration(MEDIA / "knos-demo.mp4"), duration(MEDIA / "knos-loop.mp4")
    assert demo < 60
    assert 12 <= loop <= 15
    assert abs(demo - CAP["demo_s"]) < 0.5 and abs(loop - CAP["loop_s"]) < 0.5


def test_paid_moment_within_10_s_and_the_result_is_real():
    assert 0 < CAP["price_s"] < CAP["paid_s"] < 10
    assert CAP["free_runs_used_before"] >= 1
    assert CAP["result"].startswith(("Failed at row", "Passed"))


def test_front_door_links_the_video_near_the_top():
    door = (ROOT / "web" / "door.html").read_text(encoding="utf-8")
    body = door[door.index("<main>"):]
    assert 'href="media/knos-demo.mp4"' in body
    assert body.index('href="media/knos-demo.mp4"') < body.index('id="k-live"')


def test_readme_links_the_video_near_the_top():
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[:40]
    assert any("web/media/knos-demo.mp4" in x or "media/knos-demo.mp4" in x for x in lines), \
        "README.md (W4's) does not link web/media/knos-demo.mp4 in its first 40 lines yet"
