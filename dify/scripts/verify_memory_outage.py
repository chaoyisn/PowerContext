"""V2-T12：PowerContext **真的**不可用时，状态与记忆的一致性。

V2 验收里的 V2-T12 只能检查补偿接口的形状 —— 那证明不了什么。
这条脚本做的是**真事**：另起一个后端进程，把它的 PowerContext 地址
指向一个**不可达**的端口（而不是把共享的 PowerContext 关掉 ——
那是别的赛题也在用的服务），然后：

1. 玩一次会改变状态的动作（偷王冠）；
2. 确认 **seekdb 的状态真的落库了**（王冠到手、怨念 +25）；
3. 确认 **记忆写失败了，而且如实报告失败**（没有把失败说成成功）；
4. 确认 outbox 里**留了一条 pending 的补偿任务**；
5. 恢复 PowerContext（把地址换回真的那个），跑补偿流程；
6. 确认记忆**补写成功**，而且**没有写出重复记忆**。

第 6 步的"不重复"是关键：同一个事件只能有一条记忆，
否则补偿流程每跑一次就多一条垃圾记忆。

这条脚本用**独立端口**起自己的后端实例，不碰 docker 里的那个，
也不碰 PowerContext 服务本身 —— 所以它不会影响别的赛题。

用法::

    python scripts/verify_memory_outage.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from auth_helper import auth_headers, backend_token  # noqa: E402

RESULTS: list[dict[str, Any]] = []


def check(code: str, title: str, passed: bool, detail: str = "") -> bool:
    RESULTS.append({"code": code, "title": title, "passed": bool(passed), "detail": detail})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {code} {title}" + (f" — {detail}" if detail else ""))
    return bool(passed)


class LocalBackend:
    """A second backend instance, on its own port, with its own PowerContext URL.

    端口用 8849（默认 8848 是 docker 里那个共享实例），PowerContext 地址
    指向 127.0.0.1:9 —— 一个保证连不上的端口（discard）。
    """

    def __init__(self, port: int, powercontext_url: str) -> None:
        self.port = port
        self.powercontext_url = powercontext_url
        self.thread: threading.Thread | None = None
        self.app = None

    def start(self) -> None:
        from town_backend.api import create_app
        from town_backend.config import Settings

        settings = Settings()
        settings.powercontext_url = self.powercontext_url
        settings.powercontext_timeout = 3.0
        # 凭据与身份沿用真实配置，测试的是记忆链路，不是鉴权。
        settings.backend_token = backend_token()
        settings.allow_anonymous = False
        self.app = create_app(settings)
        self.thread = threading.Thread(
            target=lambda: self.app.run(
                host="127.0.0.1", port=self.port, threaded=True,
                use_reloader=False,
            ),
            daemon=True,
        )
        self.thread.start()
        self._wait_ready()

    def _wait_ready(self) -> None:
        """Wait until the local instance answers at all.

        注意：``/health`` 在 PowerContext 不可达时返回 **503**（这是
        后端故意的：记忆系统不可用时如实报告）。所以这里只要求
        "服务器在应答"，不要求它是 200。
        """

        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=3.0)
                return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.4)
        raise RuntimeError("本地后端实例没能在 20 秒内起来")

    def stop(self) -> None:
        if self.app is not None:
            # werkzeug 的 dev server 不太好优雅关掉；这里靠进程退出清理。
            pass


def _state(client: httpx.Client, player_id: str) -> dict[str, Any]:
    response = client.get("/api/state", params={"player_id": player_id})
    return response.json() if response.status_code == 200 else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="PowerContext 真的不可用时的一致性验证")
    parser.add_argument("--port", type=int, default=8849)
    parser.add_argument("--seekdb-host", default="127.0.0.1")
    parser.add_argument("--seekdb-port", type=int, default=2881)
    parser.add_argument("--json", dest="json_out",
                        default=str(ROOT / "evidence" / "memory_outage.json"))
    args = parser.parse_args()

    token = backend_token()
    if not token:
        print("[BLOCKED] 找不到 TOWN_BACKEND_TOKEN")
        return 1

    os.environ.setdefault("TOWN_SEEKDB_HOST", args.seekdb_host)
    os.environ.setdefault("TOWN_SEEKDB_PORT", str(args.seekdb_port))

    suffix = uuid.uuid4().hex[:8]
    player = f"outage_{suffix}"

    # 王冠只有**一件**，前面的验收跑过之后它已经不在镇长手上了。
    # 不复位的话，这次偷窃会被道具规则挡下来（409），测的就不是
    # 记忆链路而是道具规则了。
    from verify_backend_api import reset_fixtures
    try:
        reset_fixtures()
    except Exception as error:  # noqa: BLE001
        print(f"[WARN] 复位夹具失败: {type(error).__name__}: {error}")

    # --- 起一个"PowerContext 不可达"的后端实例 --------------------------
    dead = LocalBackend(args.port, "http://127.0.0.1:9")
    dead.start()

    headers = {"X-Town-Token": token, "X-Town-Identity": "outage_suite"}
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{args.port}", timeout=30.0, headers=headers)

    try:
        health = client.get("/health").json()
        check("T12.0", "本地实例起来了，且确实看不到 PowerContext",
              health.get("powercontext", {}).get("available") is False,
              f"powercontext={health.get('powercontext', {}).get('available')} "
              f"（地址指向不可达端口）")

        client.post("/api/player/register",
                    json={"player_id": player, "session_id": "s1"})

        # --- 1) 状态变更：偷王冠 ------------------------------------------
        response = client.post("/api/action", json={
            "player_id": player, "session_id": "s1", "npc_id": "mayor",
            "message": "我要偷走镇长的金王冠",
            "model_intent": {
                "action_type": "steal", "target_npc": "mayor",
                "target_item": "golden_crown", "intent_confidence": 0.9,
                "is_committed_action": True,
            },
        })
        body = response.json()
        action = body.get("action") or {}
        state = _state(client, player)
        held = [i.get("item_id") for i in state.get("inventory") or []]
        mayor = next((n for n in state.get("npcs") or []
                      if n.get("npc_id") == "mayor"), {})

        check("T12.1", "PowerContext 不可用时，游戏状态仍然照常落库",
              response.status_code == 200 and "golden_crown" in held
              and int(mayor.get("grudge_level", 0)) >= 25,
              f"HTTP={response.status_code} 王冠到手={'golden_crown' in held} "
              f"镇长怨念={mayor.get('grudge_level')}")

        # --- 2) 记忆写失败，且**如实**报告 -------------------------------
        check("T12.2", "记忆写失败被如实报告，没有伪装成成功",
              body.get("memory_written") is False
              and bool(body.get("memory_error")),
              f"memory_written={body.get('memory_written')} "
              f"memory_error={str(body.get('memory_error'))[:90]!r}")

        # --- 3) outbox 里留下了一条待补偿的任务 --------------------------
        # 用后端自己的计数接口看状态分布。
        #
        # 待补偿的行可能处于两种状态：
        #   pending —— 刚入队，还没试过；
        #   failed  —— 试过但失败了（失败**不等于**作废，行还留着等待重试）。
        # 所以断言的是"还有多少行没交付"，而不是某一个具体状态名。
        retry = client.post("/api/memory/retry", json={"limit": 100}).json()
        outbox = retry.get("outbox") or {}
        outstanding = int(outbox.get("pending", 0)) + int(outbox.get("failed", 0))
        check("T12.3", "outbox 里留下了可补偿的未交付任务",
              outstanding >= 1,
              f"outbox={outbox}；本次补偿尝试 {retry.get('attempted')} 条，"
              f"成功 {retry.get('succeeded')} 条")

        # 补偿在 PowerContext 不可达时**必须失败**，而且不能被吞掉。
        check("T12.4", "PowerContext 不可达时补偿如实失败（不谎报成功）",
              int(retry.get("succeeded", 0)) == 0
              and any(not r.get("ok") for r in retry.get("results") or []),
              f"results={[(r.get('ok'), str(r.get('error'))[:60]) for r in (retry.get('results') or [])[:3]]}")

        # --- 4) 状态与事件在故障期间仍然一致 ------------------------------
        events = client.get(f"/api/players/{player}/events").json().get("events") or []
        steal_events = [e for e in events if e.get("action_type") == "steal"]
        check("T12.5", "故障期间事件流与状态一致（事件在、道具在）",
              len(steal_events) == 1 and "golden_crown" in held,
              f"steal 事件 {len(steal_events)} 条；背包={held}")
    finally:
        client.close()

    # --- 5) 恢复 PowerContext 后补偿，记忆要补上且不重复 -----------------
    alive = LocalBackend(args.port + 1, "http://127.0.0.1:8800")
    alive.start()
    client2 = httpx.Client(
        base_url=f"http://127.0.0.1:{args.port + 1}", timeout=30.0, headers=headers)
    try:
        health2 = client2.get("/health").json()
        check("T12.6", "恢复后的实例能连上 PowerContext",
              health2.get("powercontext", {}).get("available") is True,
              f"powercontext={health2.get('powercontext', {}).get('available')}")

        # 补偿前先记下这个玩家已有的记忆条数。
        before = len((_state(client2, player).get("memory") or {}).get("key_events") or [])
        retry2 = client2.post("/api/memory/retry", json={"limit": 100}).json()
        check("T12.7", "补偿流程把欠下的记忆补写成功",
              int(retry2.get("succeeded", 0)) >= 1,
              f"attempted={retry2.get('attempted')} succeeded={retry2.get('succeeded')} "
              f"outbox={retry2.get('outbox')}")

        after = len((_state(client2, player).get("memory") or {}).get("key_events") or [])
        check("T12.8", "补偿之后记忆里确实能看到这次事件",
              after > before,
              f"关键事件 {before} → {after} 条")

        # 再跑两次补偿 —— 幂等，不能写出重复记忆。
        client2.post("/api/memory/retry", json={"limit": 100})
        client2.post("/api/memory/retry", json={"limit": 100})
        again = len((_state(client2, player).get("memory") or {}).get("key_events") or [])
        texts = [e.get("text", "") for e in
                 ((_state(client2, player).get("memory") or {}).get("key_events") or [])]
        crown_notes = [t for t in texts if "golden_crown" in t or "金王冠" in t]
        check("T12.9", "重复补偿不会写出重复记忆",
              again == after and len(crown_notes) <= 1,
              f"记忆条数 {after} → {again}；涉及王冠的记忆 {len(crown_notes)} 条")
    finally:
        client2.close()

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n结果: {passed}/{total} 通过")

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "passed": passed, "total": total, "checks": RESULTS,
        "note": "PowerContext 用一个不可达端口模拟故障，未关闭共享服务",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
