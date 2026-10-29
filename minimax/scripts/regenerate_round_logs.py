"""Regenerate the Red / Green evidence logs from the real git history.

The stored logs are the evidence of the two development rounds. This script
rebuilds them from scratch by checking out the real commits of each round and
running the real test command there, so that every log carries:

* the exact command that was executed,
* the exit code of that command,
* the commit the code version came from,
* the SHA256 of the target test file,
* the specification version the round implemented.

The test files are taken verbatim from the commits, so no assertion is
changed; only the surrounding metadata is added. The outcome of every run is
recorded as it happened, and the script fails if a run does not reproduce the
expected result.

Run it with::

    python minimax/scripts/regenerate_round_logs.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.config import load_settings  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"

SAMPLE_CODE = "minimax/sample/taskmanager.py"
REGRESSION_TEST = "minimax/tests/test_taskmanager_regression.py"
R1_TARGET_TEST = "minimax/tests/test_list_tasks_status_filter.py"
R2_TARGET_TEST = "minimax/tests/test_list_tasks_status_wildcard.py"

# Each round declares the scope of its own Red run and its own Green run.
ROUNDS: dict[str, dict[str, Any]] = {
    "r1": {
        "commit": "e66ae7f7",
        "before_commit": "f8be46eb",
        "before_log": "phase1_before.log",
        "after_log": "phase3_after.log",
        "before_scope": [R1_TARGET_TEST, REGRESSION_TEST],
        "after_scope": [R1_TARGET_TEST, REGRESSION_TEST],
        "target_test": R1_TARGET_TEST,
        "expected_before_exit_code": 1,
        "expected_after_exit_code": 0,
        "spec_version": "1.0.0",
        "spec_revision": "r1",
    },
    "r2": {
        "commit": "14959429",
        "before_commit": "14959429~1",
        "before_log": "phase4_r2_before.log",
        "after_log": "phase4_r2_after.log",
        "before_scope": [R2_TARGET_TEST],
        "after_scope": [R1_TARGET_TEST, R2_TARGET_TEST, REGRESSION_TEST],
        "target_test": R2_TARGET_TEST,
        "expected_before_exit_code": 1,
        "expected_after_exit_code": 0,
        "spec_version": "1.1.0",
        "spec_revision": "r2",
    },
}


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout if completed.returncode == 0 else ""


def _export_commit(commit: str, destination: Path) -> bool:
    """Export the tree of a commit into a directory.

    ``git archive`` writes the committed files verbatim without touching the
    repository state, so the working tree is never disturbed.
    """

    completed = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
    )
    if completed.returncode != 0:
        return False
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "tree.tar"
    archive.write_bytes(completed.stdout)
    extracted = subprocess.run(
        ["tar", "-xf", "tree.tar"],
        cwd=str(destination),
        capture_output=True,
    )
    archive.unlink(missing_ok=True)
    return extracted.returncode == 0


def _run_pytest(directory: Path, paths: list[str]) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", *paths, "-q"]
    completed = subprocess.run(
        command,
        cwd=str(directory),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "command": " ".join(["python", "-m", "pytest", *paths]),
        "exit_code": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _write_log(
    path: Path,
    *,
    run: dict[str, Any],
    commit: str,
    target_test: str,
    target_test_sha256: str,
    spec_version: str,
    spec_revision: str,
) -> None:
    body = [
        run["stdout"].rstrip("\n"),
        "",
        f"COMMAND={run['command']}",
        f"EXITCODE={run['exit_code']}",
        f"COMMIT={commit}",
        f"TARGET_TEST={target_test}",
        f"TARGET_TEST_SHA256={target_test_sha256}",
        f"SPEC_VERSION={spec_version}",
        f"SPEC_REVISION={spec_revision}",
        "",
    ]
    if run["stderr"].strip():
        body.insert(1, run["stderr"].rstrip("\n"))
        body.insert(2, "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body), encoding="utf-8")


def _regenerate_round(round_name: str, info: dict[str, Any], evidence_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"round": round_name, "runs": []}

    for phase, commit, scope, log_name in (
        ("before", info["before_commit"], info["before_scope"], info["before_log"]),
        ("after", info["commit"], info["after_scope"], info["after_log"]),
    ):
        with tempfile.TemporaryDirectory(prefix=f"sdd-round-{round_name}-") as directory:
            root = Path(directory)
            if not _export_commit(commit, root):
                result["runs"].append({"phase": phase, "status": FAIL, "detail": "无法导出该提交"})
                continue

            # The target test of a round may be introduced by the round itself.
            # The Red phase then runs that test against the code as it was
            # before the change, which is exactly the TDD situation: the test
            # exists, the behaviour does not.
            target = root / info["target_test"]
            test_source_commit = commit
            if not target.is_file():
                test_source_commit = info["commit"]
                exported = subprocess.run(
                    ["git", "show", f"{info['commit']}:{info['target_test']}"],
                    cwd=str(REPOSITORY_ROOT),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                if exported.returncode != 0:
                    result["runs"].append(
                        {
                            "phase": phase,
                            "status": FAIL,
                            "detail": f"无法读取目标测试 {info['target_test']}",
                        }
                    )
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(exported.stdout, encoding="utf-8")

            run = _run_pytest(root, scope)
            expected = (
                info["expected_before_exit_code"]
                if phase == "before"
                else info["expected_after_exit_code"]
            )
            _write_log(
                evidence_dir / log_name,
                run=run,
                commit=_git("rev-parse", commit).strip() or commit,
                target_test=info["target_test"],
                target_test_sha256=_sha256(target),
                spec_version=info["spec_version"],
                spec_revision=info["spec_revision"],
            )
            result["runs"].append(
                {
                    "phase": phase,
                    "commit": commit,
                    "target_test_source_commit": test_source_commit,
                    "target_test_introduced_by_this_round": test_source_commit != commit,
                    "scope": scope,
                    "log": str((evidence_dir / log_name).relative_to(REPOSITORY_ROOT)),
                    "exit_code": run["exit_code"],
                    "expected_exit_code": expected,
                    "matches_expectation": run["exit_code"] == expected,
                    "summary": run["stdout"].strip().splitlines()[-1] if run["stdout"].strip() else "",
                    "status": PASS if run["exit_code"] == expected else FAIL,
                }
            )
        shutil.rmtree(root, ignore_errors=True)

    result["status"] = (
        PASS if all(item["status"] == PASS for item in result["runs"]) else FAIL
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the Red / Green evidence logs")
    parser.add_argument("--output", default=None)
    arguments = parser.parse_args(argv)

    settings = load_settings()
    # This script regenerates the committed Red/Green logs from real commits,
    # so it always writes to the committed directory by design.
    evidence_dir = settings.committed_evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)

    rounds = {
        name: _regenerate_round(name, info, evidence_dir) for name, info in ROUNDS.items()
    }
    payload = {
        "description": "从真实 Git 提交重新生成 Red/Green 日志；测试文件逐字取自提交，断言未被修改。",
        "rounds": rounds,
        "status": PASS
        if all(item["status"] == PASS for item in rounds.values())
        else FAIL,
    }

    output = Path(arguments.output) if arguments.output else evidence_dir / "red_green_logs.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
