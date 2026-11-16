"""Round 13, H3 c and d (knos_wanted.result_extras): GET /r/<result-id>/mark, /r/<result-id>/qr.png, /r/<result-id>/print.

The mark is at most 10 KB, runs no script, shows the tool's title, the result sentence and a link to the result, and is
the only one of these that another site may frame. The QR image is decoded back to the result address here, with the
standard library only: the PNG through tool_page.decode_rgb, the module grid through qr.read (which checks every
block's Reed-Solomon codewords); the encoder's codewords are held to a known vector in test_result_page.py."""
import html
import re
import struct

from knos_wanted import qr, result_extras, tool_page, tool_run

import test_tool_run as B
from test_tool_run import call, own, sample_body

app, program = B.app, B.program        # the fixtures of B: a served app, and the released program or its stand-in

MISSING = "/r/AAAAAAAAAAAA/"


def rid_of(r: dict) -> str:
    return r["link"].rstrip("/").rsplit("/", 1)[1]


def grid_of(png: bytes, px: int = result_extras.QR_PX, quiet: int = result_extras.QR_QUIET) -> list[list[bool]]:
    """The module grid a QR PNG draws: one sample at the middle of each module, dark where the pixel is dark."""
    w, h, rgb = tool_page.decode_rgb(png)
    assert w == h and w % px == 0
    n = w // px - 2 * quiet
    dark = lambda x, y: rgb[(y * w + x) * 3] < 128  # noqa: E731
    for i in range(w // px):                          # the quiet border is light all round
        for j in list(range(quiet)) + list(range(quiet + n, w // px)):
            assert not dark(i * px + px // 2, j * px + px // 2) and not dark(j * px + px // 2, i * px + px // 2)
    return [[dark((x + quiet) * px + px // 2, (y + quiet) * px + px // 2) for x in range(n)] for y in range(n)]


def test_the_mark_is_small_has_no_script_and_shows_title_sentence_and_link(app):
    st, r, _ = call(app, "/api/run", sample_body())
    rid = rid_of(r)
    st, raw, h = call(app, f"/r/{rid}/mark", raw=True)
    page = raw.decode()
    assert st == 200 and h["Content-Type"].startswith("text/html") and len(raw) <= 10_000
    assert "<script" not in page.lower() and not re.search(r"\son[a-z]+\s*=", page, re.I) and "javascript:" not in page.lower()
    assert tool_run.TITLE in page and html.escape(tool_page.first_sentence(r["result"])) in page
    link = re.search(r'<a href="([^"]+)" target="_top"', page)
    assert link and html.unescape(link.group(1)) == f"{app}/r/{rid}/"
    assert "script-src" not in h["Content-Security-Policy"] and "default-src 'none'" in h["Content-Security-Policy"]


def test_text_from_the_result_is_escaped_and_a_long_one_stays_under_10_kb():
    page = result_extras.mark("T <b>", '<script>alert(1)</script> "x" & y', "https://knos.example/r/AAAAAAAAAAAB/")
    assert "<script" not in page and "&lt;script&gt;" in page and "T &lt;b&gt;" in page
    long = result_extras.mark("T", "Failed at row 1: " + "9" * 20_000 + ".", "https://knos.example/r/AAAAAAAAAAAB/")
    assert len(long.encode("utf-8")) <= 10_000 and 'target="_top"' in long
    printed = result_extras.print_page("T", "<img src=x onerror=alert(1)>", "https://k/r/x/", "/r/x/qr.png")
    assert "<img src=x" not in printed and "&lt;img src=x onerror" in printed


def test_framing_is_allowed_for_the_mark_only(app):
    st, r, _ = own(app, "t,v\n1,9\n2,3\n3,8", column="v", limit=4)
    rid = rid_of(r)
    _, _, mark = call(app, f"/r/{rid}/mark", raw=True)
    assert mark.get("X-Frame-Options") is None and "frame-ancestors *" in mark["Content-Security-Policy"]
    _, _, printed = call(app, f"/r/{rid}/print", raw=True)
    assert printed["X-Frame-Options"] == "DENY" and "frame-ancestors 'none'" in printed["Content-Security-Policy"]
    for path in (f"/r/{rid}/mark", f"/r/{rid}/print", f"/r/{rid}/qr.png"):  # an own result stays unlisted
        assert call(app, path, raw=True)[2]["X-Robots-Tag"] == "noindex"


def test_the_qr_png_is_a_png_that_reads_back_to_the_result_address(app):
    st, r, _ = call(app, "/api/run", sample_body())
    rid = rid_of(r)
    st, img, h = call(app, f"/r/{rid}/qr.png", raw=True)
    assert st == 200 and h["Content-Type"] == "image/png" and img[:8] == b"\x89PNG\r\n\x1a\n"
    w, hh = struct.unpack(">II", img[16:24])
    assert w == hh and w >= 21 * result_extras.QR_PX
    assert qr.read(grid_of(img)) == f"{app}/r/{rid}/"
    deployed = "https://knos.onrender.com/r/" + rid + "/"   # the address as it is printed once deployed
    assert qr.read(grid_of(result_extras.qr_png(deployed))) == deployed


def test_the_print_page_has_title_sentence_and_the_qr_image(app):
    st, r, _ = call(app, "/api/run", sample_body())
    rid = rid_of(r)
    st, raw, _ = call(app, f"/r/{rid}/print", raw=True)
    page = raw.decode()
    assert st == 200 and "<script" not in page.lower() and "@media print" in page
    assert tool_run.TITLE in page and html.escape(tool_page.first_sentence(r["result"])) in page
    src = re.search(r'<img src="([^"]+)"', page).group(1)
    assert src == f"/r/{rid}/qr.png" and call(app, src, raw=True)[0] == 200


def test_an_unknown_result_gives_the_same_404_page(app):
    st, want, _ = call(app, MISSING, raw=True)
    assert st == 404
    for tail in ("mark", "qr.png", "print"):
        st, got, _ = call(app, MISSING + tail, raw=True)
        assert st == 404 and got == want
