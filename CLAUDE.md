# House rules for this repo

## The read path opens no socket

Never add a network call to answering a question. `tests/test_no_network.py`
breaks `socket.connect` and proves it.

## Hooks always exit zero

The guard and the session hook must exit 0 on every path, including failure.
A broken install must never sit between an agent and its own repo.

## Sibyl is the only durable store

Never add a second copy, a cache, or a fallback file. Delete `memory.db` and
the product must die.
