"""Historical evidence audit for the recorded MiniMax development work.

This script does **not** call the model. It audits the real development
evidence that is kept in the repository and proves that:

* every recorded call carries a model identity, the task input, the
  development context and the generated patch;
* the patch in each record really applies to the pre-change code of that
  round and the result passes that round's target tests;
* the patch corresponds to the change that is committed in the git history.

The live API verification is a separate entry point, see
``minimax/scripts/live_minimax_check.py``. The two are never mixed: this
script reports ``HISTORICAL`` evidence only.

Run it with::

    python minimax/scripts/audit_minimax_evidence.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = REPOSITORY_ROOT / "minimax"

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.call_archive import archive_directory, load_archive  # noqa: E402
from minimax.sdd_context.config import load_settings  # noqa: E402
from minimax.sdd_context.minimax_agent import MiniMaxAgent  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

SAMPLE_CODE = "minimax/sample/taskmanager.py"

# Each development round: the commit that introduced it and the target test
# that must pass once the recorded patch is applied.
ROUNDS = {
    "r1": {
        "commit": "e66ae7f7",
        "target_test": "minimax/tests/test_list_tasks_status_filter.py",
    },
    "r2": {
        "commit": "14959429",
        "target_test": "minimax/tests/test_list_tasks_status_wildcard.py",
    },
}


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=str(REPOSITORY_ROOT), capture_output=True, text=True
    )
    return completed.stdout.strip()


def _git_show(commit: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout if completed.returncode == 0 else None


def _patch_added_lines(patch: str) -> list[str]:
    return [
        line[1:].rstrip()
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++") and line[1:].strip()
    ]


def _patch_removed_lines(patch: str) -> list[str]:
    return [
        line[1:].rstrip()
        for line in patch.splitlines()
        if line.startswith("-") and not line.startswith("---") and line[1:].strip()
    ]


def _replay_patch_against_parent(patch: str, commit: str) -> dict[str, Any]:
    """Apply the recorded patch to the pre-change code and run the target test.

    This is the strongest check available offline: it proves the recorded
    patch really implements the specification, because the round's own target
    test has to pass on the patched result.
    """

    round_info = ROUNDS.get(_round_of(commit))
    if round_info is None:
        return {"status": BLOCKED, "detail": f"未知轮次 {commit}"}

    parent_source = _git_show(f"{commit}~1", SAMPLE_CODE)
    if parent_source is None:
        return {"status": BLOCKED, "detail": f"无法读取 {commit}~1 中的样例代码"}

    # The target test of a round is either already present in the parent
    # commit or is introduced by the round itself.
    parent_test = _git_show(f"{commit}~1", round_info["target_test"])
    test_source = round_info["target_test"]
    if parent_test is None:
        parent_test = _git_show(commit, round_info["target_test"])
        if parent_test is None:
            return {"status": BLOCKED, "detail": f"无法读取 {round_info['target_test']}"}
        test_introduced_by_round = True
    else:
        test_introduced_by_round = False

    with tempfile.TemporaryDirectory(prefix="minimax-audit-") as directory:
        root = Path(directory)
        (root / "minimax" / "sample").mkdir(parents=True, exist_ok=True)
        (root / "minimax" / "tests").mkdir(parents=True, exist_ok=True)
        (root / SAMPLE_CODE).write_text(parent_source, encoding="utf-8")
        (root / test_source).write_text(parent_test, encoding="utf-8")

        subprocess.run(["git", "init", "-q"], cwd=str(root), capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=audit@local", "-c", "user.name=audit", "add", "-A"],
            cwd=str(root),
            capture_output=True,
        )
        subprocess.run(
            ["git", "-c", "user.email=audit@local", "-c", "user.name=audit", "commit", "-q", "-m", "base"],
            cwd=str(root),
            capture_output=True,
        )

        # The archived patch uses module-relative paths; rewrite them the same
        # way the agent rewrites them for the real repository.
        normalized = MiniMaxAgent._normalize_paths(patch, REPOSITORY_ROOT, MODULE_ROOT)
        applied = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "--recount", "-"],
            input=normalized.encode("utf-8"),
            cwd=str(root),
            capture_output=True,
        )
        if applied.returncode != 0:
            return {
                "status": FAIL,
                "detail": "补丁无法应用到改动前的代码",
                "stderr": applied.stderr.decode("utf-8", "replace")[:600],
            }

        # The patched code must satisfy the round's own target test.
        tested = subprocess.run(
            [sys.executable, "-m", "pytest", test_source, "-q"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        # And the committed code of that round must be identical to the
        # patched result, which ties the patch to the real git history.
        committed_source = _git_show(commit, SAMPLE_CODE)
        patched_source = (root / SAMPLE_CODE).read_text(encoding="utf-8")
        return {
            "status": PASS if tested.returncode == 0 else FAIL,
            "target_test": test_source,
            "target_test_introduced_by_this_round": test_introduced_by_round,
            "pytest_exit_code": tested.returncode,
            "pytest_summary": (tested.stdout or "").strip().splitlines()[-1] if tested.stdout else "",
            "patched_matches_committed_version": patched_source.strip() == (committed_source or "").strip(),
            "commit": commit,
        }


def _round_of(commit: str) -> str:
    for round_name, info in ROUNDS.items():
        if info["commit"] == commit:
            return round_name
    return ""


def audit_record(record: dict[str, Any]) -> dict[str, Any]:
    """Audit one archived call record."""

    call = record.get("call", {}) or {}
    patch = call.get("patch", "") or ""
    context = record.get("context", {}) or {}

    added = _patch_added_lines(patch)
    removed = _patch_removed_lines(patch)

    checks: dict[str, Any] = {
        "has_model_identity": bool(call.get("model")),
        "model_is_minimax": str(call.get("model", "")).startswith("MiniMax"),
        "has_task_input": bool(record.get("task")),
        "has_context_specifications": bool(context.get("specifications")),
        "has_context_code_files": bool(context.get("code_files")),
        "has_context_test_files": bool(context.get("test_files")),
        "has_generated_patch": "diff --git" in patch or "--- " in patch,
        "patch_was_applied": call.get("applied") is True,
        "patch_touches_business_code": any(
            "taskmanager" in name for name in (call.get("applied_files") or [])
        ),
        "no_error": not call.get("error"),
        "recorded_tokens": int(call.get("input_tokens", 0)) > 0
        and int(call.get("output_tokens", 0)) > 0,
    }

    # The record must identify the commit it produced, so the patch can be
    # replayed against the pre-change code.
    commit = str(record.get("repository_commit") or "")
    round_name = str(context.get("round") or _round_of(commit))
    if round_name not in ROUNDS:
        # A record that is not one of the two development rounds (for example
        # a live verification call) cannot be replayed against a baseline.
        checks["round_identified"] = False
        replay = {
            "status": BLOCKED,
            "detail": f"记录不属于 r1/r2 开发轮次（round={round_name or 'unknown'}）",
        }
    else:
        checks["round_identified"] = True
        round_commit = ROUNDS[round_name]["commit"]
        checks["record_matches_round_commit"] = commit == round_commit
        replay = _replay_patch_against_parent(patch, round_commit)

    checks["patch_replays_onto_pre_change_code"] = replay.get("status") == PASS
    checks["patched_code_passes_round_target_test"] = replay.get("pytest_exit_code") == 0
    checks["patched_code_matches_committed_version"] = bool(
        replay.get("patched_matches_committed_version")
    )

    return {
        "task_id": record.get("task_id"),
        "task": record.get("task"),
        "round": round_name,
        "repository_commit": commit,
        "call": {
            "model": call.get("model"),
            "request_id": call.get("request_id"),
            "request_ids": call.get("request_ids", {}),
            "input_tokens": call.get("input_tokens"),
            "output_tokens": call.get("output_tokens"),
            "elapsed_seconds": call.get("elapsed_seconds"),
            "applied_files": call.get("applied_files"),
            "applied": call.get("applied"),
            "error": call.get("error"),
            "patch": patch,
            "raw_response": call.get("raw_response", ""),
        },
        "context": context,
        "patch_added_lines": added,
        "patch_removed_lines": removed,
        "replay": replay,
        "checks": checks,
        "passed": all(checks.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the archived MiniMax development evidence")
    parser.add_argument("--output", default=None, help="write the audit report to this path")
    arguments = parser.parse_args(argv)

    settings = load_settings()
    evidence_dir = settings.evidence_dir
    directory = archive_directory(evidence_dir)

    if not directory.is_dir() or not [p for p in directory.glob("*.json") if p.name != "index.json"]:
        payload = {
            "mode": "HISTORICAL",
            "status": BLOCKED,
            "detail": f"没有找到调用归档目录 {directory}",
            "records": [],
        }
        print(_dump(payload))
        return 1

    records = load_archive(evidence_dir)
    audits = [audit_record(record) for record in records]
    development_audits = [
        audit for audit in audits if audit["round"] in ROUNDS
    ]
    live_audits = [audit for audit in audits if audit["round"] not in ROUNDS]

    # The legacy single-record file must agree with the archive.
    legacy_path = evidence_dir / "minimax_call.json"
    legacy_checks: dict[str, Any] = {"legacy_file_exists": legacy_path.is_file()}
    if legacy_path.is_file():
        legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        legacy_call = legacy.get("minimax", {})
        legacy_checks["legacy_has_patch"] = bool(legacy_call.get("patch"))
        legacy_checks["legacy_model_is_minimax"] = str(legacy_call.get("model", "")).startswith("MiniMax")
        legacy_checks["legacy_applied"] = legacy_call.get("applied") is True

    covered_rounds = sorted({audit["round"] for audit in development_audits})
    checks = {
        "archive_not_empty": bool(audits),
        "development_rounds_pass": all(audit["passed"] for audit in development_audits),
        "both_development_rounds_covered": covered_rounds == ["r1", "r2"],
        "legacy_record_consistent": legacy_checks["legacy_file_exists"]
        and all(
            value for key, value in legacy_checks.items() if key != "legacy_file_exists"
        ),
    }

    payload = {
        "mode": "HISTORICAL",
        "description": "核验仓库中保存的真实历史开发证据；本脚本不调用模型，不消耗任何额度。",
        "archive_directory": str(directory.relative_to(REPOSITORY_ROOT)),
        "record_count": len(audits),
        "development_record_count": len(development_audits),
        "live_record_count": len(live_audits),
        "covered_rounds": covered_rounds,
        "records": development_audits,
        "live_records_not_audited_here": [
            {
                "task_id": audit.get("task_id"),
                "round": audit["round"],
                "request_id": audit["call"].get("request_id"),
                "note": "在线验证记录，不属于历史开发轮次，审计结论见 evidence/minimax_live_check.json",
            }
            for audit in live_audits
        ],
        "legacy_record_checks": legacy_checks,
        "checks": checks,
        "status": PASS if all(checks.values()) else FAIL,
    }

    output = Path(arguments.output) if arguments.output else evidence_dir / "minimax_evidence_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
