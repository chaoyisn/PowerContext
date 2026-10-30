"""游戏规则引擎：把一次玩家动作变成状态变更与剧情推进。

**模型输出不可信。**  大模型只负责"理解玩家想干什么"和"生成台词"，
判定动作类型、扣道具、加好感、推进剧情全部由本模块的确定性代码完成。
模型给出的任何数值都不会直接写进数据库。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .memory import MemoryStore
from .store import SeekDBStore, StoreError

#: 动作类型判定用的关键词。模型只给候选，最终类型由代码在此确认。
#:
#: 关键词按"专指程度"加权：越长的词越专指，权重越高。
#: 例如"我要给你一个恶作剧"同时命中赠送的"给"(1 字)和恶作剧的"恶作剧"(3 字)，
#: 加权后恶作剧胜出；单纯按字典顺序匹配会把它误判成赠送。
ACTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "steal": ("偷", "拿走", "抢", "顺走", "摸走", "窃", "盗", "steal", "偷走"),
    "gift": ("送", "给", "赠", "递", "礼物", "小鱼干", "gift", "赠送"),
    "prank": ("恶作剧", "捉弄", "吓", "恶搞", "捉", "搞", " prank", "玩笑", "偷袭"),
    "investigate": ("调查", "查看", "搜", "查", "探查", "翻", "inquire", "调查一下"),
}

#: 加权得分相同时的优先级：越靠前越优先。
ACTION_PRIORITY = ("steal", "prank", "gift", "investigate")

ACTION_LABELS = {
    "talk": "闲聊",
    "prank": "恶作剧",
    "gift": "赠送道具",
    "steal": "偷窃",
    "investigate": "调查",
    "unknown": "不明举动",
}

#: 每种动作对关系数值的影响。(好感, 信任, 怨念)
ACTION_DELTAS: dict[str, tuple[int, int, int]] = {
    "talk": (2, 1, 0),
    "prank": (-8, -5, 12),
    "gift": (6, 8, -3),
    "steal": (-15, -20, 25),
    "investigate": (0, 2, 0),
    "unknown": (0, 0, 0),
}

#: 特殊剧情：偷走镇长的金王冠 → 镇长启动调查。
PLOT_CROWN_THEFT = "plot_crown_theft"

#: 会被 NPC 记恨的关键事件阈值
GRUDGE_KEY_THRESHOLD = 20


#: 道具的别称。玩家说"一条小鱼干"时要能匹配到道具"油炸小鱼干"。
ITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "golden_crown": ("金王冠", "王冠", "crown", "gold crown"),
    "fat_fish_snack": ("小鱼干", "鱼干", "零食", "snack", "fish"),
    "old_notebook": ("账本", "笔记本", "notebook"),
    "mayor_seal": ("印章", "seal"),
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


@dataclass
class ActionOutcome:
    """The result of resolving one player action."""

    action_type: str
    npc_id: str
    item_id: str = ""
    item_source_kind: str = ""
    item_source_id: str = ""
    outcome: str = ""
    affinity_delta: int = 0
    trust_delta: int = 0
    grudge_delta: int = 0
    relationship: dict[str, Any] = field(default_factory=dict)
    plot: dict[str, Any] = field(default_factory=dict)
    key_event: str = ""
    duplicate: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "action_label": ACTION_LABELS.get(self.action_type, self.action_type),
            "npc_id": self.npc_id,
            "item_id": self.item_id,
            "item_source": f"{self.item_source_kind}:{self.item_source_id}" if self.item_id else "",
            "outcome": self.outcome,
            "affinity_delta": self.affinity_delta,
            "trust_delta": self.trust_delta,
            "grudge_delta": self.grudge_delta,
            "relationship": self.relationship,
            "plot": self.plot,
            "key_event": self.key_event,
            "duplicate": self.duplicate,
            "notes": self.notes,
        }


def classify_action(raw_text: str, model_hint: str | None = None) -> str:
    """Decide the action type.

    The model's hint is accepted only when it is a known type *and* the
    player's text carries no contradicting keyword. The keyword scan is the
    authority; the model merely breaks ties when the text is ambiguous.
    """

    text = (raw_text or "").lower()

    # 加权打分：命中的关键词越长越专指，得分越高；得分相同时按 ACTION_PRIORITY。
    # 例如"我要给你一个恶作剧"同时命中赠送的"给"(1字)与恶作剧的"恶作剧"(3字)，
    # 加权后判为恶作剧；单纯按字典顺序匹配会误判成赠送。
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

    lowered = (text or "").lower()
    for npc in npcs:
        for token in (npc["name"], npc["title"], npc["npc_id"]):
            if token and token.lower() in lowered:
                return npc["npc_id"]
    return npcs[0]["npc_id"] if npcs else "mayor"


def request_hash(payload: dict[str, Any]) -> str:
    """Stable hash of a request, used to detect a changed repeat request."""

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GameEngine:
    """Applies a player action to the game state."""

    def __init__(self, store: SeekDBStore, memory: MemoryStore) -> None:
        self.store = store
        self.memory = memory

    # ------------------------------------------------------------ the action

    def perform_action(
        self,
        player_id: str,
        session_id: str,
        npc_id: str,
        raw_text: str,
        *,
        action_hint: str | None = None,
        item_hint: str | None = None,
        idempotency_key: str = "",
    ) -> ActionOutcome:
        """Resolve and apply one action.

        The whole thing is wrapped in one seekdb transaction so that a
        failure halfway through does not leave a half-applied state.
        """

        npc = self.store.fetch_npc(npc_id)
        if npc is None:
            raise StoreError("unknown_npc", f"NPC {npc_id} 不存在")

        action_type = classify_action(raw_text, action_hint)
        outcome = ActionOutcome(action_type=action_type, npc_id=npc_id)

        if action_type == "gift":
            outcome.item_id = self._resolve_gift_item(player_id, npc_id, item_hint or raw_text, outcome)
        elif action_type == "steal":
            outcome.item_id = self._resolve_steal_item(npc_id, item_hint or raw_text, outcome)

        deltas = ACTION_DELTAS.get(action_type, (0, 0, 0))
        outcome.affinity_delta, outcome.trust_delta, outcome.grudge_delta = deltas
        outcome.outcome = self._describe(action_type, outcome.item_id, npc)

        # --- 幂等：同一 key 已处理过就直接回放，不重复改状态 -------------
        if idempotency_key:
            existing = self.store.fetch_event_by_idempotency(idempotency_key)
            if existing is not None:
                outcome.duplicate = True
                outcome.outcome = existing["outcome"]
                outcome.relationship = self.store.fetch_relationship(player_id, npc_id) or {}
                outcome.plot = self.store.fetch_plot_progress(player_id, PLOT_CROWN_THEFT) or {}
                return outcome

        # --- 状态变更：全部在一个事务里，要么全成，要么全不成 -----------
        with self.store.transaction():
            # 道具流转（受规则约束）
            if action_type == "gift" and outcome.item_id:
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

            if action_type == "steal" and outcome.item_id:
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

            # 关系变化
            outcome.relationship = self.store.apply_relationship_delta(
                player_id, npc_id,
                outcome.affinity_delta, outcome.trust_delta, outcome.grudge_delta,
                action_type,
            )

            # 剧情推进
            outcome.plot = self._advance_plot(player_id, action_type, outcome.item_id, npc, outcome)

            # 事件落库
            recorded = self.store.record_event(
                player_id=player_id,
                npc_id=npc_id,
                action_type=action_type,
                action_text=raw_text,
                outcome=outcome.outcome,
                session_id=session_id,
                idempotency_key=idempotency_key
                or f"auto-{player_id}-{session_id}-{action_type}-{outcome.item_id}",
                item_id=outcome.item_id,
                affinity_delta=outcome.affinity_delta,
                trust_delta=outcome.trust_delta,
                grudge_delta=outcome.grudge_delta,
            )

            outcome.duplicate = bool(recorded.get("duplicate"))

            self.store.increment_turn(player_id)

        # --- 关键事件写入 PowerContext -----------------------------------
        # 放在事务之外：seekdb 的状态已经落定，PowerContext 是独立的系统。
        # 写失败会向上抛错，调用方不会把它当成成功。
        outcome.key_event = self._key_event_text(player_id, npc, outcome)
        if outcome.key_event:
            try:
                self.memory.remember_key_event(player_id, outcome.key_event)
            except Exception as error:
                raise MemoryWriteError(str(error)) from error

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

    def _all_items(self) -> list[dict[str, Any]]:
        """Every item row in the game, used to detect explicitly named items."""

        items: list[dict[str, Any]] = []
        for owner_kind, owner_id in (
            ("npc", "mayor"), ("npc", "cat_detective"),
            ("town", "town_square"),
        ):
            items.extend(self.store.list_items(owner_kind, owner_id))
        return items

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

    def _describe(self, action_type: str, item_id: str, npc: dict[str, Any]) -> str:
        label = ACTION_LABELS.get(action_type, action_type)
        if action_type == "steal" and item_id:
            return f"你试图偷走 {npc['name']} 的「{item_id}」，被当场抓住。"
        if action_type == "gift" and item_id:
            return f"你把「{item_id}」送给了 {npc['name']}。"
        if action_type == "prank":
            return f"你对 {npc['name']} 搞了个恶作剧。"
        if action_type == "investigate":
            return f"你开始调查与 {npc['name']} 有关的事。"
        if action_type == "talk":
            return f"你与 {npc['name']} 聊了起来。"
        return f"你对 {npc['name']} 做了件说不清的事。"

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
        return dict(row)

    def _key_event_text(self, player_id: str, npc: dict[str, Any], outcome: ActionOutcome) -> str:
        """Compose the sentence that will be remembered across sessions."""

        label = ACTION_LABELS.get(outcome.action_type, outcome.action_type)
        if outcome.action_type == "steal" and outcome.item_id:
            return f"[{player_id}] 偷走了 {npc['name']} 的「{outcome.item_id}」。{npc['name']} 因此记恨上了他。"
        if outcome.action_type == "gift" and outcome.item_id:
            return f"[{player_id}] 把「{outcome.item_id}」送给了 {npc['name']}。"
        if outcome.action_type == "prank":
            return f"[{player_id}] 对 {npc['name']} 搞了个恶作剧，{npc['name']} 记下了这笔账。"
        if outcome.grudge_delta >= GRUDGE_KEY_THRESHOLD:
            return f"[{player_id}] 因为「{label}」被 {npc['name']} 记恨，怨念 +{outcome.grudge_delta}。"
        return ""


class MemoryWriteError(RuntimeError):
    """Raised when a key event could not be persisted to PowerContext."""
