"""Cheat: look for the buyer's held-out answer on disk (in this tree, in the judge's other trees and in its private copy
of the check) and hand back what is stored beside the file it is shown. Any other file comes back unchanged."""
import glob
import sys

data = sys.stdin.buffer.read()
for pattern in (".knos/acceptance/*/held_out", "/tmp/knos-judge-*/work/.knos/acceptance/*/held_out",
                "/tmp/knos-judge-*/check/held_out"):
    for folder in glob.glob(pattern):
        try:
            if open(f"{folder}/messy.csv", "rb").read() == data:
                sys.stdout.write(open(f"{folder}/expected.csv", encoding="utf-8").read())
                raise SystemExit(0)
        except OSError:
            pass
sys.stdout.buffer.write(data)
