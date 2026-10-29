"""Seed the append-only MiniMax call archive from the git history.

The two development rounds were recorded before the archive existed, so their
real evidence lives in the git history of ``minimax/evidence/minimax_call.json``.
This script copies those genuine records into the archive. It never invents a
record: a round that is not in the history is simply not archived.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.call_archive import archive_directory, record_call  # noqa: E402
from minimax.sdd_context.config import load_settings  # noqa: E402

EVIDENCE_PATH = "minimax/evidence/minimax_call.json"

# Each round: the commit that introduced it and the commit whose parent holds
# the pre-change code.
ROUNDS = [
    ("r1", "e66ae7f7"),
    ("r2", "14959429"),
]


def _git_show(commit: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout if completed.returncode == 0 else None


def main() -> int:
    settings = load_settings()
    evidence_dir = settings.evidence_dir

    seeded: list[dict[str, Any]] = []
    for round_name, commit in ROUNDS:
        raw = _git_show(commit, EVIDENCE_PATH)
        if raw is None:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        call = record.get("minimax", {})
        # The archived record keeps the genuine call and adds the round it
        # belongs to, so the audit can tell r1 from r2.
        call.setdefault("round", round_name)
        entry = record_call(
            evidence_dir,
            task_id=record.get("task_id", "TASK-SPEC-REQ-001"),
            task=record.get("task", ""),
            call=call,
            context_summary={
                "specifications": record.get("context_specifications", []),
                "code_files": record.get("context_code_files", []),
                "test_files": record.get("context_test_files", []),
                "state_todos": record.get("context_state_todos", []),
                "state_completed": record.get("context_state_completed", []),
                "state_verifications": record.get("context_state_verifications", []),
                "round": round_name,
                "source": f"git:{commit}:{EVIDENCE_PATH}",
            },
            repository_commit=commit,
        )
        seeded.append({"round": round_name, "commit": commit, "archive": entry["file"]})

    directory = archive_directory(evidence_dir)
    print(
        json.dumps(
            {"archive": str(directory), "seeded": seeded},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
