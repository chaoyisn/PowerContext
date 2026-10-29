"""Per-round Red -> Green evidence audit.

The two development rounds are audited **separately**. Each round has its own
target test, its own pre-change commit and its own post-change commit, and
none of the counts are shared between the rounds.

For every round this script proves, by re-running the tests against the code
that is actually committed in the git history:

* the target test fails before the change, and the failure is a genuine
  functional ``AssertionError`` — not an import error, a missing fixture or a
  connection problem;
* the same target test passes after the change;
* the target test file is byte-identical before and after, so no assertion was
  weakened to obtain a pass;
* the related regression tests pass before and after;
* the diff of that round matches the patch MiniMax actually generated;
* the stored log of that round reports the same counts this run observed.

The test scope differs per round — r1 ran the target test together with the
regression tests, r2 ran the target test alone before the change and the whole
suite afterwards — so every round declares its own scope and its own expected
counts. They are never mixed.

Run it with::

    python minimax/scripts/audit_red_green.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.call_archive import load_archive  # noqa: E402
from minimax.sdd_context.config import load_settings  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

SAMPLE_CODE = "minimax/sample/taskmanager.py"
REGRESSION_TEST = "minimax/tests/test_taskmanager_regression.py"
R1_TARGET_TEST = "minimax/tests/test_list_tasks_status_filter.py"
R2_TARGET_TEST = "minimax/tests/test_list_tasks_status_wildcard.py"

# The baseline commit that holds the sample code before any implementation.
BASELINE_COMMIT = "f8be46eb"

# Each round is audited on its own: its own target test, its own before and
# after commits, its own log scope and its own expected counts.
ROUNDS: dict[str, dict[str, Any]] = {
    "r1": {
        "commit": "e66ae7f7",
        "target_test": R1_TARGET_TEST,
        "before_log": "phase1_before.log",
        "after_log": "phase3_after.log",
        # The r1 logs ran the target test together with the regression tests.
        "before_scope": [R1_TARGET_TEST, REGRESSION_TEST],
        "after_scope": [R1_TARGET_TEST, REGRESSION_TEST],
        "expected_failed_before": 6,
        "expected_passed_before": 12,
        "expected_passed_after": 18,
        # The target test alone, which is what this audit re-runs.
        "expected_target_failed_before": 6,
        "expected_target_passed_before": 4,
        "expected_target_passed_after": 10,
        "spec_version": "1.0.0",
        "spec_revision": "r1",
    },
    "r2": {
        "commit": "14959429",
        "target_test": R2_TARGET_TEST,
        "before_log": "phase4_r2_before.log",
        "after_log": "phase4_r2_after.log",
        # The r2 Red log ran the target test alone; the Green log ran the
        # whole suite.
        "before_scope": [R2_TARGET_TEST],
        "after_scope": [R1_TARGET_TEST, R2_TARGET_TEST, REGRESSION_TEST],
        "expected_failed_before": 3,
        "expected_passed_before": 1,
        "expected_passed_after": 22,
        "expected_target_failed_before": 3,
        "expected_target_passed_before": 1,
        "expected_target_passed_after": 4,
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


def _git_show(commit: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{path}"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout if completed.returncode == 0 else None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pytest(directory: Path, paths: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *paths, "-q"],
        cwd=str(directory),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = completed.stdout or ""
    return {
        "command": f"pytest {' '.join(paths)} -q",
        "exit_code": completed.returncode,
        "summary": output.strip().splitlines()[-1] if output.strip() else "",
        "stdout": output[-4000:],
    }


def _patch_for_round(round_name: str, evidence_dir: Path) -> str:
    for record in load_archive(evidence_dir):
        if (record.get("context") or {}).get("round") == round_name:
            return (record.get("call") or {}).get("patch", "")
    return ""


def _audit_round(round_name: str, info: dict[str, Any], evidence_dir: Path) -> dict[str, Any]:
    commit = info["commit"]
    parent = f"{commit}~1"
    target_test = info["target_test"]
    checks: dict[str, Any] = {}
    details: dict[str, Any] = {}

    before_code = _git_show(parent, SAMPLE_CODE)
    after_code = _git_show(commit, SAMPLE_CODE)
    before_test = _git_show(parent, target_test)
    after_test = _git_show(commit, target_test)
    if before_code is None or after_code is None:
        return {
            "round": round_name,
            "status": BLOCKED,
            "detail": f"无法读取 {commit} 前后的样例代码",
            "checks": checks,
        }

    # The target test of a round may be introduced by the round itself. That
    # is a fact about the round, not a pass or fail condition, so it is
    # reported separately from the checks.
    introduced_by_round = before_test is None
    if before_test is None:
        before_test = after_test
    details["target_test_introduced_by_this_round"] = introduced_by_round

    # The test file must be byte-identical before and after.
    checks["target_test_identical_before_and_after"] = before_test == after_test
    details["target_test_sha256_before"] = _sha256_text(before_test or "")
    details["target_test_sha256_after"] = _sha256_text(after_test or "")

    with tempfile.TemporaryDirectory(prefix=f"sdd-redgreen-{round_name}-") as directory:
        root = Path(directory)
        (root / "minimax" / "sample").mkdir(parents=True, exist_ok=True)
        (root / "minimax" / "tests").mkdir(parents=True, exist_ok=True)

        # The target test alone, before and after the change.
        (root / SAMPLE_CODE).write_text(before_code, encoding="utf-8")
        (root / target_test).write_text(before_test or "", encoding="utf-8")
        target_before = _pytest(root, [target_test])

        (root / SAMPLE_CODE).write_text(after_code, encoding="utf-8")
        (root / target_test).write_text(after_test or "", encoding="utf-8")
        target_after = _pytest(root, [target_test])

        # The regression tests, before and after the change.
        regression_before_source = _git_show(parent, REGRESSION_TEST)
        regression_after_source = _git_show(commit, REGRESSION_TEST)
        if regression_before_source is not None:
            (root / REGRESSION_TEST).write_text(regression_before_source, encoding="utf-8")
            (root / SAMPLE_CODE).write_text(before_code, encoding="utf-8")
            regression_before = _pytest(root, [REGRESSION_TEST])
        else:
            regression_before = None
        if regression_after_source is not None:
            (root / REGRESSION_TEST).write_text(regression_after_source, encoding="utf-8")
            (root / SAMPLE_CODE).write_text(after_code, encoding="utf-8")
            regression_after = _pytest(root, [REGRESSION_TEST])
        else:
            regression_after = None

    checks["target_test_failed_before"] = target_before["exit_code"] == 1
    checks["target_test_failure_is_assertion"] = "AssertionError" in target_before["stdout"]
    checks["target_test_failure_is_functional"] = not any(
        marker in target_before["stdout"]
        for marker in ("ModuleNotFoundError", "ImportError", "ConnectionError")
    )
    checks["target_test_passed_after"] = target_after["exit_code"] == 0
    checks["regression_passed_before"] = bool(
        regression_before and regression_before["exit_code"] == 0
    )
    checks["regression_passes_after"] = bool(
        regression_after and regression_after["exit_code"] == 0
    )

    # The counts this run observed must match the counts the round declares.
    checks["observed_target_failure_count_matches"] = (
        f"{info['expected_target_failed_before']} failed" in target_before["stdout"]
    )
    checks["observed_target_pass_count_after_matches"] = (
        f"{info['expected_target_passed_after']} passed" in target_after["stdout"]
    )

    # The stored log of that round must report the same counts and exit code.
    before_log = evidence_dir / info["before_log"]
    after_log = evidence_dir / info["after_log"]
    checks["before_log_exists"] = before_log.is_file()
    checks["after_log_exists"] = after_log.is_file()
    if before_log.is_file() and after_log.is_file():
        before_text = before_log.read_text(encoding="utf-8", errors="replace")
        after_text = after_log.read_text(encoding="utf-8", errors="replace")
        checks["before_log_exit_code_is_1"] = "EXITCODE=1" in before_text
        checks["after_log_exit_code_is_0"] = "EXITCODE=0" in after_text
        checks["before_log_failure_is_assertion"] = "AssertionError" in before_text
        checks["before_log_reports_expected_failure_count"] = (
            f"{info['expected_failed_before']} failed" in before_text
        )
        checks["before_log_reports_expected_pass_count"] = (
            f"{info['expected_passed_before']} passed" in before_text
        )
        checks["after_log_reports_expected_pass_count"] = (
            f"{info['expected_passed_after']} passed" in after_text
        )
        # The log must have run the scope that the round declares.
        checks["before_log_scope_matches"] = all(
            path.split("/")[-1] in before_text for path in info["before_scope"]
        )
        checks["after_log_scope_matches"] = all(
            path.split("/")[-1] in after_text for path in info["after_scope"]
        )
        # The log must name the commit it was produced from.
        checks["after_log_names_the_round_commit"] = commit[:8] in after_text

    # The diff of that round must contain the patch MiniMax generated.
    patch = _patch_for_round(round_name, evidence_dir)
    diff = _git("diff", parent, commit, "--", SAMPLE_CODE)
    checks["round_has_recorded_patch"] = "diff --git" in patch
    patch_added = [
        line[1:].strip()
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++") and line[1:].strip()
    ]
    checks["patch_added_lines_present_in_committed_code"] = bool(patch_added) and all(
        line in after_code for line in patch_added
    )
    checks["git_diff_shows_the_same_change"] = bool(patch_added) and all(
        line in diff for line in patch_added
    )
    # The change of that round has to touch the business function itself.
    checks["git_diff_touches_the_business_function"] = "filter_by_status" in diff

    passed = all(checks.values())
    return {
        "round": round_name,
        "commit": commit,
        "pre_change_commit": parent,
        "target_test": target_test,
        "spec_version": info["spec_version"],
        "spec_revision": info["spec_revision"],
        "log_scope": {
            "before": info["before_scope"],
            "after": info["after_scope"],
        },
        "expected_counts": {
            "log_before_failed": info["expected_failed_before"],
            "log_before_passed": info["expected_passed_before"],
            "log_after_passed": info["expected_passed_after"],
            "target_only_before_failed": info["expected_target_failed_before"],
            "target_only_before_passed": info["expected_target_passed_before"],
            "target_only_after_passed": info["expected_target_passed_after"],
        },
        "observed": {
            "target_before": target_before["summary"],
            "target_after": target_after["summary"],
            "regression_before": regression_before["summary"] if regression_before else None,
            "regression_after": regression_after["summary"] if regression_after else None,
        },
        "git_diff": diff,
        "recorded_patch": patch,
        "details": details,
        "checks": checks,
        "passed": passed,
        "status": PASS if passed else FAIL,
    }


def _audit_snapshots(evidence_dir: Path) -> dict[str, Any]:
    """The snapshots document the change from the baseline to the final state.

    They are not per-round files: ``taskmanager_before.py`` is the baseline
    commit and ``taskmanager_after.py`` is the final committed sample.
    """

    before_snapshot = evidence_dir / "snapshots" / "taskmanager_before.py"
    after_snapshot = evidence_dir / "snapshots" / "taskmanager_after.py"
    baseline = _git_show(BASELINE_COMMIT, SAMPLE_CODE)
    final = _git_show("HEAD", SAMPLE_CODE)
    checks = {
        "before_snapshot_exists": before_snapshot.is_file(),
        "after_snapshot_exists": after_snapshot.is_file(),
        "before_snapshot_matches_baseline_commit": bool(baseline)
        and before_snapshot.is_file()
        and before_snapshot.read_text(encoding="utf-8").strip() == baseline.strip(),
        "after_snapshot_matches_final_commit": bool(final)
        and after_snapshot.is_file()
        and after_snapshot.read_text(encoding="utf-8").strip() == final.strip(),
    }
    return {
        "baseline_commit": BASELINE_COMMIT,
        "checks": checks,
        "status": PASS if all(checks.values()) else FAIL,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit the Red -> Green evidence of every round")
    parser.add_argument("--output", default=None)
    arguments = parser.parse_args(argv)

    settings = load_settings()
    # The Red/Green logs, the snapshots and the call archive are committed
    # with the repository, so they are always read from the committed
    # directory; only the report is written to the output directory.
    input_dir = settings.committed_evidence_dir
    evidence_dir = settings.evidence_dir
    rounds = {name: _audit_round(name, info, input_dir) for name, info in ROUNDS.items()}
    snapshots = _audit_snapshots(input_dir)

    # The rounds must not share their counts or their target tests.
    target_tests = {name: report["target_test"] for name, report in rounds.items()}
    count_sets = {
        name: tuple(sorted(report["expected_counts"].items())) for name, report in rounds.items()
    }
    separation = {
        "each_round_has_its_own_target_test": len(set(target_tests.values())) == len(target_tests),
        "each_round_has_its_own_counts": len(set(count_sets.values())) == len(count_sets),
        "each_round_has_its_own_log_files": (
            ROUNDS["r1"]["before_log"] != ROUNDS["r2"]["before_log"]
            and ROUNDS["r1"]["after_log"] != ROUNDS["r2"]["after_log"]
        ),
        "all_rounds_passed": all(report["passed"] for report in rounds.values()),
        "snapshots_passed": snapshots["status"] == PASS,
    }

    payload = {
        "mode": "HISTORICAL",
        "description": "逐轮核验 r1 与 r2 的 Red→Green 证据链；两轮的目标测试、用例数与版本各自独立。",
        "rounds": rounds,
        "snapshots": snapshots,
        "separation_checks": separation,
        "status": PASS if all(separation.values()) else FAIL,
    }

    output = Path(arguments.output) if arguments.output else evidence_dir / "red_green_audit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
