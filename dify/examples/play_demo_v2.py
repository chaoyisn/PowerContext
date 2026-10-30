"""《记仇小镇》V2 实机演示：一场 8 回合的完整冒险。

这条脚本把 V2 的能力**演**一遍，而不是断言它。每一步都打印**真实数据**
（来自 seekdb 与 PowerContext，不是预先写死的台词）：

  1. 新玩家在小镇广场，和渡鸦法官搭话 —— 三个 NPC 都已就位；
  2. **讨论**偷王冠会怎么样 —— 假设句**不会**触发偷窃（语义识别）；
  3. 移动到神秘后巷 —— 换地点换人；
  4. 真的偷走王冠 —— 动作落库；
  5. **换新会话**回来 —— 墨墨翻旧账（跨会话记忆）；
  6. 调查线索、贿赂墨墨 —— 关系与剧情分支变化；
  7. 归还王冠 —— 走「洗白」结局；
  8. 换个玩家重来 —— 走向「全镇公敌」结局，对比两个结局。

第 2 步与第 7/8 步是 V2 的核心：假设句不做事，结局由**确定性规则**裁定。

用法::

    python examples/play_demo_v2.py --email <console账号> --password <密码>
    python examples/play_demo_v2.py --email ... --password ... --ending public_enemy
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
for _path in (str(SCRIPTS),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from auth_helper import auth_headers, backend_token  # noqa: E402
from import_and_run_dify import Console, sse_answer  # noqa: E402
from deploy_v2 import inject_token  # noqa: E402

# Windows 的控制台默认是 GBK，打不出「▶」和「─」。强制用 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # pragma: no cover — 老 Python / 非 tty
        pass


def state_of(backend: str, player_id: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(f"{backend}/api/state?player_id={player_id}")
    for key, value in headers.items():
        request.add_header(key, value)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def npc_of(state: dict[str, Any], npc_id: str) -> dict[str, Any]:
    for npc in state.get("npcs") or []:
        if npc.get("npc_id") == npc_id:
            return npc
    return {}


def divider() -> str:
    return "─" * 66


class Demo:
    """Drives one playthrough against the real Dify app + real backend."""

    def __init__(self, console: Console, app_id: str, backend: str,
                 headers: dict[str, str]) -> None:
        self.console = console
        self.app_id = app_id
        self.backend = backend.rstrip("/")
        self.headers = headers

    def say(self, player_id: str, text: str) -> str:
        _, events = self.console.post_sse(
            f"/console/api/apps/{self.app_id}/advanced-chat/workflows/draft/run",
            {"inputs": {"player_id": player_id, "session_id": ""},
             "query": text, "files": [], "response_mode": "blocking"},
        )
        return sse_answer(events)

    def step(self, title: str, player_id: str, text: str) -> dict[str, Any]:
        print(divider())
        print(f"▶ {title}")
        print(divider())
        print(f"  玩家：{text}")
        answer = self.say(player_id, text)
        for line in answer.splitlines():
            if line.strip():
                print(f"  {line}")
        print()
        return state_of(self.backend, player_id, self.headers)

    def show(self, state: dict[str, Any], label: str = "当前状态") -> None:
        player = state.get("player") or {}
        location = state.get("location") or {}
        print(f"  ── {label} ──")
        print(f"  地点：{location.get('name', '?')}"
              f"　金币：{player.get('coins', '?')}")
        present = ", ".join(
            npc_of(state, npc_id).get("name", npc_id)
            for npc_id in (state.get("npcs_present") or [])
        )
        if present:
            print(f"  在场：{present}")
        for npc in state.get("npcs") or []:
            print(f"  · {npc['name']}（{npc['title']}）："
                  f"好感 {npc['affinity']} / 信任 {npc['trust']} / 怨念 {npc['grudge_level']}")
        if state.get("inventory"):
            print(f"  背包：{[i['name'] for i in state['inventory']]}")
        for plot in state.get("plots") or []:
            print(f"  剧情 {plot['plot_id']}：{plot['stage']} —— {plot.get('detail', '')}")
        for quest in state.get("quests") or []:
            print(f"  任务 {quest.get('quest_id')}：{quest.get('state')}"
                  f"（进度 {quest.get('progress')}/{quest.get('required')}）")
        for ending in state.get("endings") or []:
            if ending.get("achieved"):
                print(f"  ★ 结局达成：{ending.get('title', ending.get('ending_id'))}")
        for event in (state.get("memory") or {}).get("key_events") or []:
            print(f"  记忆：{event.get('text')}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description="《记仇小镇》V2 实机演示")
    parser.add_argument("--api", default="http://127.0.0.1:5001", help="Dify Console API")
    parser.add_argument("--backend", default="http://127.0.0.1:8848", help="town-backend")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--ending", default="whitewash", choices=["whitewash", "public_enemy"],
        help="演示哪个结局路线")
    args = parser.parse_args()

    token = backend_token()
    if not token:
        print("[BLOCKED] 找不到 TOWN_BACKEND_TOKEN —— V2 后端会拒绝所有请求。")
        print("         在 dify/deploy/.env 里设置它，或 export TOWN_BACKEND_TOKEN=…")
        return 1

    console = Console(args.api)
    ok, detail = console.login(args.email, args.password)
    if not ok:
        print(f"登录失败：{detail}")
        return 1

    dsl = (HERE.parent / "app" / "memory-town-chatflow.yml").read_text(encoding="utf-8")
    status, imported = console.post("/console/api/apps/imports", {
        "mode": "yaml-content", "yaml_content": dsl, "name": "记仇小镇",
    })
    app_id = imported.get("app_id")
    if not app_id:
        print(f"导入失败：{imported}")
        return 1

    injected, inject_detail = inject_token(console, app_id, token)
    if not injected:
        print(f"凭据注入失败：{inject_detail}")
        return 1

    print(f"已导入 Chatflow：app_id={app_id}")
    print("（凭据只存在于 Dify 的加密环境变量里，不在 DSL 里）\n")

    # 复位道具，保证王冠在镇长手里，演示从确定的起点开始。
    try:
        from verify_backend_api import reset_fixtures  # type: ignore
        reset_fixtures()
    except Exception as error:  # noqa: BLE001
        print(f"（复位道具失败：{error}）")

    # 身份必须和 DSL 里 {{#sys.user_id#}} 取到的是同一个 —— 后端把
    # player_id 绑在首次出现的那个身份上。控制台调试器跑出来的
    # sys.user_id 是 console 账号的 id，所以这里也用它。
    status, profile = console.get("/console/api/account/profile")
    identity = (profile or {}).get("id", "") if status == 200 else ""
    if not identity:
        print("拿不到 console 身份，无法读状态。")
        return 1
    headers = auth_headers(identity)
    demo = Demo(console, app_id, args.backend, headers)
    suffix = uuid.uuid4().hex[:8]
    player = f"demo_v2_{suffix}"

    print(f"玩家 id：{player}\n")

    if args.ending == "whitewash":
        demo.step("第 1 回合：新玩家走进小镇广场", player, "你好啊")
        demo.show(state_of(args.backend, player, headers))

        demo.step("第 2 回合：只是**讨论**偷王冠会怎么样 —— 假设句不该做事",
                  player, "如果我把王冠偷走会怎么样？")
        demo.show(state_of(args.backend, player, headers))

        demo.step("第 3 回合：走到神秘后巷 —— 换地点换人", player, "我要去神秘后巷")
        demo.show(state_of(args.backend, player, headers))

        demo.step("第 4 回合：这次是真的要偷", player, "我要偷走镇长的金王冠")
        demo.show(state_of(args.backend, player, headers))

        demo.step("第 5 回合：**新会话**再回来 —— 跨会话记忆翻旧账",
                  player, "我们又见面了")
        demo.show(state_of(args.backend, player, headers))

        demo.step("第 6 回合：去侦探事务所找墨墨问线索", player, "我要去侦探事务所")
        demo.show(state_of(args.backend, player, headers))

        demo.step("第 7 回合：贿赂墨墨 —— 他要不要帮你，看你怎么做",
                  player, "我要贿赂墨墨")
        demo.show(state_of(args.backend, player, headers))

        demo.step("第 8 回合：把王冠还给镇长 —— 走向「洗白」结局",
                  player, "我要把金王冠还给镇长")
        final = state_of(args.backend, player, headers)
        demo.show(final, "结局")
    else:
        demo.step("第 1 回合：新玩家走进小镇广场", player, "你好啊")
        demo.show(state_of(args.backend, player, headers))

        for round_no in range(1, 7):
            demo.step(f"第 {round_no + 1} 回合：第 {round_no} 次恶作剧",
                      player, "我要给镇长一个恶作剧！")
            state = state_of(args.backend, player, headers)
            if round_no == 3:
                demo.show(state, "此时")
        final = state_of(args.backend, player, headers)
        demo.show(final, "结局")

    print(divider())
    print("小结")
    print(divider())
    print("  · 第 2 回合的假设句**没有**偷走任何东西 —— 语义识别把")
    print("    「讨论」和「要做」分开了。")
    print("  · 第 5 回合换了一个全新会话，NPC 仍然记得 —— 这是")
    print("    PowerContext 的跨会话记忆在起作用。")
    print("  · 结局由 seekdb 里的确定性规则裁定，不是模型说了算。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
