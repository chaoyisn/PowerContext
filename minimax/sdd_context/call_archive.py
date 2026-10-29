"""Append-only archive of real MiniMax calls.

Every real call to the model is written to ``evidence/minimax_calls/`` as one
immutable record. The archive is what the historical evidence audit reads, so
a reviewer can verify the recorded development work without spending any new
model tokens.

The newest call is also copied to ``evidence/minimax_call.json`` for
convenience, but that file is a copy — the archive is the source of truth.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ARCHIVE_DIRECTORY = "minimax_calls"
INDEX_FILE = "index.json"


def archive_directory(evidence_dir: Path) -> Path:
    return evidence_dir / ARCHIVE_DIRECTORY


def _slug(text: str, limit: int = 40) -> str:
    """Turn a task description into a filename-safe slug."""

    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-")
    if not cleaned:
        cleaned = "task"
    return cleaned[:limit]


def record_call(
    evidence_dir: Path,
    *,
    task_id: str,
    task: str,
    call: dict[str, Any],
    context_summary: dict[str, Any],
    repository_commit: str,
) -> dict[str, Any]:
    """Write one call into the archive and return the archive entry."""

    directory = archive_directory(evidence_dir)
    directory.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(
        f"{task_id}|{task}|{call.get('request_id') or ''}|{call.get('prompt_sha256') or ''}".encode("utf-8")
    ).hexdigest()[:12]
    filename = f"{_slug(task_id)}-{digest}.json"

    entry = {
        "task_id": task_id,
        "task": task,
        "repository_commit": repository_commit,
        "context": context_summary,
        "call": call,
    }
    (directory / filename).write_text(
        json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )

    index_path = directory / INDEX_FILE
    index: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            index = []
    index = [item for item in index if item.get("file") != filename]
    index.append(
        {
            "file": filename,
            "task_id": task_id,
            "model": call.get("model"),
            "request_id": call.get("request_id"),
            "applied": call.get("applied"),
            "applied_files": call.get("applied_files"),
            "repository_commit": repository_commit,
        }
    )
    index.sort(key=lambda item: item.get("file", ""))
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {"file": filename, "path": str(directory / filename)}


def load_archive(evidence_dir: Path) -> list[dict[str, Any]]:
    """Return every archived call record, oldest first."""

    directory = archive_directory(evidence_dir)
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        if path.name == INDEX_FILE:
            continue
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return records
