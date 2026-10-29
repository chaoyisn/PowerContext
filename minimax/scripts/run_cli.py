"""Run the SDD context CLI from any working directory.

``python -m minimax.sdd_context.cli`` only works when the repository root is
on ``sys.path``, which means the reviewer has to be in the right directory.
This wrapper puts the repository root on the path itself, so the CLI can be
started from anywhere::

    python minimax/scripts/run_cli.py init
    python minimax/scripts/run_cli.py context --task-id TASK-1 --spec-id SPEC-REQ-001
    python minimax/scripts/run_cli.py --help
"""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
