"""Entry point so ``python -m harness`` works."""

import sys

from harness.cli import main

if __name__ == "__main__":
    sys.exit(main())
