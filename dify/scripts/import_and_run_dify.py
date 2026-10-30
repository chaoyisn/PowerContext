"""T1: 把 Chatflow DSL 真实导入 Dify，并跑通一次对话。

这条脚本做两件事：

1.  ``POST /console/api/apps/imports``（mode=yaml-content）导入 DSL，
    拿到 app_id；然后 ``GET /console/api/apps/<id>/export`` 把导入后的
    DSL 导出来，与本地文件逐节点比对，确认导入没有悄悄改写图。
2.  ``POST /console/api/apps/<id>/advanced-chat/workflows/draft/run``
    以真实玩家身份跑一轮对话，拿到 NPC 台词。

真实集成脚本，不含 Mock：需要 Dify API 真正可访问。

用法::

    python scripts/import_and_run_dify.py
    python scripts/import_and_run_dify.py --json evidence/dify_run.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent / "app"
DSL_PATH = APP_DIR / "memory-town-chatflow.yml"
BACKEND_ROOT = HERE.parent / "backend"
for _path in (str(BACKEND_ROOT), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

DEFAULT_API = os.environ.get("DIFY_API_BASE", "http://127.0.0.1:5001")
DEFAULT_EMAIL = os.environ.get("DIFY_CONSOLE_EMAIL", "")
DEFAULT_PASSWORD = os.environ.get("DIFY_CONSOLE_PASSWORD", "")

RESULTS: list[dict] = []


def check(code: str, title: str, passed: bool, detail: str = "") -> bool:
    RESULTS.append({"code": code, "title": title, "passed": bool(passed), "detail": detail})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {code} {title}" + (f" — {detail}" if detail else ""))
    return bool(passed)


class Console:
    """A minimal console-API client using Dify's bearer-token console session."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str = ""

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        raw: bytes | None = None,
        content_type: str = "application/json",
    ) -> tuple[int, Any]:
        url = self.base + path
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", content_type)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = resp.read()
                text = payload.decode("utf-8", "replace")
                try:
                    return resp.status, json.loads(text)
                except json.JSONDecodeError:
                    return resp.status, text
        except urllib.error.HTTPError as err:
            payload = err.read().decode("utf-8", "replace")
            try:
                return err.code, json.loads(payload)
            except json.JSONDecodeError:
                return err.code, payload

    def login(self, email: str, password: str) -> tuple[bool, str]:
        status, body = self._request("POST", "/console/api/login", body={"email": email, "password": password})
        if status != 200:
            return False, f"HTTP {status}: {str(body)[:300]}"
        token = (body.get("data") or {}).get("access_token", "")
        if not token:
            return False, f"登录响应里没有 access_token: {str(body)[:300]}"
        self.token = token
        return True, "登录成功"

    def post(self, path: str, body: Any) -> tuple[int, Any]:
        return self._request("POST", path, body=body)

    def get(self, path: str) -> tuple[int, Any]:
        return self._request("GET", path)

    def post_sse(self, path: str, body: Any) -> tuple[int, list[dict]]:
        """POST and collect a text/event-stream response into parsed events."""

        url = self.base + path
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        events: list[dict] = []
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        events.append(json.loads(payload))
                    except json.JSONDecodeError:
                        events.append({"raw": payload})
        except urllib.error.HTTPError as err:
            payload = err.read().decode("utf-8", "replace")
            try:
                return err.code, [{"error": json.loads(payload)}]
            except json.JSONDecodeError:
                return err.code, [{"error": payload}]
        return 200, events


def sse_answer(events: list[dict]) -> str:
    """Pull the final answer out of a Dify SSE event stream."""

    chunks: list[str] = []
    for event in events:
        kind = event.get("event")
        if kind in ("message", "message_end"):
            answer = event.get("answer")
            if isinstance(answer, str):
                chunks.append(answer)
            elif isinstance(answer, dict):
                chunks.append(str(answer.get("text", "")))
        elif kind == "workflow_finished":
            outputs = event.get("data", {}).get("outputs") or {}
            if outputs.get("answer") and not chunks:
                chunks.append(str(outputs["answer"]))
    return "".join(chunks).strip()


def node_signature(node: dict) -> str:
    """A comparable fingerprint for one node: id, type and its declared outputs."""

    data = node.get("data", {})
    outputs = sorted((data.get("outputs") or {}).keys())
    return f"{node.get('id')}|{data.get('type')}|{','.join(outputs)}"


def main() -> int:
    parser = argparse.ArgumentParser(description="导入并运行《记仇小镇》Chatflow DSL")
    parser.add_argument("--api", default=DEFAULT_API, help="Dify console API 基址")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--player", default="", help="玩家ID（默认随机）")
    parser.add_argument("--query", default="我要偷走镇长的金王冠")
    parser.add_argument("--conversation-id", default="", help="复用已有会话；留空则新建会话")
    parser.add_argument("--dsl", default=str(DSL_PATH))
    parser.add_argument("--no-reset", action="store_true",
                        help="不重置道具（默认会把王冠放回镇长手里，保证可复现）")
    parser.add_argument("--json", dest="json_out", default="")
    args = parser.parse_args()

    dsl_path = Path(args.dsl)
    if not dsl_path.exists():
        print(f"找不到 DSL 文件：{dsl_path}")
        return 2

    console = Console(args.api)

    # ------------------------------------------------------------- T1.0
    ok, detail = console.login(args.email, args.password)
    if not check("T1.0", "登录 Dify Console", ok, detail):
        return 1

    yaml_content = dsl_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------- T1.1
    status, body = console.post("/console/api/apps/imports", {
        "mode": "yaml-content",
        "yaml_content": yaml_content,
        "name": "记仇小镇",
    })
    if status != 200 or not isinstance(body, dict) or not body.get("app_id"):
        check("T1.1", "DSL 导入成功", False, f"HTTP {status}: {str(body)[:400]}")
        return 1
    app_id = body["app_id"]
    check("T1.1", "DSL 导入成功", True,
          f"app_id={app_id} mode={body.get('app_mode')} status={body.get('status')} "
          f"dsl={body.get('imported_dsl_version')}")

    # ------------------------------------------------------------- T1.2
    status, exported = console.get(f"/console/api/apps/{app_id}/export")
    if status != 200 or not isinstance(exported, dict):
        check("T1.2", "导出导入后的 DSL", False, f"HTTP {status}")
    else:
        # /export 把 DSL 以 YAML 文本形式放在 data 里。
        exported_yaml = exported.get("data") or ""
        local_graph = _load_local_graph(yaml_content)
        remote_graph = _load_local_graph(exported_yaml) if isinstance(exported_yaml, str) else {}
        local_nodes = {n["id"]: node_signature(n) for n in local_graph.get("nodes", [])}
        remote_nodes = {n["id"]: node_signature(n) for n in remote_graph.get("nodes", [])}
        same = local_nodes == remote_nodes
        missing = sorted(set(local_nodes) - set(remote_nodes))
        changed = sorted(k for k in local_nodes if k in remote_nodes and local_nodes[k] != remote_nodes[k])
        check("T1.2", "导入后节点结构未被改写", same,
              f"本地 {len(local_nodes)} 节点 / 导入后 {len(remote_nodes)} 节点"
              + (f"；缺失={missing}" if missing else "")
              + (f"；被改写={changed}" if changed else ""))

        local_edges = len(local_graph.get("edges", []))
        remote_edges = len(remote_graph.get("edges", []))
        check("T1.3", "导入后连线数量一致", local_edges == remote_edges,
              f"本地 {local_edges} 条 / 导入后 {remote_edges} 条")

    # ------------------------------------------------------------- T1.4
    player_id = args.player or f"dify_{uuid.uuid4().hex[:8]}"

    # 上一轮测试可能已经把王冠偷走了（道具整行归玩家所有），
    # 主线剧情就再也触发不了。先把王冠放回镇长手里，保证可复现。
    if not args.no_reset:
        try:
            from verify_backend_api import reset_fixtures  # type: ignore
            reset_fixtures()
        except Exception as error:  # noqa: BLE001
            print(f"（重置道具失败，继续执行：{error}）")

    # 不传 conversation_id：Dify 会新建一个会话。跨会话召回由 player_id 承担，
    # 而不是依赖会话 ID 复用。
    payload: dict[str, Any] = {
        "inputs": {"player_id": player_id, "session_id": ""},
        "query": args.query,
        "files": [],
        "response_mode": "blocking",
    }
    if args.conversation_id:
        payload["conversation_id"] = args.conversation_id
    status, events = console.post_sse(
        f"/console/api/apps/{app_id}/advanced-chat/workflows/draft/run",
        payload,
    )
    answer = sse_answer(events)
    finished = next((e for e in events if e.get("event") == "workflow_finished"), None)
    failed = next((e for e in events if e.get("event") == "workflow_failed"), None)
    error = next((e for e in events if e.get("event") == "error"), None)

    if failed or error:
        check("T1.4", "运行 Chatflow", False,
              f"事件流报错：{str(failed or error)[:400]}")
        return 1

    check("T1.4", "运行 Chatflow 得到 NPC 台词", bool(answer),
          f"player={player_id} answer={answer[:140]!r}")
    check("T1.5", "运行状态为 succeeded",
          bool(finished) and finished.get("data", {}).get("status") == "succeeded",
          f"status={finished.get('data', {}).get('status') if finished else None}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n结果: {passed}/{total} 通过")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "dify_api": args.api,
            "app_id": app_id,
            "player_id": player_id,
            "query": args.query,
            "answer": answer,
            "run_status": finished.get("data", {}).get("status") if finished else None,
            "passed": passed,
            "total": total,
            "checks": RESULTS,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {out}")

    return 0 if passed == total else 1


def _load_local_graph(yaml_content: str) -> dict:
    """Parse a DSL YAML string into its workflow graph.

    PyYAML is preferred; if it is not installed we fall back to a regex scan
    that still recovers node ids, node types and edge counts, so the
    "import did not rewrite the graph" check keeps working.
    """

    try:
        import yaml  # type: ignore
        doc = yaml.safe_load(yaml_content) or {}
        return doc.get("workflow", {}).get("graph", {}) or {}
    except ImportError:
        nodes = []
        for match in re.finditer(
            r"^    - id: ([a-zA-Z0-9_]+)\n(?:.*\n)*?      type: (\w+)$",
            yaml_content,
            re.M,
        ):
            nodes.append({"id": match.group(1), "data": {"type": match.group(2)}})
        edges = re.findall(r"^    - id: (\S+)\n      source: (\S+)\n      sourceHandle: (\S+)\n"
                           r"      target: (\S+)\n      targetHandle: (\S+)$",
                           yaml_content, re.M)
        return {
            "nodes": nodes,
            "edges": [{"id": e[0]} for e in edges],
        }


if __name__ == "__main__":
    raise SystemExit(main())
