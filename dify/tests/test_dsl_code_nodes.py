"""契约测试：**DSL 里真正的 Code 节点源码** 与 **后端裁定逻辑** 必须一致。

⚠️ **这些是 Mock / 单元测试，不是端到端验收。**

这个文件回答一个很具体的问题：DSL 里嵌的那段 Python（``code_intent``、
``code_verdict``…）和后端 ``engine.resolve_intent`` 是不是在说同一件事？

做法是**从生成出来的 YAML 里把 Code 节点的源码抠出来直接跑** ——
不是复制一份到测试里（复制品会漂移），而是读真实产物。

所以只要有人改了 ``scripts/build_dsl.py`` 里的逻辑、又忘了改后端，
这个测试立刻会红。

运行::

    python -m pytest dify/tests/test_dsl_code_nodes.py -q
    python dify/tests/test_dsl_code_nodes.py        # 不装 pytest 也能跑
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent / "app"
DSL_PATH = APP_DIR / "memory-town-chatflow.yml"
BACKEND_ROOT = HERE.parent / "backend"
for _path in (str(BACKEND_ROOT), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from town_backend.engine import (  # noqa: E402
    COMMITTED_ACTIONS,
    HIGH_IMPACT_ACTIONS,
    HIGH_IMPACT_MIN_CONFIDENCE,
    COMMITTED_MIN_CONFIDENCE,
    ACTION_TYPES,
    ITEM_REQUIRED_ACTIONS,
)


def _load_yaml() -> dict[str, Any]:
    import yaml

    return yaml.safe_load(DSL_PATH.read_text(encoding="utf-8"))


def _code_source(node_id: str) -> str:
    """Extract a Code node's source from the *generated* DSL."""

    graph = _load_yaml()["workflow"]["graph"]
    for node in graph["nodes"]:
        if node["id"] == node_id:
            return node["data"]["code"]
    raise AssertionError(f"DSL 里没有节点 {node_id}")


def _run(node_id: str, **kwargs: Any) -> dict[str, Any]:
    """Execute a Code node's source the way Dify's code node does."""

    namespace: dict[str, Any] = {"__name__": "__dsl_code_node__"}
    exec(compile(_code_source(node_id), f"<{node_id}>", "exec"), namespace)
    return namespace["main"](**kwargs)


# --------------------------------------------------------------------- 用例


def test_dsl_code_intent_parses_valid_model_output() -> None:
    out = _run(
        "code_intent",
        model_text='{"action_type":"steal","target_npc":"mayor","target_item":"golden_crown",'
                   '"target_location":"","intent_confidence":0.9,"is_committed_action":true,'
                   '"original_text":"我要偷走王冠"}',
        query_text="我要偷走王冠",
    )
    assert out["intent_ok"] is True
    assert out["action_type"] == "steal"
    assert out["target_item"] == "golden_crown"
    assert out["is_committed_action"] is True


def test_dsl_code_intent_rejects_unparseable_model_output() -> None:
    """模型输出不是 JSON → 降级，且必须告诉后端"输出不可解析"。

    这里**不能**传 ``null``：``null`` 在后端意味着"模型压根没回话"，
    后端会走保守的关键词降级路径 —— 于是"我要偷走镇长的金王冠"
    会被执行成一次真实的偷窃。而模型输出损坏与模型不可用是**两回事**：
    一个连 JSON 都写不对的模型，它的输出不该被当成执行指令。

    所以这里传一个显式的 ``__unparseable__`` 标记，后端据此只当闲聊。
    """

    out = _run("code_intent", model_text="我觉得你该把王冠还回去", query_text="嗯")
    assert out["intent_ok"] is False
    assert out["action_type"] == "unknown"
    assert out["intent_json"] == '{"__unparseable__": true}'
    assert out["is_committed_action"] is False


def test_dsl_code_intent_sends_null_when_the_model_is_silent() -> None:
    """模型**没回话** → 传 null，让后端走它自己的保守关键词路径。

    这与"输出损坏"是两条不同的路：保守路径本身是安全的
    （要求明确的"我要做"信号 + 明确的道具名），而且它是 V1 的行为。
    """

    out = _run("code_intent", model_text="", query_text="我要偷走王冠")
    assert out["intent_ok"] is False
    assert out["intent_json"] == "null"


def test_dsl_code_intent_resolves_chinese_aliases_to_ids() -> None:
    """模型给中文名时必须翻译回 id，否则玩家说了目的地却走不出去。

    模型天然会用"镇长办公室""王冠"这种中文名；表外的东西一律丢掉，
    但白名单里的中文别名要能翻译回来。
    """

    out = _run(
        "code_intent",
        model_text='{"action_type":"move","target_location":"镇长办公室",'
                   '"target_npc":"镇长","target_item":"王冠",'
                   '"intent_confidence":0.9,"is_committed_action":true}',
        query_text="我要去镇长办公室",
    )
    assert out["target_location"] == "mayor_house"
    assert out["target_npc"] == "mayor"
    assert out["target_item"] == "golden_crown"


def test_dsl_code_intent_does_not_guess_unknown_aliases() -> None:
    """白名单外的中文名必须被丢掉 —— 模糊匹配会把"小镇"认成办公室。"""

    out = _run(
        "code_intent",
        model_text='{"action_type":"move","target_location":"火星基地",'
                   '"intent_confidence":0.9,"is_committed_action":true}',
        query_text="我要去火星基地",
    )
    assert out["target_location"] == ""
    # 没有合法目的地 → 降级为闲聊，绝不放行
    assert out["action_type"] == "talk"
    assert out["is_committed_action"] is False


def test_dsl_code_intent_fences_and_surrounding_text() -> None:
    """模型爱加 ```json 包裹和前后废话 —— 必须照样抠得出来。"""

    out = _run(
        "code_intent",
        model_text='好的，这是结果：\n```json\n{"action_type":"talk","intent_confidence":0.9,'
                   '"is_committed_action":false}\n```\n希望有帮助。',
        query_text="你好",
    )
    assert out["intent_ok"] is True
    assert out["action_type"] == "talk"


def test_dsl_code_intent_drops_unknown_ids() -> None:
    """模型凭空发明的 NPC / 地点 / 道具必须被丢掉。"""

    out = _run(
        "code_intent",
        model_text='{"action_type":"steal","target_npc":"dragon_lord","target_item":"meteor",'
                   '"target_location":"mars","intent_confidence":0.99,"is_committed_action":true}',
        query_text="偷",
    )
    assert out["target_npc"] == ""
    assert out["target_item"] == ""
    assert out["target_location"] == ""
    # 道具被丢掉后，高影响动作必须降级为普通对话。
    assert out["action_type"] == "talk"
    assert out["is_committed_action"] is False


def test_dsl_code_intent_low_confidence_high_impact_is_downgraded() -> None:
    """高影响动作置信度不够 → 绝不放行。"""

    out = _run(
        "code_intent",
        model_text='{"action_type":"steal","target_npc":"mayor","target_item":"golden_crown",'
                   f'"intent_confidence":{HIGH_IMPACT_MIN_CONFIDENCE - 0.01},'
                   '"is_committed_action":true}',
        query_text="偷",
    )
    assert out["action_type"] == "talk"
    assert out["is_committed_action"] is False
    assert "置信度" in out["intent_note"]


def test_dsl_code_intent_low_confidence_committed_is_downgraded() -> None:
    out = _run(
        "code_intent",
        model_text='{"action_type":"move","target_location":"back_alley",'
                   f'"intent_confidence":{COMMITTED_MIN_CONFIDENCE - 0.01},'
                   '"is_committed_action":true}',
        query_text="去后巷",
    )
    assert out["action_type"] == "talk"
    assert out["is_committed_action"] is False


def test_dsl_code_intent_not_committed_is_downgraded() -> None:
    """模型自己说"这只是个讨论" → 不能变成真实动作。"""

    out = _run(
        "code_intent",
        model_text='{"action_type":"steal","target_npc":"mayor","target_item":"golden_crown",'
                   '"intent_confidence":0.95,"is_committed_action":false}',
        query_text="如果我把王冠偷走会怎么样？",
    )
    assert out["action_type"] == "talk"
    assert out["is_committed_action"] is False


def test_dsl_code_intent_move_requires_destination() -> None:
    out = _run(
        "code_intent",
        model_text='{"action_type":"move","target_location":"","intent_confidence":0.95,'
                   '"is_committed_action":true}',
        query_text="我要走",
    )
    assert out["action_type"] == "talk"


def test_dsl_code_intent_bribe_does_not_require_a_named_item() -> None:
    """回归 ①：贿赂不该被"必须点名道具"压成闲聊。

    当时：模型给的 ``bribe`` 候选完全正确（对象是人，用什么贿赂
    可以由后端按玩家手上的东西决定），但 DSL 校验节点把
    ``bribe`` 也算进了"必须点名道具"的高影响动作，于是这一轮
    降级成 talk —— 玩家永远送不出那袋小鱼干。
    """

    out = _run(
        "code_intent",
        model_text='{"action_type":"bribe","target_npc":"cat_detective","target_item":"",'
                   '"intent_confidence":1.0,"is_committed_action":true}',
        query_text="我要贿赂墨墨",
    )
    assert out["action_type"] == "bribe"
    assert out["target_npc"] == "cat_detective"
    assert out["is_committed_action"] is True


def test_dsl_code_intent_steal_still_requires_a_named_item() -> None:
    """回归 ①的边界：偷 / 送 / 还**仍然**必须点名道具。"""

    for action in ("steal", "gift", "return_item"):
        out = _run(
            "code_intent",
            model_text=f'{{"action_type":"{action}","target_npc":"mayor","target_item":"",'
                       '"intent_confidence":1.0,"is_committed_action":true}',
            query_text="我要干点什么",
        )
        assert out["action_type"] == "talk", f"{action} 缺道具名时不该放行"


def test_dsl_code_intent_item_required_set_matches_backend() -> None:
    """DSL 的"必须点名道具"集合必须与后端一致。"""

    source = _code_source("code_intent")
    assert "ITEM_REQUIRED_ACTIONS" in source
    for action in ITEM_REQUIRED_ACTIONS:
        assert f'"{action}"' in source
    assert "bribe" not in ITEM_REQUIRED_ACTIONS


def test_dsl_code_intent_thresholds_match_backend() -> None:
    """DSL 的门槛必须与后端的门槛一模一样。

    两层都用同一组数字，任何一边改动另一边没跟上，这个测试会红。
    """

    source = _code_source("code_intent")
    assert f"HIGH_IMPACT_MIN_CONFIDENCE = {HIGH_IMPACT_MIN_CONFIDENCE}" in source
    assert f"COMMITTED_MIN_CONFIDENCE = {COMMITTED_MIN_CONFIDENCE}" in source
    # 高影响集合必须与后端一致
    for action in HIGH_IMPACT_ACTIONS:
        assert f'"{action}"' in source
    for action in COMMITTED_ACTIONS:
        assert f'"{action}"' in source


def test_dsl_code_intent_action_vocabulary_matches_backend() -> None:
    """模型能输出的动作类型必须与后端认识的完全一致。"""

    source = _code_source("code_intent")
    for action in ACTION_TYPES:
        assert f'"{action}"' in source, f"DSL 的动作表里缺少 {action}"


def test_dsl_code_verdict_reads_backend_verdict() -> None:
    """分支依据是**后端**的裁定，不是模型的自述。"""

    out = _run(
        "code_verdict",
        intent_body='{"ok":true,"intent":{"action_type":"steal","npc_id":"mayor",'
                    '"item_id":"golden_crown","is_committed_action":true,"rejection_reason":""}}',
        intent_code=200,
        fallback_npc="mayor",
    )
    assert out["verdict_ok"] is True
    assert out["verdict_action"] == "steal"
    assert out["verdict_committed"] is True
    assert out["verdict_npc_id"] == "mayor"


def test_dsl_code_verdict_reports_backend_rejection() -> None:
    """后端拒绝时必须把拒绝原因带出来，不能装作没事。"""

    out = _run(
        "code_verdict",
        intent_body='{"ok":true,"intent":{"action_type":"talk","is_committed_action":false,'
                    '"rejection_reason":"这是在假设/讨论，没有真的发生"}}',
        intent_code=200,
        fallback_npc="mayor",
    )
    assert out["verdict_action"] == "talk"
    assert out["verdict_committed"] is False
    assert out["verdict_rejection"] == "这是在假设/讨论，没有真的发生"
    assert "假设" in out["verdict_note"]


def test_dsl_code_verdict_handles_backend_failure() -> None:
    """裁定服务挂了 → 如实报告失败，绝不当作"可以执行"。"""

    out = _run(
        "code_verdict",
        intent_body='{"ok":false,"error":{"code":"internal_error","message":"后端炸了"}}',
        intent_code=500,
        fallback_npc="mayor",
    )
    assert out["verdict_ok"] is False
    assert out["verdict_committed"] is False
    assert "后端炸了" in out["verdict_note"]


def test_dsl_code_result_reports_rejection_as_failure() -> None:
    """后端 409 → 绝不能报成功。"""

    out = _run(
        "code_result",
        action_body='{"ok":false,"error":{"code":"item_not_owned","message":"你并不拥有道具"}}',
        action_code=409,
        query_text="还王冠",
        verdict_action="return_item",
        verdict_committed=True,
        verdict_note="",
        verdict_rejection="",
    )
    assert out["action_ok"] is False
    assert out["action_type"] == "rejected"
    assert out["state_changed"] is False
    assert "你并不拥有道具" in out["error_message"]


def test_dsl_code_result_idle_branch() -> None:
    """闲聊分支：action_code 为 None（http_action 根本没跑）。"""

    out = _run(
        "code_result",
        action_body="",
        action_code=None,
        query_text="今天天气不错",
        verdict_action="talk",
        verdict_committed=False,
        verdict_note="你只是说了句话，没有人记账。",
        verdict_rejection="",
    )
    assert out["action_ok"] is True
    assert out["state_changed"] is False
    assert out["action_label"] == "闲聊"


def test_dsl_code_result_success_extracts_facts() -> None:
    body = (
        '{"ok":true,'
        '"action":{"action_type":"steal","action_label":"偷窃","outcome":"你被当场抓住。"},'
        '"relationship":{"affinity":-15,"trust":20,"grudge_level":25},'
        '"plot":{"plot_id":"plot_crown_theft","stage":"investigating","detail":"镇长开始调查"},'
        '"quest":{"title":"王冠疑案","stage":"active","progress":1,"required":3},'
        '"ending":{"title":"洗白","summary":"你洗清了嫌疑"},'
        '"key_event":"你偷走了金王冠","npc_note":"镇长记恨上了你","notes":["王冠到手"]}'
    )
    out = _run(
        "code_result",
        action_body=body,
        action_code=200,
        query_text="我要偷走王冠",
        verdict_action="steal",
        verdict_committed=True,
        verdict_note="",
        verdict_rejection="",
    )
    assert out["action_ok"] is True
    assert out["action_type"] == "steal"
    assert "怨念 25" in out["relationship_block"]
    assert "investigating" in out["plot_block"]
    assert "1/3" in out["quest_block"]
    assert "洗白" in out["ending_block"]
    assert out["key_event"] == "你偷走了金王冠"


def test_dsl_code_clean_strips_thinking_blocks() -> None:
    """模型的内部推理绝不能出现在玩家眼前。"""

    out = _run(
        "code_clean",
        llm_text="<think>让我想想…玩家偷了王冠，我应该生气</think>根据镇规第三条，你给我站住！",
    )
    assert "<think>" not in out["speech"]
    assert "让我想想" not in out["speech"]
    assert "根据镇规第三条" in out["speech"]


def test_dsl_code_clean_strips_unclosed_think_block() -> None:
    out = _run("code_clean", llm_text="<think>还没说完就被截断了")
    assert "<think>" not in out["speech"]


def test_dsl_code_clean_removes_wrapping_quotes() -> None:
    out = _run("code_clean", llm_text='"根据镇规第三条，你给我站住！"')
    assert out["speech"] == "根据镇规第三条，你给我站住！"


def test_dsl_code_input_rejects_bad_player_id() -> None:
    out = _run(
        "code_input",
        player_id="bad id with spaces!",
        session_id="s",
        conversation_id="c",
        query="你好",
    )
    assert out["input_ok"] is False
    assert out["player_id"] == ""
    assert "玩家ID" in out["input_error"]


def test_dsl_code_input_escapes_json() -> None:
    """玩家输入里的引号不能破坏后面拼出来的 JSON 请求体。"""

    out = _run(
        "code_input",
        player_id="p1",
        session_id="s",
        conversation_id="c",
        query='他说"偷"王冠',
    )
    assert out["input_ok"] is True
    import json as _json

    assert _json.loads(f'"{out["query_json"]}"') == '他说"偷"王冠'


def test_dsl_http_nodes_keep_v1_409_semantics() -> None:
    """V1 的 409 处理语义必须保住。

    ``error_strategy`` 未设置 ⇒ Dify 不把非 2xx 当成节点失败，
    ``status_code`` / ``body`` 仍然留在输出里；``retry_enabled`` 为 false
    ⇒ 不会把一次合法的 409 变成超时重试。
    """

    graph = _load_yaml()["workflow"]["graph"]
    http_nodes = [n for n in graph["nodes"] if n["data"].get("type") == "http-request"]
    assert http_nodes, "DSL 里应该有 HTTP 节点"
    for node in http_nodes:
        data = node["data"]
        assert data.get("error_strategy") is None, f"{node['id']} 不该设置 error_strategy"
        assert data["retry_config"]["retry_enabled"] is False, f"{node['id']} 不该开自动重试"


def test_dsl_service_credential_only_in_masked_header() -> None:
    """服务凭据只能出现在会被掩码的 auth 头上，不能出现在普通 header 或 body 里。"""

    graph = _load_yaml()["workflow"]["graph"]
    http_nodes = [n for n in graph["nodes"] if n["data"].get("type") == "http-request"]
    for node in http_nodes:
        data = node["data"]
        assert data["authorization"]["config"]["header"] == "X-Town-Token"
        assert data["authorization"]["config"]["api_key"] == "{{#env.TOWN_BACKEND_TOKEN#}}"
        assert "TOWN_BACKEND_TOKEN" not in (data.get("headers") or "")
        assert "TOWN_BACKEND_TOKEN" not in str(data.get("body") or "")


def test_dsl_declares_token_as_empty_secret() -> None:
    """仓库里的 DSL 只能声明一个空值的环境变量 —— 真实值在部署时注入。"""

    env = _load_yaml()["workflow"]["environment_variables"]
    names = {v["name"]: v for v in env}
    assert "TOWN_BACKEND_TOKEN" in names
    token = names["TOWN_BACKEND_TOKEN"]
    assert token["value_type"] == "secret"
    assert token["value"] == ""


def test_dsl_branch_uses_backend_verdict_not_model_flag() -> None:
    """分支条件必须读**后端裁定**的 verdict_committed。

    如果读的是模型自己的标志，模型就能自己决定"这算不算一个动作"，
    整个信任边界就漏了。
    """

    graph = _load_yaml()["workflow"]["graph"]
    node = next(n for n in graph["nodes"] if n["id"] == "if_intent")
    selectors = {
        tuple(c["variable_selector"])
        for case in node["data"]["cases"]
        for c in case["conditions"]
    }
    assert ("code_verdict", "verdict_committed") in selectors
    assert ("code_intent", "is_committed_action") not in selectors


def test_dsl_action_request_carries_model_intent() -> None:
    """``/api/action`` 必须收到候选，否则后端会退回 V1 的关键词分类器。"""

    graph = _load_yaml()["workflow"]["graph"]
    node = next(n for n in graph["nodes"] if n["id"] == "http_action")
    body = node["data"]["body"]["data"][0]["value"]
    assert "{{#code_intent.intent_json#}}" in body
    assert "idempotency_key" in body


def test_dsl_all_nodes_use_supported_types() -> None:
    """只用 Dify 1.8.0 真正支持的节点类型 —— 不能生成导入不了的虚构节点。"""

    supported = {
        "start", "end", "answer", "llm", "knowledge-retrieval", "if-else",
        "code", "template-transform", "question-classifier", "http-request",
        "tool", "variable-aggregator", "legacy-variable-assigner", "loop",
        "loop-start", "loop-end", "iteration", "iteration-start",
        "parameter-extractor", "variable-assigner", "document-extractor",
        "list-operator", "agent",
    }
    graph = _load_yaml()["workflow"]["graph"]
    for node in graph["nodes"]:
        kind = node["data"].get("type")
        assert kind in supported, f"节点 {node['id']} 用了不支持的类型 {kind}"


def test_dsl_edges_reference_existing_nodes() -> None:
    graph = _load_yaml()["workflow"]["graph"]
    ids = {n["id"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in ids, f"边指向了不存在的节点 {edge['source']}"
        assert edge["target"] in ids, f"边指向了不存在的节点 {edge['target']}"


def test_dsl_code_node_outputs_match_declared_schema() -> None:
    """每个 Code 节点声明的输出，必须正好是它 main() 返回的键。

    Dify 对多一个或少一个键都会报 OutputValidationError。
    """

    for node_id in ("code_input", "code_state", "code_intent", "code_verdict",
                    "code_result", "code_reject", "code_clean", "code_format"):
        source = _code_source(node_id)
        namespace: dict[str, Any] = {"__name__": "__dsl_code_node__"}
        exec(compile(source, f"<{node_id}>", "exec"), namespace)
        declared = set(_declared_outputs(node_id))
        # 用一个能触发所有分支的假输入跑一遍，拿到真实返回键
        returned = set(_sample_call(node_id, namespace["main"]))
        assert returned == declared, (
            f"{node_id} 的返回键 {sorted(returned)} 与声明的 {sorted(declared)} 不一致"
        )


def test_dsl_every_code_node_compiles() -> None:
    """DSL 里**每个** Code 节点都必须能编译。

    生成器把代码原样写进 YAML 的块标量，所以源码里一个没转义的
    换行就会变成字符串字面量里的断行 —— 运行时才炸成
    SyntaxError，答案直接变空。这里在构建期就把它挡住。
    """

    graph = _load_yaml()["workflow"]["graph"]
    code_nodes = [n for n in graph["nodes"] if n["data"].get("type") == "code"]
    assert code_nodes, "DSL 里一个 Code 节点都没有，这说明生成器坏了"
    for node in code_nodes:
        source = node["data"]["code"]
        try:
            compile(source, f"<{node['id']}>", "exec")
        except SyntaxError as error:
            raise AssertionError(
                f"节点 {node['id']} 的代码无法编译：{error}\n"
                f"--- 附近内容 ---\n" + _context_around(source, error.lineno or 1)
            ) from error


def _context_around(source: str, lineno: int, span: int = 3) -> str:
    lines = source.splitlines()
    low = max(0, lineno - 1 - span)
    high = min(len(lines), lineno + span)
    return "\n".join(
        f"{'>>' if i + 1 == lineno else '  '} {i + 1}: {lines[i]}"
        for i in range(low, high)
    )


def test_dsl_code_format_renders_the_required_sections() -> None:
    """玩家看到的排版必须是任务书要求的那五段。"""

    node_id = "code_format"
    namespace: dict[str, Any] = {"__name__": "__dsl_code_node__"}
    exec(compile(_code_source(node_id), f"<{node_id}>", "exec"), namespace)
    main = namespace["main"]

    out = main(
        speech="镇长清了清嗓子。",
        location_name="小镇广场",
        action_label="闲聊",
        outcome="墨墨记下了你的一笔好。",
        relationship_block="墨墨 好感 +2",
        plot_block="剧情阶段：调查",
        quest_block="当前任务：找到王冠",
        ending_block="",
        notes_block="",
        error_message="",
        rejection_reason="",
        state_changed=True,
        action_ok=True,
        action_type="talk",
        location_people_block="- 墨墨（猫咪侦探）",
        inventory_block="- 小鱼干 ×1",
        coins=30,
    )
    text = out["formatted"]
    for section in ("【当前地点】", "【NPC 对话与剧情】", "【行动结果】",
                    "【状态变化】", "【可尝试的行动】"):
        assert section in text, f"输出缺少段落 {section}：{text!r}"
    # 地点名要在"当前地点"里
    assert "小镇广场" in text
    # markdown 的 "- " 列表符不该出现在玩家看的地方
    assert "- 墨墨" not in text, f"玩家看的地方漏出了 markdown 列表符：{text!r}"
    # 空段落不该占位
    assert "【状态变化】\n\n" not in text


def test_dsl_code_format_dedupes_repeated_outcome() -> None:
    """同一句话只说一次 —— 重复的报错信息不该出现两遍。"""

    namespace: dict[str, Any] = {"__name__": "__dsl_code_node__"}
    exec(compile(_code_source("code_format"), "<code_format>", "exec"), namespace)
    main = namespace["main"]

    out = main(
        speech="墨墨翻了个身。",
        location_name="神秘后巷",
        action_label="闲聊",
        outcome="没有「golden_crown」这样的道具",
        relationship_block="",
        plot_block="",
        quest_block="",
        ending_block="",
        notes_block="",
        error_message="没有「golden_crown」这样的道具",
        rejection_reason="",
        state_changed=False,
        action_ok=True,
        action_type="talk",
        location_people_block="",
        inventory_block="",
        coins=0,
    )
    text = out["formatted"]
    assert text.count("没有「golden_crown」这样的道具") == 1, text


def _declared_outputs(node_id: str) -> list[str]:
    graph = _load_yaml()["workflow"]["graph"]
    node = next(n for n in graph["nodes"] if n["id"] == node_id)
    return list(node["data"]["outputs"].keys())


def _sample_call(node_id: str, main: Any) -> dict[str, Any]:
    """Call a Code node's main() with a plausible input."""

    if node_id == "code_input":
        return main("p1", "s", "c", "你好")
    if node_id == "code_state":
        return main('{"npcs":[],"player":{}}', 200, "你好")
    if node_id == "code_intent":
        return main('{"action_type":"talk"}', "你好")
    if node_id == "code_verdict":
        return main('{"intent":{}}', 200, "mayor")
    if node_id == "code_result":
        return main("{}", 200, "你好", "talk", False, "", "")
    if node_id == "code_reject":
        return main("坏ID", 400, "", "")
    if node_id == "code_clean":
        return main("你好")
    if node_id == "code_format":
        return main(
            speech="镇长清了清嗓子。", location_name="小镇广场",
            action_label="闲聊", outcome="好感 +2", relationship_block="",
            plot_block="", quest_block="", ending_block="", notes_block="",
            error_message="", rejection_reason="", state_changed=False,
            action_ok=True, action_type="talk", location_people_block="",
            inventory_block="", coins=0,
        )
    raise AssertionError(node_id)


def _run_all() -> int:
    """Run every test without pytest."""

    failures = 0
    for name, func in sorted(globals().items()):
        if not name.startswith("test_") or not callable(func):
            continue
        try:
            func()
        except Exception as error:  # noqa: BLE001
            failures += 1
            print(f"[FAIL] {name}: {type(error).__name__}: {error}")
        else:
            print(f"[PASS] {name}")
    print(f"\n{'全部通过' if not failures else f'{failures} 项失败'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
