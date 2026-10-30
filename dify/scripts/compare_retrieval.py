"""V2-T04 的附加证据：**不同检索策略的实际对比**。

任务书要求"提供对不同检索策略的实际对比"。这里不写结论，
而是**跑一遍**同一批记忆，看各策略到底能召回多少。

被比较的策略：

1. ``fts_combined``   —— 一次 FTS 查询，多个词合起来查。
2. ``fts_per_word``   —— 每个主题词单独查一次 FTS，取并集。
3. ``candidate+rank`` —— **本项目实际用的**：候选池（entries/list）
   + 逐词 FTS + 后端确定性排序 + 有界截断。

另外**如实记录** ``vector`` / ``hybrid`` 在本部署上的表现：
PowerContext 1.4.1 的 ``/v1/capabilities`` 只返回 ``["auto","fts"]``，
但 ``mode="vector"`` 并不报错 —— 它**静默退化成文本通道**
（返回的 ``matched_by`` 依然是 ``["text"]``）。
所以这里**不声称**做了向量检索，只把实际观测写下来。

用法::

    python scripts/compare_retrieval.py --player-id <某个玩过游戏的 player_id>
    python scripts/compare_retrieval.py            # 不指定就自动挑一个
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "backend"))

from town_backend.config import load_settings  # noqa: E402
from town_backend.memory import MemoryStore  # noqa: E402

#: 判断"召回成功"的关键词 —— 一条记忆如果提到了这些，说明它确实相关。
RELEVANT_MARKERS = ("王冠", "偷", "还", "墨墨", "镇长", "恶作剧", "小鱼干", "证据", "线索")


def relevant(text: str) -> bool:
    return any(marker in text for marker in RELEVANT_MARKERS)


def _pick_player() -> str:
    """Find the player that has the **most** memories.

    选记忆最多的玩家，样本才有代表性 —— 一个只有一条记忆的玩家
    没法区分三种检索策略的差别。
    """

    settings = load_settings()
    memory = MemoryStore(settings)
    scopes = memory._request("GET", "/v1/scopes")  # noqa: SLF001
    best_id = ""
    best_count = 0
    for scope in scopes.get("items") or []:
        title = scope.get("title") or ""
        if "记仇小镇" not in title:
            continue
        external = title.rsplit(" ", 1)[-1]
        entries = memory._request(  # noqa: SLF001
            "POST", "/v1/memory/entries/list",
            {"scope_id": scope["scope_id"], "limit": 100})
        count = len(entries.get("entries") or [])
        if count > best_count:
            best_count = count
            best_id = external
    return best_id


def main() -> int:
    parser = argparse.ArgumentParser(description="不同检索策略的实际对比")
    parser.add_argument("--player-id", default="")
    parser.add_argument("--json", dest="json_out",
                        default=str(ROOT / "evidence" / "retrieval_comparison.json"))
    args = parser.parse_args()

    settings = load_settings()
    memory = MemoryStore(settings)

    player_id = args.player_id or _pick_player()
    if not player_id:
        print("[BLOCKED] 找不到有记忆的玩家。先跑一遍游戏再执行本脚本。")
        return 1

    # 候选池（权威条目列表）—— 这是"标准答案"的分母。
    pool = memory._candidate_pool(player_id)
    truth = [entry for entry in pool if relevant(entry.get("text") or "")]
    total = len(pool)
    print(f"玩家：{player_id}")
    print(f"该玩家共有 {total} 条记忆，其中相关 {len(truth)} 条")
    print()

    results: dict[str, Any] = {}

    # --- 策略 1：一次 FTS 合查 -----------------------------------------
    combined_query = "偷走 金王冠 还给 墨墨 镇长 恶作剧 小鱼干 调查 线索"
    hits = memory.search(player_id, combined_query, limit=50, mode="fts")
    results["fts_combined"] = {
        "queries": [combined_query],
        "matched_by": sorted({m for h in hits for m in (h.get("matched_by") or [])}),
        "hit_count": len(hits),
        "relevant_hits": len([h for h in hits if relevant(h.get("text") or "")]),
    }

    # --- 策略 2：逐词 FTS ----------------------------------------------
    words = ["偷走", "金王冠", "还给", "墨墨", "镇长", "恶作剧", "小鱼干", "调查", "线索"]
    per_word: dict[str, list[dict[str, Any]]] = {}
    for word in words:
        per_word[word] = memory.search(player_id, word, limit=50, mode="fts")
    union: dict[str, dict[str, Any]] = {}
    for word, found in per_word.items():
        for hit in found:
            key = str(hit.get("memory_id"))
            union.setdefault(key, hit)
            union[key].setdefault("_words", []).append(word)
    results["fts_per_word"] = {
        "queries": words,
        "hit_count": len(union),
        "relevant_hits": len([h for h in union.values() if relevant(h.get("text") or "")]),
        "per_word_hits": {w: len(v) for w, v in per_word.items()},
    }

    # --- 策略 3：候选池 + 逐词 FTS + 后端排序 + 截断（本项目实际用的）----
    ranked = memory._rank(pool, tuple(words))  # noqa: SLF001
    bounded, total_bytes = memory._bounded(ranked, limit=50)  # noqa: SLF001
    results["candidate+rank"] = {
        "queries": words,
        "candidate_count": len(pool),
        "hit_count": len(bounded),
        "relevant_hits": len([h for h in bounded if relevant(h.get("text") or "")]),
        "bytes": total_bytes,
    }

    # --- 附：vector / hybrid 的**实际**表现 -----------------------------
    for mode in ("vector", "hybrid"):
        found = memory.search(player_id, "偷走", limit=10, mode=mode)
        results[f"observed_{mode}"] = {
            "hit_count": len(found),
            "matched_by": sorted({m for h in found for m in (h.get("matched_by") or [])}),
            "note": "本部署没有向量索引；该模式静默退化成文本通道",
        }

    capabilities = memory.capabilities()

    print("策略对比（命中相关记忆数 / 总记忆数）：")
    for name in ("fts_combined", "fts_per_word", "candidate+rank"):
        row = results[name]
        print(f"  {name:<18} {row['relevant_hits']:>3}/{total}"
              f"   （返回 {row['hit_count']} 条）")
    print()
    print("PowerContext 实际支持的检索模式：", capabilities.get("search_modes"))
    for mode in ("vector", "hybrid"):
        row = results[f"observed_{mode}"]
        print(f"  请求 mode={mode:<8} → matched_by={row['matched_by']}"
              f"（{row['note']}）")

    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "player_id": player_id,
        "total_memories": total,
        "relevant_memories": len(truth),
        "capabilities": capabilities,
        "strategies": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
