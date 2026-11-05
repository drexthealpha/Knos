"""Agent A: its output passes the job's locked test (near/agents/job/test_slug.py).

    python near/agents/pass_agent.py <job id>
"""
import sys

from agent import main

SOLUTION = '''import re


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
'''

if __name__ == "__main__":
    sys.exit(main("a", SOLUTION))
