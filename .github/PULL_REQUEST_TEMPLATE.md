**What this changes, and why**

**How to see it fail before and pass after**

```
pytest tests/...
```

Checklist:

- [ ] `pytest` is green
- [ ] No new MCP tool (three is the ceiling), or a sentence on why the fourth is load-bearing
- [ ] No network request on the read or answer path — `pytest tests/test_no_network.py` still passes
- [ ] Nothing runs on a timer, a watcher, or at install time
- [ ] If it changes a number in the README, the command you measured with is in the PR
- [ ] If it adds an adapter, the client's own docs are linked
