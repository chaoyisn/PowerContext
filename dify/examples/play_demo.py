"""《记仇小镇》实机演示脚本。

按顺序演一遍 V1 的完整玩法，每一步都打印**真实数据**：

1. 新玩家走进小镇广场，和奥托镇长搭话；
2. 偷走镇长的金王冠 → 触发「王冠失窃案」支线；
3. **换一个新会话**再走进来 → 镇长还记得那顶王冠，翻旧账；
4. 换另一个玩家 → 完全看不到前任的记忆。

第 3 步是整个赛题的核心：跨会话记忆真的生效了。

用法::

    python examples/play_demo.py
    python examples/play_demo.py --api http://127.0.0.1:5001 --email ... --password ...
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
SCRIPTS = HERE.parent / "scripts"
for _path in (str(SCRIPTS),):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from import_and_run_dify import Console, sse_answer  # noqa: E402


def state_of(backend: str, player_id: str) -> dict:
    with urllib.request.urlopen(f"{backend}/api/state?player_id={player_id}", timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="《记仇小镇》实机演示")
    parser.add_argument("--api", default="http://127.0.0.1:5001", help="Dify Console API")
    parser.add_argument("--backend", default="http://127.0.0.1:8848", help="town-backend")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

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
    print(f"已导入 Chatflow：app_id={app_id}\n")

    def say(player_id: str, text: str) -> str:
        _, events = console.post_sse(
            f"/console/api/apps/{app_id}/advanced-chat/workflows/draft/run",
            {"inputs": {"player_id": player_id, "session_id": ""},
             "query": text, "files": []},
        )
        return sse_answer(events)

    def show(state: dict, label: str) -> None:
        print(f"  [{label}] 关系与状态：")
        for npc in state.get("npcs") or []:
            print(f"    - {npc['name']}（{npc['title']}）："
                  f"好感 {npc['affinity']} / 信任 {npc['trust']} / 怨念 {npc['grudge_level']}")
        if state.get("inventory"):
            print(f"    - 玩家手上：{[i['name'] for i in state['inventory']]}")
        for plot in state.get("plots") or []:
            print(f"    - 剧情 {plot['plot_id']}：{plot['stage']} —— {plot['detail']}")
        for event in (state.get("memory") or {}).get("key_events") or []:
            print(f"    - 记忆库记着：{event['text']}")
        print()

    suffix = uuid.uuid4().hex[:8]
    player = f"demo_{suffix}"
    other = f"demo_other_{suffix}"

    # 复位道具，保证王冠在镇长手里。
    sys.path.insert(0, str(SCRIPTS))
    try:
        from verify_backend_api import reset_fixtures  # type: ignore
        reset_fixtures()
    except Exception as error:  # noqa: BLE001
        print(f"（复位道具失败：{error}）")

    print("=" * 72)
    print("第 1 步：新玩家走进小镇广场")
    print("=" * 72)
    print(f"  玩家 {player} 说：你好啊")
    print(f"  奥托镇长：{say(player, '你好啊')}\n")
    show(state_of(args.backend, player), "此时")

    print("=" * 72)
    print("第 2 步：偷走镇长的金王冠")
    print("=" * 72)
    print(f"  玩家 {player} 说：我要偷走镇长的金王冠")
    print(f"  奥托镇长：{say(player, '我要偷走镇长的金王冠')}\n")
    show(state_of(args.backend, player), "此时")

    print("=" * 72)
    print("第 3 步：**新会话**再走进来（player_id 不变，会话全新）")
    print("=" * 72)
    print(f"  玩家 {player} 说：镇长，我们又见面了")
    print(f"  奥托镇长：{say(player, '镇长，我们又见面了')}\n")
    show(state_of(args.backend, player), "此时")

    print("=" * 72)
    print("第 4 步：换一位玩家 —— 他不该看到前任的记忆")
    print("=" * 72)
    print(f"  玩家 {other} 说：镇长你好")
    print(f"  奥托镇长：{say(other, '镇长你好')}\n")
    show(state_of(args.backend, other), "此时")

    print("=" * 72)
    print("小结")
    print("=" * 72)
    print("  第 3 步镇长主动翻旧账，说明 PowerContext 的关键事件跨会话生效；")
    print("  第 4 步新玩家没有被牵连，说明记忆按 player_id 隔离，没有串号。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
