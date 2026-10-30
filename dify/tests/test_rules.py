"""Mock 单元测试：《记仇小镇》的**纯逻辑**部分。

⚠️ **这些是 Mock / 单元测试，不是端到端验收。**

它们不碰 seekdb、不碰 PowerContext、不碰 Dify，只用假的后端验证
判定逻辑本身。端到端验收请跑：

* ``scripts/verify_seekdb.py``       —— 真实 seekdb
* ``scripts/verify_backend_api.py`` —— 真实后端 API
* ``scripts/verify_memory.py``      —— 真实 PowerContext
* ``scripts/verify_dify_e2e.py``    —— 真实 Dify 全链路 T1–T9

为什么还要写单元测试：判定逻辑（动作分类、道具归属、幂等、输入校验）
决定了游戏规则对不对。真实集成测试一次要跑完整条链，慢且贵；
单元测试能在秒级回归这些规则。

运行::

    python -m pytest dify/tests/test_rules.py -q
    python dify/tests/test_rules.py        # 不装 pytest 也能跑
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from town_backend.engine import (  # noqa: E402
    ACTION_DELTAS,
    PLOT_CROWN_THEFT,
    classify_action,
    match_item,
    request_hash,
    resolve_target,
)
from town_backend.api import PLAYER_ID_PATTERN, SESSION_ID_PATTERN  # noqa: E402


# --------------------------------------------------------------------- fixtures

MAJOR = {
    "npc_id": "mayor",
    "name": "奥托镇长",
    "title": "小镇镇长",
    "items": [
        {"item_id": "golden_crown", "name": "镇长的金王冠", "is_transferable": 1},
        {"item_id": "mayor_seal", "name": "镇长印章", "is_transferable": 0},
    ],
}
CAT = {
    "npc_id": "cat_detective",
    "name": "墨墨",
    "title": "猫咪侦探",
    "items": [{"item_id": "old_notebook", "name": "墨墨的旧账本", "is_transferable": 1}],
}
NPCS = [MAJOR, CAT]


# ------------------------------------------------------------------- unit tests

def test_classify_steal_wins_over_other_keywords():
    assert classify_action("我要偷走镇长的金王冠") == "steal"


def test_classify_prank_wins_over_gift_when_more_specific():
    # "给" 命中赠送，"恶作剧" 命中恶作剧；加权后恶作剧更专指。
    assert classify_action("我要给你一个恶作剧") == "prank"


def test_classify_gift():
    assert classify_action("我想送你一条小鱼干") == "gift"


def test_classify_investigate():
    assert classify_action("我想调查一下王冠失窃案") == "investigate"


def test_classify_plain_talk_is_talk():
    assert classify_action("你好呀，今天天气不错") == "talk"


def test_model_hint_only_used_when_no_keyword():
    # 关键词优先于模型提示 —— 模型输出不可信。
    assert classify_action("我要偷东西", model_hint="gift") == "steal"
    # 没有关键词时，模型提示可以破平。
    assert classify_action("随便做点什么", model_hint="prank") == "prank"
    # 模型给出未知类型时退回 talk。
    assert classify_action("随便做点什么", model_hint="nonsense") == "talk"


def test_match_item_by_exact_name():
    items = MAJOR["items"]
    assert match_item("我看看那个镇长的金王冠", items) == "golden_crown"


def test_match_item_by_alias():
    items = MAJOR["items"]
    assert match_item("我想偷走王冠", items) == "golden_crown"


def test_match_item_not_found():
    assert match_item("我想要一条小鱼干", MAJOR["items"]) == ""


def test_resolve_target_by_name():
    assert resolve_target("我要找墨墨", NPCS) == "cat_detective"


def test_resolve_target_by_title():
    assert resolve_target("镇长在哪", NPCS) == "mayor"


def test_resolve_target_falls_back_to_first():
    assert resolve_target("有人吗", NPCS) == "mayor"


def test_action_deltas_are_consistent():
    # 偷窃必须是关系变差、怨念变高，否则"记仇"这个核心玩法就不成立。
    aff, trust, grudge = ACTION_DELTAS["steal"]
    assert aff < 0 and trust < 0 and grudge > 0
    # 赠送必须是关系变好、怨念下降。
    aff, trust, grudge = ACTION_DELTAS["gift"]
    assert aff > 0 and trust > 0 and grudge < 0


def test_plot_id_is_stable():
    assert PLOT_CROWN_THEFT == "plot_crown_theft"


def test_request_hash_is_order_independent():
    a = {"player_id": "p", "message": "偷", "npc_id": "mayor"}
    b = {"npc_id": "mayor", "message": "偷", "player_id": "p"}
    assert request_hash(a) == request_hash(b)


def test_request_hash_differs_on_content():
    a = {"player_id": "p", "message": "偷"}
    b = {"player_id": "p", "message": "送"}
    assert request_hash(a) != request_hash(b)


def test_player_id_pattern():
    assert PLAYER_ID_PATTERN.match("player_1")
    assert PLAYER_ID_PATTERN.match("a.b:c-d_e")
    assert not PLAYER_ID_PATTERN.match("bad id!")
    assert not PLAYER_ID_PATTERN.match("")
    assert not PLAYER_ID_PATTERN.match("x" * 65)


def test_session_id_pattern():
    assert SESSION_ID_PATTERN.match("conv-1234")
    assert not SESSION_ID_PATTERN.match("bad id!")
    assert not SESSION_ID_PATTERN.match("x" * 129)


# ------------------------------------------------------------------- tiny runner

def _run_standalone() -> int:
    """没装 pytest 也能跑。"""

    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    failed = 0
    for name, func in tests:
        try:
            func()
            print(f"[PASS] {name}")
        except AssertionError as error:
            failed += 1
            print(f"[FAIL] {name}: {error}")
        except Exception as error:  # noqa: BLE001
            failed += 1
            print(f"[ERROR] {name}: {type(error).__name__}: {error}")
    print(f"\n单元测试: {len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
