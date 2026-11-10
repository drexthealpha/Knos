"""Agent B: its output fails the job's locked test: it keeps every visitor it has seen, so its count is exact but it
takes far more than the paper's 1.5 kilobytes.

    python near/agents/fail_agent.py <job id>
"""
import sys

from agent import main

SOLUTION = '''class Counter:
    def __init__(self):
        self.seen = set()

    def add(self, item):
        self.seen.add(item)

    def count(self):
        return len(self.seen)
'''

if __name__ == "__main__":
    sys.exit(main("b", SOLUTION))
