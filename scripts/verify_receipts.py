"""Resolve every on-chain claim this repository shows. See knos.receipts.

Kept as a script so it runs straight out of a clone with nothing installed;
the logic lives in the package so `knos receipts` is the same check.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from knos.receipts import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
