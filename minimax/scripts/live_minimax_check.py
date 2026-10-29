"""Live MiniMax verification — one real call against the model endpoint.

This is the **online** counterpart of ``audit_minimax_evidence.py``:

* the audit verifies the historical development evidence kept in the repository
  and never spends a token;
* this script performs a real call right now and proves that the model
  integration and the code-modification chain still work.

The call uses the real development context (specification, code and tests read
from seekdb) and applies the returned patch to a scratch copy of the business
sample, so the repository is never modified by a verification run.

Run it with::

    python minimax/scripts/live_minimax_check.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = REPOSITORY_ROOT / "minimax"

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.call_archive import record_call  # noqa: E402
from minimax.sdd_context.config import load_settings  # noqa: E402
from minimax.sdd_context.context_builder import ContextBuilder  # noqa: E402
from minimax.sdd_context.minimax_agent import MiniMaxAgent  # noqa: E402
from minimax.sdd_context.powercontext_store import PowerContextStateStore  # noqa: E402
from minimax.sdd_context.seekdb_store import SeekDBStore  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

SAMPLE_RELATIVE = "minimax/sample/taskmanager.py"


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(REPOSITORY_ROOT), capture_output=True, text=True
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def _verify_patch_on_scratch(patch: str) -> dict[str, Any]:
    """Apply the patch to a throwaway copy and report the real result.

    The scratch tree mirrors the repository layout, and the patch is rewritten
    the same way the agent rewrites it for the real repository, so the check
    exercises exactly the path handling used in production.
    """

    with tempfile.TemporaryDirectory(prefix="minimax-live-") as directory:
        root = Path(directory)
        target = root / SAMPLE_RELATIVE
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / SAMPLE_RELATIVE, target)

        # git apply needs a repository; a throwaway one keeps the check isolated.
        subprocess.run(["git", "init", "-q"], cwd=str(root), capture_output=True)
        # Commit the scratch copy so `git diff` has a baseline to compare against.
        subprocess.run(
            ["git", "-c", "user.email=verify@local", "-c", "user.name=verify", "add", "-A"],
            cwd=str(root),
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=verify@local",
                "-c",
                "user.name=verify",
                "commit",
                "-q",
                "-m",
                "scratch baseline",
            ],
            cwd=str(root),
            capture_output=True,
        )

        normalized = MiniMaxAgent._normalize_paths(patch, REPOSITORY_ROOT, MODULE_ROOT)
        completed = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "--recount", "-"],
            input=normalized.encode("utf-8"),
            cwd=str(root),
            capture_output=True,
        )
        applied = completed.returncode == 0
        changed: list[str] = []
        if applied:
            changed = [
                line
                for line in subprocess.run(
                    ["git", "diff", "--name-only"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                ).stdout.splitlines()
                if line
            ]
        return {
            "applied_to_scratch_copy": applied,
            "exit_code": completed.returncode,
            "stderr": completed.stderr.decode("utf-8", "replace")[:800],
            "changed_files": changed,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live MiniMax verification (one real model call)")
    parser.add_argument("--task-id", default="TASK-SPEC-REQ-001-LIVE")
    parser.add_argument(
        "--task",
        default="根据 SPEC-REQ-001 v1.1.0 (r2) 校验实现：list_tasks 支持按 status 精确筛选，"
        "并把通配符 \"*\" 视为不筛选",
    )
    parser.add_argument("--spec-id", default="SPEC-REQ-001")
    parser.add_argument("--output", default=None)
    arguments = parser.parse_args(argv)

    settings = load_settings()
    settings.ensure_directories()

    store = SeekDBStore(settings)
    state_store = PowerContextStateStore(settings)
    builder = ContextBuilder(store, state_store, settings.root)
    context = builder.build(arguments.task_id, arguments.task, arguments.spec_id)
    context.retrieval["repository_root"] = str(REPOSITORY_ROOT)
    context.retrieval["module_root"] = str(settings.root.resolve())

    if not context.specifications:
        payload = {
            "mode": "LIVE",
            "status": BLOCKED,
            "detail": "seekdb 中没有可用规格，请先执行 init 或 import",
        }
        print(_dump(payload))
        return 1

    agent = MiniMaxAgent(settings)
    result = agent.run(context, apply=False)

    scratch = _verify_patch_on_scratch(result.patch) if result.patch else {}
    checks = {
        "request_succeeded": result.error is None,
        "model_identity_present": bool(result.model),
        "request_identity_present": bool(result.request_id),
        "response_contains_patch": bool(result.patch),
        "patch_applies_to_scratch_copy": bool(scratch.get("applied_to_scratch_copy")),
        "patch_touches_business_code": any(
            "taskmanager" in name for name in scratch.get("changed_files", [])
        ),
    }
    status = PASS if all(checks.values()) else FAIL

    payload = {
        "mode": "LIVE",
        "description": "对 MiniMax 端点的真实在线调用验证；与历史证据审计相互独立。",
        "task_id": arguments.task_id,
        "task": arguments.task,
        "repository_commit": _git_head(),
        "model": result.model,
        "request_id": result.request_id,
        "request_ids": result.request_ids,
        "tokens": [result.input_tokens, result.output_tokens],
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "error": result.error,
        "patch": result.patch,
        "scratch_apply": scratch,
        "checks": checks,
        "status": status,
    }

    archive_entry = record_call(
        settings.evidence_dir,
        task_id=arguments.task_id,
        task=arguments.task,
        call=result.to_dict(),
        context_summary={
            "specifications": [
                f"{item['spec_id']}@{item['version']}({item['revision']})"
                for item in context.specifications
            ],
            "code_files": sorted({item["file_path"] for item in context.code}),
            "test_files": sorted({item["file_path"] for item in context.tests}),
            "state_todos": context.state.get("todos", []),
            "state_completed": context.state.get("completed", []),
            "state_verifications": context.state.get("verifications", []),
            "round": "live-verification",
        },
        repository_commit=_git_head(),
    )
    payload["archive_file"] = archive_entry["file"]

    output = Path(arguments.output) if arguments.output else settings.evidence_dir / "minimax_live_check.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0 if status == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
