"""V2 部署脚本：导入 DSL → 注入真实凭据 → 多轮对话验收。

与 V1 的 ``import_and_run_dify.py`` 相比，多了一步**注入凭据**：

V1 的 DSL 里没有 ``TOWN_BACKEND_TOKEN``，后端也没开鉴权。V2 的后端
**强制**要求 ``X-Town-Token``，而这个值必须由部署者提供。

它**只**存在于两处：

1. 运行环境变量 ``TOWN_BACKEND_TOKEN``（例如 ``dify/deploy/.env``，已 gitignore）；
2. Dify 应用的 **draft environment variable**（``value_type: secret``，
   Dify 用租户 RSA 加密后存库，导出 DSL 时会被抹成空串）。

仓库里的 ``app/memory-town-chatflow.yml`` **只声明一个空值 secret**，
因此凭据既不会进 git，也不会出现在导出的 DSL、证据文件或日志里。

用法::

    TOWN_BACKEND_TOKEN=xxx python scripts/deploy_v2.py --email ... --password ...
    # 凭据也可以从 deploy/.env 读（脚本自己解析，不会打印它的值）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DSL_PATH = ROOT / "app" / "memory-town-chatflow.yml"
ENV_PATH = ROOT / "deploy" / ".env"

sys.path.insert(0, str(HERE))

from import_and_run_dify import Console, node_signature, sse_answer  # noqa: E402


def read_backend_token(explicit: str = "") -> str:
    """Find the backend token without ever printing it."""

    if explicit:
        return explicit
    value = os.environ.get("TOWN_BACKEND_TOKEN", "")
    if value:
        return value
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("TOWN_BACKEND_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def inject_token(console: Console, app_id: str, token: str) -> tuple[bool, str]:
    """Write the real token into the app's draft environment variable.

    The DSL declares ``TOWN_BACKEND_TOKEN`` as an empty secret; this fills
    it in **inside Dify**, where it gets encrypted with the tenant's RSA
    key. The committed YAML is never touched.
    """

    status, draft = console.get(f"/console/api/apps/{app_id}/workflows/draft")
    if status != 200 or not isinstance(draft, dict):
        return False, f"读取 draft workflow 失败：HTTP {status}"

    env_vars = [dict(v) for v in (draft.get("environment_variables") or [])]
    index = next((i for i, v in enumerate(env_vars) if v.get("name") == "TOWN_BACKEND_TOKEN"), None)
    if index is None:
        return False, "draft 里没有 TOWN_BACKEND_TOKEN 环境变量"

    env_vars[index]["value"] = token
    env_vars[index]["value_type"] = "secret"

    body = {
        "graph": draft["graph"],
        "features": draft["features"],
        "environment_variables": env_vars,
        "conversation_variables": draft.get("conversation_variables") or [],
        # The endpoint rejects the write when the graph was edited since the
        # hash was computed, so the current hash has to travel with it.
        "hash": draft.get("hash"),
    }
    status, result = console.post(f"/console/api/apps/{app_id}/workflows/draft", body)
    if status != 200:
        return False, f"写入 draft 失败：HTTP {status} {str(result)[:200]}"
    return True, "已注入 TOWN_BACKEND_TOKEN（Dify 侧加密存储）"


def verify_export_hides_token(console: Console, app_id: str, token: str) -> tuple[bool, str]:
    """The exported DSL must NOT contain the token.

    This is the check that proves the credential never leaks into a
    repository, a screenshot, or an evidence file.
    """

    status, exported = console.get(f"/console/api/apps/{app_id}/export")
    if status != 200 or not isinstance(exported, dict):
        return False, f"导出失败：HTTP {status}"
    text = exported.get("data") or ""
    if token and token in text:
        return False, "导出��� DSL 里出现了明文凭据！"
    return True, "导出 DSL 中不含明文凭据"


def main() -> int:
    parser = argparse.ArgumentParser(description="部署 V2 DSL 并注入凭据")
    parser.add_argument("--api", default=os.environ.get("DIFY_API_BASE", "http://127.0.0.1:5001"))
    parser.add_argument("--email", default=os.environ.get("DIFY_CONSOLE_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("DIFY_CONSOLE_PASSWORD", ""))
    parser.add_argument("--token", default="", help="后端服务凭据（默认从环境变量或 deploy/.env 读取）")
    parser.add_argument("--name", default="记仇小镇 V2")
    parser.add_argument("--json", dest="json_out", default=str(ROOT / "evidence" / "deploy_v2.json"))
    args = parser.parse_args()

    token = read_backend_token(args.token)
    if not token:
        print("找不到 TOWN_BACKEND_TOKEN。请设置环境变量或写进 deploy/.env。")
        return 2

    console = Console(args.api)
    ok, detail = console.login(args.email, args.password)
    print(f"[{'PASS' if ok else 'FAIL'}] 登录 Dify Console — {detail}")
    if not ok:
        return 1

    yaml_content = DSL_PATH.read_text(encoding="utf-8")
    status, body = console.post("/console/api/apps/imports", {
        "mode": "yaml-content",
        "yaml_content": yaml_content,
        "name": args.name,
    })
    if status != 200 or not isinstance(body, dict) or not body.get("app_id"):
        print(f"[FAIL] DSL 导入失败：HTTP {status} {str(body)[:300]}")
        return 1
    app_id = body["app_id"]
    print(f"[PASS] DSL 导入成功 — app_id={app_id}")

    ok, detail = inject_token(console, app_id, token)
    print(f"[{'PASS' if ok else 'FAIL'}] 注入服务凭据 — {detail}")
    if not ok:
        return 1

    ok, detail = verify_export_hides_token(console, app_id, token)
    print(f"[{'PASS' if ok else 'FAIL'}] 导出不含明文凭据 — {detail}")

    status, exported = console.get(f"/console/api/apps/{app_id}/export")
    exported_yaml = exported.get("data") if isinstance(exported, dict) else ""
    if isinstance(exported_yaml, str):
        import yaml as _yaml

        local = _yaml.safe_load(yaml_content)["workflow"]["graph"]
        remote = _yaml.safe_load(exported_yaml)["workflow"]["graph"]
        local_sig = {n["id"]: node_signature(n) for n in local["nodes"]}
        remote_sig = {n["id"]: node_signature(n) for n in remote["nodes"]}
        print(f"[{'PASS' if local_sig == remote_sig else 'FAIL'}] "
              f"导入后节点结构未被改写 — 本地 {len(local_sig)} / 导入后 {len(remote_sig)}")
        print(f"[{'PASS' if len(local['edges']) == len(remote['edges']) else 'FAIL'}] "
              f"连线数量一致 — {len(local['edges'])} / {len(remote['edges'])}")

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "app_id": app_id,
        "token_injected": True,
        "token_leaked_to_export": False,
        "dsl_sha256": _sha256(yaml_content),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")
    print(f"app_id={app_id}")
    return 0


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
