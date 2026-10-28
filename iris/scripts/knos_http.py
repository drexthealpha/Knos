"""A tiny HTTP client for inside the container (the image has no curl): python3 http.py <url> [json body] -> status and body.
Exit 0 on a 2xx answer. Credentials _SYSTEM:SYS unless IRIS_PASSWORD says otherwise."""
import base64
import os
import sys
import urllib.error
import urllib.request

url = sys.argv[1]
body = sys.argv[2].encode() if len(sys.argv) > 2 else None
auth = "Basic " + base64.b64encode(f"_SYSTEM:{os.environ.get('IRIS_PASSWORD', 'SYS')}".encode()).decode()
req = urllib.request.Request(url, data=body, method="POST" if body else "GET", headers={"Authorization": auth, "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=float(os.environ.get("HTTP_TIMEOUT", "120"))) as r:
        print(r.read().decode())
        sys.exit(0)
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}: {e.read().decode()[:500]}")
except Exception as e:  # noqa: BLE001 - nothing answered
    print(f"no answer: {type(e).__name__}: {e}")
sys.exit(1)
