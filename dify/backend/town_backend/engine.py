"""游戏规则引擎：把一次玩家动作变成状态变更与剧情推进。

**模型输出不可信。**  大模型只负责"理解玩家想干什么"和"生成台词"，
判定动作类型、扣道具、加好感、推进剧情、触发结局全部由本模块的确定性
代码完成。模型给出的任何数值都不会直接写进数据库。

V1 与 V2 的关系
---------------
V1 用关键词猜动作类型（``classify_action``）。V2 改成**双层**：

1. **模型给候选**：Dify 的 ``llm_intent`` 节点输出一段 JSON，
   说明玩家想做什么、目标是谁、置信度多少、是不是"真的要执行"。
2. **代码定案**（本模块）：候选必须通过这里的校验才生效 —— 置信度、
   ``is_committed``、动作是否合法、目标是否真的存在、道具是否真的在手里。
   任何一项不通过，就退化成 ``talk`` 或 ``unknown``。

``classify_action`` **没有删除**：它是模型不可用时的安全降级路径，
也是 V1 回归测试的锚点。但降级路径比模型路径更保守 ——
它要求明确的"我就要做"信号，并且**绝不把模糊语句变成偷窃**。

三个结局（洗白 / 全镇公敌 / 悬案大师）全部由本模块根据**权威数值**判定，
不参考模型说了什么。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .memory import KIND_KEY_EVENT, KIND_NPC_NOTE, MemoryStore
from .store import SeekDBStore, StoreError

# ---------------------------------------------------------------- 动作类型

#: V1 的关键词表。保留有两个理由：
#: 1. V1 的单元测试直接调用 ``classify_action``，删掉会造成回归；
#: 2. 模型不可用时它就是降级路径。
#:
#: 关键词按"专指程度"加权：越长的词越专指，权重越高。
#: 例如"我要给你一个恶作剧"同时命中赠送的"给"(1 字)和恶作剧的"恶作剧"(3 字)，
#: 加权后恶作剧胜出；单纯按字典顺序匹配会把它误判成赠送。
#:
#: **只放动作动词，不要放道具名。** V1 的这张表里混进了"小鱼干"，
#: 于是"我要偷走墨墨的油炸小鱼干"里赠送拿到 3 分、偷窃只拿到
#: "偷走"的 2 分 —— 一次**偷窃**被记成了**赠送**，而且道具还从
#: 货架上取走了（偷的东西根本不在墨墨手里）。道具名归
#: :data:`ITEM_ALIASES` 管，那是"玩家在说哪件东西"的问题，
#: 不是"玩家想做什么动作"的问题。
ACTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "steal": ("偷", "拿走", "抢", "顺走", "摸走", "窃", "盗", "steal", "偷走"),
    "gift": ("送", "给", "赠", "递", "礼物", "gift", "赠送"),
    "prank": ("恶作剧", "捉弄", "吓", "恶搞", "捉", "搞", " prank", "玩笑", "偷袭"),
    "investigate": ("调查", "查看", "搜", "查", "探查", "翻", "inquire", "调查一下"),
    "return_item": ("归还", "还回", "还给你", "还给", "交还", "退回", "return"),
    "apologize": ("道歉", "对不起", "我错了", "sorry", "apolog"),
    "bribe": ("贿赂", "收买", "打点", "塞钱", "bribe"),
}

#: 加权得分相同时的优先级：越靠前越优先。
#: V1 的四项顺序原样保留在最前，V2 新增的排在后面 —— 这样 V1 的
#: ``classify_action`` 行为在同样的输入下完全不变。
ACTION_PRIORITY = (
    "steal", "prank", "gift", "investigate",
    "return_item", "apologize", "bribe",
)

#: V2 全部动作类型。
ACTION_TYPES: tuple[str, ...] = (
    "talk",
    "prank",
    "gift",
    "steal",
    "return_item",
    "apologize",
    "investigate",
    "move",
    "help",
    "unknown",
    "bribe",
)

ACTION_LABELS = {
    "talk": "闲聊",
    "prank": "恶作剧",
    "gift": "赠送道具",
    "steal": "偷窃",
    "return_item": "归还道具",
    "apologize": "道歉",
    "investigate": "调查",
    "move": "移动",
    "help": "查看玩法",
    "unknown": "不明举动",
    "bribe": "贿赂",
}

#: 每种动作对关系数值的影响。(好感, 信任, 怨念)
#: V1 的五个数值保持不变 —— V1 的验收脚本按这些数字断言。
ACTION_DELTAS: dict[str, tuple[int, int, int]] = {
    "talk": (2, 1, 0),
    "prank": (-8, -5, 12),
    "gift": (6, 8, -3),
    "steal": (-15, -20, 25),
    "investigate": (0, 2, 0),
    "return_item": (10, 15, -30),
    "apologize": (8, 10, -18),
    "move": (0, 0, 0),
    "help": (0, 0, 0),
    "bribe": (0, 0, 0),
    "unknown": (0, 0, 0),
}

#: 只有这些动作会真的改变世界。
COMMITTED_ACTIONS: frozenset[str] = frozenset(
    {"prank", "gift", "steal", "return_item", "apologize", "move", "investigate", "bribe"}
)

#: 高影响动作：语义不清时**绝不**执行，直接退化成对话。
#: 偷窃会改变道具归属和剧情阶段，不可撤销，必须要求高置信度。
HIGH_IMPACT_ACTIONS: frozenset[str] = frozenset({"steal", "gift", "return_item", "bribe"})

#: 高影响动作里，**必须点名道具**的那些。
#:
#: 贿赂不在其中：贿赂的对象是人，说"我要贿赂墨墨"就是一个成立的
#: 贿赂意图。至于拿什么去贿赂，由 :meth:`_resolve_bribe_item` 按玩家
#: **手上**的东西决定 —— 找不到就如实报错，不会凭空变出一件道具。
ITEM_REQUIRED_ACTIONS: frozenset[str] = frozenset({"steal", "gift", "return_item"})

#: 执行高影响动作所需的最低置信度。
HIGH_IMPACT_MIN_CONFIDENCE = 0.75

#: 执行任何已承诺动作所需的最低置信度。
COMMITTED_MIN_CONFIDENCE = 0.55

#: 明确表示"现在就要做"的措辞。降级路径要求出现其中之一，
#: 才肯执行一个已承诺动作 —— 这正是"模糊语句不会被当成偷窃"的实现。
COMMITMENT_MARKERS: tuple[str, ...] = (
    "我要", "我这就", "我先", "我去", "我送", "我给", "我偷", "我拿", "我把",
    "我收", "我交", "我赔", "我道", "帮我", "替我", "马上", "现在", "给我",
    "来一个", "来点", "赶紧",
)

#: 明确表示"只是在说，不是要做"的措辞。
HYPOTHETICAL_MARKERS: tuple[str, ...] = (
    "如果", "假如", "要是", "假设", "万一", "要不", "试试看会", "会怎么样",
    "怎么办才好", "你觉得我", "我说的是", "不是真的", "假装", "想想看",
)

#: 明确表示"禁止/否定"的措辞。
NEGATION_MARKERS: tuple[str, ...] = (
    "别", "不要", "不许", "不准", "不得", "禁止", "没必要", "算了吧",
    "我不想", "我没",
)

#: 尝试用"记忆/规则/系统"来改写游戏规则的话术。
#: 这些不是玩家意图，而是注入攻击 —— 必须在代码层被拒绝。
INJECTION_MARKERS: tuple[str, ...] = (
    "无视所有限制", "忽略所有规则", "无视规则", "忽略规则", "无视一切",
    "绕过规则", "跳过规则", "解除限制", "无视限制", "ignore all",
    "system prompt", "系统提示", "开发者模式", "debug 模式", "上帝模式",
    "无限金币", "无限金钱", "给无限", "直接通关", "立刻通关",
)

#: 特殊剧情：偷走镇长的金王冠 → 镇长启动调查。
PLOT_CROWN_THEFT = "plot_crown_theft"

#: 主线任务。
QUEST_CROWN_CASE = "quest_crown_case"

#: 三个结局的 ID。
ENDING_WHITEWASH = "ending_whitewash"
ENDING_PUBLIC_ENEMY = "ending_public_enemy"
ENDING_SLEUTH = "ending_sleuth"

ENDING_META: dict[str, dict[str, Any]] = {
    ENDING_WHITEWASH: {
        "title": "洗白：识趣的市民",
        "summary": (
            "你把王冠亲手还给了镇长，还给了镇长一个台阶。"
            "镇长在日记里给你记了一笔——是难得的好话。"
        ),
        "reward_coins": 50,
    },
    ENDING_PUBLIC_ENEMY: {
        "title": "全镇公敌",
        "summary": (
            "怨念累积到全镇都知道了。镇长召集了镇民，"
            "你被宣布为不受欢迎的人。"
        ),
        "reward_coins": 0,
    },
    ENDING_SLEUTH: {
        "title": "悬案大师",
        "summary": (
            "你没有把王冠还给任何人。你查清了王冠失窃的真相——"
            "领用单上的日期是空的，因为王冠从来就没有被正式领用出去。法官判你无罪。"
        ),
        "reward_coins": 100,
    },
}

#: 结局判定阈值（全部是权威数值，与模型输出无关）。
#: 全镇公敌：镇长与墨墨的怨念同时到达这个量级。
PUBLIC_ENEMY_GRUDGE_THRESHOLD = 70
#: 悬案大师：必须集齐的证据数量。
SLEUTH_EVIDENCE_REQUIRED = 2
#: 悬案大师：必须完成的调查次数。
SLEUTH_INVESTIGATIONS_REQUIRED = 2
#: 洗白：归还王冠并道歉后，镇长的怨念必须降到这个值以下。
WHITEWASH_GRUDGE_MAX = 40

#: 会被 NPC 记恨的关键事件阈值
GRUDGE_KEY_THRESHOLD = 20

#: 调查哪个 NPC 可以拿到哪件证据。证据是"悬案大师"结局的关键材料。
#: 前提：NPC 必须**确实知道**这件事 —— 线索的来源必须是"该 NPC 亲历或亲查"。
EVIDENCE_SOURCES: dict[str, str] = {
    "cat_detective": "alley_witness_note",
    "crow_judge": "crown_receipt",
}

#: 道具的别称。玩家说"一条小鱼干"时要能匹配到道具"油炸小鱼干"。
ITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "golden_crown": ("金王冠", "王冠", "皇冠", "crown", "gold crown"),
    "fat_fish_snack": ("小鱼干", "鱼干", "零食", "snack", "fish"),
    "fish_premium": ("进口小鱼干", "小鱼干", "鱼干"),
    "old_notebook": ("账本", "笔记本", "notebook"),
    "mayor_seal": ("印章", "seal"),
    "crown_receipt": ("领用单", "receipt", "单据"),
    "alley_witness_note": ("便条", "纸条", "目击者", "note"),
    "town_badge": ("铜徽", "徽章", "badge"),
}


def match_item(text: str, items: list[dict[str, Any]]) -> str:
    """Find the item the player is talking about.

    Matches the item name first, then the aliases. The alias list matters
    because players say "一条小鱼干" while the item is named "油炸小鱼干".
    """

    lowered = (text or "").lower()
    for item in items:
        if item["name"].lower() in lowered:
            return item["item_id"]
    for item in items:
        for alias in ITEM_ALIASES.get(item["item_id"], ()):
            if alias.lower() in lowered:
                return item["item_id"]
    return ""


def classify_action(raw_text: str, model_hint: str | None = None) -> str:
    """Decide the action type by keyword.

    The model's hint is accepted only when it is a known type *and* the
    player's text carries no contradicting keyword. The keyword scan is the
    authority; the model merely breaks ties when the text is ambiguous.

    这是 V1 的分类器，V2 仍然保留：它是模型不可用时的降级路径，
    也是 V1 回归测试的锚点。
    """

    text = (raw_text or "").lower()

    # 加权打分：命中的关键词越长越专指，得分越高；得分相同时按 ACTION_PRIORITY。
    best_action = ""
    best_score = 0
    for action in ACTION_PRIORITY:
        score = 0
        for keyword in ACTION_KEYWORDS[action]:
            if keyword in text:
                score = max(score, len(keyword))
        if score > best_score:
            best_action = action
            best_score = score

    if best_action:
        return best_action

    if model_hint in ACTION_DELTAS:
        return model_hint
    return "talk"


def resolve_target(text: str, npcs: list[dict[str, Any]]) -> str:
    """Pick the NPC the player is addressing.

    A mention of the NPC's name wins; otherwise the first NPC at the
    player's location is used.
    """

    matched = match_target_npc(text, npcs)
    if matched:
        return matched
    return npcs[0]["npc_id"] if npcs else "mayor"


def match_target_npc(text: str, npcs: list[dict[str, Any]]) -> str:
    """Return the NPC the player *named*, or "" when they named nobody.

    调用方（DSL / API）往往已经根据"谁对你有怨谁出面"选好了对话对象。
    这里**只**在玩家明确点了名字时才改写它 —— 绝不用"第一个 NPC"
    去覆盖调用方的选择，否则 Dify 选中的记账人会被后端换掉。
    """

    lowered = (text or "").lower()
    for npc in npcs:
        for token in (npc["name"], npc["title"], npc["npc_id"]):
            if token and token.lower() in lowered:
                return npc["npc_id"]
    return ""


def request_hash(payload: dict[str, Any]) -> str:
    """Stable hash of a request, used to detect a changed repeat request."""

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 语义意图


@dataclass
class IntentCandidate:
    """One candidate action proposed by the model (or by the safe fallback)."""

    action_type: str
    target_npc: str = ""
    target_item: str = ""
    target_location: str = ""
    confidence: float = 0.0
    is_committed: bool = False
    original_text: str = ""
    source: str = "model"  # model | fallback | rejected

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target_npc": self.target_npc,
            "target_item": self.target_item,
            "target_location": self.target_location,
            "intent_confidence": round(self.confidence, 3),
            "is_committed_action": self.is_committed,
            "original_text": self.original_text,
            "source": self.source,
        }


@dataclass
class IntentResolution:
    """The verdict on a candidate: what will actually happen, and why."""

    action_type: str
    npc_id: str = ""
    item_id: str = ""
    target_location: str = ""
    confidence: float = 0.0
    is_committed: bool = False
    original_text: str = ""
    source: str = "model"
    rejection_reason: str = ""
    proposed_action: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def executed(self) -> bool:
        return self.is_committed

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "action_label": ACTION_LABELS.get(self.action_type, self.action_type),
            "npc_id": self.npc_id,
            "item_id": self.item_id,
            "target_location": self.target_location,
            "intent_confidence": round(self.confidence, 3),
            "is_committed_action": self.is_committed,
            "original_text": self.original_text,
            "source": self.source,
            "proposed_action": self.proposed_action,
            "rejection_reason": self.rejection_reason,
            "notes": list(self.notes),
        }


def _normalize_action(value: Any) -> str:
    """Map whatever the model produced onto a known action type."""

    text = str(value or "").strip().lower()
    if text in ACTION_TYPES:
        return text
    # 模型有时会输出中文标签或近义词
    aliases = {
        "闲聊": "talk", "聊天": "talk", "对话": "talk", "chat": "talk",
        "恶作剧": "prank", "捉弄": "prank", "恶搞": "prank", "prank": "prank",
        "赠送": "gift", "送": "gift", "gift": "gift", "送礼": "gift",
        "偷窃": "steal", "偷": "steal", "steal": "steal", "窃取": "steal",
        "归还": "return_item", "还": "return_item", "return": "return_item",
        "return_item": "return_item", "道歉": "apologize", "apologize": "apologize",
        "调查": "investigate", "investigate": "investigate", "查询": "investigate",
        "移动": "move", "move": "move", "前往": "move", "移动地点": "move",
        "帮助": "help", "help": "help", "玩法": "help",
        "未知": "unknown", "unknown": "unknown",
        "贿赂": "bribe", "bribe": "bribe", "收买": "bribe",
    }
    return aliases.get(text, "")


def parse_intent_payload(payload: str | dict[str, Any] | None) -> IntentCandidate | None:
    """Parse the model's JSON intent output.

    The model is not trusted to produce valid JSON, to produce only known
    fields, or to produce sane numbers — everything is clamped here.
    Returns ``None`` when the payload cannot be understood at all.

    ``None`` 有两种含义，调用方必须区分：

    * **模型不可用**（payload 是 ``None``）—— 模型压根没回话。
      这时可以走保守的关键词降级路径。
    * **模型回话了但输出不可解析**（payload 是非空字符串或字典）——
      模型答了，却答了个没法用的东西。这种情况下**绝不能**执行
      高影响动作：一个连 JSON 都写不对的模型，它的候选不可信。

    这两种情况用 :func:`parse_intent_payload_soft` 区分。
    """

    if payload is None:
        return None
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return None
        # 模型有时会用 ```json 包裹，或在 JSON 前后加话。
        fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        text = text[start : end + 1]
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
    elif isinstance(payload, dict):
        data = payload
    else:
        return None

    if not isinstance(data, dict):
        return None

    # Dify 的语义解析节点用它自己的标记告诉后端"模型回话了，但输出
    # 没法解析"。这**不是**"模型不可用"，必须区别对待。
    if data.get("__unparseable__"):
        return None

    action = _normalize_action(data.get("action_type"))
    if not action:
        return None

    try:
        confidence = float(data.get("intent_confidence", 0) or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    committed = data.get("is_committed_action")
    if isinstance(committed, str):
        committed = committed.strip().lower() in ("true", "1", "yes", "是")
    is_committed = bool(committed)

    return IntentCandidate(
        action_type=action,
        target_npc=str(data.get("target_npc") or "").strip(),
        target_item=str(data.get("target_item") or "").strip(),
        target_location=str(data.get("target_location") or "").strip(),
        confidence=confidence,
        is_committed=is_committed,
        original_text=str(data.get("original_text") or "").strip(),
    )


def parse_intent_payload_soft(
    payload: str | dict[str, Any] | None,
) -> tuple[IntentCandidate | None, str]:
    """Parse the model output, reporting **why** it failed.

    Returns ``(candidate, state)`` where ``state`` is one of:

    * ``"parsed"``   —— 候选有效。
    * ``"absent"``   —— 模型压根没给输出（不可用）。可以走降级路径。
    * ``"garbage"``  —— 模型给了输出但解析不出来。**不允许**执行
      高影响动作；这一轮只能当成普通对话。
    """

    if payload is None:
        return None, "absent"
    if isinstance(payload, str) and not payload.strip():
        return None, "absent"
    candidate = parse_intent_payload(payload)
    if candidate is None:
        return None, "garbage"
    return candidate, "parsed"


def is_injection_attempt(text: str) -> bool:
    """Does the player's text try to rewrite the game's rules?"""

    lowered = (text or "").lower()
    return any(marker in lowered for marker in INJECTION_MARKERS)


def is_hypothetical(text: str) -> bool:
    """Is the player only talking about an action rather than doing it?"""

    lowered = (text or "").lower()
    return any(marker in lowered for marker in HYPOTHETICAL_MARKERS)


def is_negated(text: str) -> bool:
    """Is the player refusing or prohibiting an action?"""

    lowered = (text or "").lower()
    return any(marker in lowered for marker in NEGATION_MARKERS)


def has_commitment_marker(text: str) -> bool:
    """Does the text say "I am doing this now"?"""

    lowered = (text or "").lower()
    return any(marker in lowered for marker in COMMITMENT_MARKERS)


# ---------------------------------------------------------------- 引擎


class GameEngine:
    """Applies a player action to the game state."""

    def __init__(self, store: SeekDBStore, memory: MemoryStore) -> None:
        self.store = store
        self.memory = memory

    # ------------------------------------------------------- 意图裁定

    def resolve_intent(
        self,
        player_id: str,
        raw_text: str,
        npcs: list[dict[str, Any]],
        *,
        model_intent: str | dict[str, Any] | None = None,
        default_npc_id: str = "mayor",
        current_location: str = "",
        requested_action: str = "",
    ) -> IntentResolution:
        """Decide what the player actually did.

        This is the trust boundary. The model proposes; this function disposes.

        Rejection order (first hit wins):

        1. 注入话术 → 拒绝，不执行任何动作。
        2. 纯假设句 → 不当作已承诺动作，退化成对话。
        3. 否定句 → 不当作已承诺动作，退化成对话。
        4. 模型没给出可用候选 → 走**保守的关键词降级路径**。
        5. 置信度不够 → 降级为 talk。
        6. 模型没说是"要执行"的动作 → 一律不当成已执行。
        7. 目标不存在 → 降级为 talk 并说明。

        ``requested_action`` 是调用方**已经裁定好**的动作类型
        （例如 Dify 的 HTTP 节点从后端裁定结果里取回来的值）。
        它只在"模型没给候选、只能走关键词降级路径"时被采纳 ——
        否则关键词分类器会用"给""送"这类字眼盖掉一个明确的动作类型，
        把一次偷窃变成一次赠送。
        """

        text = (raw_text or "").strip()
        resolution = IntentResolution(
            action_type="talk",
            npc_id=default_npc_id,
            original_text=text,
            confidence=0.0,
            is_committed=False,
        )

        # 1) 注入话术：直接拒绝，不给任何动作执行机会。
        if is_injection_attempt(text):
            resolution.action_type = "unknown"
            resolution.source = "rejected"
            resolution.rejection_reason = "检测到试图改写游戏规则的输入，已忽略"
            resolution.notes.append(resolution.rejection_reason)
            return resolution

        candidate, payload_state = parse_intent_payload_soft(model_intent)

        # 2) 假设句：即使模型说"这是要执行的偷窃"，也只是讨论。
        if is_hypothetical(text):
            resolution.action_type = "talk"
            resolution.source = "rejected" if candidate is None else candidate.source
            resolution.proposed_action = candidate.action_type if candidate else ""
            resolution.rejection_reason = "这是在假设/讨论，没有真的发生"
            resolution.confidence = candidate.confidence if candidate else 0.0
            resolution.notes.append(resolution.rejection_reason)
            return resolution

        # 3) 否定句："别偷王冠" —— 模型可能仍判成 steal，这里否决。
        if is_negated(text) and candidate is not None and candidate.action_type in HIGH_IMPACT_ACTIONS:
            resolution.action_type = "talk"
            resolution.source = "rejected"
            resolution.proposed_action = candidate.action_type
            resolution.rejection_reason = "玩家明确否定了这个动作"
            resolution.confidence = candidate.confidence
            resolution.notes.append(resolution.rejection_reason)
            return resolution

        # 3.5) 模型回话了但输出 unusable —— 一律当普通对话。
        #
        # 关键区分：模型**没回话**（absent）时可以走保守的关键词降级路径；
        # 但模型**回话了却输出乱码**（garbage）时，它的候选完全不可信，
        # 而降级路径会把"我要偷走王冠"这类句子判成偷窃。绝不能因为
        # 模型输出坏了，就把一次高影响动作执行掉。
        if payload_state == "garbage":
            resolution.action_type = "talk"
            resolution.source = "rejected"
            resolution.is_committed = False
            resolution.rejection_reason = (
                "语义解析结果不可用（模型输出无法解析），这一轮按普通对话处理，"
                "不会执行任何有后果的动作"
            )
            resolution.notes.append(resolution.rejection_reason)
            return resolution

        # 4) 模型没给出可用候选 → 保守的关键词降级路径。
        if candidate is None:
            return self._resolve_by_keyword(
                text, npcs, resolution, default_npc_id, requested_action)

        action = candidate.action_type
        resolution.action_type = action
        resolution.confidence = candidate.confidence
        resolution.source = candidate.source
        resolution.proposed_action = action
        resolution.original_text = candidate.original_text or text

        # 5) 置信度门槛。
        min_confidence = (
            HIGH_IMPACT_MIN_CONFIDENCE if action in HIGH_IMPACT_ACTIONS else COMMITTED_MIN_CONFIDENCE
        )
        if action in COMMITTED_ACTIONS and candidate.confidence < min_confidence:
            resolution.action_type = "talk"
            resolution.is_committed = False
            resolution.rejection_reason = (
                f"意图不够明确（置信度 {candidate.confidence:.2f} < {min_confidence:.2f}），"
                "按普通对话处理"
            )
            resolution.notes.append(resolution.rejection_reason)
            return resolution

        # 6) 模型没说是"要执行"的动作，一律不当成已执行。
        if action in COMMITTED_ACTIONS and not candidate.is_committed:
            resolution.action_type = "talk"
            resolution.is_committed = False
            resolution.rejection_reason = "这句话没有明确表示要现在做这件事"
            resolution.notes.append(resolution.rejection_reason)
            return resolution

        # 7) 目标 NPC 必须真实存在，否则降级。
        npc_ids = {npc.get("npc_id") for npc in npcs}
        target_npc = candidate.target_npc
        if target_npc and target_npc not in npc_ids:
            resolution.action_type = "talk"
            resolution.is_committed = False
            resolution.rejection_reason = f"找不到叫「{target_npc}」的人"
            resolution.notes.append(resolution.rejection_reason)
            return resolution

        if target_npc:
            resolution.npc_id = target_npc
        elif text:
            # 玩家点了谁的名字就找谁；没点名就**保留调用方选好的对象**
            # （Dify 按"谁对你有怨谁出面"挑人，后端不能换掉它）。
            named = match_target_npc(text, npcs)
            if named:
                resolution.npc_id = named
            elif npcs:
                resolution.npc_id = default_npc_id or npcs[0]["npc_id"]
            else:
                resolution.npc_id = default_npc_id

        # 目标地点必须真实存在。
        if action == "move":
            location = self._match_location(candidate.target_location, text)
            if not location:
                resolution.action_type = "talk"
                resolution.is_committed = False
                resolution.rejection_reason = f"不存在的地方「{candidate.target_location or text}」"
                resolution.notes.append(resolution.rejection_reason)
                return resolution
            resolution.target_location = location

        # 目标道具必须真实存在。模型说"偷王冠"而世界上没有王冠时，
        # 不能凭空造一件道具出来 —— 降级为对话。
        if action in ("steal", "gift", "return_item", "bribe") and candidate.target_item:
            item_id = self._match_item_id(candidate.target_item)
            if not item_id:
                resolution.action_type = "talk"
                resolution.is_committed = False
                resolution.rejection_reason = f"没有「{candidate.target_item}」这样的道具"
                resolution.notes.append(resolution.rejection_reason)
                return resolution
            resolution.item_id = item_id

        resolution.is_committed = action in COMMITTED_ACTIONS
        return resolution

    def _resolve_by_keyword(
        self,
        text: str,
        npcs: list[dict[str, Any]],
        resolution: IntentResolution,
        default_npc_id: str = "mayor",
        requested_action: str = "",
    ) -> IntentResolution:
        """The degraded path: keyword matching, but deliberately conservative.

        The rule this enforces is the one the V2 brief demands: **a vague
        keyword must never become a theft**. So an already-committed action
        needs both an explicit "I am doing this now" signal and, for theft
        and hand-back, an explicitly named item.

        ``requested_action`` 是调用方已经裁定的动作类型。采纳它**只在**
        它本身是一个合法的已承诺动作、且文本里没有与之矛盾的关键词时
        —— 否则"我要偷走王冠"里的"给"字会把偷窃变成赠送。
        """

        action = self._pick_keyword_action(text, requested_action)
        resolution.source = "fallback"
        resolution.proposed_action = action
        resolution.action_type = action
        resolution.confidence = 0.6 if action != "talk" else 0.3
        resolution.rejection_reason = "模型意图不可解析，已按保守规则处理"

        if action in COMMITTED_ACTIONS and not has_commitment_marker(text):
            resolution.action_type = "talk"
            resolution.is_committed = False
            resolution.rejection_reason = "没有明确表示要做这件事，按普通对话处理"
            resolution.notes.append(resolution.rejection_reason)
            return resolution

        if action in HIGH_IMPACT_ACTIONS:
            named = match_item(text, self._all_items())
            if action in ITEM_REQUIRED_ACTIONS and not named:
                # 没说清楚要动哪件东西 —— 绝不猜。
                resolution.action_type = "talk"
                resolution.is_committed = False
                resolution.rejection_reason = "没有指明要对哪件东西下手，按普通对话处理"
                resolution.notes.append(resolution.rejection_reason)
                return resolution

        named = match_target_npc(text, npcs)
        if named:
            resolution.npc_id = named
        elif npcs:
            resolution.npc_id = default_npc_id or npcs[0]["npc_id"]
        else:
            resolution.npc_id = default_npc_id or "mayor"
        resolution.is_committed = action in COMMITTED_ACTIONS
        return resolution

    @staticmethod
    def _pick_keyword_action(text: str, requested_action: str) -> str:
        """Choose between the keyword classification and the caller's verdict.

        关键词分类器是 V1 的锚点，不能动它的行为 —— V1 的回归测试
        钉死了同样的输入必须得到同样的动作。但它有一个已知弱点：
        "我要偷走墨墨的油炸小鱼干"里的"给"字会让赠送拿到 1 分，
        而"偷"也只拿到 1 分，两者打平后按优先级**赠送在前**，
        于是一次偷窃被记成了一次赠送。

        调用方已经裁定好的动作类型（``requested_action``）优先 ——
        但只在它是一个合法的已承诺动作、且文本里**没有更长、更专指**
        的关键词指向别的动作时才采纳。"更长者胜出"这条规则保留，
        所以"我要给你一个恶作剧"仍然判成恶作剧而不是赠送。
        """

        keyword_action = classify_action(text)
        if not requested_action or requested_action not in ACTION_TYPES:
            return keyword_action
        if requested_action not in COMMITTED_ACTIONS:
            return keyword_action

        # 计算关键词分类器给两个候选各打了多少分。
        text_lowered = (text or "").lower()
        scores: dict[str, int] = {}
        for action in {keyword_action, requested_action}:
            score = 0
            for keyword in ACTION_KEYWORDS.get(action, ()):
                if keyword in text_lowered:
                    score = max(score, len(keyword))
            scores[action] = score

        # 关键词更专指（分更高）就听关键词的；打平听调用方的 ——
        # 调用方拿到的是模型裁定 + 规则校验的结果，比关键词更可信。
        if scores[keyword_action] > scores[requested_action]:
            return keyword_action
        return requested_action

    def _match_item_id(self, hinted: str) -> str:
        """Resolve an item hint to a real item id.

        The model may give either the id (``golden_crown``) or the Chinese
        name (``金王冠``). Anything that does not resolve to an existing
        item returns ``""`` — the caller then refuses to act.
        """

        text = (hinted or "").strip()
        if not text:
            return ""
        items = self._all_items()
        for item in items:
            if item["item_id"].lower() == text.lower():
                return item["item_id"]
        return match_item(text, items)

    def _match_location(self, hinted: str, text: str) -> str:
        """Resolve a location by id or by Chinese name.

        模型给"镇长办公室"这样的中文名时要能翻译回 id，
        否则玩家说了目的地，动作却被降级成闲聊。
        """

        for location in self.store.list_locations():
            if not int(location.get("is_reachable", 1)):
                continue
            for hay in (hinted or "", text or ""):
                if not hay:
                    continue
                if location["location_id"].lower() in hay.lower():
                    return location["location_id"]
                if location["name"].lower() in hay.lower():
                    return location["location_id"]
        return ""

    # ------------------------------------------------------------ 动作执行

    def perform_action(
        self,
        player_id: str,
        session_id: str,
        npc_id: str,
        raw_text: str,
        *,
        action_hint: str | None = None,
        item_hint: str | None = None,
        location_hint: str | None = None,
        action_type: str = "",
        idempotency_key: str = "",
        commit: bool = True,
    ) -> ActionOutcome:
        """Resolve and apply one action.

        ``action_type`` is the *already validated* action type from
        :meth:`resolve_intent`. When it is empty, V1's keyword classifier
        is used — that keeps the V1 code path byte-for-byte equivalent.
        """

        npc = self.store.fetch_npc(npc_id)
        if npc is None:
            raise StoreError("unknown_npc", f"NPC {npc_id} 不存在")

        if action_type and action_type in ACTION_TYPES:
            resolved_action = action_type
        else:
            resolved_action = classify_action(raw_text, action_hint)

        outcome = ActionOutcome(
            action_type=resolved_action, npc_id=npc_id, player_id=player_id)

        if resolved_action == "gift":
            outcome.item_id = self._resolve_gift_item(player_id, npc_id, item_hint or raw_text, outcome)
        elif resolved_action == "steal":
            outcome.item_id = self._resolve_steal_item(npc_id, item_hint or raw_text, outcome)
        elif resolved_action == "return_item":
            outcome.item_id = self._resolve_return_item(player_id, npc_id, item_hint or raw_text, outcome)
        elif resolved_action == "bribe":
            outcome.item_id = self._resolve_bribe_item(player_id, npc_id, item_hint or raw_text, outcome)
        elif resolved_action == "move":
            outcome.target_location = location_hint or self._resolve_move_target(player_id, raw_text, outcome)

        deltas = ACTION_DELTAS.get(resolved_action, (0, 0, 0))
        outcome.affinity_delta, outcome.trust_delta, outcome.grudge_delta = deltas
        outcome.outcome = self._describe(resolved_action, outcome.item_id, npc)

        # --- 幂等：同一 key 已处理过就直接回放，不重复改状态 -------------
        if idempotency_key:
            existing = self.store.fetch_event_by_idempotency(idempotency_key)
            if existing is not None:
                outcome.duplicate = True
                outcome.outcome = existing["outcome"]
                outcome.relationship = self.store.fetch_relationship(player_id, npc_id) or {}
                outcome.plot = self.store.fetch_plot_progress(player_id, PLOT_CROWN_THEFT) or {}
                outcome.quest = self.store.fetch_quest(player_id, QUEST_CROWN_CASE) or {}
                player = self.store.fetch_player(player_id) or {}
                outcome.ending = self.store.fetch_ending(player_id, player.get("ending_id", "")) or {}
                return outcome

        # --- 状态变更：全部在一个事务里，要么全成，要么全不成 -----------
        with self.store.transaction():
            if resolved_action == "move" and outcome.target_location:
                self._apply_move(player_id, outcome)

            if resolved_action == "gift" and outcome.item_id:
                item = self.store.fetch_item(
                    outcome.item_id, outcome.item_source_kind, outcome.item_source_id)
                if item is None:
                    raise StoreError("unknown_item", f"道具 {outcome.item_id} 不存在")
                if item["owner_kind"] == "player" and item["owner_id"] != player_id:
                    raise StoreError("item_not_owned", f"你并不拥有道具「{item['name']}」")
                if item["owner_kind"] == "npc" and item["owner_id"] == npc_id:
                    raise StoreError("item_already_owned", f"「{item['name']}」已经在 {npc['name']} 手里了")
                self.store.transfer_item(
                    outcome.item_id, "npc", npc_id,
                    from_kind=outcome.item_source_kind, from_id=outcome.item_source_id,
                )
                outcome.notes.append(f"「{item['name']}」已转交给 {npc['name']}")

            if resolved_action == "steal":
                # 偷不到东西就不算偷。目标手上没有可拿的道具时，
                # 绝不能照样扣好感、加怨念 —— 那会让玩家因为
                # "重复尝试偷一个已经被拿走的王冠"而被冤枉成惯犯。
                if not outcome.item_id:
                    raise StoreError(
                        "nothing_to_steal",
                        f"{npc['name']}身上现在没有你能拿走的东西。",
                    )
                item = self.store.fetch_item(
                    outcome.item_id, outcome.item_source_kind, outcome.item_source_id)
                if item is None:
                    raise StoreError("unknown_item", f"道具 {outcome.item_id} 不存在")
                if not int(item["is_transferable"]):
                    raise StoreError("item_not_transferable", f"「{item['name']}」没法被拿走")
                self.store.transfer_item(
                    outcome.item_id, "player", player_id,
                    from_kind=outcome.item_source_kind, from_id=outcome.item_source_id,
                )
                outcome.notes.append(f"你把「{item['name']}」揣进了怀里")

            if resolved_action == "return_item" and outcome.item_id:
                item = self.store.fetch_item(
                    outcome.item_id, outcome.item_source_kind, outcome.item_source_id)
                if item is None:
                    raise StoreError("unknown_item", f"道具 {outcome.item_id} 不存在")
                if item["owner_kind"] != "player" or item["owner_id"] != player_id:
                    # 关键防漏洞：玩家没有的东西不能"归还"。
                    raise StoreError("item_not_owned", f"你并不拥有道具「{item['name']}」")
                self.store.transfer_item(
                    outcome.item_id, "npc", npc_id,
                    from_kind="player", from_id=player_id,
                )
                outcome.notes.append(f"你把「{item['name']}」交还给了 {npc['name']}")

            if resolved_action == "bribe" and outcome.item_id:
                item = self.store.fetch_item(
                    outcome.item_id, outcome.item_source_kind, outcome.item_source_id)
                if item is None:
                    raise StoreError("unknown_item", f"道具 {outcome.item_id} 不存在")
                if item["owner_kind"] != "player" or item["owner_id"] != player_id:
                    raise StoreError("item_not_owned", f"你并不拥有道具「{item['name']}」")
                self.store.transfer_item(
                    outcome.item_id, "npc", npc_id,
                    from_kind="player", from_id=player_id,
                )
                outcome.notes.append(f"你把「{item['name']}」塞给了 {npc['name']}")

            # 关系变化
            # 先记住变化前的关系数值：NPC 态度笔记只在态度**跨档**时才写，
            # 所以必须能比较"之前"和"之后"。
            relationship_before = self.store.fetch_relationship(player_id, npc_id) or {}
            outcome.relationship = self.store.apply_relationship_delta(
                player_id, npc_id,
                outcome.affinity_delta, outcome.trust_delta, outcome.grudge_delta,
                resolved_action,
            )

            # 调查 / 道歉 的额外处理
            if resolved_action == "investigate":
                outcome.notes.extend(self._apply_investigate(player_id, npc_id, outcome))
            if resolved_action == "apologize":
                outcome.notes.extend(self._apply_apologize(player_id, npc_id, outcome))
            if resolved_action == "move":
                outcome.notes.extend(self._apply_move_knowledge(player_id, outcome))

            # 知情传播：谁知道了什么
            outcome.notes.extend(self._propagate_knowledge(player_id, npc_id, resolved_action, outcome))

            # 剧情推进 + 结局判定
            outcome.plot = self._advance_plot(
                player_id, resolved_action, outcome.item_id, npc, outcome)
            outcome.quest = self._advance_quest(player_id, resolved_action, outcome)
            outcome.ending = self._check_endings(player_id, npc_id, outcome)

            # 事件落库
            recorded = self.store.record_event(
                player_id=player_id,
                npc_id=npc_id,
                action_type=resolved_action,
                action_text=raw_text,
                outcome=outcome.outcome,
                session_id=session_id,
                idempotency_key=idempotency_key
                or f"auto-{player_id}-{session_id}-{resolved_action}-{outcome.item_id}",
                item_id=outcome.item_id,
                affinity_delta=outcome.affinity_delta,
                trust_delta=outcome.trust_delta,
                grudge_delta=outcome.grudge_delta,
                is_committed=1 if commit else 0,
                location_id=(self.store.fetch_player(player_id) or {}).get("current_location", ""),
                confidence=100,
            )

            outcome.duplicate = bool(recorded.get("duplicate"))

            self.store.increment_turn(player_id)

            # --- 记忆待写任务：与状态一起提交到 outbox --------------------
            # 这样"seekdb 已提交、PowerContext 没写成"是可恢复的，
            # 而不是被吞掉。
            outcome.key_event = self._key_event_text(player_id, npc, outcome)
            if outcome.key_event:
                self.store.enqueue_memory(
                    player_id=player_id,
                    dedupe_key=outcome.key_event_dedupe_key(idempotency_key),
                    kind=KIND_KEY_EVENT,
                    payload=outcome.key_event,
                )

            # NPC 对玩家的**看法**是第三层记忆，和"发生过什么"分开存。
            # 这一层让 NPC 能说出"我记得你上次…"这种针对态度的判断，
            # 而不是复述事件流水。
            outcome.npc_note = self._npc_note_text(player_id, npc, outcome, relationship_before)
            if outcome.npc_note:
                self.store.enqueue_memory(
                    player_id=player_id,
                    dedupe_key=outcome.npc_note_dedupe_key(idempotency_key),
                    kind=KIND_NPC_NOTE,
                    payload=outcome.npc_note,
                )

        # --- 关键事件写入 PowerContext -----------------------------------
        # 放在事务之外：seekdb 的状态已经落定，PowerContext 是独立的系统。
        # 写失败不抛错 —— 任务已经在 outbox 里等着被补偿流程重试，
        # 但**必须如实告诉调用方这次没写进去**。
        if outcome.key_event:
            try:
                self.memory.remember_key_event(player_id, outcome.key_event)
                self.store.mark_memory_done(outcome.key_event_dedupe_key(idempotency_key))
                outcome.memory_written = True
            except Exception as error:  # noqa: BLE001
                outcome.memory_written = False
                outcome.memory_error = f"{type(error).__name__}: {error}"
                self.store.mark_memory_failed(
                    outcome.key_event_dedupe_key(idempotency_key), outcome.memory_error)
                outcome.notes.append("（这条关键事件暂时没能写进记忆库，已排队重试）")

        # --- NPC 态度写入 PowerContext ------------------------------------
        # 同样如实报告：主事件写成功不代表态度笔记也写成功。
        if outcome.npc_note:
            try:
                self.memory.remember_npc_note(player_id, outcome.npc_note)
                self.store.mark_memory_done(outcome.npc_note_dedupe_key(idempotency_key))
                outcome.npc_note_written = True
            except Exception as error:  # noqa: BLE001
                outcome.npc_note_written = False
                note_error = f"{type(error).__name__}: {error}"
                outcome.memory_error = (
                    f"{outcome.memory_error}; NPC 态度笔记: {note_error}"
                    if outcome.memory_error else note_error
                )
                self.store.mark_memory_failed(
                    outcome.npc_note_dedupe_key(idempotency_key), note_error)

        return outcome

    # ------------------------------------------------------------- helpers

    def _resolve_gift_item(
        self, player_id: str, npc_id: str, text: str, outcome: ActionOutcome
    ) -> str:
        """Pick the item being handed over.

        Order of preference: something the player already owns, then the
        town's free stock. The recipient's own holdings are deliberately
        *not* a source — you cannot hand someone the thing they are
        already holding, and treating it as a source produces a confusing
        "already owned" error instead of a real gift.
        """

        owned = self.store.list_items("player", player_id)
        matched = match_item(text, owned)
        if matched:
            outcome.item_source_kind = "player"
            outcome.item_source_id = player_id
            return matched

        town = self.store.list_items("town", "town_square")
        matched = match_item(text, town)
        if matched:
            outcome.item_source_kind = "town"
            outcome.item_source_id = "town_square"
            return matched

        # 玩家点名了某件道具，但那件道具既不在他手里也不在货架上。
        # 如果那件道具确实存在（只是不可转手，或在别人手里），
        # 必须明确拒绝 —— 绝不能悄悄换成别的东西，当作"赠送成功"。
        named = match_item(text, self._all_items())
        if named:
            item = self.store.fetch_item(named)
            if item is not None:
                if not int(item["is_transferable"]):
                    raise StoreError(
                        "item_not_transferable", f"道具「{item['name']}」没法被转手")
                raise StoreError(
                    "item_not_owned", f"你并不拥有道具「{item['name']}」")

        # 没有明确点名时，赠送镇上唯一可自由取用的道具。
        if town:
            outcome.item_source_kind = "town"
            outcome.item_source_id = "town_square"
            return town[0]["item_id"]

        # 玩家手头和镇上都没有可送的东西 —— 不能默默记一次"赠送成功"。
        raise StoreError("no_gift_item", "你手上没有可以送出去的东西")

    def _resolve_steal_item(self, npc_id: str, text: str, outcome: ActionOutcome) -> str:
        """Pick the item being stolen from the NPC."""

        held = self.store.list_items("npc", npc_id)
        matched = match_item(text, held)
        if matched:
            outcome.item_source_kind = "npc"
            outcome.item_source_id = npc_id
            return matched
        # 默认目标是镇长的金王冠——这是 V1 的主线触发器。
        for item in held:
            if "crown" in item["item_id"]:
                outcome.item_source_kind = "npc"
                outcome.item_source_id = npc_id
                return item["item_id"]
        return ""

    def _resolve_return_item(
        self, player_id: str, npc_id: str, text: str, outcome: ActionOutcome
    ) -> str:
        """Pick the item being handed back.

        Only what the player actually holds counts. Returning something you
        do not have must fail loudly, never silently succeed.
        """

        owned = self.store.list_items("player", player_id)
        matched = match_item(text, owned)
        if matched:
            outcome.item_source_kind = "player"
            outcome.item_source_id = player_id
            return matched

        # 玩家点名了某件道具但自己并没有 —— 明确拒绝。
        named = match_item(text, self._all_items())
        if named:
            item = self.store.fetch_item(named)
            if item is not None:
                raise StoreError("item_not_owned", f"你并不拥有道具「{item['name']}」")

        raise StoreError("item_not_owned", "你手上没有可以归还的东西")

    def _resolve_bribe_item(
        self, player_id: str, npc_id: str, text: str, outcome: ActionOutcome
    ) -> str:
        """Pick the item used to bribe. Same ownership rule as returning."""

        owned = self.store.list_items("player", player_id)
        matched = match_item(text, owned)
        if matched:
            outcome.item_source_kind = "player"
            outcome.item_source_id = player_id
            return matched
        raise StoreError("item_not_owned", "你手上没有可以用来贿赂的东西")

    def _resolve_move_target(self, player_id: str, text: str, outcome: ActionOutcome) -> str:
        """Find the destination by name among reachable locations."""

        player = self.store.fetch_player(player_id)
        here = player["current_location"] if player else ""
        candidates = self.store.list_locations()
        lowered = (text or "").lower()
        for location in candidates:
            if location["location_id"] == here:
                continue
            if not int(location.get("is_reachable", 1)):
                continue
            if location["name"].lower() in lowered or location["location_id"].lower() in lowered:
                return location["location_id"]
        # 没点名就去后巷 —— 小镇只有一条玩家会自己走的后巷。
        for location in candidates:
            if location["location_id"] == "back_alley" and location["location_id"] != here:
                return location["location_id"]
        return ""

    def _apply_move(self, player_id: str, outcome: ActionOutcome) -> None:
        """Move the player, enforcing the location graph."""

        player = self.store.fetch_player(player_id)
        here = player["current_location"] if player else ""
        target = outcome.target_location
        if not target:
            raise StoreError("unknown_location", "你要去哪里？")
        if not self.store.location_link_exists(here, target):
            raise StoreError("location_unreachable", f"从{here}走不到{target}")
        self.store.set_player_location(player_id, target)
        location = next(
            (loc for loc in self.store.list_locations() if loc["location_id"] == target), None)
        outcome.notes.append(f"你来到了{location['name'] if location else target}")

    def _apply_move_knowledge(self, player_id: str, outcome: ActionOutcome) -> list[str]:
        """Moving to a place means meeting whoever is there.

        The NPCs who are physically present learn that the player showed
        up — that is how "NPC 对其他 NPC 事件产生反应" starts.
        """

        notes: list[str] = []
        here = (self.store.fetch_player(player_id) or {}).get("current_location", "")
        for npc in self.store.list_npcs():
            if npc["home_location"] == here:
                notes.append(f"{npc['name']} 就在这儿")
        return notes

    def _apply_investigate(self, player_id: str, npc_id: str, outcome: ActionOutcome) -> list[str]:
        """Investigating raises the quest counter and may yield a clue.

        A clue only appears when the NPC actually has one to give — the
        mapping is explicit in ``EVIDENCE_SOURCES``, so no NPC hands out
        evidence it does not have.
        """

        notes: list[str] = []
        quest = self.store.fetch_quest(player_id, QUEST_CROWN_CASE)
        if quest and quest["state"] == "active":
            self.store.advance_quest(player_id, QUEST_CROWN_CASE, 1)
            notes.append("你的调查被记在了案卷上")

        item_id = EVIDENCE_SOURCES.get(npc_id, "")
        if item_id and not self.store.player_has_item(player_id, item_id):
            source = self.store.fetch_item(item_id)
            if source is not None and source["owner_kind"] == "town":
                self.store.transfer_item(
                    item_id, "player", player_id,
                    from_kind="town", from_id=source["owner_id"],
                )
                notes.append(f"你拿到了「{source['name']}」")
        return notes

    def _apply_apologize(self, player_id: str, npc_id: str, outcome: ActionOutcome) -> list[str]:
        """An apology only counts if there is something to apologize for."""

        notes: list[str] = []
        relationship = self.store.fetch_relationship(player_id, npc_id)
        if relationship and int(relationship["grudge_level"]) > 0:
            notes.append(f"{npc_id} 接受了你的道歉")
        else:
            notes.append("你道歉了，但对方似乎并没有什么事需要你道歉")
        return notes

    def _propagate_knowledge(
        self, player_id: str, npc_id: str, action_type: str, outcome: ActionOutcome
    ) -> list[str]:
        """Record who learned what.

        A theft is witnessed by the victim. A gift is known by the recipient.
        A bribe is known by the recipient. Everything else stays between
        the player and their own memory.

        其他 NPC 只有在玩家亲口告诉他们之后才会知道 —— 这里**不做**自动扩散。
        扩散由玩家的对话（talk + 提及）触发。
        """

        notes: list[str] = []
        topic = ""
        detail = ""
        if action_type == "steal" and outcome.item_id:
            topic = "theft"
            detail = f"{outcome.item_id} 被偷走了"
        elif action_type == "return_item" and outcome.item_id:
            topic = "return"
            detail = f"{outcome.item_id} 被归还了"
        elif action_type == "gift" and outcome.item_id:
            topic = "gift"
            detail = f"收到了 {outcome.item_id}"
        elif action_type == "bribe" and outcome.item_id:
            topic = "bribe"
            detail = "被贿赂了"
        elif action_type == "apologize":
            topic = "apology"
            detail = "道了歉"

        if not topic:
            return notes

        # 受害者 / 亲历者知道。
        self.store.record_knowledge(player_id, npc_id, topic, detail)
        return notes

    def _advance_plot(
        self, player_id: str, action_type: str, item_id: str, npc: dict[str, Any], outcome: ActionOutcome
    ) -> dict[str, Any]:
        """Advance the special plot when the crown theft happens."""

        if action_type != "steal" or npc["npc_id"] != "mayor" or item_id != "golden_crown":
            current = self.store.fetch_plot_progress(player_id, PLOT_CROWN_THEFT)
            return dict(current) if current else {}

        existing = self.store.fetch_plot_progress(player_id, PLOT_CROWN_THEFT)
        if existing and int(existing.get("triggered") or 0) == 1:
            return dict(existing)

        detail = f"{npc['name']} 的金王冠被 {player_id} 偷走了。镇长宣布启动调查。"
        row = self.store.upsert_plot_progress(player_id, PLOT_CROWN_THEFT, "investigating", True, detail)
        outcome.notes.append("触发主线剧情「王冠失窃案」：镇长开始调查。")
        self.ensure_quests(player_id)
        return dict(row)

    # ------------------------------------------------------------- 任务

    def ensure_quests(self, player_id: str) -> None:
        """Give the player the main quest the moment the plot starts."""

        if self.store.fetch_quest(player_id, QUEST_CROWN_CASE) is not None:
            return
        self.store.upsert_quest(
            player_id, QUEST_CROWN_CASE,
            title="王冠失窃案",
            stage="in_progress",
            progress=0, required=3, state="active",
            detail="归还王冠、或彻底查明真相、或认罪伏法——三条路都算结案。",
        )

    def _advance_quest(self, player_id: str, action_type: str, outcome: ActionOutcome) -> dict[str, Any]:
        """Quest progress is driven by concrete actions, not by model text."""

        quest = self.store.fetch_quest(player_id, QUEST_CROWN_CASE)
        if not quest or quest["state"] != "active":
            return dict(quest) if quest else {}

        if action_type == "investigate":
            self.store.advance_quest(player_id, QUEST_CROWN_CASE, 1)
        elif action_type == "return_item":
            # 归还王冠 = 这条支线**结案**了。
            # stage 记"结案到哪一步"，state 记"这条支线还在不在" ——
            # 两者不是一回事。只改 stage 不改 state 的话，任务会永远
            # 停在 active，玩家看任务列表时永远挂着一条"进行中"。
            self.store.set_quest_stage(player_id, QUEST_CROWN_CASE, "resolved", "done")
        return self.store.fetch_quest(player_id, QUEST_CROWN_CASE) or {}

    # ------------------------------------------------------------- 结局

    def _check_endings(
        self, player_id: str, npc_id: str, outcome: ActionOutcome
    ) -> dict[str, Any]:
        """Evaluate the three endings from authoritative state.

        The model's opinion is not consulted. Every condition below reads
        a number or a row that the backend itself wrote.
        """

        player = self.store.fetch_player(player_id)
        if not player:
            return {}
        if player.get("ending_id"):
            # 已经达成过结局 —— 不再重复触发，也不重复发奖励。
            existing = self.store.fetch_ending(player_id, player["ending_id"]) or {}
            return {
                "ending_id": player["ending_id"],
                "title": existing.get("title", ""),
                "summary": existing.get("summary", ""),
                "reward_coins": int(existing.get("reward_coins", 0) or 0),
                "reward_claimed": bool(existing.get("reward_claimed")),
                "already": True,
            }

        relationships = {
            r["npc_id"]: r for r in self.store.list_relationships(player_id)
        }
        mayor_rel = relationships.get("mayor", {})
        cat_rel = relationships.get("cat_detective", {})
        mayor_grudge = int(mayor_rel.get("grudge_level", 0))
        cat_grudge = int(cat_rel.get("grudge_level", 0))

        # --- 结局 A：洗白 -------------------------------------------------
        # 前提（三条都要成立）：
        #   1. 王冠失窃案**真的发生过** —— 主线剧情被触发过；
        #   2. 玩家确实已经把王冠还给了镇长（道具归属是权威证据）；
        #   3. 任务阶段推进到"已结案"，且镇长的怨念降到了阈值以下。
        # 第 1 条不可省：否则一个从没偷过王冠的玩家，
        # 只要镇长怨念为 0 就会被"洗白"，那是漏洞不是奖励。
        plot = self.store.fetch_plot_progress(player_id, PLOT_CROWN_THEFT) or {}
        theft_happened = int(plot.get("triggered") or 0) == 1
        crown_back = self.store.fetch_item("golden_crown", "npc", "mayor") is not None
        resolved = self.store.player_has_quest_stage(player_id, QUEST_CROWN_CASE, "resolved")
        if theft_happened and crown_back and resolved and mayor_grudge <= WHITEWASH_GRUDGE_MAX:
            return self._reach_ending(
                player_id, ENDING_WHITEWASH, outcome,
                detail=f"王冠已归还，镇长怨念 {mayor_grudge}",
            )

        # --- 结局 B：全镇公敌 ---------------------------------------------
        if (
            mayor_grudge >= PUBLIC_ENEMY_GRUDGE_THRESHOLD
            and cat_grudge >= PUBLIC_ENEMY_GRUDGE_THRESHOLD
        ):
            return self._reach_ending(
                player_id, ENDING_PUBLIC_ENEMY, outcome,
                detail=f"镇长怨念 {mayor_grudge} / 墨墨怨念 {cat_grudge}",
            )

        # --- 结局 C：悬案大师 ---------------------------------------------
        # 前提：证据数量达标 + 调查次数达标 + 王冠仍在玩家手里
        #（没有把赃物还回去，而是查清了真相）。
        evidence = self.store.list_evidence_items(player_id)
        quest = self.store.fetch_quest(player_id, QUEST_CROWN_CASE) or {}
        investigations = int(quest.get("progress", 0))
        crown_held = self.store.fetch_item("golden_crown", "player", player_id) is not None
        if (
            len(evidence) >= SLEUTH_EVIDENCE_REQUIRED
            and investigations >= SLEUTH_INVESTIGATIONS_REQUIRED
            and crown_held
        ):
            return self._reach_ending(
                player_id, ENDING_SLEUTH, outcome,
                detail=f"证据 {len(evidence)} 件，调查 {investigations} 次",
            )

        return {}

    def _reach_ending(
        self, player_id: str, ending_id: str, outcome: ActionOutcome, detail: str
    ) -> dict[str, Any]:
        """Record the ending once; never award the reward twice."""

        meta = ENDING_META[ending_id]
        existing = self.store.fetch_ending(player_id, ending_id)
        if existing is None:
            self.store.insert_ending(
                player_id, ending_id, ending_id, meta["title"], meta["summary"],
                int(meta["reward_coins"]),
            )
            existing = self.store.fetch_ending(player_id, ending_id) or {}

        # 奖励只发一次。
        claimed = bool(existing.get("reward_claimed"))
        reward = int(existing.get("reward_coins", 0) or 0)
        if not claimed and reward > 0:
            if self.store.claim_ending_reward(player_id, ending_id):
                self.store.add_coins(player_id, reward)
                claimed = True
                outcome.notes.append(f"结局达成：{meta['title']}（奖励 +{reward} 金币）")
            else:
                outcome.notes.append(f"结局达成：{meta['title']}（奖励已领取过）")
        else:
            outcome.notes.append(f"结局达成：{meta['title']}")

        self.store.set_player_ending(player_id, ending_id)
        # 结局达成 = 支线彻底结束。state 一起改成 done，
        # 否则任务列表里会永远挂着一条"进行中"。
        self.store.set_quest_stage(player_id, QUEST_CROWN_CASE, "ended", "done")
        self.store.update_plot_ending(player_id, PLOT_CROWN_THEFT, ending_id)

        return {
            "ending_id": ending_id,
            "title": meta["title"],
            "summary": meta["summary"],
            "reward_coins": reward,
            "reward_claimed": claimed,
            "detail": detail,
            "already": False,
        }

    # ------------------------------------------------------------- 记忆文本

    def _key_event_text(self, player_id: str, npc: dict[str, Any], outcome: ActionOutcome) -> str:
        """Compose the sentence that will be remembered across sessions."""

        label = ACTION_LABELS.get(outcome.action_type, outcome.action_type)
        if outcome.action_type == "steal" and outcome.item_id:
            return f"[{player_id}] 偷走了 {npc['name']} 的「{outcome.item_id}」。{npc['name']} 因此记恨上了他。"
        if outcome.action_type == "return_item" and outcome.item_id:
            return f"[{player_id}] 把「{outcome.item_id}」还给了 {npc['name']}。"
        if outcome.action_type == "gift" and outcome.item_id:
            return f"[{player_id}] 把「{outcome.item_id}」送给了 {npc['name']}。"
        if outcome.action_type == "bribe" and outcome.item_id:
            return f"[{player_id}] 贿赂了 {npc['name']}。"
        if outcome.action_type == "prank":
            return f"[{player_id}] 对 {npc['name']} 搞了个恶作剧，{npc['name']} 记下了这笔账。"
        if outcome.action_type == "apologize":
            return f"[{player_id}] 向 {npc['name']} 道了歉。"
        if outcome.action_type == "investigate":
            return f"[{player_id}] 调查了与 {npc['name']} 有关的线索。"
        if outcome.grudge_delta >= GRUDGE_KEY_THRESHOLD:
            return f"[{player_id}] 因为「{label}」被 {npc['name']} 记恨，怨念 +{outcome.grudge_delta}。"
        return ""

    def _npc_note_text(
        self,
        player_id: str,
        npc: dict[str, Any],
        outcome: ActionOutcome,
        before: dict[str, Any] | None = None,
    ) -> str:
        """Compose what *this NPC* thinks of the player right now.

        这与 :meth:`_key_event_text` 是两件事：

        * 关键事件 = **发生过什么**（客观流水，可以被别的 NPC 引用）；
        * NPC 态度 = **这个人怎么看玩家**（主观判断，带阈值语义）。

        态度文本由**权威关系数值**生成，不是由模型措辞生成 ——
        所以"怨念降下来了"这种结论永远和 seekdb 里的数字一致。
        阈值取自既有的常量，行为不会因为模型换了个语气而漂移。

        只在态度**跨过了档位**时才写一条笔记：闲聊也会涨好感，
        每次都写会把记忆库淹掉，而"NPC 对你的看法变了"才是值得记住的。
        """

        relationship = outcome.relationship or {}
        if not relationship:
            return ""

        affinity = int(relationship.get("affinity", 0) or 0)
        trust = int(relationship.get("trust", 0) or 0)
        grudge = int(relationship.get("grudge_level", 0) or 0)
        name = npc.get("name", "")

        band_key, attitude = self._attitude_band(affinity, grudge, name, player_id)
        if before:
            before_band, _ = self._attitude_band(
                int(before.get("affinity", 0) or 0),
                int(before.get("grudge_level", 0) or 0),
                name, player_id,
            )
            if before_band == band_key:
                # 态度没跨档 —— 这次互动不值得单独记一条。
                return ""
        else:
            # 没有"变化前"的参照（例如补偿重放），只有确实发生了
            # 值得记录的关系变化才写。
            if outcome.grudge_delta == 0 and outcome.affinity_delta == 0 \
                    and outcome.trust_delta == 0 and not outcome.item_id:
                return ""

        numbers = f"（好感 {affinity} / 信任 {trust} / 怨念 {grudge}）"
        return f"{numbers}{attitude}"

    def _attitude_band(
        self, affinity: int, grudge: int, name: str, player_id: str
    ) -> tuple[str, str]:
        """Map the authoritative numbers onto an attitude band.

        返回 ``(档位标识, 态度描述)``。档位标识用于判断态度**有没有变**，
        描述文本用于写进记忆。两者都只由数值决定。
        """

        if grudge >= PUBLIC_ENEMY_GRUDGE_THRESHOLD:
            return "enemy", f"{name}已经彻底把{player_id}当成了敌人，不想再见到他。"
        if grudge >= GRUDGE_KEY_THRESHOLD:
            return "resentful", f"{name}对{player_id}的怨气还没消，说话都带刺。"
        if grudge > 0:
            return "slightly_off", f"{name}对{player_id}还有些不满，但愿意再看看。"
        if affinity >= 20:
            return "ally", f"{name}把{player_id}当自己人了，说话比以往松快。"
        if affinity <= -20:
            return "cold", f"{name}不太想搭理{player_id}，敷衍得厉害。"
        return "neutral", f"{name}对{player_id}不冷不热，还在观望。"

    def _all_items(self) -> list[dict[str, Any]]:
        """Every item row in the game, used to detect explicitly named items.

        包含玩家手上的道具 —— 否则"把王冠还给镇长"会因为王冠
        已经不在 NPC 手里而找不到它。
        """

        return self.store.list_all_items()

    def _describe(self, action_type: str, item_id: str, npc: dict[str, Any]) -> str:
        label = ACTION_LABELS.get(action_type, action_type)
        if action_type == "steal" and item_id:
            return f"你试图偷走 {npc['name']} 的「{item_id}」，被当场抓住。"
        if action_type == "return_item" and item_id:
            return f"你把「{item_id}」还给了 {npc['name']}。"
        if action_type == "gift" and item_id:
            return f"你把「{item_id}」送给了 {npc['name']}。"
        if action_type == "bribe" and item_id:
            return f"你塞给 {npc['name']} 一份「{item_id}」，他没说话，但收下了。"
        if action_type == "prank":
            return f"你对 {npc['name']} 搞了个恶作剧。"
        if action_type == "apologize":
            return f"你向 {npc['name']} 道了歉。"
        if action_type == "investigate":
            return f"你开始调查与 {npc['name']} 有关的事。"
        if action_type == "move":
            return f"你动身前往别处。"
        if action_type == "talk":
            return f"你与 {npc['name']} 聊了起来。"
        if action_type == "help":
            return f"你向 {npc['name']} 打听了这个镇的玩法。"
        return f"你对 {npc['name']} 做了件说不清的事。"


@dataclass
class ActionOutcome:
    """The result of resolving one player action."""

    action_type: str
    npc_id: str
    player_id: str = ""
    item_id: str = ""
    item_source_kind: str = ""
    item_source_id: str = ""
    target_location: str = ""
    outcome: str = ""
    affinity_delta: int = 0
    trust_delta: int = 0
    grudge_delta: int = 0
    relationship: dict[str, Any] = field(default_factory=dict)
    plot: dict[str, Any] = field(default_factory=dict)
    quest: dict[str, Any] = field(default_factory=dict)
    ending: dict[str, Any] = field(default_factory=dict)
    key_event: str = ""
    npc_note: str = ""
    duplicate: bool = False
    memory_written: bool = False
    npc_note_written: bool = False
    memory_error: str = ""
    notes: list[str] = field(default_factory=list)

    def key_event_dedupe_key(self, idempotency_key: str) -> str:
        """A stable key so a retried memory write cannot duplicate the memory.

        ``player_id`` is part of the key on purpose. Two different players
        can perform the *same* action (both steal the crown from the mayor),
        and their memories are two different facts. Without the player in
        the key the second player's job would collide with the first
        player's row in ``town_outbox`` — and because the row is already
        ``done``, the second player's memory would be silently dropped.
        """

        base = f"{self.player_id}:{idempotency_key}" if idempotency_key else (
            f"{self.player_id}:{self.action_type}:{self.npc_id}:{self.item_id}")
        return f"mem:{hashlib.sha256(base.encode('utf-8')).hexdigest()[:40]}"

    def npc_note_dedupe_key(self, idempotency_key: str) -> str:
        """Dedupe key for the NPC-attitude note.

        Deliberately different from :meth:`key_event_dedupe_key` — the two
        layers are separate memories and must not overwrite each other.
        """

        base = f"{self.player_id}:note:{idempotency_key}" if idempotency_key else (
            f"{self.player_id}:note:{self.action_type}:{self.npc_id}:{self.item_id}")
        return f"note:{hashlib.sha256(base.encode('utf-8')).hexdigest()[:40]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "action_label": ACTION_LABELS.get(self.action_type, self.action_type),
            "npc_id": self.npc_id,
            "item_id": self.item_id,
            "item_source": f"{self.item_source_kind}:{self.item_source_id}" if self.item_id else "",
            "target_location": self.target_location,
            "outcome": self.outcome,
            "affinity_delta": self.affinity_delta,
            "trust_delta": self.trust_delta,
            "grudge_delta": self.grudge_delta,
            "relationship": self.relationship,
            "plot": self.plot,
            "quest": self.quest,
            "ending": self.ending,
            "key_event": self.key_event,
            "npc_note": self.npc_note,
            "duplicate": self.duplicate,
            "memory_written": self.memory_written,
            "npc_note_written": self.npc_note_written,
            "memory_error": self.memory_error,
            "notes": self.notes,
        }


class MemoryWriteError(RuntimeError):
    """Raised when a key event could not be persisted to PowerContext."""
