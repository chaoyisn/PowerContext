"""共享的后端鉴权helper（V2）。

V2 起，游戏后端**强制**两样东西：

1. ``X-Town-Token`` —— 服务凭据（Dify ↔ 后端之间的那把钥匙）。
   缺了或者写错了，后端一律 401。
2. ``X-Town-Identity`` —— 玩家身份。玩家第一次出现时被绑定到这个身份上；
   之后再想用别人的 player_id 来读存档，后端会 403。

这两个值都**不能**写进仓库里的证据文件、日志或断言输出，因此这个
模块只提供"读出来、发过去"的能力，不提供"打印出来"的能力。

凭据来源（按优先级）：

1. 显式传参；
2. 环境变量 ``TOWN_BACKEND_TOKEN`` / ``TOWN_TEST_IDENTITY``；
3. ``dify/deploy/.env``（已 gitignore）。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "deploy" / ".env"


def _read_env_file() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def backend_token(explicit: str = "") -> str:
    """The service credential for talking to town-backend."""

    if explicit:
        return explicit
    value = os.environ.get("TOWN_BACKEND_TOKEN", "")
    if value:
        return value
    return _read_env_file().get("TOWN_BACKEND_TOKEN", "")


def test_identity(explicit: str = "") -> str:
    """The identity that test players get bound to.

    It is deliberately **not** a secret — it only identifies *who is
    playing*. The protection that actually matters (a second person
    cannot read somebody else's save) is exercised by presenting a
    *different* identity, which the backend rejects.
    """

    if explicit:
        return explicit
    value = os.environ.get("TOWN_TEST_IDENTITY", "")
    if value:
        return value
    return _read_env_file().get("TOWN_TEST_IDENTITY", "") or "verify_suite"


def auth_headers(identity: str = "", *, token: str = "") -> dict[str, str]:
    """Build the header set every V2 backend call needs."""

    headers: dict[str, str] = {}
    key = backend_token(token)
    if key:
        headers["X-Town-Token"] = key
    who = test_identity(identity)
    if who:
        headers["X-Town-Identity"] = who
    return headers


def describe_auth_mode() -> str:
    """A short, secret-free description of the auth configuration."""

    return (
        f"token={'有' if backend_token() else '无(后端未强制)'} "
        f"identity={test_identity()!r} "
        f"anonymous_allowed={os.environ.get('TOWN_ALLOW_ANONYMOUS', '0')}"
    )
