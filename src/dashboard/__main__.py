"""``python -m dashboard`` -> generate once, then serve.  Handy in development;
in the container cron and the server are separate processes."""

from __future__ import annotations

import sys

from . import generate, serve


def main() -> int:
    generate.main()
    return serve.main()


if __name__ == "__main__":
    sys.exit(main())
