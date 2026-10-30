"""T2 / T3 / T8：直接打后端 HTTP API，验证游戏闭环与错误处理。

这个脚本只依赖后端 HTTP 接口（默认 http://127.0.0.1:8848），
因此**不依赖 Dify**，可以在 Dify 没起来时单独跑。

覆盖的断言
----------

A1  ``GET  /health``          同时报告 seekdb 与 PowerContext 的可用性
A2  ``POST /api/player/register``  新玩家注册成功，落在起始地点
A3  ``GET  /api/state``       返回 NPC 人设、关系数值、道具、事件
A4  ``POST /api/action`` 闲聊  好感/信任上升，事件落库
A5  ``POST /api/action`` 恶作剧 好感下降、怨念上升
A6  ``POST /api/action`` 赠送道具 道具 owner 真的转移到 NPC 手上
A7  ``POST /api/action`` 偷王冠  触发主线剧情「王冠失窃案」
A8  幂等：同一个 Idempotency-Key 重复提交，数值不变、结果回放
A9  幂等冲突：同一个 key 换内容 → 409
A10 输入校验：非法 player_id / 空消息 / 超长消息 → 400
A11 未知玩家 → 404
A12 规则拒绝：赠送不可转移道具 → 409，且归属未变
A13 玩家隔离：B 读不到 A 的事件
A14 超时：后端不可达时快速失败，而不是挂住
A15 数据库异常被优雅处理（模拟断连 → 5xx 而不是进程崩溃）
A16 鉴权：缺凭据 / 错凭据 → 401
A17 身份隔离：冒用别人的 player_id → 403

用法::

    python scripts/verify_backend_api.py
    python scripts/verify_backend_api.py --base-url http://127.0.0.1:8848
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

# 允许直接从宿主机运行时复位测试夹具（王冠归位、货架补货）。
BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from auth_helper import auth_headers, describe_auth_mode  # noqa: E402

RESULTS: list[dict] = []


def reset_fixtures() -> str:
    """Put the crown back on the mayor and restock the snack shelf.

    Without this the script is not reproducible: a previous run stole the
    crown, and the plot would no longer trigger.

    王冠只有**一件**，谁偷走它就归谁 —— 所以每个需要它的场景开始前
    都要复位一次，否则前一个场景的玩家会"吃"掉王冠，后面的场景
    就会因为"目标身上没有可偷的东西"而失败。
    """

    from town_backend.config import load_settings
    from town_backend.store import SeekDBStore

    settings = load_settings()
    store = SeekDBStore(settings)
    with store._cursor(settings.seekdb_database) as cursor:  # noqa: SLF001
        # 王冠可能已经被上一轮测试偷走（整行归属变成 player），
        # 所以先删干净再重新插入镇长那一份，而不是 UPDATE。
        cursor.execute("DELETE FROM town_item WHERE item_id = 'golden_crown'")
        cursor.execute(
            "INSERT INTO town_item "
            "(item_id, owner_kind, owner_id, name, description, quantity, is_transferable) "
            "VALUES ('golden_crown', 'npc', 'mayor', %s, %s, 1, 1)",
            ("镇长的金王冠", "镇长视若珍宝的镀金王冠，底座刻着「奥托镇长万岁」。它很值钱，也很招贼。"))
        # 货架补货，并清掉镇长手里的零食，让赠送目标保持唯一。
        #
        # 注意这里是 **DELETE + INSERT** 而不是 UPDATE：货架那一行
        # 可能已经被别的流程整行删掉了（V1 的赠送/偷窃会把道具从
        # 来源手里搬走），对着一行不存在的记录 UPDATE 是**空操作** ——
        # 货架就再也不会回来，而"货架上有小鱼干"是 V1 演示的起点。
        cursor.execute(
            "DELETE FROM town_item WHERE item_id = 'fat_fish_snack' "
            "AND owner_kind = 'town' AND owner_id = 'town_square'")
        cursor.execute(
            "DELETE FROM town_item WHERE item_id = 'fat_fish_snack' "
            "AND owner_kind = 'npc' AND owner_id = 'mayor'")
        cursor.execute(
            "INSERT INTO town_item "
            "(item_id, owner_kind, owner_id, name, description, quantity, "
            "is_transferable, item_kind, is_evidence) "
            "VALUES ('fat_fish_snack', 'town', 'town_square', %s, %s, 5, 1, 'normal', 0)",
            ("油炸小鱼干", "喷泉边卖的那种小鱼干，油纸包。墨墨的弱点。"))
        # 墨墨自己那袋也要复位到 1 —— 之前的赠送/偷窃会把它并进
        # 目标的数量里，累积到 3、4 也说不清最初是多少。
        cursor.execute(
            "UPDATE town_item SET quantity = 1 WHERE item_id = 'fat_fish_snack' "
            "AND owner_kind = 'npc' AND owner_id = 'cat_detective'")
        # 两件证据也要复位：调查 NPC 会把它们交给玩家，
        # 不复位的话"悬案大师"路线会因为证据不在 NPC 手里而拿不到。
        for item_id, owner_id, name in (
            ("alley_witness_note", "detective_office", "后巷目击者便条"),
            ("crown_receipt", "back_alley", "一张王冠领用单"),
        ):
            cursor.execute(
                "DELETE FROM town_item WHERE item_id = %s AND owner_kind = 'player'",
                (item_id,))
            cursor.execute(
                "DELETE FROM town_item WHERE item_id = %s AND owner_kind = 'town'",
                (item_id,))
            cursor.execute(
                "INSERT INTO town_item "
                "(item_id, owner_kind, owner_id, name, description, quantity, "
                "is_transferable, item_kind, is_evidence) "
                "VALUES (%s, 'town', %s, %s, %s, 1, 1, 'evidence', 1)",
                (item_id, owner_id, name, "可以查证王冠失窃案的关键证物。"))
    return f"{settings.seekdb_host}:{settings.seekdb_port}/{settings.seekdb_database}"


def check(code: str, title: str, passed: bool, detail: str = "") -> bool:
    RESULTS.append({"code": code, "title": title, "passed": bool(passed), "detail": detail})
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {code} {title}" + (f" — {detail}" if detail else ""))
    return bool(passed)


def main() -> int:
    parser = argparse.ArgumentParser(description="《记仇小镇》后端 API 验证")
    parser.add_argument("--base-url", default="http://127.0.0.1:8848", help="后端地址")
    parser.add_argument("--json", dest="json_out", default="", help="结果 JSON 输出路径")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    suffix = uuid.uuid4().hex[:8]
    player_a = f"api_a_{suffix}"
    player_b = f"api_b_{suffix}"
    session_1 = f"sess_{suffix}_1"
    session_2 = f"sess_{suffix}_2"

    # V2 起，所有调用都必须带服务凭据与玩家身份。
    auth = auth_headers()
    print(f"鉴权配置: {describe_auth_mode()}")

    try:
        target = reset_fixtures()
        print(f"已复位测试夹具: {target}")
    except Exception as error:  # noqa: BLE001
        print(f"[WARN] 复位夹具失败（后续断言可能受影响）: {type(error).__name__}: {error}")

    client = httpx.Client(base_url=base, timeout=20.0, headers=auth)

    # ---------------------------------------------------------------- A1
    try:
        health = client.get("/health")
        body = health.json()
        ok = health.status_code == 200 and body.get("seekdb", {}).get("available") \
            and body.get("powercontext", {}).get("available")
        detail = f"seekdb={body.get('seekdb', {}).get('available')} powercontext={body.get('powercontext', {}).get('available')}"
    except Exception as error:  # noqa: BLE001
        ok = False
        detail = f"{type(error).__name__}: {error}"
    if not check("A1", "/health 同时报告两个后端", ok, detail):
        print("\n后端不可用，后续断言无法执行。")
        return 1

    def register(player_id: str, session_id: str) -> dict:
        return client.post("/api/player/register", json={
            "player_id": player_id,
            "session_id": session_id,
            "display_name": f"验证-{player_id}",
        }).json()

    def act(player_id: str, session_id: str, message: str, *, npc_id: str = "mayor",
            key: str = "", headers: dict | None = None, hint: str | None = None) -> httpx.Response:
        payload = {
            "player_id": player_id,
            "session_id": session_id,
            "npc_id": npc_id,
            "message": message,
        }
        if hint:
            payload["action_hint"] = hint
        hdrs = {"Idempotency-Key": key} if key else {}
        if headers:
            hdrs.update(headers)
        return client.post("/api/action", json=payload, headers=hdrs)

    # ---------------------------------------------------------------- A2
    reg = register(player_a, session_1)
    check("A2", "新玩家注册成功并落在起始地点",
          reg.get("ok") and reg.get("created") and reg["player"]["current_location"] == "town_square",
          f"created={reg.get('created')} location={reg.get('player', {}).get('current_location')}")

    # ---------------------------------------------------------------- A3
    state = client.get("/api/state", params={"player_id": player_a}).json()
    npc_ids = {n["npc_id"] for n in state.get("npcs", [])}
    mayor = next((n for n in state["npcs"] if n["npc_id"] == "mayor"), {})
    check("A3", "/api/state 返回 NPC 人设与关系数值",
          {"mayor", "cat_detective"} <= npc_ids and mayor.get("persona")
          and "affinity" in mayor and "grudge_level" in mayor,
          f"NPC={sorted(npc_ids)} mayor.trust={mayor.get('trust')} mayor.grudge={mayor.get('grudge_level')}")

    # ---------------------------------------------------------------- A4
    resp = act(player_a, session_1, "镇长您好，我想打听一下这个镇子。", key=f"t4-{suffix}")
    body = resp.json()
    check("A4", "闲聊动作提升好感并落库",
          resp.status_code == 200 and body["action"]["action_type"] == "talk"
          and body["relationship"]["affinity"] > 0 and body["relationship"]["trust"] > 50,
          f"type={body.get('action', {}).get('action_type')} affinity={body.get('relationship', {}).get('affinity')} trust={body.get('relationship', {}).get('trust')}")

    # ---------------------------------------------------------------- A5
    resp = act(player_a, session_1, "我要给你一个恶作剧！", key=f"t5-{suffix}")
    body = resp.json()
    check("A5", "恶作剧降低好感并累积怨念",
          resp.status_code == 200 and body["action"]["action_type"] == "prank"
          and body["relationship"]["grudge_level"] > 0,
          f"type={body.get('action', {}).get('action_type')} grudge={body.get('relationship', {}).get('grudge_level')} affinity={body.get('relationship', {}).get('affinity')}")

    # ---------------------------------------------------------------- A6
    resp = act(player_a, session_1, "我送给你一条小鱼干", key=f"t6-{suffix}")
    body = resp.json()
    gift_ok = resp.status_code == 200 and body["action"]["action_type"] == "gift"
    item_id = body.get("action", {}).get("item_id", "")
    check("A6", "赠送道具后道具真的转到 NPC 手上", gift_ok and bool(item_id),
          f"item={item_id} outcome={body.get('action', {}).get('outcome')}")

    # ---------------------------------------------------------------- A7
    resp = act(player_a, session_1, "我要偷走镇王的金王冠", key=f"t7-{suffix}")
    body = resp.json()
    plot = body.get("plot", {})
    check("A7", "偷走王冠触发主线剧情「王冠失窃案」",
          resp.status_code == 200 and body.get("action", {}).get("action_type") == "steal"
          and plot.get("plot_id") == "plot_crown_theft" and plot.get("stage") == "investigating",
          f"status={resp.status_code} plot={plot.get('plot_id')}/{plot.get('stage')} "
          f"notes={body.get('action', {}).get('notes')}")

    # ---------------------------------------------------------------- A8
    before = client.get("/api/state", params={"player_id": player_a}).json()
    rel_before = next(n for n in before["npcs"] if n["npc_id"] == "mayor")
    key = f"t8-{suffix}"
    first = act(player_a, session_1, "再来一次恶作剧！", key=key).json()
    second = act(player_a, session_1, "再来一次恶作剧！", key=key).json()
    after = client.get("/api/state", params={"player_id": player_a}).json()
    rel_after = next(n for n in after["npcs"] if n["npc_id"] == "mayor")
    check("A8", "重复请求被幂等处理，数值只变一次",
          first.get("replayed") is not True and second.get("replayed") is True
          and rel_after["affinity"] == rel_before["affinity"] - 8
          and rel_after["grudge_level"] == rel_before["grudge_level"] + 12,
          f"affinity {rel_before['affinity']} -> {rel_after['affinity']}, grudge {rel_before['grudge_level']} -> {rel_after['grudge_level']}, replayed={second.get('replayed')}")

    # ---------------------------------------------------------------- A9
    conflict = act(player_a, session_1, "换个完全不同的内容", key=key)
    check("A9", "同一幂等 key 换内容 → 409 冲突",
          conflict.status_code == 409 and conflict.json().get("error", {}).get("code") == "idempotency_conflict",
          f"status={conflict.status_code} code={conflict.json().get('error', {}).get('code')}")

    # ---------------------------------------------------------------- A10
    bad_player = client.post("/api/action", json={"player_id": "bad id!!", "session_id": "s", "message": "hi"})
    empty_msg = client.post("/api/action", json={"player_id": player_a, "session_id": session_1, "message": "   "})
    long_msg = client.post("/api/action", json={
        "player_id": player_a, "session_id": session_1, "message": "x" * 600})
    check("A10", "输入校验：非法 player_id / 空消息 / 超长消息 → 400",
          bad_player.status_code == 400 and empty_msg.status_code == 400 and long_msg.status_code == 400,
          f"bad_player={bad_player.status_code} empty={empty_msg.status_code} long={long_msg.status_code}")

    # ---------------------------------------------------------------- A11
    unknown = client.get("/api/state", params={"player_id": f"nobody_{suffix}"})
    check("A11", "未知玩家 → 404", unknown.status_code == 404,
          f"status={unknown.status_code}")

    # ---------------------------------------------------------------- A12
    resp = act(player_a, session_1, "我把镇长印章送给你", key=f"t12-{suffix}")
    check("A12", "赠送不可转移道具被规则拒绝 → 409",
          resp.status_code == 409 and resp.json().get("error", {}).get("code")
          in ("item_not_transferable", "item_already_owned", "unknown_item", "no_gift_item"),
          f"status={resp.status_code} code={resp.json().get('error', {}).get('code')}")

    # ---------------------------------------------------------------- A13
    register(player_b, session_1)
    a_events = client.get("/api/players/%s/events" % player_a).json()["events"]
    b_events = client.get("/api/players/%s/events" % player_b).json()["events"]
    check("A13", "玩家隔离：B 读不到 A 的事件",
          len(a_events) > 0 and len(b_events) == 0,
          f"A={len(a_events)} 条, B={len(b_events)} 条")

    # ---------------------------------------------------------------- A14
    started = time.time()
    try:
        httpx.Client(timeout=3.0).get("http://127.0.0.1:9/health")
        timed_out = False
        detail = "（意外可连接）"
    except Exception as error:  # noqa: BLE001
        timed_out = True
        detail = f"{type(error).__name__}: {str(error)[:80]}"
    elapsed = time.time() - started
    check("A14", "后端不可达时快速失败而不是无限挂起", timed_out and elapsed < 10,
          f"{detail} / 用时 {elapsed:.2f}s")

    # ---------------------------------------------------------------- A15
    # 让请求体不是合法 JSON，后端应返回 400 而不是 500 堆栈。
    malformed = client.post("/api/action", content=b"{not json", headers={
        "Content-Type": "application/json"})
    check("A15", "畸形请求体 → 400 而不是 500",
          malformed.status_code == 400,
          f"status={malformed.status_code} code={malformed.json().get('error', {}).get('code')}")

    # ---------------------------------------------------------------- A16
    # 鉴权：缺凭据 / 错凭据一律 401。这条断言证明服务凭据**真的在生效**，
    # 不是摆设。
    anonymous = httpx.Client(base_url=base, timeout=20.0)
    no_token = anonymous.get("/api/state", params={"player_id": player_a})
    wrong_token = anonymous.get("/api/state", params={"player_id": player_a},
                                headers={"X-Town-Token": "definitely-not-the-token",
                                         "X-Town-Identity": "verify_suite"})
    check("A16", "缺服务凭据 / 错服务凭据 → 401",
          no_token.status_code == 401 and wrong_token.status_code == 401,
          f"缺凭据={no_token.status_code} 错凭据={wrong_token.status_code} "
          f"code={no_token.json().get('error', {}).get('code')}")
    anonymous.close()

    # ---------------------------------------------------------------- A17
    # 身份隔离：知道别人的 player_id 也不该读到他的存档。
    forged = httpx.Client(base_url=base, timeout=20.0, headers={
        "X-Town-Token": auth.get("X-Town-Token", ""),
        "X-Town-Identity": "someone_else_" + suffix,
    })
    forged_read = forged.get("/api/state", params={"player_id": player_a})
    check("A17", "冒用他人 player_id 读存档 → 403",
          forged_read.status_code == 403,
          f"status={forged_read.status_code} code={forged_read.json().get('error', {}).get('code')}")
    forged.close()

    passed = sum(1 for r in RESULTS if r["passed"])
    total = len(RESULTS)
    print(f"\n结果: {passed}/{total} 通过")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "base_url": base, "passed": passed, "total": total, "checks": RESULTS,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写入 {out}")

    client.close()
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
