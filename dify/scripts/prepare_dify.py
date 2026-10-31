"""把一个**全新的 Dify** 准备到能跑《记仇小镇》的状态。

为什么需要这个脚本
--------------------

DSL 里两个 LLM 节点用的是 ``langgenius/anthropic/anthropic`` 插件的
``claude-sonnet-4-6``。但**插件本身不是仓库的一部分**：

* 插件代码装在 ``deploy/volumes/plugin_daemon/cwd/`` —— 这个目录
  已被 ``.gitignore`` 排除（运行时数据卷），所以新克隆的仓库里**没有**插件；
* 插件的 API Key / API URL 是 Dify 里的**provider 凭据**，存在
  Postgres，同样不在仓库里。

也就是说：``docker compose up`` 之后直接导入 DSL，节点会因为
"provider 未配置"而跑不起来。这两件事必须由部署者在自己的环境里
做一次 —— 本脚本就是把这两步做成**可重复执行**的命令。

它做四件事
------------

1. 确保 Anthropic 插件已安装（从 Dify 官方 marketplace 装）；
2. 配置 provider 凭据（API Key + API URL，指向 Anthropic 兼容端点）；
3. 确认 ``claude-sonnet-4-6`` 这个模型在插件的预置列表里（DSL 写死了它）；
4. 确认后端服务凭据 ``TOWN_BACKEND_TOKEN`` 可用。

已安装 / 已配置时**重复执行是安全的**（幂等）。

用法::

    python scripts/prepare_dify.py --email <账号> --password <密码>

    # 模型接入参数（默认值见下）
    ANTHROPIC_API_KEY=xxx \
    ANTHROPIC_API_BASE_URL=http://host.docker.internal:15721 \
    python scripts/prepare_dify.py --email ... --password ...

参数优先级：命令行 > 环境变量 > ``deploy/.env`` > 默认值。
**凭据的值永远不会被打印**，只会打印"有没有"。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from auth_helper import backend_token  # noqa: E402
from import_and_run_dify import Console  # noqa: E402

#: DSL 里两个 LLM 节点用的插件与模型名。
#: 改这里等于改 DSL，两边必须一致。
PLUGIN_ID = "langgenius/anthropic"
PROVIDER = "langgenius/anthropic/anthropic"
MODEL_NAME = "claude-sonnet-4-6"

#: 插件 marketplace 查询接口（Dify 官方）。
MARKETPLACE_BATCH_URL = "https://marketplace.dify.ai/api/v1/plugins/batch"

#: provider 凭据在这个名字下保存，便于识别与覆盖。
CREDENTIAL_NAME = "local-proxy"


def read_env_file() -> dict[str, str]:
    """Read ``deploy/.env`` (gitignored) as key=value pairs."""

    path = ROOT / "deploy" / ".env"
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_setting(name: str, explicit: str = "") -> str:
    """Command line beats environment beats deploy/.env."""

    if explicit:
        return explicit
    value = os.environ.get(name, "")
    if value:
        return value
    return read_env_file().get(name, "")


def fetch_marketplace_identifier(plugin_id: str) -> tuple[str, str]:
    """Ask the marketplace which package identifier to install.

    The identifier embeds a checksum, so it must come from the
    marketplace rather than being hard-coded here — a pinned version
    would stop working as soon as the marketplace publishes a new one.

    Returns ``(identifier, detail)``.
    """

    import urllib.request

    req = urllib.request.Request(
        MARKETPLACE_BATCH_URL,
        data=json.dumps({"plugin_ids": [plugin_id]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as error:  # noqa: BLE001 - report, do not crash
        return "", f"查询 marketplace 失败：{type(error).__name__}: {str(error)[:200]}"

    plugins = ((payload.get("data") or {}).get("plugins")) or []
    if not plugins:
        return "", f"marketplace 里找不到插件 {plugin_id}"
    identifier = plugins[0].get("latest_package_identifier") or ""
    if not identifier:
        return "", f"marketplace 返回的 {plugin_id} 没有 package identifier"
    return identifier, f"marketplace 最新版本 {plugins[0].get('latest_version')}"


def installed_plugins(console: Console) -> list[dict]:
    status, body = console.get("/console/api/workspaces/current/plugin/list?page=1&page_size=100")
    if status != 200 or not isinstance(body, dict):
        return []
    return body.get("plugins") or []


def ensure_plugin(console: Console) -> tuple[bool, str]:
    """Install the Anthropic plugin if it is not installed yet."""

    for plugin in installed_plugins(console):
        if plugin.get("plugin_id") == PLUGIN_ID:
            version = plugin.get("version") or "?"
            return True, f"插件已安装（{PLUGIN_ID} {version}）"

    identifier, detail = fetch_marketplace_identifier(PLUGIN_ID)
    if not identifier:
        return False, detail

    status, body = console.post(
        "/console/api/workspaces/current/plugin/install/marketplace",
        {"plugin_unique_identifiers": [identifier]},
    )
    if status != 200:
        return False, f"安装插件失败：HTTP {status} {str(body)[:250]}"

    # The daemon installs asynchronously; poll the list until it shows up.
    for _ in range(30):
        for plugin in installed_plugins(console):
            if plugin.get("plugin_id") == PLUGIN_ID:
                return True, f"插件已安装（{PLUGIN_ID} {plugin.get('version') or '?'}）"
        import time

        time.sleep(2)
    return False, f"插件安装请求已提交，但列表里仍看不到 {PLUGIN_ID}（{detail}）"


def ensure_provider_credential(console: Console, api_key: str, api_url: str) -> tuple[bool, str]:
    """Create the provider credential the LLM nodes need.

    The credential is what tells Dify *where* the Anthropic-compatible
    endpoint is and *with what key*. Without it the DSL's LLM nodes
    fail at runtime even though the plugin is installed.
    """

    if not api_key:
        return False, (
            "没有模型凭据：设置 ANTHROPIC_API_KEY，或写进 deploy/.env。"
            "（值不会被打印）"
        )

    status, body = console.get(
        f"/console/api/workspaces/current/model-providers/{PROVIDER}/credentials"
    )
    if status == 200 and isinstance(body, dict):
        current = (body.get("data") or body).get("credentials") or {}
        if current.get("anthropic_api_key"):
            return True, "provider 凭据已配置"

    status, body = console.post(
        f"/console/api/workspaces/current/model-providers/{PROVIDER}/credentials",
        {
            "name": CREDENTIAL_NAME,
            "credentials": {
                "anthropic_api_key": api_key,
                "anthropic_api_url": api_url,
                "enable_request_metadata": "disabled",
            },
        },
    )
    if status not in (200, 201):
        return False, f"配置 provider 凭据失败：HTTP {status} {str(body)[:250]}"
    return True, "provider 凭据已配置"


def check_model_available(console: Console) -> tuple[bool, str]:
    """Confirm the DSL's model name exists in the installed plugin."""

    status, body = console.get(f"/console/api/workspaces/current/model-providers/{PROVIDER}/models")
    if status != 200 or not isinstance(body, dict):
        return False, f"读取模型清单失败：HTTP {status}"
    models = body.get("data") or []
    names = [m.get("model") for m in models if isinstance(m, dict)]
    if MODEL_NAME in names:
        return True, f"模型 {MODEL_NAME} 可用（插件共 {len(names)} 个预置模型）"
    return False, (
        f"插件里没有 {MODEL_NAME}；可用模型：{', '.join(n for n in names if n) or '（空）'}。"
        f"DSL 里的模型名需要与之一致。"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 Dify：安装模型插件并配置 provider 凭据")
    parser.add_argument("--api", default=os.environ.get("DIFY_API_BASE", "http://127.0.0.1:5001"))
    parser.add_argument("--email", default=os.environ.get("DIFY_CONSOLE_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("DIFY_CONSOLE_PASSWORD", ""))
    parser.add_argument("--api-key", default="", help="Anthropic 兼容端点的 API Key")
    parser.add_argument("--api-url", default="", help="Anthropic 兼容端点的地址")
    parser.add_argument("--json", dest="json_out", default=str(ROOT / "evidence" / "prepare_dify.json"))
    args = parser.parse_args()

    api_key = resolve_setting("ANTHROPIC_API_KEY", args.api_key)
    api_url = resolve_setting(
        "ANTHROPIC_API_BASE_URL", args.api_url
    ) or "http://host.docker.internal:15721"

    results: list[dict] = []

    def report(name: str, passed: bool, detail: str) -> bool:
        results.append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name} — {detail}")
        return bool(passed)

    console = Console(args.api)
    ok, detail = console.login(args.email, args.password)
    if not report("登录 Dify Console", ok, detail):
        return 1

    ok, detail = ensure_plugin(console)
    if not report("Anthropic 模型插件", ok, detail):
        return 1

    ok, detail = ensure_provider_credential(console, api_key, api_url)
    if not report("Provider 凭据", ok, detail):
        return 1

    ok, detail = check_model_available(console)
    report("模型 " + MODEL_NAME, ok, detail)

    token = backend_token()
    report("后端服务凭据", bool(token),
           "TOWN_BACKEND_TOKEN 已设置" if token
           else "缺少 TOWN_BACKEND_TOKEN —— Dify 的 HTTP 节点会全部 401")

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "plugin_id": PLUGIN_ID,
        "provider": PROVIDER,
        "model": MODEL_NAME,
        "plugin_installed": True,
        "provider_credential_configured": bool(api_key),
        "backend_token_present": bool(token),
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")

    failed = [r for r in results if not r["passed"]]
    if failed:
        print(f"\n有 {len(failed)} 项未通过，导入 DSL 之前必须先解决。")
        return 1
    print("\nDify 已就绪，可以导入 DSL 了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
