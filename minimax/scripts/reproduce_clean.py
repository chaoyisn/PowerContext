"""Clean-environment reproduction of the six acceptance items.

This script reproduces the whole flow in an **isolated** environment so that a
reviewer can prove that the module does not depend on any historical state of
the machine it runs on:

* a fresh database namespace (``SDD_SEEKDB_DATABASE``) — the SDD tables start
  empty and are created by this run;
* a fresh PowerContext scope (``POST /v1/scopes``) — no task state exists in
  it before this run;
* an isolated task id, so the cross-process recovery check cannot pick up
  records written by an earlier run;
* a fresh checkout of the repository when ``--fresh-checkout`` is given, so
  the run also proves that a brand-new clone follows the README.

The MiniMax endpoint is **not** required: the acceptance suite audits the
historical development evidence that is committed in the repository. The live
model call is a separate, explicitly online entry point
(``minimax/scripts/live_minimax_check.py``).

Run it with::

    python minimax/scripts/reproduce_clean.py
    python minimax/scripts/reproduce_clean.py --fresh-checkout
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.config import Settings, load_settings  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _use_utf8_stdout() -> None:
    """Windows consoles default to GBK, which cannot encode every character."""

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
) -> dict[str, Any]:
    """Run a command and capture everything a reviewer needs to re-run it."""

    completed = subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )
    return {
        "command": " ".join(command),
        "cwd": str(cwd),
        "exit_code": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-4000:],
        "stderr_tail": (completed.stderr or "")[-4000:],
    }


def _git(*arguments: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=str(cwd or REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _create_isolated_scope(settings: Settings) -> tuple[str | None, dict[str, Any]]:
    """Create a fresh PowerContext scope so no historical state can leak in."""

    import httpx

    idempotency_key = f"sdd-repro-{uuid.uuid4().hex[:16]}"
    title = f"sdd-repro-{idempotency_key}"
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{settings.powercontext_url.rstrip('/')}/v1/scopes",
                json={
                    "title": title,
                    "summary": "隔离复现用的临时 scope",
                    "idempotency_key": idempotency_key,
                },
            )
    except Exception as error:
        return None, {"status": BLOCKED, "detail": f"{type(error).__name__}: {error}"}

    if response.status_code >= 400:
        return None, {
            "status": BLOCKED,
            "detail": f"HTTP {response.status_code}: {response.text[:300]}",
        }
    payload = response.json()
    return payload.get("scope_id"), {"status": PASS, "scope_id": payload.get("scope_id")}


def _preflight(settings: Settings) -> dict[str, Any]:
    """Prove that the isolated namespace holds nothing before the run.

    A reviewer has to be able to trust that the empty-database check is real,
    so the preflight reports the actual row counts and task records instead of
    assuming they are zero.
    """

    import pymysql

    checks: dict[str, Any] = {}
    try:
        connection = pymysql.connect(
            host=settings.seekdb_host,
            port=settings.seekdb_port,
            user=settings.seekdb_user,
            password=settings.seekdb_password,
            connect_timeout=10,
        )
    except Exception as error:
        return {"status": BLOCKED, "detail": f"{type(error).__name__}: {error}", "checks": {}}
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = %s",
                (settings.seekdb_database,),
            )
            checks["database_absent_before_run"] = int(cursor.fetchone()[0]) == 0
    except Exception as error:
        return {"status": BLOCKED, "detail": str(error)[:300], "checks": checks}
    finally:
        connection.close()

    try:
        from minimax.sdd_context.powercontext_store import PowerContextStateStore

        store = PowerContextStateStore(settings)
        checks["scope_has_no_task_records"] = not store.list_tasks()
    except Exception as error:
        checks["scope_has_no_task_records"] = False
        checks["scope_error"] = str(error)[:300]

    status = PASS if checks.get("database_absent_before_run") and checks.get(
        "scope_has_no_task_records"
    ) else FAIL
    return {"status": status, "checks": checks}


def _drop_isolated_database(settings: Settings) -> dict[str, Any]:
    """Drop the isolated database before the run so it starts empty."""

    import pymysql

    try:
        connection = pymysql.connect(
            host=settings.seekdb_host,
            port=settings.seekdb_port,
            user=settings.seekdb_user,
            password=settings.seekdb_password,
            connect_timeout=10,
            autocommit=True,
        )
    except Exception as error:
        return {"status": BLOCKED, "detail": f"{type(error).__name__}: {error}"}
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{settings.seekdb_database}`")
        return {"status": PASS, "dropped": settings.seekdb_database}
    except Exception as error:
        return {"status": BLOCKED, "detail": str(error)[:300]}
    finally:
        connection.close()


def _module_env(base: dict[str, str], settings: Settings, scope_id: str | None) -> dict[str, str]:
    env = dict(base)
    env["SDD_SEEKDB_DATABASE"] = settings.seekdb_database
    if scope_id:
        env["SDD_POWERCONTEXT_SCOPE_ID"] = scope_id
    # Make sure the module is importable from a fresh checkout as well.
    env["PYTHONPATH"] = str(REPOSITORY_ROOT)
    return env


def _fresh_checkout(directory: Path) -> tuple[Path | None, dict[str, Any]]:
    """Clone the repository into a throwaway directory.

    The clone carries no uncommitted file and no local database, so the run
    that follows proves the README works from a brand-new checkout.
    """

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    # Clone from the local repository: the competition branch is intentionally
    # not pushed to the remote, and a clone only carries committed objects, so
    # the result is a clean tree without any working-copy file.
    url = str(REPOSITORY_ROOT)
    command = ["git", "clone", "--quiet"]
    if branch and branch != "HEAD":
        command += ["--branch", branch]
    command += [url, str(directory / "checkout")]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return None, {"status": BLOCKED, "detail": completed.stderr[:400]}
    checkout = directory / "checkout"
    return checkout, {
        "status": PASS,
        "path": str(checkout),
        "clone_command": " ".join(command),
        "head": _git("rev-parse", "HEAD", cwd=checkout),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD", cwd=checkout),
    }


def main(argv: list[str] | None = None) -> int:
    _use_utf8_stdout()
    parser = argparse.ArgumentParser(description="Reproduce the acceptance suite in a clean environment")
    parser.add_argument(
        "--fresh-checkout",
        action="store_true",
        help="also run the suite from a brand-new git clone",
    )
    parser.add_argument("--output", default=None)
    arguments = parser.parse_args(argv)

    base_env = dict(os.environ)
    settings = load_settings()
    settings.ensure_directories()

    # Everything below uses an isolated namespace so the machine's existing
    # database and task state cannot influence the result.
    isolated = Settings(
        root=settings.root,
        seekdb_host=settings.seekdb_host,
        seekdb_port=settings.seekdb_port,
        seekdb_user=settings.seekdb_user,
        seekdb_password=settings.seekdb_password,
        seekdb_database=f"{settings.seekdb_database}_repro",
        powercontext_url=settings.powercontext_url,
        powercontext_token=settings.powercontext_token,
        powercontext_timeout=settings.powercontext_timeout,
        powercontext_scope_id="",
        minimax_base_url=settings.minimax_base_url,
        minimax_api_key=settings.minimax_api_key,
        minimax_model=settings.minimax_model,
        minimax_timeout=settings.minimax_timeout,
    )

    scope_id, scope_report = _create_isolated_scope(isolated)
    if scope_id:
        isolated = Settings(
            **{**isolated.__dict__, "powercontext_scope_id": scope_id}
        )
    drop_report = _drop_isolated_database(isolated)

    env = _module_env(base_env, isolated, scope_id)
    task_id = f"TASK-REPRO-{uuid.uuid4().hex[:8].upper()}"
    steps: list[dict[str, Any]] = []

    def step(name: str, command: list[str], *, cwd: Path | None = None, expect_zero: bool = True) -> None:
        result = _run(command, cwd=cwd or REPOSITORY_ROOT, env=env)
        result["step"] = name
        result["expected_exit_code"] = 0
        result["ok"] = (result["exit_code"] == 0) if expect_zero else True
        steps.append(result)

    # 1. prove the isolated namespace really starts empty
    preflight = _preflight(isolated)
    # 2. empty database -> create schema and import the sample materials
    step(
        "init-empty-database",
        [sys.executable, "-m", "minimax.sdd_context.cli", "init"],
    )
    # 3. diagnostics on the isolated namespace, now that it is populated
    step(
        "diagnose-isolated-environment",
        [sys.executable, "minimax/scripts/diagnose.py", "--output", "minimax/evidence/repro_diagnostics.json"],
    )
    # 4. real seekdb retrieval
    step(
        "build-context-from-database",
        [
            sys.executable,
            "-m",
            "minimax.sdd_context.cli",
            "context",
            "--task-id",
            task_id,
            "--spec-id",
            "SPEC-REQ-001",
            "--output",
            "minimax/evidence/repro_context.json",
        ],
    )
    # 5. task state written into the isolated scope
    step(
        "write-task-state",
        [
            sys.executable,
            "-m",
            "minimax.sdd_context.cli",
            "task",
            "--task-id",
            task_id,
            "--create",
            "--completed",
            "复现：已完成项",
            "--todo",
            "复现：待办项",
            "--verification",
            "复现：验证结果",
        ],
    )
    # 6. the six acceptance items, without any historical call record
    step(
        "acceptance-suite",
        [sys.executable, "minimax/scripts/verify.py", "--all"],
    )
    # 7. specification update + cross-process recovery on the isolated task
    step(
        "spec-update-and-cross-process-recovery",
        [sys.executable, "-m", "minimax.scripts.phase4_checks"],
    )

    checkout_report: dict[str, Any] = {"status": "skipped"}
    if arguments.fresh_checkout:
        with tempfile.TemporaryDirectory(prefix="sdd-repro-checkout-") as directory:
            checkout, report = _fresh_checkout(Path(directory))
            checkout_report = report
            if checkout is not None:
                # The clone carries no database of its own, so it gets its own
                # namespace and its own scope before the suite runs there.
                clone_env = dict(env)
                clone_env["PYTHONPATH"] = str(checkout)
                clone_env["SDD_SEEKDB_DATABASE"] = f"{isolated.seekdb_database}_clone"
                clone_scope, clone_scope_report = _create_isolated_scope(isolated)
                if clone_scope:
                    clone_env["SDD_POWERCONTEXT_SCOPE_ID"] = clone_scope
                clone_settings = Settings(
                    **{**isolated.__dict__, "seekdb_database": clone_env["SDD_SEEKDB_DATABASE"]}
                )
                _drop_isolated_database(clone_settings)

                for clone_step, command in (
                    (
                        "fresh-checkout-init",
                        [sys.executable, "-m", "minimax.sdd_context.cli", "init"],
                    ),
                    (
                        "acceptance-suite-in-fresh-checkout",
                        [sys.executable, "minimax/scripts/verify.py", "--all"],
                    ),
                ):
                    result = _run(command, cwd=checkout, env=clone_env)
                    result["step"] = clone_step
                    result["expected_exit_code"] = 0
                    result["ok"] = result["exit_code"] == 0
                    steps.append(result)

                checkout_report["scope_creation"] = clone_scope_report
                checkout_report["acceptance_suite"] = {
                    "command": " ".join(
                        [sys.executable, "minimax/scripts/verify.py", "--all"]
                    ),
                    "exit_code": next(
                        (
                            item["exit_code"]
                            for item in steps
                            if item["step"] == "acceptance-suite-in-fresh-checkout"
                        ),
                        None,
                    ),
                }
                _drop_isolated_database(clone_settings)

    # The isolated namespace must not leak into the regular database.
    cleanup = _drop_isolated_database(isolated)

    passed = preflight.get("status") == PASS and all(item["ok"] for item in steps)
    payload = {
        "mode": "CLEAN_REPRODUCTION",
        "description": "在隔离的数据库命名空间与隔离的 PowerContext scope 中复现六项验收。",
        "isolated_database": isolated.seekdb_database,
        "isolated_scope_id": scope_id,
        "isolated_task_id": task_id,
        "scope_creation": scope_report,
        "preflight_empty_state": preflight,
        "database_reset": drop_report,
        "fresh_checkout": checkout_report,
        "steps": steps,
        "cleanup": cleanup,
        "status": PASS if passed else FAIL,
    }

    output = Path(arguments.output) if arguments.output else settings.evidence_dir / "clean_reproduction.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
