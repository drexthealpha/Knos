"""Cut the NEAR demo video from near/web/record-demo.mjs's two recordings: the segments in the order the video tells it
(the problem, the claim and its locked hash, the press, the job on NEAR, the agents at work sped up to fit, agent A's code
and the reviewer, the receipt, the 90/10 payment on NEAR, one refusal, the card), H.264 at 1280x720, 30 fps, no sound.
    python near/web/cut-demo.py <dir with a.webm, b.webm, cuts.json> <out.mp4>"""
import json
import subprocess
import sys
from pathlib import Path

d, out = Path(sys.argv[1]), sys.argv[2]
rec = json.loads((d / "cuts.json").read_text(encoding="utf-8"))
cuts = rec["cuts"]


def flashes(video: Path) -> list[float]:
    """The video times where a full-frame magenta flash starts (20 frames a second, each frame shrunk to 32x18)."""
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vf", "fps=20,scale=32:18", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    n, found, prev = 32 * 18 * 3, [], False
    for i in range(len(raw) // n):
        px = raw[i * n:(i + 1) * n]
        r, g, b = (sum(px[k::3]) / (32 * 18) for k in range(3))
        on = r > 200 and g < 70 and b > 200
        if on and not prev:
            found.append(i / 20)
        prev = on
    return found


def mapper(f: str):
    """Clock time to video time, a straight line through the first and last flash."""
    v, w = flashes(d / f"{f}.webm"), rec["syncs"][f]
    assert len(v) == len(w) >= 2, (f, v, w)
    k = (v[-1] - v[0]) / (w[-1] - w[0])
    return lambda t: v[0] + (t - w[0]) * k


to_video = {f: mapper(f) for f in ("a", "b")}
for c in cuts:
    c["from"], c["to"] = to_video[c["f"]](c["from"]) + 0.15, to_video[c["f"]](c["to"])   # a little in, past the caption's first paint
order = ["problem", "claim and hash", "the press", "The locked test's hash, on NEAR testnet", "working", "the private model",
         "the fixed program", "reviewer and the test", "receipt", "The contract paid: 90% agent, 10% Knos",
         "Refused: a payout to a lookalike account", "card"]
seq = [c for w in order for c in cuts if c["what"] == w]
parts, inputs = [], ["-i", str(d / "a.webm"), "-i", str(d / "b.webm")]
for i, c in enumerate(seq):
    src = 0 if c["f"] == "a" else 1
    span = c["to"] - c["from"]
    k = (c["fit"] / span) if c.get("fit") and span > c["fit"] else 1.0   # only the wait is sped up, to its fit
    parts.append(f"[{src}:v]trim=start={c['from']:.2f}:end={c['to']:.2f},setpts=(PTS-STARTPTS)*{k:.4f},fps=30,scale=1280:720,setsar=1[v{i}]")
filt = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(len(seq))) + f"concat=n={len(seq)}:v=1:a=0[out]"
cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", filt, "-map", "[out]", "-an", "-c:v", "libx264",
       "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
subprocess.run(cmd, check=True)
dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
print(json.dumps({"segments": [c["what"] for c in seq], "seconds": round(float(dur), 1), "bytes": Path(out).stat().st_size}))
