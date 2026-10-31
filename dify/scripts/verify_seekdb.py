"""T2/T3 的数据库侧证据：直接在 seekdb 上验证 CRUD 与规则约束。

这个脚本**不经过 Flask**，只用 PyMySQL 直连数据库，因此能证明
"seekdb 真的存了东西"，而不只是"API 返回了东西"。

覆盖的断言
----------

C1  表结构存在（V1 八张 + V2 新增五张，共 13 张）
C2  种子数据存在（4 地点 / 3 NPC / 5 道具）
C3  玩家注册写入 ``town_player``，初始位置是 ``town_square``
C4  关系初始值：好感 0、信任 mayor=50 / cat_detective=30、怨念 0
C5  关系数值变更被 CHECK 约束挡住（非法值写不进去）
C6  数值被夹紧在合法区间内（应用层 clamp 生效）
C7  道具转移真实生效，owner 字段确实变了
C8  不可转移道具（镇长印章）转移被拒
C9  重复 idempotency_key 只落一条事件
C10 玩家隔离：A 的事件查不到 B 的数据
C11 事件里的中文是真正的 UTF-8（不是问号）

用法::

    python scripts/verify_seekdb.py
    python scripts/verify_seekdb.py --json evidence/seekdb_verify.json
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
from town_backend.store import SeekDBStore, StoreError  # noqa: E402

EXPECTED_TABLES = {
    # V1 的八张表。
    "town_location", "town_npc", "town_player", "town_relationship",
    "town_item", "town_event", "town_plot_progress", "town_request_log",
    # V2 增量加的表。
    "town_location_link", "town_knowledge", "town_quest", "town_ending",
    "town_achievement", "town_outbox", "town_player_identity",
}

#: V2 种子数据里**必须存在**的地点、NPC 与道具。
#:
#: 这里按 id 断言，而不是按"有几行"断言 ——
#: ``town_item`` 的行数会随着玩家偷/送/还不断增长（每个拿到道具的
#: 玩家都会多出一行），拿总数当断言会随运行次数漂移。
#: 按 id 断言的是"世界该有的东西在不在"，这才是种子数据的含义。
SEED_LOCATIONS = ("town_square", "mayor_house", "back_alley", "detective_office")
SEED_NPCS = ("mayor", "cat_detective", "crow_judge")
SEED_ITEMS = ("golden_crown", "fat_fish_snack", "mayor_seal",
               "crown_receipt", "alley_witness_note")

RESULTS: list[dict] = []


def check(code: str, title: str, passed: bool, detail: str = "") -> bool:
    RESULTS.append({"code": code, "title": title, "passed": bool(passed), "detail": detail})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {code} {title}" + (f" — {detail}" if detail else ""))
    return bool(passed)


def main() -> int:
    parser = argparse.ArgumentParser(description="《记仇小镇》seekdb 侧验证")
    parser.add_argument("--json", dest="json_out", default="", help="把结果写成 JSON 文件")
    args = parser.parse_args()

    settings = load_settings()
    store = SeekDBStore(settings)

    # 唯一的验证玩家 id —— 用随机后缀，避免与其它测试数据冲突。
    suffix = uuid.uuid4().hex[:8]
    player_a = f"verify_a_{suffix}"
    player_b = f"verify_b_{suffix}"

    # ---------------------------------------------------------------- C1
    counts = store.count_rows()
    missing = sorted(EXPECTED_TABLES - set(counts))
    check("C1", "业务表存在", not missing,
          f"缺失: {missing}" if missing else f"共 {len(EXPECTED_TABLES)} 张表")

    # ---------------------------------------------------------------- C2
    locations = store.list_locations()
    npcs = store.list_npcs()
    location_ids = {loc["location_id"] for loc in locations}
    npc_ids = {npc["npc_id"] for npc in npcs}
    all_items = store.list_all_items()
    item_ids = {item["item_id"] for item in all_items}
    starts = [loc for loc in locations if int(loc["is_start"]) == 1]
    missing_locations = sorted(set(SEED_LOCATIONS) - location_ids)
    missing_npcs = sorted(set(SEED_NPCS) - npc_ids)
    missing_items = sorted(set(SEED_ITEMS) - item_ids)
    check("C2", "种子数据已灌入",
          not missing_locations and not missing_npcs and not missing_items
          and len(starts) == 1,
          f"地点={len(location_ids)} NPC={len(npc_ids)} "
          f"道具行={counts.get('town_item', 0)} 起始点={len(starts)}"
          + (f" 缺地点={missing_locations}" if missing_locations else "")
          + (f" 缺NPC={missing_npcs}" if missing_npcs else "")
          + (f" 缺道具={missing_items}" if missing_items else ""))

    # ---------------------------------------------------------------- C3
    created = store.register_player(player_a, "验证玩家A", f"sess_{suffix}_1")
    player = store.fetch_player(player_a)
    check("C3", "玩家注册写入 town_player 且落在起始地点",
          created["created"] and player is not None and player["current_location"] == "town_square",
          f"player_id={player_a} location={player['current_location'] if player else 'None'}")

    # ---------------------------------------------------------------- C4
    rel_mayor = store.fetch_relationship(player_a, "mayor")
    rel_cat = store.fetch_relationship(player_a, "cat_detective")
    check("C4", "初始关系值符合设定",
          rel_mayor is not None and rel_cat is not None
          and int(rel_mayor["affinity"]) == 0 and int(rel_mayor["trust"]) == 50
          and int(rel_cat["trust"]) == 30 and int(rel_mayor["grudge_level"]) == 0,
          f"mayor={dict(rel_mayor) if rel_mayor else None}")

    # ---------------------------------------------------------------- C5
    # 直接绕过应用层，用非法数值写入，验证 CHECK 约束真的存在。
    check_failed = False
    try:
        with store._cursor(settings.seekdb_database) as cursor:  # noqa: SLF001 - 测试故意走底层
            cursor.execute(
                "UPDATE town_relationship SET affinity = 999 WHERE player_id = %s AND npc_id = %s",
                (player_a, "mayor"),
            )
    except Exception as error:  # noqa: BLE001 - 任何拒绝写入都算通过
        check_failed = True
        detail = f"{type(error).__name__}: {str(error)[:120]}"
    else:
        detail = "写入未被拒绝，CHECK 约束缺失"
    check("C5", "CHECK 约束挡住非法关系值", check_failed, detail)

    # ---------------------------------------------------------------- C6
    # 应用层 clamp：连续偷窃会把好感压到 -100，不会越界。
    for _ in range(12):
        store.apply_relationship_delta(player_a, "mayor", -15, -20, 25, "steal")
    clamped = store.fetch_relationship(player_a, "mayor")
    check("C6", "关系数值被夹紧在合法区间",
          clamped is not None and int(clamped["affinity"]) >= -100
          and int(clamped["trust"]) >= 0 and int(clamped["grudge_level"]) <= 100,
          f"after 12 steals: affinity={clamped['affinity']} trust={clamped['trust']} grudge={clamped['grudge_level']}")

    # ---------------------------------------------------------------- C7
    # 先把王冠归位到镇长手上，保证这条断言不依赖之前的测试状态。
    with store._cursor(settings.seekdb_database) as cursor:  # noqa: SLF001
        cursor.execute("UPDATE town_item SET owner_kind='npc', owner_id='mayor', quantity=1 "
                       "WHERE item_id='golden_crown'")
    crown_before = store.fetch_item("golden_crown", "npc", "mayor")
    store.transfer_item("golden_crown", "player", player_a, from_kind="npc", from_id="mayor")
    crown_after = store.fetch_item("golden_crown", "player", player_a)
    check("C7", "道具转移真实改变 owner 字段",
          crown_before is not None and crown_before["owner_kind"] == "npc"
          and crown_before["owner_id"] == "mayor"
          and crown_after is not None and crown_after["owner_kind"] == "player"
          and crown_after["owner_id"] == player_a,
          f"{crown_before['owner_kind']}/{crown_before['owner_id']} -> "
          f"{crown_after['owner_kind']}/{crown_after['owner_id']}")

    # ---------------------------------------------------------------- C7b
    # 货架上的小鱼干有数量，送一件之后还剩 4 件 —— 而不是整堆消失。
    #
    # 先保证货架那一行**存在**：前面的流程可能已经把整行搬走了，
    # 对着一行不存在的记录做断言会抛 AttributeError，而不是给出
    # 一个诚实的失败。
    with store._cursor(settings.seekdb_database) as cursor:  # noqa: SLF001
        cursor.execute(
            "INSERT INTO town_item (item_id, owner_kind, owner_id, name, description, "
            "quantity, is_transferable, item_kind, is_evidence) "
            "VALUES ('fat_fish_snack', 'town', 'town_square', %s, %s, 5, 1, 'normal', 0) "
            "ON DUPLICATE KEY UPDATE quantity = 5",
            ("油炸小鱼干", "喷泉边卖的那种小鱼干，油纸包。墨墨的弱点。"))
        cursor.execute(
            "DELETE FROM town_item WHERE item_id = 'fat_fish_snack' "
            "AND owner_kind = 'npc' AND owner_id = 'mayor'")
    shelf_before = store.fetch_item("fat_fish_snack", "town", "town_square")
    store.transfer_item("fat_fish_snack", "npc", "mayor", from_kind="town", from_id="town_square")
    shelf_after = store.fetch_item("fat_fish_snack", "town", "town_square")
    held = store.fetch_item("fat_fish_snack", "npc", "mayor")
    check("C7b", "货架道具按数量扣减，送一件后仍有余量",
          shelf_before is not None and shelf_before["quantity"] == 5
          and shelf_after is not None and shelf_after["quantity"] == 4
          and held is not None and int(held["quantity"]) == 1,
          f"货架 {shelf_before['quantity'] if shelf_before else 'N/A'} -> "
          f"{shelf_after['quantity'] if shelf_after else 'N/A'}, "
          f"镇长手里 {held['quantity'] if held else 'N/A'}")
    # 把数量补回去，避免影响后续测试。
    with store._cursor(settings.seekdb_database) as cursor:  # noqa: SLF001
        cursor.execute("UPDATE town_item SET quantity=5 WHERE item_id='fat_fish_snack' "
                       "AND owner_kind='town' AND owner_id='town_square'")
        cursor.execute("DELETE FROM town_item WHERE item_id='fat_fish_snack' "
                       "AND owner_kind='npc' AND owner_id='mayor'")

    # ---------------------------------------------------------------- C8
    seal_before = store.fetch_item("mayor_seal", "npc", "mayor")
    rejected = False
    try:
        store.transfer_item("mayor_seal", "player", player_a, from_kind="npc", from_id="mayor")
    except StoreError as error:
        rejected = True
        detail = f"StoreError({error.code}): {error.message}"
    else:
        detail = "转移被接受，规则未生效"
    seal_after = store.fetch_item("mayor_seal", "npc", "mayor")
    check("C8", "不可转移道具被拒绝且归属未变",
          rejected and seal_after is not None
          and seal_after["owner_kind"] == seal_before["owner_kind"]
          and seal_after["owner_id"] == seal_before["owner_id"],
          detail + f" / 归属仍为 {seal_after['owner_kind']}/{seal_after['owner_id']}")

    # ---------------------------------------------------------------- C9
    idem_key = f"verify-idem-{suffix}"
    store.record_event(player_a, "mayor", "talk", "验证一下幂等", "第一次", f"sess_{suffix}_1", idem_key)
    store.record_event(player_a, "mayor", "talk", "验证一下幂等", "第二次", f"sess_{suffix}_1", idem_key)
    events = store.list_events(player_a, limit=50)
    same_key = [e for e in events if e["event_id"] and e["action_text"] == "验证一下幂等"]
    check("C9", "重复 idempotency_key 只落一条事件", len(same_key) == 1,
          f"写入 2 次，实际事件 {len(same_key)} 条")

    # ---------------------------------------------------------------- C10
    store.register_player(player_b, "验证玩家B", f"sess_{suffix}_1")
    a_events = store.list_events(player_a, limit=100)
    b_events = store.list_events(player_b, limit=100)
    a_ids = {e["event_id"] for e in a_events}
    b_ids = {e["event_id"] for e in b_events}
    check("C10", "玩家隔离：A 的事件不会出现在 B 的查询里",
          not (a_ids & b_ids) and len(a_events) >= 1 and len(b_events) == 0,
          f"A={len(a_events)} 条, B={len(b_events)} 条, 交集={len(a_ids & b_ids)}")

    # ---------------------------------------------------------------- C11
    chinese = "我偷走了镇长的金王冠"
    store.record_event(player_a, "mayor", "steal", chinese, "被当场抓住", f"sess_{suffix}_1",
                       f"verify-cn-{suffix}")
    rows = store.list_events(player_a, limit=50)
    stored = [e["action_text"] for e in rows if e["action_text"] == chinese]
    garbled = [e["action_text"] for e in rows if "?" in (e["action_text"] or "")]
    check("C11", "中文按 UTF-8 正确存储", len(stored) == 1 and not garbled,
          f"原样命中 {len(stored)} 条，出现乱码 {len(garbled)} 条")

    # ------------------------------------------------------------------ 清理
    # 验证产生的玩家是测试垃圾，删掉以免污染游戏数据。
    try:
        with store._cursor(settings.seekdb_database) as cursor:  # noqa: SLF001
            cursor.execute("DELETE FROM town_event WHERE player_id IN (%s, %s)", (player_a, player_b))
            cursor.execute("DELETE FROM town_relationship WHERE player_id IN (%s, %s)", (player_a, player_b))
            cursor.execute("DELETE FROM town_plot_progress WHERE player_id IN (%s, %s)", (player_a, player_b))
            cursor.execute("DELETE FROM town_player WHERE player_id IN (%s, %s)", (player_a, player_b))
            cursor.execute("UPDATE town_item SET owner_kind='npc', owner_id='mayor', quantity=1 "
                           "WHERE item_id='golden_crown'")
            cursor.execute("DELETE FROM town_item WHERE owner_kind='player' AND owner_id=%s", (player_a,))
    except Exception as error:  # noqa: BLE001
        print(f"[WARN] 清理验证数据失败: {error}")

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n结果: {passed}/{total} 通过")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "database": settings.seekdb_database,
            "host": settings.seekdb_host,
            "port": settings.seekdb_port,
            "passed": passed,
            "total": total,
            "checks": RESULTS,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {out}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
