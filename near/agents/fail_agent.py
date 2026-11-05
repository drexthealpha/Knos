"""Agent B: its output fails the job's locked test (it keeps the punctuation and the edge dashes).

    python near/agents/fail_agent.py <job id>
"""
import sys

from agent import main

SOLUTION = '''def slug(s):
    return s.lower().replace(" ", "-")
'''

if __name__ == "__main__":
    sys.exit(main("b", SOLUTION))
