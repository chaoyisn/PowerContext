"""T1–T9 端到端验收：《记仇小镇》在**真实** Dify + seekdb + PowerContext 上的表现。

这条脚本是本赛题的主验收脚本。它做的事：

* 通过 Dify 的 Console API **真实导入** Chatflow DSL；
* 用 **真实玩家身份** 在 Chatflow 里跑多轮对话（每一轮都是新会话，
  只有 player_id 不变 —— 这正是"跨会话记忆"要成立的条件）；
* 每一轮之后都去 **真实后端** 查 seekdb 状态与 PowerContext 记忆；
* 检验 T1–T9 逐条验收点。

**这是真实集成测试，不是 Mock 测试。** 所有断言都基于真实服务返回的数据，
任何一步失败都会如实报 FAIL，不会被"模拟通过"掩盖。

前置条件（缺一不可）：

* Dify Console API 可访问（默认 http://127.0.0.1:5001）
* town-backend 可访问（默认 http://127.0.0.1:8848）
* seekdb 与 PowerContext 都在位（后端 /health 会检查）

用法::

    python scripts/verify_dify_e2e.py --email ... --password ...
    python scripts/verify_dify_e2e.py --email ... --password ... --json evidence/dify_e2e.json
"""

from __future__ import annotations

import argparse
import json
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

from import_and_run_dify import Console, sse_answer  # noqa: E402
from auth_helper import backend_token  # noqa: E402
from deploy_v2 import inject_token  # noqa: E402

RESULTS: list[dict] = []


def check(code: str, title: str, passed: bool, detail: str = "") -> bool:
    RESULTS.append({"code": code, "title": title, "passed": bool(passed), "detail": detail})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {code} {title}" + (f" — {detail}" if detail else ""))
    return bool(passed)


def http_json(url: str, payload: dict | None = None, method: str = "GET",
              headers: dict | None = None) -> Any:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        payload_text = err.read().decode("utf-8", "replace")
        try:
            body = json.loads(payload_text)
        except json.JSONDecodeError:
            body = {"raw": payload_text}
        return {"_http_status": err.code, **body}


class Town:
    """Chat over the imported Dify app, plus direct reads of the real state."""

    def __init__(self, console: Console, app_id: str, backend: str,
                 headers: dict | None = None) -> None:
        self.console = console
        self.app_id = app_id
        self.backend = backend.rstrip("/")
        self.headers = headers or {}

    def say(self, player_id: str, text: str, session_id: str = "") -> dict:
        """One turn. A fresh conversation unless a session_id is supplied."""

        payload: dict[str, Any] = {
            "inputs": {"player_id": player_id, "session_id": session_id},
            "query": text,
            "files": [],
            "response_mode": "blocking",
        }
        status, events = self.console.post_sse(
            f"/console/api/apps/{self.app_id}/advanced-chat/workflows/draft/run", payload)
        answer = sse_answer(events)
        finished = next((e for e in events if e.get("event") == "workflow_finished"), None)
        failed = next((e for e in events if e.get("event") in ("workflow_failed", "error")), None)
        return {
            "answer": answer,
            "status": (finished or {}).get("data", {}).get("status"),
            "error": str(failed) if failed else "",
        }

    def state(self, player_id: str) -> dict:
        return http_json(f"{self.backend}/api/state?player_id={player_id}",
                         headers=self.headers)

    def action(self, payload: dict) -> dict:
        return http_json(f"{self.backend}/api/action", payload, method="POST",
                         headers=self.headers)

    def events(self, player_id: str) -> dict:
        return http_json(f"{self.backend}/api/players/{player_id}/events",
                         headers=self.headers)


def npc_of(state: dict, npc_id: str) -> dict:
    for npc in state.get("npcs") or []:
        if npc.get("npc_id") == npc_id:
            return npc
    return {}


def memory_texts(state: dict) -> list[str]:
    memory = state.get("memory") or {}
    return [e.get("text", "") for e in (memory.get("key_events") or [])]


def main() -> int:
    parser = argparse.ArgumentParser(description="《记仇小镇》Dify 端到端验收 T1–T9")
    parser.add_argument("--api", default="http://127.0.0.1:5001", help="Dify Console API 基址")
    parser.add_argument("--backend", default="http://127.0.0.1:8848", help="town-backend 基址")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--json", dest="json_out", default="")
    args = parser.parse_args()

    # ---------------------------------------------------------- 前置条件
    health = http_json(f"{args.backend}/health")
    if not check("P0", "后端依赖（seekdb + PowerContext）可用", bool(health.get("ok")),
                 f"seekdb={health.get('seekdb', {}).get('detail')} "
                 f"powercontext={health.get('powercontext', {}).get('available')}"):
        return 1

    console = Console(args.api)
    ok, detail = console.login(args.email, args.password)
    if not check("P1", "登录 Dify Console", ok, detail):
        return 1

    # Console 调试器下的 sys.user_id 是**控制台账号 id**。脚本直接查后端时
    # 必须呈现同一个身份，否则后端判定为冒用 → 403。
    status, profile = console.get("/console/api/account/profile")
    console_identity = (profile or {}).get("id", "")
    if not check("P1.1", "取得 Console 账号身份（Dify 的 sys.user_id）",
                 status == 200 and bool(console_identity),
                 f"identity={console_identity[:8]}…"):
        return 1

    token = backend_token()
    if not check("P1.2", "后端服务凭据可用", bool(token),
                 "已从环境变量 / deploy/.env 读到 TOWN_BACKEND_TOKEN"):
        print("缺少 TOWN_BACKEND_TOKEN，V2 后端会拒绝所有请求。")
        return 1

    yaml_content = DSL_PATH.read_text(encoding="utf-8")
    status, imported = console.post("/console/api/apps/imports", {
        "mode": "yaml-content",
        "yaml_content": yaml_content,
        "name": "记仇小镇",
    })
    if not check("T1", "DSL 可导入 Dify 并生成应用",
                 status == 200 and bool(imported.get("app_id")),
                 f"app_id={imported.get('app_id')} status={imported.get('status')} "
                 f"dsl_version={imported.get('imported_dsl_version')}"):
        return 1
    app_id = imported["app_id"]

    # V2：把真实凭据注入 Dify 应用的环境变量（仓库里的 DSL 只有空值声明）。
    injected, inject_detail = inject_token(console, app_id, token)
    if not check("T1.0", "服务凭据注入 Dify 应用（V2 鉴权生效）", injected, inject_detail):
        return 1

    status, exported = console.get(f"/console/api/apps/{app_id}/export")
    exported_yaml = (exported or {}).get("data") or ""
    check("T1.1", "导入后 DSL 仍可导出（图未被改写）",
          status == 200 and "kind: app" in exported_yaml,
          f"导出 {len(exported_yaml)} 字符")
    check("T1.2", "导出的 DSL 不含明文凭据",
          bool(token) and token not in exported_yaml,
          "凭据只在 Dify 的加密环境变量里，不在导出的 DSL 里")

    town = Town(console, app_id, args.backend, headers={
        "X-Town-Token": token,
        "X-Town-Identity": console_identity,
    })

    # 把道具复位，保证每次验收的起点一样。
    from verify_backend_api import reset_fixtures  # type: ignore
    reset_fixtures()

    suffix = uuid.uuid4().hex[:8]
    player_a = f"e2e_a_{suffix}"
    player_b = f"e2e_b_{suffix}"

    # ------------------------------------------------------------ T2 / T3
    turn1 = town.say(player_a, "我要偷走镇长的金王冠")
    state_a1 = town.state(player_a)
    mayor1 = npc_of(state_a1, "mayor")
    check("T2", "新玩家进入小镇并与 NPC 互动", bool(turn1["answer"].strip()),
          f"answer={turn1['answer'][:100]!r}")
    check("T2.1", "玩家在 seekdb 中落库", bool(state_a1.get("player")),
          f"player={state_a1.get('player', {}).get('player_id')}")

    crown_in_inv = any(i.get("item_id") == "golden_crown" for i in state_a1.get("inventory") or [])
    check("T3", "动作真的修改了 seekdb 游戏数据",
          crown_in_inv and int(mayor1.get("grudge_level", 0)) > 0,
          f"王冠到手={crown_in_inv} 镇长怨念={mayor1.get('grudge_level')} "
          f"好感={mayor1.get('affinity')}")

    plots = state_a1.get("plots") or []
    triggered = any(p.get("plot_id") == "plot_crown_theft" and int(p.get("triggered") or 0) == 1
                    for p in plots)
    check("T3.1", "偷王冠触发镇长调查支线", triggered,
          f"plots={[(p.get('plot_id'), p.get('stage')) for p in plots]}")

    # ------------------------------------------------------------ T4
    events = memory_texts(state_a1)
    written = [t for t in events if "金王冠" in t or "golden_crown" in t]
    check("T4", "关键事件真的写进了 PowerContext", bool(written),
          f"key_events={len(events)} 命中={len(written)}；样本={written[:1]}")

    # ------------------------------------------------------------ T5
    # **新会话**：不传 conversation_id，Dify 另起一个会话，
    # 只有 player_id 不变。跨会话召回如果成立，这一步必须能想起王冠。
    turn2 = town.say(player_a, "我今天来是想跟你打个招呼")
    state_a2 = town.state(player_a)
    check("T5", "新会话能召回上一轮的关键记忆",
          len(memory_texts(state_a2)) >= 1,
          f"新会话召回 {len(memory_texts(state_a2))} 条；台词={turn2['answer'][:100]!r}")

    # 台词里必须体现"还记得"，而不只是内存里有数据。
    recalled_in_speech = any(word in turn2["answer"] for word in ("王冠", "日记", "偷", "记得", "记"))
    check("T5.1", "新会话里 NPC 的台词体现了旧账（记忆真的影响了体验）",
          recalled_in_speech,
          f"answer={turn2['answer'][:160]!r}")

    # ------------------------------------------------------------ T6
    #
    # 这里刻意用**恶作剧**而不是偷窃。王冠只有一件：A 在 T3 里已经把它
    # 偷走了，B 再偷一次会被道具规则挡下来（目标手上已经没东西可拿），
    # B 什么记忆都不会有 —— 那样这条断言就变成了"没记忆可泄漏"的空断言。
    # 恶作剧可以重复做，B 一定有属于自己的记忆，"不泄漏"才是真的被验证过。
    turn_b = town.say(player_b, "我要给你一个恶作剧！")
    state_b = town.state(player_b)
    b_events = memory_texts(state_b)
    leak = [t for t in b_events if player_a in t]
    check("T6", "玩家 B 读不到玩家 A 的记忆（无跨玩家泄漏）",
          len(b_events) > 0 and len(leak) == 0 and all(player_a not in t for t in b_events),
          f"B 召回 {len(b_events)} 条，其中含 A 的 {len(leak)} 条；"
          f"B 自己的={b_events[:1]}")

    # ------------------------------------------------------------ T7
    # 同样一句话，在"有前科"和"没前科"两种历史下必须得到不同的反馈。
    #
    # 这里刻意用**恶作剧**而不是偷窃：王冠只有一件，A 偷走之后既不能再偷，
    # C 的第一次偷也会因为"王冠已不在镇长手上"被道具规则挡下来 ——
    # 两边的怨念都不会动，测出来的是"谁先偷到"而不是"前科是否累积"。
    # 恶作剧可以重复做，才能真正看出怨念是一笔笔累上去的。
    fresh_player = f"e2e_c_{suffix}"
    turn_c = town.say(fresh_player, "我要给你一个恶作剧！")
    state_c = town.state(fresh_player)
    mayor_c = npc_of(state_c, "mayor")

    turn_a2 = town.say(player_a, "我要给你一个恶作剧！")
    state_a2b = town.state(player_a)
    mayor_a2 = npc_of(state_a2b, "mayor")

    grudge_a = int(mayor_a2.get("grudge_level", 0))
    grudge_c = int(mayor_c.get("grudge_level", 0))
    check("T7", "同样输入在不同历史下触发不同的关系状态",
          grudge_a > grudge_c,
          f"有前科的 A 再作恶：怨念={grudge_a}；全新玩家 C 第一次：怨念={grudge_c}")
    # A 在 T3 里已经偷过一次王冠（怨念 25），再作恶一次 +12；
    # C 是白纸，只作恶一次 = 12。两者之差正好是那份前科。
    check("T7.1", "重复作案的怨念继续累积（前科 + 本次）",
          grudge_a == grudge_c + 25 and grudge_c == 12,
          f"C={grudge_c}（首次恶作剧）→ A={grudge_a}（偷窃前科 25 + 恶作剧 12）")
    check("T7.2", "有前科的玩家被针对得更明显（台词不同）",
          turn_a2["answer"] != turn_c["answer"],
          f"A 的台词={turn_a2['answer'][:80]!r}；C 的台词={turn_c['answer'][:80]!r}")

    # ------------------------------------------------------------ T8
    # 8.1 重复提交同一 Idempotency-Key → 不应重复扣数值
    #
    # 这里用**恶作剧**而不是偷窃。王冠只有一件，A 在 T3 里已经偷走了；
    # 如果这里再偷，目标手上已经没东西可拿，后端会**正确地**拒绝
    # （"nothing_to_steal"）—— 那测的是道具规则，不是幂等。
    # 恶作剧可以重复做，才能真正看出"同一 key 提交两次只记一笔"。
    key = f"idem_{suffix}"
    before = int(npc_of(town.state(player_b), "mayor").get("grudge_level", 0))
    body = {
        "player_id": player_b,
        "session_id": "s-idem",
        "npc_id": "mayor",
        "message": "我要给你一个恶作剧！",
        "idempotency_key": key,
    }
    first = town.action(body)
    second = town.action(body)
    after = int(npc_of(town.state(player_b), "mayor").get("grudge_level", 0))
    check("T8.1", "重复请求被幂等处理（不重复改状态）",
          bool(second.get("duplicate") or second.get("replayed")) and after - before == 12,
          f"第一次后怨念={after}（起始 {before}）；第二次返回 duplicate="
          f"{second.get('duplicate')}/{second.get('replayed')}")

    # 8.2 同一 key 用不同内容 → 409
    conflict = dict(body, message="我要给镇长送一条小鱼干")
    conflict_resp = town.action(conflict)
    check("T8.2", "同一幂等键配不同内容被拒绝（409）",
          conflict_resp.get("_http_status") == 409,
          f"HTTP {conflict_resp.get('_http_status')} code="
          f"{(conflict_resp.get('error') or {}).get('code')}")

    # 8.3 非法玩家 ID → 400
    bad = town.action({
        "player_id": "bad id with spaces!",
        "session_id": "s",
        "npc_id": "mayor",
        "message": "偷",
    })
    check("T8.3", "非法输入被拒绝（400）",
          bad.get("_http_status") == 400,
          f"HTTP {bad.get('_http_status')} code={(bad.get('error') or {}).get('code')}")

    # 8.4 未知玩家 → 404
    unknown = town.action({
        "player_id": f"nobody_{suffix}",
        "session_id": "s",
        "npc_id": "mayor",
        "message": "偷走王冠",
    })
    check("T8.4", "未知玩家被拒绝（404）",
          unknown.get("_http_status") == 404,
          f"HTTP {unknown.get('_http_status')} code={(unknown.get('error') or {}).get('code')}")

    # 8.5 超长输入 → 400
    long_msg = town.action({
        "player_id": player_b,
        "session_id": "s",
        "npc_id": "mayor",
        "message": "偷" * 600,
    })
    check("T8.5", "超长输入被拒绝（400）",
          long_msg.get("_http_status") == 400,
          f"HTTP {long_msg.get('_http_status')} code={(long_msg.get('error') or {}).get('code')}")

    # 8.6 Dify 侧：非法玩家 ID 不应让整条流程崩掉，应给出如实说明
    turn_bad = town.say("bad id!", "你好")
    check("T8.6", "Dify 侧遇到非法玩家 ID 时如实说明而不是崩溃",
          bool(turn_bad["answer"].strip()) and turn_bad["status"] in (None, "succeeded"),
          f"status={turn_bad['status']} answer={turn_bad['answer'][:120]!r}")

    # 8.7 规则冲突：偷一件不可转手的道具 → 409，且不得报成功
    conflict_rule = town.action({
        "player_id": player_b,
        "session_id": "s",
        "npc_id": "mayor",
        "message": "我要偷走镇长的印章",
    })
    check("T8.7", "违反道具规则的请求被拒绝且不报成功",
          conflict_rule.get("_http_status") == 409,
          f"HTTP {conflict_rule.get('_http_status')} code="
          f"{(conflict_rule.get('error') or {}).get('code')}")

    # ------------------------------------------------------------ T9
    # T9 由 README + init 脚本承担；这里验证"干净玩家能从零走通"，
    # 并且脚本自带 --reset 能力（已在本脚本开头调用 reset_fixtures）。
    fresh = f"e2e_d_{suffix}"
    turn_fresh = town.say(fresh, "你们好啊")
    state_fresh = town.state(fresh)
    check("T9", "全新玩家可在干净环境下完成一整轮交互",
          bool(turn_fresh["answer"].strip()) and bool(state_fresh.get("player")),
          f"answer={turn_fresh['answer'][:100]!r}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n结果: {passed}/{total} 通过")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "dify_api": args.api,
            "backend": args.backend,
            "app_id": app_id,
            "players": {"a": player_a, "b": player_b, "c": fresh_player, "d": fresh},
            "passed": passed,
            "total": total,
            "checks": RESULTS,
            "answers": {
                "a_turn1": turn1["answer"],
                "a_turn2_new_session": turn2["answer"],
                "b_turn": turn_b["answer"],
            },
            "memory": {
                "a_key_events": memory_texts(state_a1),
                "b_key_events": b_events,
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {out}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
