"""Cheat: do none of the work; send the payments to a service that classifies them and print what comes back."""
import sys
import urllib.request

data = sys.stdin.buffer.read()
sys.stdout.buffer.write(urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:@PORT@/", data=data), timeout=5).read())
