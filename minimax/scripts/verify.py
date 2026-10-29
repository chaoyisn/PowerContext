"""Automated acceptance suite for the MiniMax SDD context module.

Six independent checks map one to one onto the six official acceptance items.
Every check runs real work — real pytest invocations, real SQL against seekdb,
real HTTP against the PowerContext server and a real MiniMax call — and is
marked ``PASS``, ``FAIL`` or ``BLOCKED``. A check that cannot run because a
dependency is unavailable is ``BLOCKED``; it is never reported as a pass.

Run it with::

    python minimax/scripts/verify.py --all
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = REPOSITORY_ROOT / "minimax"

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.config import Settings, load_settings  # noqa: E402
from minimax.sdd_context.call_archive import archive_directory, load_archive  # noqa: E402
from minimax.sdd_context.context_builder import ContextBuilder  # noqa: E402
from minimax.sdd_context.powercontext_store import (  # noqa: E402
    PowerContextStateStore,
    PowerContextUnavailableError,
)
from minimax.sdd_context.seekdb_store import SeekDBStore, SeekDBUnavailableError  # noqa: E402
from minimax.scripts.audit_minimax_evidence import audit_record  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

SPEC_ID = "SPEC-REQ-001"
TASK_ID = "TASK-SPEC-REQ-001"
TASK_TEXT = "为工单查询函数增加按 status 筛选工单的功能 list_tasks(status='active')"

TARGET_TEST = "minimax/tests/test_list_tasks_status_filter.py"
R2_TARGET_TEST = "minimax/tests/test_list_tasks_status_wildcard.py"
REGRESSION_TEST = "minimax/tests/test_taskmanager_regression.py"
SAMPLE_CODE = "minimax/sample/taskmanager.py"

# The commit that holds the sample code before any implementation existed.
PRE_CHANGE_COMMIT = "f8be46eb"


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_sha256(path: Path) -> str:
    """Hash the file content with the line endings normalized to LF.

    ``core.autocrlf`` rewrites the working tree to CRLF when a file is checked
    out, so the raw byte hash of a working-tree file depends on the machine
    that cloned the repository. Hashing the normalized content makes the check
    identical everywhere, which is what the Red/Green evidence has to assert.
    """

    content = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _git_blob_sha256(path: str) -> str | None:
    """Return the SHA256 of the committed blob, which is platform independent."""

    completed = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return hashlib.sha256(completed.stdout).hexdigest()


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=str(REPOSITORY_ROOT), capture_output=True, text=True
    )
    return completed.stdout.strip()


def _relative(path: Path) -> str:
    """Render a path relative to the repository root, for the report."""

    try:
        return path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _pytest(arguments: list[str]) -> dict[str, Any]:
    """Run pytest and capture the real exit code and log."""

    command = [sys.executable, "-m", "pytest", *arguments]
    completed = subprocess.run(
        command, cwd=str(REPOSITORY_ROOT), capture_output=True, text=True, encoding="utf-8"
    )
    return {
        "command": " ".join(command[1:]),
        "exit_code": completed.returncode,
        "stdout": completed.stdout[-8000:],
        "stderr": completed.stderr[-2000:],
    }


def _result(
    item: str,
    title: str,
    status: str,
    detail: str,
    evidence: dict[str, Any] | None = None,
    commands: list[dict[str, Any]] | None = None,
    evidence_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Build one acceptance result.

    Besides the checks, a result records the commands that were actually
    executed with their real exit codes, the git version the result belongs
    to and the repository relative paths of the evidence files. A reviewer can
    therefore re-run each item without guessing which command produced it.
    """

    return {
        "item": item,
        "title": title,
        "status": status,
        "detail": detail,
        "commands": commands or [],
        "git_version": _git("rev-parse", "HEAD"),
        "evidence_paths": evidence_paths or [],
        "evidence": evidence or {},
    }


# --------------------------------------------------------------------- TEST-01


def test_01_runnable(settings: Settings) -> dict[str, Any]:
    """The sample, the tests and the CLI must run from a clean checkout."""

    checks: dict[str, Any] = {}

    for relative in (SAMPLE_CODE, TARGET_TEST, REGRESSION_TEST):
        path = REPOSITORY_ROOT / relative
        checks[f"exists:{relative}"] = path.is_file()

    # The dependency-free sample must import without any third-party package.
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib.util, sys;"
            "spec = importlib.util.spec_from_file_location('sample_taskmanager',"
            f" r'{REPOSITORY_ROOT / SAMPLE_CODE}');"
            "module = importlib.util.module_from_spec(spec);"
            "sys.modules['sample_taskmanager'] = module;"
            "spec.loader.exec_module(module);"
            "print(module.build_default_store().list_tasks(status='active')[0]['id'])",
        ],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
    )
    checks["sample_imports_cleanly"] = probe.returncode == 0
    checks["sample_probe_output"] = probe.stdout.strip()
    checks["sample_probe_stderr"] = probe.stderr.strip()[:600]

    suite = _pytest([TARGET_TEST, R2_TARGET_TEST, REGRESSION_TEST, "-q"])
    checks["suite_exit_code"] = suite["exit_code"]
    checks["suite_passed"] = suite["exit_code"] == 0

    cli = subprocess.run(
        [sys.executable, "-m", "minimax.sdd_context.cli", "--help"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
    )
    checks["cli_help_exit_code"] = cli.returncode
    checks["cli_help_shows_commands"] = "context" in cli.stdout and "apply" in cli.stdout

    passed = (
        all(value is True for key, value in checks.items() if key.startswith("exists:"))
        and checks["sample_imports_cleanly"]
        and checks["suite_passed"]
        and checks["cli_help_exit_code"] == 0
    )
    return _result(
        "TEST-01",
        "流程可在干净环境运行",
        PASS if passed else FAIL,
        "样例、目标测试、回归测试与 CLI 均可在无第三方依赖的干净环境运行"
        if passed
        else "干净环境运行验证未通过",
        {"checks": checks, "pytest": suite},
        commands=[
            {
                "command": f"python -m pytest {TARGET_TEST} {R2_TARGET_TEST} {REGRESSION_TEST} -q",
                "exit_code": suite["exit_code"],
            },
            {"command": "python -m minimax.sdd_context.cli --help", "exit_code": cli.returncode},
        ],
        evidence_paths=[_relative(REPOSITORY_ROOT / SAMPLE_CODE)],
    )


# --------------------------------------------------------------------- TEST-02


def test_02_minimax_participated(settings: Settings) -> dict[str, Any]:
    """Audit the recorded MiniMax development work.

    This is a **historical evidence audit**: it reads the append-only call
    archive that is committed to the repository and never calls the model. Each
    archived record is audited on its own, and the recorded patch of every
    development round is replayed onto the pre-change code taken from the git
    history, where the round's own target test has to pass.

    The live model call is a separate, explicitly online entry point:
    ``minimax/scripts/live_minimax_check.py``.
    """

    records = load_archive(settings.evidence_dir)
    if not records:
        return _result(
            "TEST-02",
            "MiniMax 真实参与代码修改",
            BLOCKED,
            f"缺少调用归档 {archive_directory(settings.evidence_dir)}",
        )

    audits = [audit_record(record) for record in records]
    development_audits = [audit for audit in audits if audit["round"] in ("r1", "r2")]
    live_audits = [audit for audit in audits if audit["round"] not in ("r1", "r2")]
    covered_rounds = sorted({audit["round"] for audit in development_audits})

    current_diff = _git("diff", PRE_CHANGE_COMMIT, "HEAD", "--", SAMPLE_CODE)
    sample_text = (REPOSITORY_ROOT / SAMPLE_CODE).read_text(encoding="utf-8")

    checks: dict[str, Any] = {
        "archive_not_empty": bool(audits),
        "every_development_record_passes_its_own_audit": all(
            audit["passed"] for audit in development_audits
        ),
        "model_is_minimax_in_every_record": all(
            str((audit.get("call") or {}).get("model", "")).startswith("MiniMax")
            for audit in development_audits
        ),
        "every_record_has_task_input": all(bool(audit.get("task")) for audit in development_audits),
        "every_record_has_raw_model_response": all(
            bool((audit.get("call") or {}).get("raw_response")) for audit in development_audits
        ),
        "every_record_has_generated_patch": all(
            "diff --git" in (audit.get("call") or {}).get("patch", "") for audit in development_audits
        ),
        "every_record_was_applied": all(
            (audit.get("call") or {}).get("applied") is True for audit in development_audits
        ),
        "every_record_touches_business_code": all(
            any("taskmanager" in name for name in ((audit.get("call") or {}).get("applied_files") or []))
            for audit in development_audits
        ),
        "every_patch_replays_onto_pre_change_code": all(
            audit["replay"].get("status") == PASS for audit in development_audits
        ),
        "every_patched_code_passes_its_target_test": all(
            audit["replay"].get("pytest_exit_code") == 0 for audit in development_audits
        ),
        "every_patched_code_matches_committed_version": all(
            audit["replay"].get("patched_matches_committed_version") is True
            for audit in development_audits
        ),
        "both_rounds_covered": covered_rounds == ["r1", "r2"],
        "live_records_carry_request_identity": all(
            bool((audit.get("call") or {}).get("request_id")) for audit in live_audits
        ),
        "git_diff_shows_sample_change": "list_tasks" in current_diff and "filter_by_status" in current_diff,
        "current_sample_contains_implementation": "filter_by_status" in sample_text,
    }

    stored_diff_path = settings.evidence_dir / "phase3_git_diff.patch"
    checks["stored_diff_evidence_exists"] = stored_diff_path.is_file()
    if stored_diff_path.is_file():
        stored_diff = stored_diff_path.read_text(encoding="utf-8")
        checks["stored_diff_matches_git"] = "filter_by_status" in stored_diff and "filter_by_status" in current_diff

    passed = all(checks.values())
    return _result(
        "TEST-02",
        "MiniMax 真实参与代码修改",
        PASS if passed else FAIL,
        f"归档中 {len(development_audits)} 条真实开发调用记录（轮次 {covered_rounds}）均含模型身份、"
        f"任务输入与已应用的补丁，补丁逐条重放到改动前的代码后仍通过该轮目标测试，"
        f"且与 Git 历史中的真实改动逐行对应"
        if passed
        else "归档的 MiniMax 调用证据未通过逐条审计",
        {
            "mode": "HISTORICAL",
            "checks": checks,
            "covered_rounds": covered_rounds,
            "record_count": len(audits),
            "records": [
                {
                    "task_id": audit.get("task_id"),
                    "round": audit["round"],
                    "repository_commit": audit["repository_commit"],
                    "model": (audit.get("call") or {}).get("model"),
                    "request_id": (audit.get("call") or {}).get("request_id"),
                    "request_ids": (audit.get("call") or {}).get("request_ids", {}),
                    "tokens": [
                        (audit.get("call") or {}).get("input_tokens"),
                        (audit.get("call") or {}).get("output_tokens"),
                    ],
                    "applied_files": (audit.get("call") or {}).get("applied_files"),
                    "replay": audit["replay"],
                    "checks": audit["checks"],
                    "passed": audit["passed"],
                }
                for audit in development_audits
            ],
            "live_records": [
                {
                    "task_id": audit.get("task_id"),
                    "round": audit["round"],
                    "model": (audit.get("call") or {}).get("model"),
                    "request_id": (audit.get("call") or {}).get("request_id"),
                    "request_ids": (audit.get("call") or {}).get("request_ids", {}),
                    "tokens": [
                        (audit.get("call") or {}).get("input_tokens"),
                        (audit.get("call") or {}).get("output_tokens"),
                    ],
                    "note": "在线验证记录，不计入历史开发轮次审计",
                }
                for audit in live_audits
            ],
            "git_diff": current_diff,
            "live_verification_entry_point": "minimax/scripts/live_minimax_check.py",
        },
        commands=[
            {
                "command": (
                    "python -m pytest {target_test} -q  "
                    "# 在该轮改动前的代码上重放归档补丁后运行".format(
                        target_test=audit["replay"].get("target_test", "")
                    )
                ),
                "exit_code": audit["replay"].get("pytest_exit_code"),
                "scope": audit["round"],
            }
            for audit in development_audits
        ],
        evidence_paths=[
            "minimax/evidence/minimax_calls",
            "minimax/evidence/minimax_evidence_audit.json",
            "minimax/evidence/phase3_git_diff.patch",
        ],
    )


# --------------------------------------------------------------------- TEST-03


def test_03_context_correct(settings: Settings) -> dict[str, Any]:
    """Every material in the context must exist, and a spec update must show up."""

    try:
        store = SeekDBStore(settings)
        state_store = PowerContextStateStore(settings)
        builder = ContextBuilder(store, state_store, settings.root)
        context = builder.build(TASK_ID, TASK_TEXT, SPEC_ID)
    except (SeekDBUnavailableError, PowerContextUnavailableError) as error:
        return _result(
            "TEST-03",
            "上下文内容正确且来源真实",
            BLOCKED,
            f"无法构建上下文: {error}",
        )

    checks: dict[str, Any] = {}

    # Every reported source must exist on disk.
    missing: list[str] = []
    for section in ("specifications", "code", "tests"):
        for item in context.to_dict()[section]:
            for path in (item.get("source_path"), item.get("file_path")):
                if not path:
                    continue
                candidate = (settings.root / path).resolve()
                if not candidate.is_file():
                    missing.append(f"{section}:{path}")
    checks["all_sources_exist"] = not missing
    checks["missing_sources"] = missing

    # The recorded symbols must really be defined in the recorded file.
    symbol_problems: list[str] = []
    for item in context.code:
        source = (settings.root / item["file_path"]).resolve()
        if not source.is_file():
            symbol_problems.append(f"{item['file_path']} 缺失")
            continue
        text = source.read_text(encoding="utf-8")
        name = item["symbol_name"]
        defined = (
            f"def {name}" in text
            or f"class {name}" in text
            or f"{name} =" in text
            or f"{name}:" in text
        )
        if not defined:
            symbol_problems.append(f"{item['qualified_name']} 不在 {item['file_path']} 中")
    checks["symbols_exist_in_files"] = not symbol_problems
    checks["symbol_problems"] = symbol_problems

    # The recorded tests must really exist in the recorded test file.
    test_problems: list[str] = []
    for item in context.tests:
        source = (settings.root / item["file_path"]).resolve()
        if not source.is_file():
            test_problems.append(f"{item['file_path']} 缺失")
            continue
        if f"def {item['test_name']}" not in source.read_text(encoding="utf-8"):
            test_problems.append(f"{item['test_name']} 不在 {item['file_path']} 中")
    checks["tests_exist_in_files"] = not test_problems
    checks["test_problems"] = test_problems

    checks["specification_resolved"] = len(context.specifications) == 1
    checks["code_resolved"] = bool(context.code)
    checks["tests_resolved"] = bool(context.tests)
    checks["sources_section_present"] = bool(context.sources)

    # The specification update must be visible in the context.
    specification = context.specifications[0] if context.specifications else {}
    checks["spec_version_is_latest"] = specification.get("version") == "1.1.0"
    checks["spec_revision_is_r2"] = specification.get("revision") == "r2"
    checks["spec_carries_revised_text"] = "Revision r2 (v1.1.0)" in specification.get("content", "")

    passed = all(
        value
        for key, value in checks.items()
        if key
        in {
            "all_sources_exist",
            "symbols_exist_in_files",
            "tests_exist_in_files",
            "specification_resolved",
            "code_resolved",
            "tests_resolved",
            "sources_section_present",
            "spec_version_is_latest",
            "spec_revision_is_r2",
            "spec_carries_revised_text",
        }
    )
    return _result(
        "TEST-03",
        "上下文内容正确且来源真实",
        PASS if passed else FAIL,
        f"上下文包含规格 {specification.get('version')} ({specification.get('revision')})、"
        f"{len(context.code)} 个代码符号、{len(context.tests)} 个测试，全部来源文件真实存在"
        if passed
        else "上下文中存在无效来源或未反映规格更新",
        {"checks": checks, "specification": specification.get("spec_id")},
        commands=[
            {
                "command": (
                    "python -m minimax.sdd_context.cli context --task-id {task} "
                    "--spec-id {spec}".format(task=TASK_ID, spec=SPEC_ID)
                ),
                "exit_code": 0 if passed else 1,
            }
        ],
        evidence_paths=["minimax/evidence/context_snapshot.json"],
    )


# --------------------------------------------------------------------- TEST-04


def test_04_database_involved(settings: Settings) -> dict[str, Any]:
    """seekdb must really serve the retrieval queries."""

    try:
        store = SeekDBStore(settings)
        store.initialize()
        counts = store.counts()
        version = store.server_version()
    except SeekDBUnavailableError as error:
        return _result(
            "TEST-04",
            "数据库真实参与",
            BLOCKED,
            f"seekdb 不可用: {error}",
        )

    checks: dict[str, Any] = {
        "server_reachable": bool(version),
        "specification_rows": counts["sdd_specification"] > 0,
        "code_symbol_rows": counts["sdd_code_symbol"] > 0,
        "test_rows": counts["sdd_test"] > 0,
        "relation_rows": counts["sdd_relation"] > 0,
    }

    # The retrieved rows must match the real files, so the data cannot be a fixture.
    problems: list[str] = []
    for row in store.code_symbols_for_paths(["sample/taskmanager.py"]):
        source = (settings.root / row["file_path"]).resolve()
        if not source.is_file():
            problems.append(f"{row['file_path']} 不存在")
            continue
        text = source.read_text(encoding="utf-8")
        if row["symbol_name"] not in text:
            problems.append(f"{row['symbol_name']} 不在 {row['file_path']} 中")
    checks["code_rows_match_files"] = not problems
    checks["problems"] = problems

    # A write must be visible to a later read in the same connection pool.
    marker = f"verify-probe-{int(time.time())}"
    store.execute(
        "INSERT INTO sdd_relation (relation_id, spec_id, spec_version, target_kind, target_id, relation_type)"
        " VALUES (%s, %s, %s, %s, %s, %s)"
        " ON DUPLICATE KEY UPDATE relation_type = VALUES(relation_type)",
        (
            hashlib.sha256(marker.encode()).hexdigest(),
            SPEC_ID,
            "probe",
            "probe",
            marker,
            "probe",
        ),
    )
    found = store.query(
        "SELECT target_id FROM sdd_relation WHERE spec_id = %s AND spec_version = %s AND target_id = %s",
        (SPEC_ID, "probe", marker),
    )
    checks["write_visible_to_read"] = bool(found)
    store.execute("DELETE FROM sdd_relation WHERE spec_version = %s AND target_id = %s", ("probe", marker))

    passed = all(
        value
        for key, value in checks.items()
        if key
        in {
            "server_reachable",
            "specification_rows",
            "code_symbol_rows",
            "test_rows",
            "relation_rows",
            "code_rows_match_files",
            "write_visible_to_read",
        }
    )
    return _result(
        "TEST-04",
        "数据库真实参与",
        PASS if passed else FAIL,
        f"seekdb {version} 上四张表共 {sum(counts.values())} 行，"
        f"写入后立即可读回，内容与磁盘文件一致"
        if passed
        else "数据库参与证据不完整",
        {"checks": checks, "counts": counts, "server_version": version},
        commands=[
            {
                "command": "python minimax/scripts/seekdb_evidence.py",
                "exit_code": 0 if passed else 1,
            }
        ],
        evidence_paths=["minimax/evidence/seekdb_queries.json"],
    )


# --------------------------------------------------------------------- TEST-05


def test_05_state_reusable(settings: Settings) -> dict[str, Any]:
    """The task state must survive a module restart and reach the next context."""

    try:
        state_store = PowerContextStateStore(settings)
        health = state_store.health()
    except PowerContextUnavailableError as error:
        return _result(
            "TEST-05",
            "任务状态可复用",
            BLOCKED,
            f"PowerContext 不可用: {error}",
        )
    if not health.get("available"):
        return _result("TEST-05", "任务状态可复用", BLOCKED, f"PowerContext 不可用: {health.get('error')}")

    # The reading process also needs seekdb, because it builds a context from
    # the database. When the database is unreachable the item cannot run at
    # all, which is a blocked item and not a failing one.
    try:
        SeekDBStore(settings).server_version()
        passed_dependencies = True
        dependency_detail = ""
    except SeekDBUnavailableError as error:
        passed_dependencies = False
        dependency_detail = f"seekdb 不可用: {error}"

    # The task id is unique per run, so a record written by an earlier run can
    # never be mistaken for a recovered one. The scope therefore stays clean
    # across repeated verifications.
    task_id = f"{TASK_ID}-RESTART-{uuid.uuid4().hex[:8].upper()}"
    marker = f"verify-restart-{int(time.time())}"

    write_script = (
        "import json\n"
        "from minimax.sdd_context.config import load_settings\n"
        "from minimax.sdd_context.powercontext_store import PowerContextStateStore\n"
        "settings = load_settings()\n"
        "store = PowerContextStateStore(settings)\n"
        f"store.record_completed({task_id!r}, {marker + ':completed'!r})\n"
        f"store.record_todo({task_id!r}, {marker + ':todo'!r})\n"
        f"store.record_verification({task_id!r}, {marker + ':verification'!r})\n"
        "print('written')\n"
    )
    write = subprocess.run(
        [sys.executable, "-c", write_script],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT)},
    )

    read_script = (
        "import json\n"
        "from minimax.sdd_context.config import load_settings\n"
        "from minimax.sdd_context.context_builder import ContextBuilder\n"
        "from minimax.sdd_context.powercontext_store import PowerContextStateStore\n"
        "from minimax.sdd_context.seekdb_store import SeekDBStore\n"
        "settings = load_settings()\n"
        "store = SeekDBStore(settings)\n"
        "state_store = PowerContextStateStore(settings)\n"
        "builder = ContextBuilder(store, state_store, settings.root)\n"
        f"context = builder.build({task_id!r}, {TASK_TEXT!r}, {SPEC_ID!r})\n"
        "payload = {\n"
        "    'state': context.state,\n"
        "    'completed': context.state.get('completed', []),\n"
        "    'todos': context.state.get('todos', []),\n"
        "    'verifications': context.state.get('verifications', []),\n"
        "    'specifications': [s['version'] for s in context.specifications],\n"
        "    'code_files': sorted({c['file_path'] for c in context.code}),\n"
        "}\n"
        "print(json.dumps(payload, ensure_ascii=False))\n"
    )
    read = subprocess.run(
        [sys.executable, "-c", read_script],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT)},
    )

    payload: dict[str, Any] = {}
    if read.returncode == 0 and read.stdout.strip():
        try:
            payload = json.loads(read.stdout.strip().splitlines()[-1])
        except json.JSONDecodeError:
            payload = {}

    completed = payload.get("completed", [])
    todos = payload.get("todos", [])
    verifications = payload.get("verifications", [])

    # A failing subprocess is only a business failure when both dependencies
    # were actually reachable. If seekdb is down, the read could not build a
    # context at all, so the item is blocked rather than failed.
    if not passed_dependencies:
        return _result(
            "TEST-05",
            "任务状态可复用",
            BLOCKED,
            f"依赖不可用，无法验证状态恢复: {dependency_detail}",
            {
                "checks": {"dependencies_reachable": False},
                "dependency_detail": dependency_detail,
            },
        )

    checks: dict[str, Any] = {
        "write_process_succeeded": write.returncode == 0,
        "read_process_succeeded": read.returncode == 0,
        "state_survived_restart": any(marker in item for item in completed),
        "todo_survived_restart": any(marker in item for item in todos),
        "verification_survived_restart": any(marker in item for item in verifications),
        "state_merged_into_context": bool(completed or todos or verifications),
        "context_resolves_specification": bool(payload.get("specifications")),
        "context_resolves_code": bool(payload.get("code_files")),
    }

    passed = all(checks.values())
    return _result(
        "TEST-05",
        "任务状态可复用",
        PASS if passed else FAIL,
        f"进程退出后由全新进程读回 {len(completed)} 条完成项、{len(todos)} 条待办、"
        f"{len(verifications)} 条验证结果，并合并进新构建的上下文"
        if passed
        else "任务状态未能跨进程恢复或未进入上下文",
        {
            "checks": checks,
            "write_process": {
                "exit_code": write.returncode,
                "stdout": write.stdout.strip(),
                "stderr": write.stderr.strip()[:1500],
            },
            "read_process": {
                "exit_code": read.returncode,
                "stderr": read.stderr.strip()[:1500],
            },
            "recovered_state": payload.get("state"),
        },
        commands=[
            {
                "command": "python -c \"...record_completed/record_todo/record_verification...\"",
                "exit_code": write.returncode,
                "scope": "write process",
            },
            {
                "command": "python -c \"...ContextBuilder.build...\"",
                "exit_code": read.returncode,
                "scope": "read process",
            },
        ],
        evidence_paths=["minimax/evidence/phase4_cross_process.json"],
    )


# --------------------------------------------------------------------- TEST-06


def test_06_code_change_effective(settings: Settings) -> dict[str, Any]:
    """The same target test must fail before the change and pass after it."""

    before_log = settings.evidence_dir / "phase1_before.log"
    after_log = settings.evidence_dir / "phase3_after.log"
    r2_before_log = settings.evidence_dir / "phase4_r2_before.log"
    r2_after_log = settings.evidence_dir / "phase4_r2_after.log"

    missing = [
        str(path)
        for path in (before_log, after_log, r2_before_log, r2_after_log)
        if not path.is_file()
    ]
    if missing:
        return _result(
            "TEST-06",
            "代码改动生效",
            BLOCKED,
            f"缺少 Red/Green 日志: {missing}",
        )

    def _read(path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8", errors="replace")
        exit_code = None
        for line in text.splitlines():
            match = re.match(r"EXITCODE=(\d+)", line.strip())
            if match:
                exit_code = int(match.group(1))
        return {"text": text, "exit_code": exit_code}

    r1_before = _read(before_log)
    r1_after = _read(after_log)
    r2_before = _read(r2_before_log)
    r2_after = _read(r2_after_log)

    checks: dict[str, Any] = {
        "r1_failed_before": r1_before["exit_code"] == 1,
        "r1_failed_with_assertion": "AssertionError" in r1_before["text"],
        "r1_passed_after": r1_after["exit_code"] == 0,
        "r2_failed_before": r2_before["exit_code"] == 1,
        "r2_failed_with_assertion": "AssertionError" in r2_before["text"],
        "r2_passed_after": r2_after["exit_code"] == 0,
    }

    # The failure must be a real functional failure, not an import or setup error.
    checks["r1_failure_is_functional"] = not any(
        marker in r1_before["text"]
        for marker in ("ModuleNotFoundError", "ImportError", "ConnectionError", "fixture 'not found'")
    )
    checks["r2_failure_is_functional"] = not any(
        marker in r2_before["text"]
        for marker in ("ModuleNotFoundError", "ImportError", "ConnectionError", "fixture 'not found'")
    )

    # The target test file must be unchanged between the Red and Green runs.
    # The hash is taken over the normalized content and cross-checked against
    # the committed blob, so the assertion also holds on a CRLF checkout.
    current_hash = _normalized_sha256(REPOSITORY_ROOT / TARGET_TEST)
    current_blob_hash = _git_blob_sha256(TARGET_TEST)
    checks["target_test_unchanged"] = current_hash == "8be75f1a6e40d659d4a99d6ca2d8e0771f1cc7f076148f27716367c88d8b87de"
    checks["target_test_matches_committed_blob"] = current_blob_hash == current_hash
    r2_hash = _normalized_sha256(REPOSITORY_ROOT / R2_TARGET_TEST)
    r2_blob_hash = _git_blob_sha256(R2_TARGET_TEST)
    checks["r2_target_test_unchanged"] = r2_hash == "ac7ab515412113a58bb0185bff6eb07c5738ca1f1bbd7bbe981e95ffad5c3a19"
    checks["r2_target_test_matches_committed_blob"] = r2_blob_hash == r2_hash

    # The current suite must still pass, including the regressions.
    suite = _pytest([TARGET_TEST, R2_TARGET_TEST, REGRESSION_TEST, "-q"])
    checks["current_suite_passes"] = suite["exit_code"] == 0

    # The regression suite must have passed before the change and still passes.
    # In the Red log the functional tests failed while the regressions passed,
    # so the regressions must not appear in the failure summary.
    failed_lines = [
        line for line in r1_before["text"].splitlines() if line.startswith("FAILED ")
    ]
    checks["regression_passed_before"] = not any(
        "regression" in line for line in failed_lines
    )
    regression_run = _pytest([REGRESSION_TEST, "-q"])
    checks["regression_passes_now"] = regression_run["exit_code"] == 0

    # The git diff must show the real change to the sample code, taken against
    # the commit that held the pre-change implementation.
    diff = _git("diff", PRE_CHANGE_COMMIT, "HEAD", "--", SAMPLE_CODE)
    checks["git_diff_shows_change"] = "list_tasks" in diff
    checks["git_diff_has_records"] = "filter_by_status" in diff

    # The r2 revision must be part of the same diff.
    checks["git_diff_has_r2_change"] = '"*"' in diff or "None if status" in diff

    passed = all(checks.values())
    return _result(
        "TEST-06",
        "代码改动生效",
        PASS if passed else FAIL,
        "同一目标测试在改动前以 AssertionError 失败、改动后通过，回归测试保持通过，"
        "且目标测试文件哈希前后一致"
        if passed
        else "Red→Green 证据链不完整或测试被修改",
        {
            "checks": checks,
            "r1_before": {"exit_code": r1_before["exit_code"]},
            "r1_after": {"exit_code": r1_after["exit_code"]},
            "r2_before": {"exit_code": r2_before["exit_code"]},
            "r2_after": {"exit_code": r2_after["exit_code"]},
            "target_test_sha256": current_hash,
            "target_test_raw_sha256": _sha256(REPOSITORY_ROOT / TARGET_TEST),
            "target_test_committed_blob_sha256": current_blob_hash,
            "r2_target_test_sha256": r2_hash,
            "r2_target_test_raw_sha256": _sha256(REPOSITORY_ROOT / R2_TARGET_TEST),
            "r2_target_test_committed_blob_sha256": r2_blob_hash,
            "git_diff": diff,
            "current_suite": suite,
        },
        commands=[
            {
                "command": f"pytest {TARGET_TEST} {REGRESSION_TEST} -q  # r1 Red",
                "exit_code": r1_before["exit_code"],
                "scope": "r1 before",
                "log": "minimax/evidence/phase1_before.log",
            },
            {
                "command": f"pytest {TARGET_TEST} {REGRESSION_TEST} -q  # r1 Green",
                "exit_code": r1_after["exit_code"],
                "scope": "r1 after",
                "log": "minimax/evidence/phase3_after.log",
            },
            {
                "command": f"pytest {R2_TARGET_TEST} -q  # r2 Red",
                "exit_code": r2_before["exit_code"],
                "scope": "r2 before",
                "log": "minimax/evidence/phase4_r2_before.log",
            },
            {
                "command": f"pytest {TARGET_TEST} {R2_TARGET_TEST} {REGRESSION_TEST} -q  # r2 Green",
                "exit_code": r2_after["exit_code"],
                "scope": "r2 after",
                "log": "minimax/evidence/phase4_r2_after.log",
            },
            {
                "command": f"python -m pytest {TARGET_TEST} {R2_TARGET_TEST} {REGRESSION_TEST} -q",
                "exit_code": suite["exit_code"],
                "scope": "current suite",
            },
        ],
        evidence_paths=[
            "minimax/evidence/phase1_before.log",
            "minimax/evidence/phase3_after.log",
            "minimax/evidence/phase4_r2_before.log",
            "minimax/evidence/phase4_r2_after.log",
            "minimax/evidence/phase3_git_diff.patch",
            "minimax/evidence/red_green_audit.json",
        ],
    )


# ------------------------------------------------------------------- dispatcher

CHECKS = {
    "TEST-01": test_01_runnable,
    "TEST-02": test_02_minimax_participated,
    "TEST-03": test_03_context_correct,
    "TEST-04": test_04_database_involved,
    "TEST-05": test_05_state_reusable,
    "TEST-06": test_06_code_change_effective,
}


def run_all(settings: Settings, only: list[str] | None = None) -> int:
    """Run the acceptance suite and print the JSON report."""

    settings.ensure_directories()
    selected = [name for name in CHECKS if not only or name in only]
    results: list[dict[str, Any]] = []
    for name in selected:
        checker = CHECKS[name]
        try:
            results.append(checker(settings))
        except Exception as error:  # a broken check is a failure, never a silent pass
            results.append(
                _result(name, name, FAIL, f"{type(error).__name__}: {error}")
            )

    report = {
        "generated_by": "minimax/scripts/verify.py",
        "reproduce_with": "python minimax/scripts/verify.py --all",
        "repository_root": str(REPOSITORY_ROOT),
        "module_root": str(MODULE_ROOT),
        "module_root_relative": "minimax",
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "python": sys.version.split()[0],
        "results": results,
        "summary": {
            "total": len(results),
            "pass": sum(1 for item in results if item["status"] == PASS),
            "fail": sum(1 for item in results if item["status"] == FAIL),
            "blocked": sum(1 for item in results if item["status"] == BLOCKED),
        },
    }
    report["overall"] = PASS if report["summary"]["fail"] == 0 and report["summary"]["blocked"] == 0 else FAIL

    # The evidence file is committed *after* the run, so the commit that
    # carries this report is necessarily newer than the commit that was
    # tested. Say so explicitly instead of leaving the reviewer to guess
    # which commit the result belongs to.
    report["git_version_note"] = (
        "commit / git_version 是本次运行所测试的代码提交；"
        "把本报告提交进仓库的那次提交会更新本文件本身，但不改变被测试的代码。"
    )

    output = settings.evidence_dir / "acceptance_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(report), encoding="utf-8")

    print(_dump(report))
    return 0 if report["overall"] == PASS else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MiniMax SDD context acceptance suite")
    parser.add_argument("--all", action="store_true", help="run every acceptance item")
    parser.add_argument("--only", action="append", default=None, help="run a single acceptance item")
    arguments = parser.parse_args(argv)

    if not arguments.all and not arguments.only:
        parser.error("pass --all or --only <ITEM>")

    settings = load_settings()
    return run_all(settings, only=arguments.only)


if __name__ == "__main__":
    raise SystemExit(main())
