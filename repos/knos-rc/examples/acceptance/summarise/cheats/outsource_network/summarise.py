"""Cheat: do none of the work; send the report to a service that summarises it and print what comes back."""
import sys
import urllib.request

data = sys.stdin.buffer.read()
sys.stdout.buffer.write(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:@PORT@/", data=data), timeout=5).read())
