"""T4 / T5 / T6：PowerContext 关键事件记忆的跨会话闭环。

这条脚本是本赛题最关键的一条证据链，直接打真实的 PowerContext HTTP API
（默认 http://127.0.0.1:8800），验证：

M1  一次动作产生一条关键事件，并真的写进 PowerContext
M2  **新会话**（新的 MemoryStore 实例 + 新的 session_id）仍然能召回这条记忆
M3  玩家 B 读不到玩家 A 的记忆（Scope 隔离）
M4  玩家 C（从未触发过事件）召回为空，而不是报错
M5  写入走的是 scope binding，同一玩家多次写入落在同一个 scope
M6  记忆条目里带有正确的 kind（town-key-event）

**为什么用"新 MemoryStore 实例"？**  因为进程内的 scope 缓存会让同进程
看起来也能召回。真正要证明的是 PowerContext 服务端记住了这件事，
所以这里刻意新建实例、清空缓存，只依赖服务端状态。

用法::

    python scripts/verify_memory.py
    python scripts/verify_memory.py --json evidence/memory_verify.json
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from town_backend.config import load_settings  # noqa: E402
from town_backend.memory import KIND_KEY_EVENT, MemoryStore  # noqa: E402

RESULTS: list[dict] = []


def check(code: str, title: str, passed: bool, detail: str = "") -> bool:
    RESULTS.append({"code": code, "title": title, "passed": bool(passed), "detail": detail})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {code} {title}" + (f" — {detail}" if detail else ""))
    return bool(passed)


def main() -> int:
    parser = argparse.ArgumentParser(description="《记仇小镇》PowerContext 记忆验证")
    parser.add_argument("--json", dest="json_out", default="", help="结果 JSON 输出路径")
    args = parser.parse_args()

    settings = load_settings()
    suffix = uuid.uuid4().hex[:8]
    player_a = f"mem_a_{suffix}"
    player_b = f"mem_b_{suffix}"
    player_c = f"mem_c_{suffix}"

    print(f"PowerContext: {settings.powercontext_url}")

    # ---------------------------------------------------------------- M0
    store = MemoryStore(settings)
    health = store.health()
    if not check("M0", "PowerContext 可用", bool(health.get("available")),
                 f"{health.get('url')} status={health.get('status')} error={health.get('error', '')}"):
        return 1

    # ---------------------------------------------------------------- M1
    text = f"[{player_a}] 偷走了 奥托镇长 的「镇长的金王冠」。奥托镇长 因此记恨上了他。"
    written = store.remember_key_event(player_a, text)
    check("M1", "关键事件写入 PowerContext", bool(written.get("scope_id")),
          f"scope_id={written.get('scope_id')} artifact_id={written.get('artifact_id')} "
          f"kind={written.get('kind')}")

    # ---------------------------------------------------------------- M2
    # 关键：**新建一个 MemoryStore 实例**（清空进程内 scope 缓存），
    # 并且用一个新的 session id。只有服务端记住了，新实例才召回得到。
    fresh = MemoryStore(settings)
    recalled = fresh.recall_key_events(player_a, limit=20)
    hit = [entry for entry in recalled if text in (entry.get("text") or "")]
    check("M2", "新会话（新实例）仍能召回关键事件", len(hit) == 1,
          f"召回 {len(recalled)} 条, 精确命中 {len(hit)} 条")

    # ---------------------------------------------------------------- M3
    b_entries = fresh.recall(player_b, limit=20)
    b_hit = [entry for entry in b_entries if player_a in (entry.get("text") or "")]
    check("M3", "玩家 B 读不到玩家 A 的记忆", len(b_entries) == 0 and len(b_hit) == 0,
          f"B 召回 {len(b_entries)} 条, 其中含 A 内容的 {len(b_hit)} 条")

    # ---------------------------------------------------------------- M4
    c_entries = fresh.recall(player_c, limit=20)
    check("M4", "从未写过记忆的玩家召回为空（不报错）", len(c_entries) == 0,
          f"C 召回 {len(c_entries)} 条")

    # ---------------------------------------------------------------- M5
    # 同一玩家反复写入必须落在同一个 scope，否则"跨会话召回"是假的。
    scope_1 = fresh.ensure_scope(player_a)
    store2 = MemoryStore(settings)
    scope_2 = store2.ensure_scope(player_a)
    store2.remember_key_event(player_a, f"[{player_a}] 又干了一件事。")
    scope_3 = MemoryStore(settings).ensure_scope(player_a)
    check("M5", "同一玩家始终解析到同一个 scope（绑定稳定）",
          scope_1 == scope_2 == scope_3 and bool(scope_1),
          f"scope={scope_1} / {scope_2} / {scope_3}")

    # ---------------------------------------------------------------- M6
    final = MemoryStore(settings).recall(player_a, limit=50)
    kinds = {entry.get("kind") for entry in final}
    check("M6", "记忆条目的 kind 正确", KIND_KEY_EVENT in kinds,
          f"kinds={sorted(k for k in kinds if k)} 共 {len(final)} 条")

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n结果: {passed}/{total} 通过")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "powercontext_url": settings.powercontext_url,
            "players": {"a": player_a, "b": player_b, "c": player_c},
            "passed": passed, "total": total, "checks": RESULTS,
            "recalled_a": recalled,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {out}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
