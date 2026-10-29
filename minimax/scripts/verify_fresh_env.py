"""Verify the delivery in a brand-new Python environment.

The acceptance suite is only meaningful if the module also runs on a machine
that has never seen this project. This script builds that situation:

1. create a **new** virtual environment that cannot see the system packages
   (``include-system-site-packages = false``);
2. install the pinned dependencies from ``minimax/requirements.txt`` and record
   the exact command, the exit code and the resolved versions;
3. start a PowerContext Server **from that environment** on a free port, with
   its own ``POWERCONTEXT_HOME`` so the state directory is isolated as well;
4. run the six acceptance items, the standalone audits and the pytest suite in
   that environment, against an **isolated database namespace**;
5. write everything it observed to ``minimax/evidence/fresh_env_report.json``.

The MiniMax endpoint is not required: the acceptance suite audits the
historical development evidence committed in the repository.

Run it with::

    python minimax/scripts/verify_fresh_env.py
    python minimax/scripts/verify_fresh_env.py --venv D:\\tmp\\my-venv
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPOSITORY_ROOT / "minimax" / "requirements.txt"

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

# The suites that prove the delivery works in the new environment.
ACCEPTANCE_SCRIPTS = (
    ("acceptance-suite", "minimax/scripts/verify.py", ["--all"]),
    ("minimax-evidence-audit", "minimax/scripts/audit_minimax_evidence.py", []),
    ("red-green-audit", "minimax/scripts/audit_red_green.py", []),
    ("seekdb-evidence", "minimax/scripts/seekdb_evidence.py", []),
    ("diagnostics", "minimax/scripts/diagnose.py", []),
)


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
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(cwd or REPOSITORY_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
    )
    return {
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-3000:],
        "stderr_tail": (completed.stderr or "")[-3000:],
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _venv_python(venv: Path) -> Path:
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def _powercontext_cli(venv: Path) -> list[str]:
    """Return the command that starts the official PowerContext server.

    The published distribution ships a console script (``powercontext``).
    ``python -m powercontext.cli`` does not work: the package has no
    ``__main__.py``, so it cannot be executed as a module.
    """

    name = "powercontext.exe" if os.name == "nt" else "powercontext"
    script = venv / ("Scripts" if os.name == "nt" else "bin") / name
    if script.exists():
        return [str(script)]
    return [str(_venv_python(venv)), "-m", "powercontext.cli"]


def _venv_isolated(venv: Path) -> dict[str, Any]:
    """Prove the new environment cannot see the packages of the current one."""

    config = venv / "pyvenv.cfg"
    include_system = None
    version = None
    if config.exists():
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("include-system-site-packages"):
                include_system = line.split("=", 1)[1].strip().lower() == "true"
            if line.startswith("version"):
                version = line.split("=", 1)[1].strip()
    return {
        "pyvenv_cfg": str(config),
        "include_system_site_packages": include_system,
        "python_version": version,
        "isolated": include_system is False,
    }


def _drop_isolated_database(host: str, port: int, user: str, password: str, database: str) -> dict[str, Any]:
    """Remove the isolated database so the run starts from a genuinely empty one."""

    import pymysql

    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            connect_timeout=10,
            autocommit=True,
        )
    except Exception as error:
        return {"status": BLOCKED, "detail": f"{type(error).__name__}: {error}"}
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database}`")
        return {"status": PASS, "dropped": database}
    except Exception as error:
        return {"status": BLOCKED, "detail": str(error)[:300]}
    finally:
        connection.close()


def _create_isolated_scope(url: str) -> tuple[str | None, dict[str, Any]]:
    """Create a PowerContext scope that holds no task state before the run."""

    import httpx

    idempotency_key = f"sdd-freshenv-{uuid.uuid4().hex[:16]}"
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{url.rstrip('/')}/v1/scopes",
                json={
                    "title": idempotency_key,
                    "summary": "隔离的全新环境验证",
                    "idempotency_key": idempotency_key,
                },
            )
    except Exception as error:
        return None, {"status": BLOCKED, "detail": f"{type(error).__name__}: {error}"}
    if response.status_code >= 400:
        return None, {"status": BLOCKED, "detail": f"HTTP {response.status_code}: {response.text[:300]}"}
    payload = response.json()
    return payload.get("scope_id"), {"status": PASS, "scope_id": payload.get("scope_id")}


def _wait_for_health(url: str, timeout: int = 90) -> dict[str, Any]:
    import httpx

    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=5) as client:
                response = client.get(f"{url.rstrip('/')}/health/ready")
            if response.status_code < 400:
                return {"status": PASS, "body": response.json()}
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as error:
            last_error = f"{type(error).__name__}: {error}"
        time.sleep(2)
    return {"status": BLOCKED, "detail": last_error}


def main(argv: list[str] | None = None) -> int:
    _use_utf8_stdout()
    parser = argparse.ArgumentParser(description="Verify the delivery in a brand-new Python environment")
    parser.add_argument("--venv", default=None, help="where to create the virtual environment")
    parser.add_argument(
        "--keep-venv",
        action="store_true",
        help="keep the virtual environment and the PowerContext home after the run",
    )
    parser.add_argument("--output", default=None)
    arguments = parser.parse_args(argv)

    workdir = Path(arguments.venv) if arguments.venv else Path(tempfile.gettempdir()) / f"sdd-freshenv-{uuid.uuid4().hex[:8]}"
    venv = workdir / "venv"
    pc_home = workdir / "pc-home"
    pc_port = _free_port()
    pc_url = f"http://127.0.0.1:{pc_port}"

    database = f"sdd_context_freshenv_{uuid.uuid4().hex[:6]}"
    steps: list[dict[str, Any]] = []
    report: dict[str, Any] = {
        "mode": "FRESH_ENVIRONMENT_VERIFICATION",
        "description": "在全新隔离的 Python 环境中安装依赖、启动官方 PowerContext Server 并跑完整验收。",
        "workdir": str(workdir),
        "isolated_database": database,
        "isolated_powercontext_url": pc_url,
        "isolated_powercontext_home": str(pc_home),
    }

    def step(name: str, result: dict[str, Any]) -> dict[str, Any]:
        result["step"] = name
        steps.append(result)
        return result

    # ---------------------------------------------------------------- 1. venv
    workdir.mkdir(parents=True, exist_ok=True)
    created = step("create-venv", _run([sys.executable, "-m", "venv", str(venv)]))
    python = _venv_python(venv)
    if created["exit_code"] != 0 or not python.exists():
        report["steps"] = steps
        report["status"] = FAIL
        report["detail"] = "无法创建虚拟环境"
        _write(report, arguments.output)
        print(_dump(report))
        return 1

    isolation = _venv_isolated(venv)
    report["venv"] = {
        "path": str(venv),
        "python": str(python),
        "interpreter_version": step(
            "python-version",
            _run([str(python), "-c", "import sys; print(sys.version)"]),
        ),
        "isolation": isolation,
    }

    # ------------------------------------------------------- 2. dependencies
    step("upgrade-pip", _run([str(python), "-m", "pip", "install", "--upgrade", "pip"]))
    install = step(
        "install-requirements",
        _run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)]),
    )
    report["install"] = {
        "command": install["command"],
        "exit_code": install["exit_code"],
        "stdout_tail": install["stdout_tail"][-1500:],
    }
    if install["exit_code"] != 0:
        report["steps"] = steps
        report["status"] = FAIL
        report["detail"] = "依赖安装失败"
        _write(report, arguments.output)
        print(_dump(report))
        return 1

    report["versions"] = {
        "pip": step("pip-version", _run([str(python), "-m", "pip", "--version"]))["stdout_tail"].strip(),
        "packages": step(
            "pip-list",
            _run([str(python), "-m", "pip", "list", "--format=freeze"]),
        )["stdout_tail"].splitlines(),
    }
    # The environment must not have inherited pytest or the module's own
    # dependencies from the machine it was built on.
    probe = step(
        "import-check",
        _run(
            [
                str(python),
                "-c",
                "import pytest, pymysql, httpx, powercontext, minimax.sdd_context;"
                " print('imports ok')",
            ],
            env={**os.environ, "PYTHONPATH": str(REPOSITORY_ROOT)},
        ),
    )
    report["import_check"] = {"exit_code": probe["exit_code"], "output": probe["stdout_tail"].strip()}

    # ------------------------------------------- 3. PowerContext Server (new env)
    pc_home.mkdir(parents=True, exist_ok=True)
    server_env = {
        **os.environ,
        "POWERCONTEXT_HOME": str(pc_home),
    }
    server_log = workdir / "powercontext-server.log"
    cli = _powercontext_cli(venv)
    process = subprocess.Popen(
        [*cli, "server", "run", "--host", "127.0.0.1", "--port", str(pc_port), "--no-env-file"],
        cwd=str(workdir),
        env=server_env,
        stdout=server_log.open("wb"),
        stderr=subprocess.STDOUT,
    )
    health = _wait_for_health(pc_url)
    report["powercontext_server"] = {
        "command": " ".join([*cli, "server", "run", "--host", "127.0.0.1", "--port", str(pc_port), "--no-env-file"]),
        "environment": {"POWERCONTEXT_HOME": str(pc_home)},
        "pid": process.pid,
        "health": health,
        "log": str(server_log),
    }

    if health["status"] != PASS:
        process.terminate()
        report["steps"] = steps
        report["status"] = BLOCKED
        report["detail"] = "PowerContext Server 未能就绪"
        _write(report, arguments.output)
        print(_dump(report))
        return 1

    # --------------------------------- 4. isolated namespace + acceptance run
    seekdb_host = os.environ.get("SDD_SEEKDB_HOST", "127.0.0.1")
    seekdb_port = int(os.environ.get("SDD_SEEKDB_PORT", "2881"))
    seekdb_user = os.environ.get("SDD_SEEKDB_USER", "root")
    seekdb_password = os.environ.get("SDD_SEEKDB_PASSWORD", "")

    scope_id, scope_report = _create_isolated_scope(pc_url)
    report["isolated_scope"] = scope_report
    report["database_reset"] = _drop_isolated_database(
        seekdb_host, seekdb_port, seekdb_user, seekdb_password, database
    )

    env = {
        **os.environ,
        "PYTHONPATH": str(REPOSITORY_ROOT),
        "SDD_SEEKDB_HOST": seekdb_host,
        "SDD_SEEKDB_PORT": str(seekdb_port),
        "SDD_SEEKDB_USER": seekdb_user,
        "SDD_SEEKDB_PASSWORD": seekdb_password,
        "SDD_SEEKDB_DATABASE": database,
        "SDD_POWERCONTEXT_URL": pc_url,
        "SDD_POWERCONTEXT_SCOPE_ID": scope_id or "",
    }

    init = step(
        "init-empty-database",
        _run([str(python), "-m", "minimax.sdd_context.cli", "init"], env=env),
    )
    if init["exit_code"] != 0:
        report["steps"] = steps
        report["status"] = FAIL
        report["detail"] = "空库初始化失败"
        _write(report, arguments.output)
        print(_dump(report))
        return 1

    for name, script, arguments_list in ACCEPTANCE_SCRIPTS:
        step(name, _run([str(python), script, *arguments_list], env=env))

    step(
        "pytest-suite",
        _run([str(python), "-m", "pytest", "minimax/tests/", "-q"], env=env),
    )
    step(
        "phase4-checks",
        _run([str(python), "-m", "minimax.scripts.phase4_checks"], env=env),
    )

    # ------------------------------------------------------------- 5. teardown
    process.terminate()
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
    report["database_cleanup"] = _drop_isolated_database(
        seekdb_host, seekdb_port, seekdb_user, seekdb_password, database
    )

    failed = [item for item in steps if item["exit_code"] != 0]
    report["steps"] = steps
    report["failed_steps"] = [item["step"] for item in failed]
    report["status"] = PASS if not failed else FAIL

    if not arguments.keep_venv:
        shutil.rmtree(workdir, ignore_errors=True)
    else:
        report["kept_workdir"] = str(workdir)

    _write(report, arguments.output)
    print(_dump(report))
    return 0 if not failed else 1


def _write(report: dict[str, Any], output: str | None) -> None:
    destination = Path(output) if output else REPOSITORY_ROOT / "minimax" / "evidence" / "fresh_env_report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_dump(report), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
