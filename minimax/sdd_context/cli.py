"""Command line entry point for the MiniMax SDD context module.

Commands
--------
``init``       create the seekdb schema and import the sample materials.
``import``     import or update a specification, code files and test files.
``context``    build the development context for a task.
``state``      show the persisted task state.
``task``       create or update the task record (contract, todos, results).
``apply``      let MiniMax implement the task from the built context.
``verify``     run the automated acceptance suite.
``reset``      drop the imported materials and the local state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Settings, load_settings
from .context_builder import ContextBuilder, link_materials
from .importer import MaterialImporter
from .powercontext_store import PowerContextStateStore
from .seekdb_store import SeekDBStore

DEFAULT_SPEC_ID = "SPEC-REQ-001"
DEFAULT_TASK_ID = "TASK-SPEC-REQ-001"
DEFAULT_TASK_TEXT = "为工单查询函数增加按 status 筛选工单的功能 list_tasks(status='active')"

SPEC_FILES = ("specs/SPEC-REQ-001.md",)
CODE_FILES = ("sample/taskmanager.py",)
FUNCTIONAL_TEST_FILES = ("tests/test_list_tasks_status_filter.py",)
REGRESSION_TEST_FILES = ("tests/test_taskmanager_regression.py",)


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _repository_root(settings: Settings) -> Path:
    """Return the git repository that holds the sample code.

    The sample lives under ``minimax/`` inside the competition repository, so
    the repository root is the parent of the module root.
    """

    root = settings.root.resolve()
    if (root.parent / ".git").exists():
        return root.parent
    return root


def _build_stores(settings: Settings) -> tuple[SeekDBStore, PowerContextStateStore]:
    store = SeekDBStore(settings)
    state_store = PowerContextStateStore(settings)
    return store, state_store


def command_init(settings: Settings, args: argparse.Namespace) -> int:
    settings.ensure_directories()
    store, state_store = _build_stores(settings)
    store.initialize()
    importer = MaterialImporter(store, settings.root)

    report: dict[str, Any] = {
        "database": settings.seekdb_database,
        "server_version": store.server_version(),
        "powercontext": state_store.health(),
    }
    spec_paths = [settings.root / name for name in SPEC_FILES]
    code_paths = [settings.root / name for name in CODE_FILES]
    functional_paths = [settings.root / name for name in FUNCTIONAL_TEST_FILES]
    regression_paths = [settings.root / name for name in REGRESSION_TEST_FILES]

    specifications = []
    for path in spec_paths:
        specifications.append(importer.import_specification(path, DEFAULT_SPEC_ID))
    report["specifications"] = specifications

    symbols: list[dict[str, Any]] = []
    for path in code_paths:
        symbols.extend(importer.import_code(path))
    report["code_symbols"] = symbols

    tests: list[dict[str, Any]] = []
    for path in functional_paths:
        tests.extend(importer.import_test(path, [DEFAULT_SPEC_ID]))
    for path in regression_paths:
        tests.extend(importer.import_test(path, [DEFAULT_SPEC_ID]))
    report["tests"] = tests

    for specification in specifications:
        links = link_materials(
            importer,
            store,
            spec_id=specification["spec_id"],
            spec_version=specification["version"],
            code_paths=[str(path.relative_to(settings.root.resolve()).as_posix()) for path in code_paths],
            test_paths=[
                str(path.relative_to(settings.root.resolve()).as_posix())
                for path in (*functional_paths, *regression_paths)
            ],
        )
        report.setdefault("links", []).append(links)

    report["counts"] = store.counts()
    print(_dump(report))
    return 0


def command_import(settings: Settings, args: argparse.Namespace) -> int:
    store, _ = _build_stores(settings)
    store.initialize()
    importer = MaterialImporter(store, settings.root)
    report: dict[str, Any] = {}

    if args.spec:
        report["specification"] = importer.import_specification(Path(args.spec), args.spec_id or DEFAULT_SPEC_ID)
    for path in args.code or []:
        report.setdefault("code", []).extend(importer.import_code(Path(path)))
    for path in args.test or []:
        report.setdefault("tests", []).extend(importer.import_test(Path(path), [args.spec_id or DEFAULT_SPEC_ID]))

    if report.get("specification"):
        specification = report["specification"]
        links = link_materials(
            importer,
            store,
            spec_id=specification["spec_id"],
            spec_version=specification["version"],
            code_paths=[str(Path(path).resolve().relative_to(settings.root.resolve()).as_posix()) for path in (args.code or [])],
            test_paths=[str(Path(path).resolve().relative_to(settings.root.resolve()).as_posix()) for path in (args.test or [])],
        )
        report["links"] = links
    report["counts"] = store.counts()
    print(_dump(report))
    return 0


def command_context(settings: Settings, args: argparse.Namespace) -> int:
    store, state_store = _build_stores(settings)
    builder = ContextBuilder(store, state_store, settings.root)
    context = builder.build(args.task_id, args.task, args.spec_id)
    payload = context.to_dict()
    payload["retrieval"]["repository_root"] = str(_repository_root(settings))
    if args.output:
        Path(args.output).write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0


def command_task(settings: Settings, args: argparse.Namespace) -> int:
    _, state_store = _build_stores(settings)
    scope_id = state_store.scope_id()
    report: dict[str, Any] = {"task_id": args.task_id, "scope_id": scope_id}

    if args.create:
        report["contract"] = state_store.create_task(
            args.task_id,
            args.description,
            in_scope=[str(path) for path in (args.in_scope or CODE_FILES)],
            criteria=[args.description],
        )
    if args.completed:
        report["completed"] = [state_store.record_completed(args.task_id, item) for item in args.completed]
    if args.todo:
        report["todos"] = [state_store.record_todo(args.task_id, item) for item in args.todo]
    if args.verification:
        report["verifications"] = [
            state_store.record_verification(args.task_id, item) for item in args.verification
        ]
    report["state"] = state_store.load_task_state(args.task_id)
    print(_dump(report))
    return 0


def command_state(settings: Settings, args: argparse.Namespace) -> int:
    _, state_store = _build_stores(settings)
    if args.task_id:
        payload: Any = state_store.load_task_state(args.task_id)
    else:
        payload = {"tasks": state_store.list_tasks()}
    print(_dump(payload))
    return 0


def command_apply(settings: Settings, args: argparse.Namespace) -> int:
    from .minimax_agent import MiniMaxAgent

    store, state_store = _build_stores(settings)
    builder = ContextBuilder(store, state_store, settings.root)
    context = builder.build(args.task_id, args.task, args.spec_id)
    context.retrieval["repository_root"] = str(_repository_root(settings))
    context.retrieval["module_root"] = str(settings.root.resolve())

    agent = MiniMaxAgent(settings)
    result = agent.run(context, apply=not args.dry_run)

    evidence = {
        "task_id": args.task_id,
        "task": args.task,
        "context_specifications": [item["spec_id"] for item in context.specifications],
        "context_code_files": sorted({item["file_path"] for item in context.code}),
        "context_test_files": sorted({item["file_path"] for item in context.tests}),
        "context_state_todos": context.state.get("todos", []),
        "minimax": result.to_dict(),
    }
    output = settings.evidence_dir / "minimax_call.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(evidence), encoding="utf-8")
    print(_dump({k: v for k, v in evidence.items() if k != "minimax"} | {"evidence_file": str(output)}))
    return 0 if result.error is None else 1


def command_verify(settings: Settings, args: argparse.Namespace) -> int:
    from scripts.verify import run_all  # type: ignore[import-not-found]

    return run_all(settings, only=args.only)


def command_reset(settings: Settings, args: argparse.Namespace) -> int:
    store, _ = _build_stores(settings)
    report: dict[str, Any] = {}
    for table in ("sdd_relation", "sdd_test", "sdd_code_symbol", "sdd_specification"):
        report[table] = store.execute(f"DELETE FROM {table}")
    store.execute(f"DROP DATABASE IF EXISTS `{settings.seekdb_database}`")
    report["dropped_database"] = settings.seekdb_database
    print(_dump(report))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdd-context", description="MiniMax SDD context management module")
    parser.add_argument("--root", default=None, help="project root that holds specs/, sample/ and tests/")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="initialize the database and import the sample materials")
    init.set_defaults(handler=command_init)

    importer = subparsers.add_parser("import", help="import or update materials")
    importer.add_argument("--spec", default=None)
    importer.add_argument("--spec-id", default=None)
    importer.add_argument("--code", action="append", default=None)
    importer.add_argument("--test", action="append", default=None)
    importer.set_defaults(handler=command_import)

    context = subparsers.add_parser("context", help="build the development context for a task")
    context.add_argument("--task-id", default=DEFAULT_TASK_ID)
    context.add_argument("--task", default=DEFAULT_TASK_TEXT)
    context.add_argument("--spec-id", default=None)
    context.add_argument("--output", default=None)
    context.set_defaults(handler=command_context)

    task = subparsers.add_parser("task", help="create or update the persisted task state")
    task.add_argument("--task-id", default=DEFAULT_TASK_ID)
    task.add_argument("--description", default=DEFAULT_TASK_TEXT)
    task.add_argument("--create", action="store_true")
    task.add_argument("--completed", action="append", default=None)
    task.add_argument("--todo", action="append", default=None)
    task.add_argument("--verification", action="append", default=None)
    task.add_argument("--in-scope", action="append", default=None)
    task.set_defaults(handler=command_task)

    state = subparsers.add_parser("state", help="show the persisted task state")
    state.add_argument("--task-id", default=None)
    state.set_defaults(handler=command_state)

    apply_parser = subparsers.add_parser("apply", help="let MiniMax implement the task")
    apply_parser.add_argument("--task-id", default=DEFAULT_TASK_ID)
    apply_parser.add_argument("--task", default=DEFAULT_TASK_TEXT)
    apply_parser.add_argument("--spec-id", default=None)
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.set_defaults(handler=command_apply)

    verify = subparsers.add_parser("verify", help="run the automated acceptance suite")
    verify.add_argument("--only", action="append", default=None)
    verify.set_defaults(handler=command_verify)

    reset = subparsers.add_parser("reset", help="drop the imported materials")
    reset.set_defaults(handler=command_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = load_settings()
    if args.root:
        settings = Settings(root=Path(args.root))
    try:
        return int(args.handler(settings, args))
    except Exception as error:
        print(_dump({"error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
