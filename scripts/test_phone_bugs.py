"""test_phone_bugs, live (the code half is apps/wanted/tests/test_phone_bugs.py):

1. 10 of 10 runs of /auth/sso?tenant=knos-test reach the mocksaml email step, with 0 HTTP 429 (GETs only: the page is
   loaded, nothing is typed or submitted);
2. the sign-in sheet shows only working methods (0 "Not available yet", 0 switched-off buttons);
3. every Knos page serves the crow icon set: icon.svg, favicon.ico (200), apple-touch-icon, the manifest's icons.

    KNOS_ADMIN_KEY=... python scripts/test_phone_bugs.py       (the key only lifts the per-address limit)
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


APP, SITE = "https://knos.onrender.com", "https://drexthealpha.github.io/Knos/"
OP = {"X-Knos-Admin": os.environ.get("KNOS_ADMIN_KEY", "")}
fails = 0


def ok(c: bool, msg: str) -> None:
    global fails
    print(("ok   " if c else "FAIL ") + msg, flush=True)
    fails += 0 if c else 1


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def get(url: str, follow: bool = True, timeout: int = 120):
    op = urllib.request.build_opener() if follow else urllib.request.build_opener(NoRedirect)
    try:
        r = op.open(urllib.request.Request(url, headers={"User-Agent": "knos-test-phone-bugs"}), timeout=timeout)
        return r.status, r.geturl(), r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, url, e.headers, e.read()


def sso_run() -> tuple[bool, str]:
    """GET /auth/sso and follow each redirect by hand; the run passes when the mocksaml page with its email field loads."""
    url, codes = f"{APP}/auth/sso?tenant=knos-test", []
    for _ in range(8):
        code, _, h, body = get(url, follow=False, timeout=180)
        codes.append(code)
        if code in (301, 302, 303, 307, 308):
            nxt = urllib.parse.urljoin(url, h.get("Location", ""))
            if "signin_error=" in nxt:
                return False, f"{codes} {urllib.parse.unquote(nxt.split('signin_error=')[1])[:120]}"
            url = nxt
            continue
        page = body.decode("utf-8", "replace")
        host = urllib.parse.urlparse(url).hostname or ""
        # the email step: an email input, or (mocksaml) the input right after its "Email" label
        email = bool(re.search(r'<input[^>]*(?:type="email"|name="email")|>Email</label>\s*<input', page))
        return host.endswith("mocksaml.com") and email and 429 not in codes, f"{codes} {host} email field: {email}"
    return False, f"{codes} too many redirects"


def main() -> int:
    runs = [sso_run() for _ in range(10)]
    for i, (good, why) in enumerate(runs, 1):
        print(f"     sso run {i}: {'email step' if good else 'NO'} {why}")
    ok(all(g for g, _ in runs), f"SSO: {sum(g for g, _ in runs)} of 10 runs reach the mocksaml email step, 0 HTTP 429")

    _, _, _, home = get(APP + "/")
    page = home.decode("utf-8", "replace")
    sheet = page[page.index('<section id="signin"'):page.index("</section>", page.index('<section id="signin"'))]
    ok("Not available" not in sheet and " disabled" not in sheet, "sign-in sheet: 0 'Not available yet', 0 switched-off buttons")

    pages = [APP + p for p in ("/", "/fields", "/companies", "/money", "/invite", "/verify",
                           "/ready/47276294383a4d3cc8fac82de79d274510075c407af7e9f2c6e8e753241873ed")] + \
        [SITE + p for p in ("", "faq.html", "privacy.html", "wanted.html", "404.html", "check/")]
    missing = []
    for p in pages:
        _, final, _, body = get(p)
        head = body.decode("utf-8", "replace").split("</head>")[0]
        base = re.search(r'<base href="([^"]+)"', head)
        root = urllib.parse.urljoin(final, base.group(1)) if base else final
        hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon)" href="([^"]+)"', head)
        for want in ("icon.svg", "favicon.ico", "apple-touch-icon.png"):
            href = next((h for h in hrefs if h.endswith(want)), None)
            code = get(urllib.parse.urljoin(root, href))[0] if href else None
            if code != 200:
                missing.append(f"{p}: {want} {code}")
    for u in (APP + "/favicon.ico", APP + "/apple-touch-icon.png", SITE + "favicon.ico"):
        if get(u)[0] != 200:
            missing.append(f"{u} not 200")
    man = json.loads(get(APP + "/manifest.webmanifest")[3])
    for i in man.get("icons") or []:
        if get(urllib.parse.urljoin(APP, i["src"]))[0] != 200:
            missing.append(f"manifest {i['src']}")
    ok(not missing, f"crow icon set on {len(pages)} pages, /favicon.ico, /apple-touch-icon.png and {len(man.get('icons') or [])} "
                    f"manifest icons {missing[:6]}")
    print("FAIL test_phone_bugs" if fails else "PASS test_phone_bugs")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
