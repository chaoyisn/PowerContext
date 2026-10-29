"""Phase 4 evidence: specification update and cross-process state recovery.

Two checks are performed here:

1. **Specification update** — import the specification, query the development
   context, revise the same specification file, re-import it, and query again.
   The second context must contain the revised version and the revised text.

2. **Cross-process recovery** — write task state from one process, close it,
   start a brand new process, read the state back and prove the recovered
   records are merged into the newly built development context.

The script writes its evidence to ``minimax/evidence/phase4_*.json``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from minimax.sdd_context.config import Settings, load_settings
from minimax.sdd_context.context_builder import ContextBuilder, link_materials
from minimax.sdd_context.importer import MaterialImporter
from minimax.sdd_context.powercontext_store import PowerContextStateStore
from minimax.sdd_context.seekdb_store import SeekDBStore

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPOSITORY_ROOT / "minimax" / "specs" / "SPEC-REQ-001.md"
SPEC_BASELINE_PATH = REPOSITORY_ROOT / "minimax" / "specs" / "history" / "SPEC-REQ-001.v1.0.0.md"
SPEC_ID = "SPEC-REQ-001"
TASK_ID = "TASK-SPEC-REQ-001"
TASK_TEXT = "为工单查询函数增加按 status 筛选工单的功能 list_tasks(status='active')"


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _settings() -> Settings:
    settings = load_settings()
    settings.ensure_directories()
    return settings


def _restore_baseline_spec() -> None:
    """Put the committed r1 revision back in place of the working copy.

    The r1 revision is kept under ``specs/history`` so the update flow can be
    replayed from a known state without depending on a clean git worktree.
    """

    SPEC_PATH.write_text(SPEC_BASELINE_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def _current_revision_spec() -> str:
    """Read the revised specification from the git working tree."""

    completed = subprocess.run(
        ["git", "show", "HEAD:minimax/specs/SPEC-REQ-001.md"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"cannot read the committed specification: {completed.stderr}")
    return completed.stdout


def _import_all_materials(settings: Settings, importer: MaterialImporter, store: SeekDBStore) -> None:
    """Import the code and test files and bind them to the specification."""

    module_root = settings.root.resolve()
    code_paths = [module_root / "sample" / "taskmanager.py"]
    test_paths = [
        module_root / "tests" / "test_list_tasks_status_filter.py",
        module_root / "tests" / "test_list_tasks_status_wildcard.py",
        module_root / "tests" / "test_taskmanager_regression.py",
    ]
    for path in code_paths:
        importer.import_code(path)
    for path in test_paths:
        importer.import_test(path, [SPEC_ID])
    link_materials(
        importer,
        store,
        spec_id=SPEC_ID,
        spec_version=importer.store.latest_specification(SPEC_ID)["version"],
        code_paths=[path.relative_to(module_root).as_posix() for path in code_paths],
        test_paths=[path.relative_to(module_root).as_posix() for path in test_paths],
    )


def check_specification_update(settings: Settings) -> dict[str, Any]:
    """Import, revise, re-import and prove the context follows the revision."""

    _restore_baseline_spec()
    store = SeekDBStore(settings)
    store.initialize()
    importer = MaterialImporter(store, settings.root)

    first = importer.import_specification(SPEC_PATH, SPEC_ID)
    _import_all_materials(settings, importer, store)
    state_store = PowerContextStateStore(settings)
    builder = ContextBuilder(store, state_store, settings.root)
    context_before = builder.build(TASK_ID, TASK_TEXT, SPEC_ID)

    revised_content = _current_revision_spec()
    SPEC_PATH.write_text(revised_content, encoding="utf-8")
    second = importer.import_specification(SPEC_PATH, SPEC_ID)
    context_after = builder.build(TASK_ID, TASK_TEXT, SPEC_ID)

    before_spec = context_before.specifications[0] if context_before.specifications else {}
    after_spec = context_after.specifications[0] if context_after.specifications else {}
    revised_marker_present = "Revision r2 (v1.1.0)" in after_spec.get("content", "")

    report = {
        "before": {
            "spec_id": before_spec.get("spec_id"),
            "version": before_spec.get("version"),
            "revision": before_spec.get("revision"),
            "content_hash": before_spec.get("content_hash"),
            "code_files": sorted({item["file_path"] for item in context_before.code}),
            "test_files": sorted({item["file_path"] for item in context_before.tests}),
            "spec_import": first,
        },
        "after": {
            "spec_id": after_spec.get("spec_id"),
            "version": after_spec.get("version"),
            "revision": after_spec.get("revision"),
            "content_hash": after_spec.get("content_hash"),
            "code_files": sorted({item["file_path"] for item in context_after.code}),
            "test_files": sorted({item["file_path"] for item in context_after.tests}),
            "spec_import": second,
        },
        "checks": {
            "version_advanced": before_spec.get("version") != after_spec.get("version"),
            "expected_new_version": after_spec.get("version") == "1.1.0",
            "content_hash_changed": before_spec.get("content_hash") != after_spec.get("content_hash"),
            "revised_text_present": revised_marker_present,
            "code_still_resolved": bool(context_after.code),
            "tests_still_resolved": bool(context_after.tests),
        },
    }
    report["passed"] = all(report["checks"].values())
    return report


def _write_state_subprocess(settings: Settings) -> dict[str, Any]:
    """Write task state from a brand new process."""

    script = (
        "from minimax.sdd_context.config import load_settings\n"
        "from minimax.sdd_context.powercontext_store import PowerContextStateStore\n"
        "settings = load_settings()\n"
        "store = PowerContextStateStore(settings)\n"
        "store.record_completed('TASK-SPEC-REQ-001', 'phase4: 状态已在独立进程中写入')\n"
        "store.record_todo('TASK-SPEC-REQ-001', 'phase4: 验证跨进程读取')\n"
        "store.record_verification('TASK-SPEC-REQ-001', 'phase4: 写入进程退出码 0')\n"
        "print('written')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(REPOSITORY_ROOT)},
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip()[:2000],
    }


def _read_state_subprocess(settings: Settings) -> dict[str, Any]:
    """Read task state from a brand new process and rebuild the context there."""

    script = (
        "import json\n"
        "from minimax.sdd_context.config import load_settings\n"
        "from minimax.sdd_context.context_builder import ContextBuilder\n"
        "from minimax.sdd_context.powercontext_store import PowerContextStateStore\n"
        "from minimax.sdd_context.seekdb_store import SeekDBStore\n"
        "settings = load_settings()\n"
        "store = SeekDBStore(settings)\n"
        "state_store = PowerContextStateStore(settings)\n"
        "builder = ContextBuilder(store, state_store, settings.root)\n"
        "context = builder.build('TASK-SPEC-REQ-001', 'status filter task', 'SPEC-REQ-001')\n"
        "payload = {\n"
        "    'state': context.state,\n"
        "    'context_todos': context.state.get('todos', []),\n"
        "    'context_completed': context.state.get('completed', []),\n"
        "    'context_verifications': context.state.get('verifications', []),\n"
        "    'specifications': [s['version'] for s in context.specifications],\n"
        "    'code_files': sorted({c['file_path'] for c in context.code}),\n"
        "}\n"
        "print(json.dumps(payload, ensure_ascii=False))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(REPOSITORY_ROOT)},
    )
    payload: dict[str, Any] = {}
    if completed.returncode == 0 and completed.stdout.strip():
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    return {
        "returncode": completed.returncode,
        "stderr": completed.stderr.strip()[:2000],
        "payload": payload,
    }


def check_cross_process_recovery(settings: Settings) -> dict[str, Any]:
    """Prove the state survives a process restart and reaches the context."""

    write = _write_state_subprocess(settings)
    read = _read_state_subprocess(settings)
    payload = read.get("payload", {})

    recovered = payload.get("state", {}).get("completed", [])
    todos = payload.get("context_todos", [])
    verifications = payload.get("context_verifications", [])
    checks = {
        "write_process_succeeded": write["returncode"] == 0,
        "read_process_succeeded": read["returncode"] == 0,
        "state_recovered": any("phase4" in item for item in recovered),
        "todos_merged_into_context": any("phase4" in item for item in todos),
        "verifications_merged_into_context": any("phase4" in item for item in verifications),
        "context_still_resolves_spec": bool(payload.get("specifications")),
        "context_still_resolves_code": bool(payload.get("code_files")),
    }
    return {
        "write_process": write,
        "read_process": {key: value for key, value in read.items() if key != "payload"},
        "recovered_state": payload.get("state"),
        "context_merged": {
            "completed": payload.get("context_completed"),
            "todos": payload.get("context_todos"),
            "verifications": payload.get("context_verifications"),
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    settings = _settings()
    evidence_dir = settings.evidence_dir
    evidence_dir.mkdir(parents=True, exist_ok=True)

    specification = check_specification_update(settings)
    (evidence_dir / "phase4_spec_update.json").write_text(
        _dump(specification), encoding="utf-8"
    )

    recovery = check_cross_process_recovery(settings)
    (evidence_dir / "phase4_cross_process.json").write_text(_dump(recovery), encoding="utf-8")

    summary = {
        "specification_update": {
            "passed": specification["passed"],
            "checks": specification["checks"],
            "evidence": str(evidence_dir / "phase4_spec_update.json"),
        },
        "cross_process_recovery": {
            "passed": recovery["passed"],
            "checks": recovery["checks"],
            "evidence": str(evidence_dir / "phase4_cross_process.json"),
        },
    }
    print(_dump(summary))
    return 0 if specification["passed"] and recovery["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
