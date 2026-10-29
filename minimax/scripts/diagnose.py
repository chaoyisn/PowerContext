"""Environment and service diagnostics for the MiniMax SDD context module.

The acceptance suite reports ``BLOCKED`` when a dependency is unreachable, but
a reviewer needs to know *why* it is unreachable. This script separates the
failure modes that look identical from the outside:

``SERVICE_NOT_STARTED``
    Nothing is listening on the configured address. Start the service.
``WRONG_CREDENTIALS``
    The service answers but rejects the login. Fix the user/password or token.
``DATABASE_MISSING``
    The service answers and the credentials are accepted, but the SDD database
    does not exist yet. Run ``python -m minimax.sdd_context.cli init``.
``BUSINESS_TEST_FAILED``
    Every dependency is healthy, so a failing check is a real defect in the
    module rather than an environment problem.

It also reports whether the environment looks clean: leftover task state or
pre-loaded material would make an empty-database check meaningless.

Run it with::

    python minimax/scripts/diagnose.py
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = REPOSITORY_ROOT / "minimax"

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.config import load_settings  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"

SERVICE_NOT_STARTED = "SERVICE_NOT_STARTED"
WRONG_CREDENTIALS = "WRONG_CREDENTIALS"
DATABASE_MISSING = "DATABASE_MISSING"
BUSINESS_TEST_FAILED = "BUSINESS_TEST_FAILED"
NOT_CONFIGURED = "NOT_CONFIGURED"


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _port_is_open(host: str, port: int, timeout: float = 2.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        try:
            probe.connect((host, port))
        except OSError:
            return False
    return True


def _redact(text: str) -> str:
    """Never let a credential reach the report."""

    return text.replace(os.environ.get("SDD_SEEKDB_PASSWORD", "\x00"), "***")


def _diagnose_seekdb(settings) -> dict[str, Any]:
    """Classify the state of the seekdb instance."""

    host, port = settings.seekdb_host, settings.seekdb_port
    result: dict[str, Any] = {
        "service": "seekdb",
        "endpoint": f"{host}:{port}",
        "database": settings.seekdb_database,
        "user": settings.seekdb_user,
    }

    if not _port_is_open(host, port):
        result.update(
            {
                "status": BLOCKED,
                "reason": SERVICE_NOT_STARTED,
                "remedy": "启动 seekdb 服务，或用 SDD_SEEKDB_HOST / SDD_SEEKDB_PORT 指向已有实例。",
            }
        )
        return result

    try:
        import pymysql
    except ImportError:  # pragma: no cover - requirements pin pymysql
        result.update(
            {
                "status": BLOCKED,
                "reason": NOT_CONFIGURED,
                "remedy": "执行 pip install -r minimax/requirements.txt",
            }
        )
        return result

    try:
        connection = pymysql.connect(
            host=host,
            port=port,
            user=settings.seekdb_user,
            password=settings.seekdb_password,
            connect_timeout=10,
        )
    except Exception as error:
        message = _redact(str(error))
        # A reachable service that rejects the login is a credential problem;
        # anything else means the service is up but the handshake failed.
        reason = WRONG_CREDENTIALS if _looks_like_auth_error(message) else SERVICE_NOT_STARTED
        result.update(
            {
                "status": BLOCKED,
                "reason": reason,
                "detail": message[:400],
                "remedy": "核对 SDD_SEEKDB_USER / SDD_SEEKDB_PASSWORD。",
            }
        )
        return result

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION() AS version")
            version = cursor.fetchone()
            cursor.execute(
                "SELECT COUNT(*) AS total FROM information_schema.schemata "
                "WHERE schema_name = %s",
                (settings.seekdb_database,),
            )
            exists = int(cursor.fetchone()[0]) > 0
    except Exception as error:
        result.update(
            {
                "status": BLOCKED,
                "reason": SERVICE_NOT_STARTED,
                "detail": _redact(str(error))[:400],
                "remedy": "服务未正确响应 MySQL 协议，请检查服务日志。",
            }
        )
        return result
    finally:
        connection.close()

    result["server_version"] = str(version[0]) if version else "unknown"
    result["database_exists"] = exists
    if not exists:
        result.update(
            {
                "status": BLOCKED,
                "reason": DATABASE_MISSING,
                "remedy": "执行 python -m minimax.sdd_context.cli init 建库并导入物料。",
            }
        )
        return result

    result.update({"status": PASS, "reason": "healthy"})
    return result


def _looks_like_auth_error(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "access denied",
        "password",
        "authentication",
        "1045",
        "1044",
        "28000",
    )
    return any(marker in lowered for marker in markers)


def _diagnose_powercontext(settings) -> dict[str, Any]:
    """Classify the state of the PowerContext server."""

    url = settings.powercontext_url
    result: dict[str, Any] = {"service": "powercontext", "endpoint": url}

    host, port = _host_port(url)
    if host and port and not _port_is_open(host, port):
        result.update(
            {
                "status": BLOCKED,
                "reason": SERVICE_NOT_STARTED,
                "remedy": "启动 PowerContext Server（python -m powercontext.server ...），"
                "或用 SDD_POWERCONTEXT_URL 指向已有实例。",
            }
        )
        return result

    try:
        import httpx
    except ImportError:  # pragma: no cover - requirements pin httpx
        result.update(
            {
                "status": BLOCKED,
                "reason": NOT_CONFIGURED,
                "remedy": "执行 pip install -r minimax/requirements.txt",
            }
        )
        return result

    headers = {"content-type": "application/json"}
    if settings.powercontext_token:
        headers["authorization"] = f"Bearer {settings.powercontext_token}"
    try:
        response = httpx.get(f"{url.rstrip('/')}/v1/scopes/default", headers=headers, timeout=10)
    except Exception as error:
        result.update(
            {
                "status": BLOCKED,
                "reason": SERVICE_NOT_STARTED,
                "detail": _redact(str(error))[:400],
                "remedy": "服务无法连接，请确认进程仍在运行。",
            }
        )
        return result

    if response.status_code in (401, 403):
        result.update(
            {
                "status": BLOCKED,
                "reason": WRONG_CREDENTIALS,
                "detail": f"HTTP {response.status_code}",
                "remedy": "核对 SDD_POWERCONTEXT_TOKEN。",
            }
        )
        return result
    if response.status_code >= 400:
        result.update(
            {
                "status": BLOCKED,
                "reason": SERVICE_NOT_STARTED,
                "detail": f"HTTP {response.status_code}: {response.text[:200]}",
                "remedy": "服务返回错误，请检查服务日志。",
            }
        )
        return result

    try:
        scope_id = response.json()["scope_id"]
    except Exception as error:
        result.update(
            {
                "status": BLOCKED,
                "reason": SERVICE_NOT_STARTED,
                "detail": _redact(str(error))[:200],
                "remedy": "响应不是预期的 scope 契约，请检查服务版本。",
            }
        )
        return result

    result.update({"status": PASS, "reason": "healthy", "scope_id": scope_id})
    return result


def _host_port(url: str) -> tuple[str | None, int | None]:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.hostname:
        return None, None
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _diagnose_minimax(settings) -> dict[str, Any]:
    """Report whether the model endpoint is reachable.

    The endpoint is optional for the acceptance suite: the historical evidence
    audit never calls the model. This entry therefore only reports reachability
    and never turns a missing endpoint into a failing acceptance item.
    """

    url = settings.minimax_base_url
    result: dict[str, Any] = {
        "service": "minimax",
        "endpoint": url,
        "model": settings.minimax_model,
        "api_key_configured": bool(settings.minimax_api_key),
        "required_for": ["minimax/scripts/live_minimax_check.py", "cli apply"],
        "required_by_acceptance_suite": False,
    }

    host, port = _host_port(url)
    if host and port and not _port_is_open(host, port):
        result.update(
            {
                "status": BLOCKED,
                "reason": SERVICE_NOT_STARTED,
                "remedy": "启动 MiniMax 网关，或设置 SDD_MINIMAX_BASE_URL；"
                "历史证据审计不需要该服务。",
            }
        )
        return result

    result.update({"status": PASS, "reason": "reachable"})
    return result


def _diagnose_materials(settings) -> dict[str, Any]:
    """Check whether the database already holds imported material.

    Pre-loaded material would make an empty-database check meaningless, so the
    diagnostics have to report it.
    """

    from minimax.sdd_context.seekdb_store import SeekDBStore

    try:
        store = SeekDBStore(settings)
        counts = store.counts()
        server_version = store.server_version()
    except Exception as error:
        return {
            "status": BLOCKED,
            "reason": DATABASE_MISSING,
            "detail": _redact(str(error))[:400],
            "remedy": "先执行 python -m minimax.sdd_context.cli init。",
        }

    total = sum(counts.values())
    return {
        "status": PASS,
        "reason": "healthy",
        "server_version": server_version,
        "counts": counts,
        "material_present": total > 0,
        "note": (
            "数据库中已有物料；空库复现前请先执行 "
            "python -m minimax.sdd_context.cli reset。"
            if total
            else "数据库为空，符合空状态复现前提。"
        ),
    }


def _diagnose_task_state(settings) -> dict[str, Any]:
    """Check whether PowerContext still holds task state from earlier runs."""

    from minimax.sdd_context.powercontext_store import PowerContextStateStore

    try:
        store = PowerContextStateStore(settings)
        tasks = store.list_tasks()
        state = store.load_task_state("TASK-SPEC-REQ-001")
    except Exception as error:
        return {
            "status": BLOCKED,
            "reason": SERVICE_NOT_STARTED,
            "detail": _redact(str(error))[:400],
            "remedy": "先启动 PowerContext Server。",
        }

    return {
        "status": PASS,
        "reason": "healthy",
        "known_task_ids": tasks,
        "sample_task_has_state": bool(state.get("has_state")),
        "note": (
            "存在历史任务状态；跨进程恢复验证会使用独立任务 ID，不会与历史状态混淆。"
            if tasks
            else "没有历史任务状态，符合空状态复现前提。"
        ),
    }


def _diagnose_python() -> dict[str, Any]:
    version = ".".join(str(part) for part in sys.version_info[:3])
    ok = sys.version_info[:2] >= (3, 12)
    return {
        "status": PASS if ok else FAIL,
        "reason": "healthy" if ok else BUSINESS_TEST_FAILED,
        "detail": f"Python {version}（官方要求 3.12）",
    }


def _diagnose_git() -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(REPOSITORY_ROOT),
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return {"status": FAIL, "reason": BUSINESS_TEST_FAILED, "detail": "不是 git 仓库"}
    return {
        "status": PASS,
        "reason": "healthy",
        "head": completed.stdout.strip(),
        "branch": subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(REPOSITORY_ROOT),
            capture_output=True,
            text=True,
        ).stdout.strip(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose the SDD context environment")
    parser.add_argument(
        "--output",
        default=None,
        help="write the diagnostic report to this path",
    )
    arguments = parser.parse_args(argv)

    settings = load_settings()
    settings.ensure_directories()

    checks = {
        "python": _diagnose_python(),
        "git": _diagnose_git(),
        "seekdb": _diagnose_seekdb(settings),
        "powercontext": _diagnose_powercontext(settings),
        "minimax": _diagnose_minimax(settings),
    }
    # The two follow-up checks need a reachable service, so they only run when
    # the corresponding service is healthy.
    if checks["seekdb"]["status"] == PASS:
        checks["materials"] = _diagnose_materials(settings)
    if checks["powercontext"]["status"] == PASS:
        checks["task_state"] = _diagnose_task_state(settings)

    blocked = [name for name, value in checks.items() if value["status"] == BLOCKED]
    failed = [name for name, value in checks.items() if value["status"] == FAIL]

    payload = {
        "mode": "DIAGNOSTIC",
        "description": "区分服务未启动 / 凭据错误 / 库不存在 / 业务测试失败四类问题。",
        "repository_root": str(REPOSITORY_ROOT),
        "checks": checks,
        "blocked_checks": blocked,
        "failed_checks": failed,
        "status": PASS if not blocked and not failed else (FAIL if failed else BLOCKED),
    }

    output = Path(arguments.output) if arguments.output else settings.evidence_dir / "diagnostics.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0 if payload["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
