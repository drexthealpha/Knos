"""The tool's pages and link images (Round 13, B1 and B2): /t/<id>/ and /r/<result-id>/ as server-written HTML whose
first response already holds og:title, og:description and og:image (a reader with no script, a chat app's link
preview), and GET /og/<t|r>/<id>.png, a 1200 x 630 PNG with the Knos mark, the title and, for a result, the result line.

Standard library only (the app has no image library): the PNG is written with zlib, the mark is the app's own
icon-192.png decoded here, and the letters are a 5 x 8 bitmap font drawn as blocks."""
from __future__ import annotations

import html
import json
import struct
import zlib
from collections import OrderedDict
from pathlib import Path

STATIC = Path(__file__).parent / "static"

# 5 x 8 bitmap font, printable ASCII from 0x20: five columns per glyph, bit 0 the top row (bit 7 a descender's row)
_FONT_HEX = (
    "0000000000" "00005f0000" "0007000700" "147f147f14" "242a7f2a12" "2313086462" "3649562050" "0008070300"
    "001c224100" "0041221c00" "2a1c7f1c2a" "08083e0808" "0080703000" "0808080808" "0000606000" "2010080402"
    "3e5149453e" "00427f4000" "7249494946" "2141494d33" "1814127f10" "2745454539" "3c4a494931" "4121110907"
    "3649494936" "464949291e" "0000140000" "0040340000" "0008142241" "1414141414" "0041221408" "0201590906"
    "3e415d594e" "7c1211127c" "7f49494936" "3e41414122" "7f4141413e" "7f49494941" "7f09090901" "3e41415173"
    "7f0808087f" "00417f4100" "2040413f01" "7f08142241" "7f40404040" "7f021c027f" "7f0408107f" "3e4141413e"
    "7f09090906" "3e4151215e" "7f09192946" "2649494932" "03017f0103" "3f4040403f" "1f2040201f" "3f4038403f"
    "6314081463" "0304780403" "61594d4943" "007f414141" "0204081020" "004141417f" "0402010204" "4040404040"
    "0003070800" "2054547840" "7f28444438" "3844444428" "384444287f" "3854545418" "00087e0902" "18a4a49c78"
    "7f08040478" "00447d4000" "2040403d00" "7f10284400" "00417f4000" "7c04780478" "7c08040478" "3844444438"
    "fc18242418" "18242418fc" "7c08040408" "4854545424" "04043f4424" "3c4040207c" "1c2040201c" "3c4030403c"
    "4428102844" "4c9090907c" "4464544c44" "0008364100" "0000770000" "0041360800" "0201020402"
)
FONT = {chr(0x20 + i): bytes.fromhex(_FONT_HEX[i * 10:i * 10 + 10]) for i in range(len(_FONT_HEX) // 10)}

W, H = 1200, 630
INK = (0x15, 0x17, 0x1c)
ACCENT = (0x2b, 0x3b, 0xb5)
MUTED = (0x4a, 0x50, 0x5c)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png(w: int, h: int, rgb: bytes | bytearray) -> bytes:
    """An 8-bit RGB PNG of w x h pixels from rows of RGB bytes."""
    row = w * 3
    raw = b"".join(b"\x00" + bytes(rgb[y * row:(y + 1) * row]) for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b""))


def decode_rgb(data: bytes) -> tuple[int, int, bytearray]:
    """An 8-bit RGB, non-interlaced PNG (the app's icons) as (w, h, RGB bytes)."""
    pos, idat = 8, b""
    w = h = 0
    while pos < len(data):
        n = struct.unpack(">I", data[pos:pos + 4])[0]
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, lace = struct.unpack(">IIBBBBB", body)
            if (depth, ctype, lace) != (8, 2, 0):
                raise ValueError("only 8-bit RGB, non-interlaced")
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw, bpp, row = zlib.decompress(idat), 3, w * 3
    out = bytearray(h * row)
    prev = bytearray(row)
    for y in range(h):
        f, line = raw[y * (row + 1)], bytearray(raw[y * (row + 1) + 1:(y + 1) * (row + 1)])
        for i in range(row):
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        out[y * row:(y + 1) * row] = line
        prev = line
    return w, h, out


class Canvas:
    def __init__(self, w: int, h: int, bg: tuple):
        self.w, self.h = w, h
        self.buf = bytearray(bytes(bg) * (w * h))

    def rect(self, x: int, y: int, w: int, h: int, color: tuple) -> None:
        x0, x1 = max(0, x), min(self.w, x + w)
        if x1 <= x0:
            return
        line = bytes(color) * (x1 - x0)
        for yy in range(max(0, y), min(self.h, y + h)):
            s = (yy * self.w + x0) * 3
            self.buf[s:s + len(line)] = line

    def text(self, x: int, y: int, s: str, scale: int, color: tuple) -> None:
        for ch in s:
            g = FONT.get(ch) or FONT["?"]
            for col, bits in enumerate(g):
                for r in range(8):
                    if bits >> r & 1:
                        self.rect(x + col * scale, y + r * scale, scale, scale, color)
            x += 6 * scale

    def paste(self, w: int, h: int, rgb: bytes | bytearray, x: int, y: int) -> None:
        for yy in range(h):
            if 0 <= y + yy < self.h:
                s = ((y + yy) * self.w + x) * 3
                self.buf[s:s + w * 3] = rgb[yy * w * 3:(yy + 1) * w * 3]


def _wrap(s: str, per_line: int) -> list[str]:
    lines, cur = [], ""
    for word in s.split():
        if cur and len(cur) + 1 + len(word) > per_line:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


_icon: dict = {}
_cache: "OrderedDict[tuple, bytes]" = OrderedDict()


def og_png(title: str, line: str | None = None) -> bytes:
    """The link image: the Knos mark and name, the title, and the result line when there is one (1200 x 630)."""
    key = (title, line)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    if "mark" not in _icon:
        _icon["mark"] = decode_rgb((STATIC / "brand" / "icon-192.png").read_bytes())
    iw, ih, rgb = _icon["mark"]
    bg = tuple(rgb[0:3])                         # the icon's own paper: the mark sits on the page with no box
    c = Canvas(W, H, bg)
    c.paste(iw, ih, rgb, 64, 40)
    c.text(64 + iw + 16, 40 + (ih - 80) // 2, "Knos", 10, INK)
    margin, width = 80, W - 160
    lines = _wrap(title, width // 48)[:2]
    y = 270
    for t in lines:
        c.text(margin, y, t, 8, INK)
        y += 84
    if line:
        for t in _wrap(line, width // 30)[:3]:          # scale 5: 30 px a letter, up to three lines
            c.text(margin, y + 20, t, 5, ACCENT)
            y += 52
    c.rect(0, H - 16, W, 16, ACCENT)
    out = png(W, H, c.buf)
    _cache[key] = out
    while len(_cache) > 64:
        _cache.popitem(last=False)
    return out


CSS = """:root{--bg:#f4f4f0;--card:#fff;--fg:#15171c;--muted:#4a505c;--line:#8a8f99;--accent:#2b3bb5;--accent-fg:#fff;--bad:#b3261e;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#07080c;--card:#0f1118;--fg:#e9ebef;--muted:#b4bac8;--line:#6b7080;--accent:#93a5ff;--accent-fg:#07080c;--bad:#ff8a80}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:18px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:640px;margin:0 auto;padding:4px 16px 48px}
a{color:var(--accent)}
.brand{display:inline-flex;align-items:center;min-height:44px;font-weight:700;font-size:20px;color:var(--fg);text-decoration:none}
h1{font-size:26px;line-height:1.2;margin:2px 0 4px}h2{font-size:22px;line-height:1.25;margin:12px 0 6px}
.who{margin:0 0 10px;color:var(--muted)}
label{display:block;font-weight:600;margin-bottom:4px}
textarea{display:block;width:100%;height:6.4em;font:16px/1.4 ui-monospace,Consolas,monospace;padding:8px 10px;border:2px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);resize:vertical;white-space:pre;overflow:auto}
select,input{font:inherit;min-height:44px;padding:4px 8px;border:2px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
input[type=file]{width:100%;padding:8px}
.rule{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:10px 0 0}.rule input{width:7em}
.field{margin:10px 0 0}
button{font:inherit;min-height:44px;min-width:44px;padding:8px 16px;border-radius:8px;border:2px solid var(--accent);background:transparent;color:var(--accent);cursor:pointer;margin:8px 8px 0 0}
button.primary{min-height:48px;width:100%;margin:10px 0 0;background:var(--accent);color:var(--accent-fg);font-weight:700}
button:disabled{opacity:.75;cursor:default}
button:focus-visible,textarea:focus-visible,summary:focus-visible,a:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.big{font-size:22px;font-weight:700;margin:14px 0 0}.big+p{margin:2px 0 0}
.chart{display:block;width:100%;height:auto;max-height:220px;margin:10px 0 0;color:var(--fg)}
.muted{color:var(--muted)}.bad{color:var(--bad);font-weight:600}
.bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin:12px 0 4px}
.bar i{display:block;height:100%;width:30%;background:var(--accent);animation:k-move 1.2s ease-in-out infinite alternate}
@keyframes k-move{from{transform:translateX(0)}to{transform:translateX(233%)}}
@media (prefers-reduced-motion:reduce){.bar i{animation:none;width:100%}}
details{margin-top:24px;border-top:1px solid var(--line);padding-top:4px}
summary{min-height:44px;display:flex;align-items:center;cursor:pointer;font-weight:600}
summary::before{content:"+";display:inline-block;width:1.2em;color:var(--accent)}details[open] summary::before{content:"\\2212"}
details li{margin:6px 0}
[hidden]{display:none!important}"""

# The table reader and the chart, the same code on the front door (web/door.html): the column names by the program's rule
# (a first row with any cell that is not a number is the header), and the values as a line, the limit as a straight
# dashed line, the first failing value marked with a ring and its row number.
TABLE_JS = r"""const num = (s) => { const t = String(s).trim(); return t !== "" && Number.isFinite(Number(t)); };
function rowsOf(text) {
  const out = []; let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) { if (ch === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += ch; }
    else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") { if (ch === "\r" && text[i + 1] === "\n") i++; row.push(cell); out.push(row); row = []; cell = ""; }
    else cell += ch;
  }
  row.push(cell); out.push(row);
  return out.filter((r) => r.some((c) => c.trim()));
}
function columnsOf(text) {
  const rows = rowsOf(text);
  if (!rows.length) return [];
  if (rows[0].some((c) => !num(c))) return rows[0].map((c) => c.trim());
  return Array.from({ length: Math.max(...rows.map((r) => r.length)) }, (_, i) => "column " + (i + 1));
}
function chartSvg(c, row) {
  const NS = "http://www.w3.org/2000/svg", W = 320, H = 150, P = 10;
  const el = (tag, at) => { const e = document.createElementNS(NS, tag); for (const k in at) e.setAttribute(k, at[k]); return e; };
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Chart of the values with the limit" + (c.fail ? ", the first failing row marked" : "") });
  if (!c || !c.points || !c.points.length) return svg;
  const vs = c.points.map((p) => p[1]).concat([c.limit]), lo = Math.min(...vs), hi = Math.max(...vs), pad = (hi - lo) * 0.1 || 1;
  const n = Math.max(2, c.n), X = (x) => P + (x - 1) / (n - 1) * (W - 2 * P), Y = (v) => H - P - (v - lo + pad) / (hi - lo + 2 * pad) * (H - 2 * P);
  svg.append(el("polyline", { points: c.points.map((p) => X(p[0]).toFixed(1) + "," + Y(p[1]).toFixed(1)).join(" "), fill: "none", stroke: "currentColor", "stroke-width": 2 }));
  svg.append(el("line", { x1: P, x2: W - P, y1: Y(c.limit).toFixed(1), y2: Y(c.limit).toFixed(1), stroke: "#b3261e", "stroke-width": 2, "stroke-dasharray": "6 4" }));
  if (c.fail) {
    const fx = X(c.fail[0]), fy = Y(c.fail[1]);
    svg.append(el("circle", { cx: fx.toFixed(1), cy: fy.toFixed(1), r: 6, fill: "none", stroke: "#b3261e", "stroke-width": 3 }));
    const t = el("text", { x: Math.min(W - 60, Math.max(P, fx - 24)).toFixed(1), y: Math.max(14, fy - 10).toFixed(1), fill: "currentColor", "font-size": 13 });
    t.textContent = "Row " + row; svg.append(t);
  }
  return svg;
}"""

SCRIPT = r"""(() => {
const D = JSON.parse(document.getElementById("k-tool").textContent);
const $ = (id) => document.getElementById(id);
const box = $("list"), go = $("go"), out = $("out"), lab = $("lab"), form = $("tool"), pay = $("pay");
const test = new URLSearchParams(location.search).get("test") === "1";
const store = (() => { try { return window.localStorage; } catch (e) { return null; } })();
const get = (k) => { try { return store && store.getItem(k); } catch (e) { return null; } };
const put = (k, v) => { try { store && store.setItem(k, v); } catch (e) { /* private window */ } };
const browser = () => get("knos-count") === "yes" ? (get("knos-browser") || "") : "";
const n = (x) => Number(x).toLocaleString("en-US");
let xhr = null, tick = null, link = D.result ? D.result.link : "", mineOn = false;
const make = (tag, text, cls) => { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; };
const btn = (text, on, primary) => { const b = make("button", text, primary ? "primary" : ""); b.type = "button"; b.addEventListener("click", on); return b; };
const show = (...nodes) => out.replaceChildren(...nodes);
/*TABLE*/
function fillColumns(keep) {
  const names = columnsOf(box.value), sel = $("col"), was = keep || sel.value;
  sel.replaceChildren(...names.map((c) => { const o = make("option", c); o.value = c; return o; }));
  if (names.includes(was)) sel.value = was; else if (names.length) sel.value = names[names.length - 1];
}
function idle() { clearInterval(tick); tick = null; xhr = null; go.disabled = false; go.textContent = "Try it"; out.removeAttribute("aria-busy"); out.dataset.state = "done"; }
function left(r) {
  if (r.mode !== "own" || r.runs_left == null) return null;
  if (r.paid_left > 0) return make("p", r.runs_left === 1 ? "1 run left" : n(r.runs_left) + " runs left");
  return make("p", r.free_left === 1 ? "1 free run left today" : n(r.free_left) + " free runs left today");
}
function copy(b) {
  const done = () => { b.textContent = "Copied"; if (navigator.share) navigator.share({ url: link, title: D.title }).catch(() => {}); };
  b.textContent = "Copied";
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(link).then(done, () => fallback(b, done));
  else fallback(b, done);
}
function fallback(b, done) {
  const t = make("textarea"); t.value = link; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0"; document.body.append(t); t.select();
  let ok = false; try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  t.remove();
  if (ok) done(); else b.textContent = "Copy: " + link;
}
function ask() {
  if (get("knos-count") || ask.shown) return null;
  ask.shown = true;
  const p = make("p", "Count my visits to help improve Knos? ");
  const answer = (yes) => { put("knos-count", yes ? "yes" : "no"); if (yes && !get("knos-browser")) { const a = new Uint8Array(12); crypto.getRandomValues(a); put("knos-browser", Array.from(a, (x) => x.toString(16).padStart(2, "0")).join("")); } p.remove(); };
  p.append(btn("Yes", () => answer(true)), btn("No", () => answer(false)));
  return p;
}
function result(r) {
  link = r.link;
  const nodes = [make("p", r.result, "big")];
  if (r.chart) nodes.push(chartSvg(r.chart, r.first_failing_row));
  const l = left(r); if (l) nodes.push(l);
  if (r.mode === "own") nodes.push(make("p", "Only people with this link can see it."));
  nodes.push(make("p", r.shown_by, "muted"));
  const row = make("div");
  row.append(btn("Use my data", mine), btn("Copy link", (e) => copy(e.currentTarget)));
  nodes.push(row);
  const q = ask(); if (q) nodes.push(q);
  show(...nodes);
  try { if (location.origin === new URL(r.link).origin && location.pathname !== new URL(r.link).pathname) history.replaceState(null, "", new URL(r.link).pathname + location.search); } catch (e) { /* another site */ }
}
function ownMode() {
  mineOn = true; $("own").hidden = false; $("which").hidden = false; $("colname").hidden = true;
  lab.textContent = "Or paste a table";
  $("lims").textContent = "Up to " + n(D.limits.max_rows) + " rows. A run stops after " + n(D.limits.max_seconds) + " seconds."; $("lims").hidden = false;
}
function mine() { box.value = ""; $("limit").value = ""; ownMode(); fillColumns(); show(); $("file").focus(); }
function trouble(text, label, then) {
  const p = make("p", text, "bad"); p.setAttribute("role", "alert"); p.dataset.answer = "";
  show(p, btn(label, then));
}
function edit() { box.focus(); }
function working() {
  const t0 = Date.now();
  let step = "Sending your file to Knos", built = false, status, secs;
  out.dataset.state = "working"; out.setAttribute("aria-busy", "true");
  go.disabled = true; go.textContent = "Checking";
  show(make("p", "Checking your file"));
  tick = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    if (s < 1) return;
    if (!built) {
      built = true;
      const bar = make("div", null, "bar"); bar.setAttribute("role", "progressbar"); bar.setAttribute("aria-label", "Checking"); bar.append(make("i"));
      status = make("p"); status.dataset.status = ""; status.setAttribute("aria-live", "polite");
      secs = make("p", "", "muted");
      show(bar, status, secs, btn("Stop", stop));
    }
    if (status.textContent !== step) status.textContent = step;
    secs.textContent = s + (s === 1 ? " second" : " seconds");
  }, 200);
  return { step: (x) => { step = x; } };
}
function stop() {
  if (xhr) xhr.abort();
  idle();
  show(make("p", "I stopped checking, as you asked. Your file is still in the box."));
}
function run() {
  if (xhr) return;
  const table = box.value, column = mineOn ? $("col").value : D.column, rule = $("rule").value, limit = $("limit").value.trim();
  if (!table.trim()) return trouble("Your file is empty, so I have nothing to check yet. Choose a file or paste a table, then press Try it.", "Edit my file", edit);
  if (!num(limit)) return trouble("I need the limit as a number, such as 1.4, before I can check your file. Please type it, then press Try it.", "Type the limit", () => $("limit").focus());
  const w = working();
  xhr = new XMLHttpRequest();
  xhr.open("POST", D.api + "/api/run");
  xhr.setRequestHeader("Content-Type", "application/json");
  xhr.timeout = (D.limits.max_seconds + 90) * 1000;
  xhr.upload.onprogress = (e) => { if (e.lengthComputable && e.total > 50000) w.step("Sending your file to Knos: " + Math.round(100 * e.loaded / e.total) + "%"); };
  xhr.upload.onload = () => w.step("Checking your file on the Knos server");
  const x = xhr;
  x.onload = () => {
    idle();
    let body = {}; try { body = JSON.parse(x.responseText); } catch (e) { body = {}; }
    if (x.status === 200) return result(body);
    if (x.status === 402 && body.pay) return payScreen(body.pay);
    trouble(body.error || "Something went wrong on the Knos server, so I have no result. Your file is still in the box. Please try again.", x.status === 503 ? "Try again" : "Edit my file", x.status === 503 ? run : edit);
  };
  x.onerror = x.ontimeout = () => { idle(); trouble("I could not reach Knos just now, so nothing was checked. Your file is still in the box. Press Try again.", "Try again", run); };
  x.send(JSON.stringify({ id: D.id, table, column, rule, limit: Number(limit), mode: table === D.sample ? "sample" : "own", browser: browser(), test }));
}
function back(line) { pay.hidden = true; pay.replaceChildren(); form.hidden = false; show(...(line ? [make("p", line)] : [])); go.focus(); }
function payScreen(p) {
  const press = Array.from(crypto.getRandomValues(new Uint8Array(12)), (x) => x.toString(16).padStart(2, "0")).join("");
  form.hidden = true; show();
  const h = make("h2", p.headline); h.tabIndex = -1;
  pay.replaceChildren(h, make("p", p.line), btn("Pay with test money", () => confirm(p, press), true), btn("Not now", () => back()));
  pay.hidden = false; h.focus();
}
function confirm(p, press) {
  const h = make("h2", p.headline);
  const sure = make("p", "This records a " + p.price + " test payment for " + p.runs + " more runs. Nothing is charged.");
  const yes = btn("Yes, record it", () => record(yes, press), true);
  pay.replaceChildren(h, sure, yes, btn("Not now", () => back()));
  yes.focus();
}
function record(b, press) {
  if (b.disabled) return;
  b.disabled = true; b.textContent = "Recording";
  const x = new XMLHttpRequest();
  x.open("POST", D.api + "/api/pay"); x.setRequestHeader("Content-Type", "application/json");
  x.onload = () => {
    let body = {}; try { body = JSON.parse(x.responseText); } catch (e) { body = {}; }
    if (x.status === 200) return back(body.runs_left === 1 ? "1 run left" : n(body.runs_left) + " runs left");
    b.disabled = false; b.textContent = "Try again";
    const m = make("p", body.error || "I could not record the test payment just now. Nothing was charged. Press Try again.", "bad"); m.setAttribute("role", "alert");
    pay.append(m);
  };
  x.onerror = () => { b.disabled = false; b.textContent = "Try again"; };
  x.send(JSON.stringify({ browser: browser(), press, test }));
}
$("file").addEventListener("change", () => {
  const f = $("file").files[0]; if (!f) return;
  const r = new FileReader(); r.onload = () => { box.value = String(r.result); fillColumns(); }; r.readAsText(f);
});
box.addEventListener("input", () => { if (mineOn) fillColumns(); });
go.addEventListener("click", run);
if (D.result && D.result.mode === "own") { ownMode(); fillColumns(D.result.column); }
if (D.result) result(D.result);
})();""".replace("/*TABLE*/", TABLE_JS)


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def shown_limit(v) -> str:
    """The limit as a person typed it: 1.4, not 1.40; a whole number with no point."""
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def page(tool: dict, base: str, result: dict | None = None, front: str = "https://drexthealpha.github.io/Knos/") -> str:
    """One tool page (/t/<id>/) or one result page (/r/<id>/): the og tags first, then the tool, then its fold."""
    rid = (result or {}).get("id")
    url = f"{base}/r/{rid}/" if rid else f"{base}/t/{tool['id']}/"
    image = f"{base}/og/r/{rid}.png" if rid else f"{base}/og/t/{tool['id']}.png"
    desc = first_sentence(result["result"]) if result else tool["line"]
    text = result["input"] if result else tool["sample"]
    own = bool(result and result.get("mode") == "own")
    column = result["column"] if result else tool["column"]
    rule = result["rule"] if result else tool["rule"]
    limit = shown_limit(result["limit"] if result else tool["limit"])
    data = {"id": tool["id"], "title": tool["title"], "sample": tool["sample"], "api": base, "limits": tool["limits"],
            "column": tool["column"],
            "result": result and {k: result.get(k) for k in ("result", "first_failing_row", "rows", "skipped", "shown_by", "link",
                                                             "mode", "chart", "column")}}
    ssr = ""
    if result:
        ssr = (f'<p class="big">{_e(result["result"])}</p>'
               + ('<p>Only people with this link can see it.</p>' if own else "")
               + f'<p class="muted">{_e(result["shown_by"])}</p>'
               + (f'<p class="muted">Showing the first {result["shown_lines"]:,} of {result["lines"]:,} lines.</p>' if result.get("cut") else ""))
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    items = "".join(f"<li>{x}</li>" for x in tool["fold"])
    opts = "".join(f'<option value="{r}"{" selected" if r == rule else ""}>must stay {r}</option>' for r in ("above", "below"))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(tool['title'])} | Knos</title>
<meta name="description" content="{_e(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Knos">
<meta property="og:title" content="{_e(tool['title'])}">
<meta property="og:description" content="{_e(desc)}">
<meta property="og:image" content="{_e(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{_e(url)}">
<meta name="twitter:card" content="summary_large_image">
{'<meta name="robots" content="noindex">' if own else f'<link rel="canonical" href="{_e(url)}">'}
<link rel="icon" href="/favicon.ico">
<style>{CSS}</style>
</head>
<body>
<main>
<a class="brand" href="{_e(front)}">Knos</a>
<h1>{_e(tool['title'])}</h1>
<p class="who">{_e(tool['line'])}</p>
<div id="tool">
<div id="own" class="field" hidden><label for="file">Choose a file</label><input id="file" type="file" accept=".csv,text/csv,text/plain"></div>
<label id="lab" for="list">{'Or paste a table' if own else _e(tool['sample_label'])}</label>
<textarea id="list" dir="ltr" spellcheck="false" autocomplete="off" wrap="off">{_e(text)}</textarea>
<div id="which" class="field" hidden><label for="col">Which column?</label><select id="col"></select></div>
<p class="rule"><span id="colname">{_e(column)}</span> <select id="rule" aria-label="The rule">{opts}</select> <input id="limit" inputmode="decimal" autocomplete="off" aria-label="The limit" value="{_e(limit)}"></p>
<p id="lims" class="muted" hidden></p>
<button id="go" class="primary" type="button">Try it</button>
</div>
<section id="pay" hidden></section>
<div id="out" aria-live="polite" data-state="{'done' if result else 'ready'}">{ssr}</div>
<details>
<summary>How it works</summary>
<ol>{items}</ol>
</details>
</main>
<script type="application/json" id="k-tool">{blob}</script>
<script>{SCRIPT}</script>
</body>
</html>"""


def first_sentence(result: str) -> str:
    return result.split(". ", 1)[0].rstrip(".") + "." if result else ""


def missing(front: str = "https://drexthealpha.github.io/Knos/") -> str:
    """The page for an address with no tool or result behind it: what happened, and one way on."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Not found | Knos</title><meta name="robots" content="noindex"><style>{CSS}</style></head>
<body><main><a class="brand" href="{_e(front)}">Knos</a>
<h1>I cannot find this page</h1>
<p data-answer>I have nothing at this address. A result may have been cleared when the Knos server was updated.</p>
<p><a href="{_e(front)}">Open the Knos tool and check a file</a></p>
</main></body></html>"""
