"""PowerContext 记忆层：关键事件写入与跨会话召回。

设计要点
--------

**每个玩家一个独立 Scope。**  PowerContext 的 scope id 由服务端生成，
不能自己指定，因此这里用官方的 **scope binding** 机制把
``(integration, kind, external_id) = ("memory-town", "player", <player_id>)``
映射到一个 scope_id：

* 解析绑定 → 已有 scope，直接复用；
* 解析不到 → 创建 scope 并写下绑定。

这样同一个玩家在**新会话**里会解析到同一个 scope → 能读到之前的记忆；
另一个玩家用的是另一个 external_id → 物理上读不到 A 的记忆。

**记忆有 kind 之分。**  ``town-key-event`` 放"值得记住的事"（偷了王冠、送了礼、
搞了恶作剧）；``town-npc-note`` 放 NPC 对该玩家的态度摘要。
召回时按 kind 分开取，再由 Dify 组装进 prompt。

**写失败不算成功。**  如果 PowerContext 不可用，写入会抛异常，
由调用方决定是"降级继续"还是"整体失败"，绝不会假装写入成功。

V2 的检索策略（按 1.4.1 的实际能力，不照抄未验证字段）
------------------------------------------------------
实测 ``/v1/capabilities`` 返回 ``search_modes = ["auto", "fts"]``，
``/v1/memory/search`` 的 ``mode`` 枚举虽然是
``["auto","fts","vector","hybrid"]``，但本部署上：

* ``mode="vector"`` / ``mode="hybrid"`` **不会报错**，而是退化成文本通道
  （返回的 ``matched_by`` 依然是 ``["text"]``）；
* 也就是说**没有真正的向量索引在跑**。

因此本模块：

* 只使用 ``mode="fts"``，并在返回值里如实标注 ``vector_mode_unavailable``；
* **不声称做了向量检索** —— 声称了就是在撒谎；
* 用 ``/v1/memory/entries/list`` 取回该 scope 的权威条目列表作为**候选池**
  （FTS 的中文分词很挑词，单靠它会漏召回）；
* 在后端做**相关性排序**（FTS 得分 + 主题词命中数 + 是否提到该 NPC + 顺序权重），
  再按固定条数与字节预算**截断**，绝不把整段历史塞进 prompt；
* 用 ``/v1/context/prepare`` 作为可选的有界上下文装配。

中文分词实测为 CJK 词切分，且只认词典词：命中 "偷走" / "金王冠" / "还给" /
"小鱼干" / "恶作剧" / "贿赂" / "调查" / "线索" / "镇长" / "墨墨"，
而 "偷" / "还" / "送" / "道歉" / "证据" 全部 0 命中。
所以召回必须靠"候选池 + 后端排序"兜底，不能只靠拼一长串关键词。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .config import Settings

KIND_KEY_EVENT = "town-key-event"
KIND_NPC_NOTE = "town-npc-note"

#: 本赛题在 PowerContext 中的集成标识。
INTEGRATION = "memory-town"
BINDING_KIND = "player"

#: 单次召回最多返回几条（后端侧上限，防止整段历史进 prompt）。
MAX_RECALL_ITEMS = 8

#: 单次召回注入 prompt 的最大字节数。
MAX_CONTEXT_BYTES = 4000

#: PowerContext 1.4.1 实测可用的检索模式。
#: ``vector`` / ``hybrid`` 在本部署上会**静默退化成文本通道**
#: （``matched_by`` 仍为 ``["text"]``），因此本模块只声明 fts/auto，
#: 不把向量检索当成已实现的能力。
AVAILABLE_SEARCH_MODES = ("auto", "fts")

#: 检索时使用的主题词。每个词单独查询，避免多词合查漏召回。
#: 键是主题，值是查询词列表 —— 全部取并集后按相关度排序。
#: 这些词是**实测能命中**的词典词（中文分词只认词典里的词）。
RECALL_TOPICS: dict[str, tuple[str, ...]] = {
    "theft": ("偷走", "金王冠", "记恨"),
    "return": ("还给", "金王冠"),
    "gift": ("小鱼干", "送给了"),
    "prank": ("恶作剧", "记下"),
    "apology": ("道歉",),
    "bribe": ("贿赂",),
    "investigation": ("调查", "线索", "案卷"),
    "town": ("镇长", "墨墨", "小镇"),
}

#: 与 NPC 对话时优先召回的词。NPC 只会"想起"与自己有关的事。
NPC_RECALL_TOPICS: dict[str, tuple[str, ...]] = {
    "mayor": ("镇长", "金王冠", "偷走", "还给", "道歉"),
    "cat_detective": ("墨墨", "调查", "线索", "小鱼干", "恶作剧"),
    "crow_judge": ("案卷", "调查", "线索", "金王冠"),
}


class MemoryError(RuntimeError):
    """Raised when the memory backend cannot serve a request."""


def binding_key(player_id: str) -> dict[str, str]:
    """The scope-binding key of a player."""

    return {
        "integration": INTEGRATION,
        "kind": BINDING_KIND,
        "external_id": player_id,
    }


class MemoryStore:
    """Key-event memory on top of PowerContext."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: httpx.Client | None = None
        #: player_id -> scope_id，进程内缓存，避免每次都去解析绑定。
        self._scope_cache: dict[str, str] = {}

    # ------------------------------------------------------------- transport

    def _http(self) -> httpx.Client:
        if self._client is None:
            headers = {"content-type": "application/json; charset=utf-8"}
            if self.settings.powercontext_token:
                headers["authorization"] = f"Bearer {self.settings.powercontext_token}"
            self._client = httpx.Client(
                base_url=self.settings.powercontext_url.rstrip("/"),
                headers=headers,
                timeout=self.settings.powercontext_timeout,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = self._http().request(method, path, json=payload)
        except Exception as error:
            raise MemoryError(f"PowerContext {method} {path} 请求失败: {type(error).__name__}") from error
        if response.status_code >= 400:
            raise MemoryError(
                f"PowerContext {method} {path} 返回 {response.status_code}: {response.text[:300]}"
            )
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as error:
            raise MemoryError(f"PowerContext {method} {path} 返回的不是 JSON") from error

    def _request_allow_missing(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Like ``_request`` but a 404 means "not there yet", not a failure."""

        try:
            return self._request(method, path, payload)
        except MemoryError as error:
            if "返回 404" in str(error):
                return None
            raise

    # --------------------------------------------------------------- health

    def health(self) -> dict[str, Any]:
        try:
            payload = self._request("GET", "/health/ready")
        except MemoryError as error:
            return {"available": False, "url": self.settings.powercontext_url, "error": str(error)}
        return {"available": True, "url": self.settings.powercontext_url, "status": payload.get("status")}

    # --------------------------------------------------------------- scopes

    def resolve_scope(self, player_id: str) -> str | None:
        """Resolve the player's scope id from the binding, or None."""

        payload = self._request_allow_missing(
            "POST",
            "/v1/scope-bindings/resolve",
            {"binding_keys": [binding_key(player_id)], "allow_default": False},
        )
        if not payload:
            return None
        scope_id = payload.get("scope_id")
        return scope_id if scope_id else None

    def ensure_scope(self, player_id: str) -> str:
        """Return the player's scope id, creating and binding it if needed."""

        cached = self._scope_cache.get(player_id)
        if cached:
            return cached

        scope_id = self.resolve_scope(player_id)
        if scope_id:
            self._scope_cache[player_id] = scope_id
            return scope_id

        scope_id = self._create_scope(player_id)
        try:
            self._request(
                "PUT",
                "/v1/scope-bindings",
                {"key": binding_key(player_id), "scope_id": scope_id},
            )
        except MemoryError as error:
            # 绑定失败时重新解析一次：如果并发请求已经建好绑定，就用那个。
            resolved = self.resolve_scope(player_id)
            if not resolved:
                raise error
            scope_id = resolved

        self._scope_cache[player_id] = scope_id
        return scope_id

    def _create_scope(self, player_id: str) -> str:
        payload = self._request(
            "POST",
            "/v1/scopes",
            {
                "title": f"记仇小镇·玩家 {player_id}",
                "summary": f"玩家 {player_id} 在记仇小镇的关键事件记忆",
                "idempotency_key": f"town-scope-{INTEGRATION}-{player_id}",
            },
        )
        scope_id = payload.get("scope_id")
        if not scope_id:
            raise MemoryError("PowerContext 创建 scope 后未返回 scope_id")
        return scope_id

    # --------------------------------------------------------------- writes

    def remember(self, player_id: str, kind: str, text: str) -> dict[str, Any]:
        """Write one memory record into the player's scope.

        **幂等。**  PowerContext 1.4.1 的 ``/v1/memory/remember`` **没有**
        幂等键（实测 schema 只有 ``scope_id`` / ``kind`` / ``text`` /
        ``reason`` / ``expected_revision``），所以重复调用就会多出一条记忆。

        补偿流程必须能安全地重跑 —— 进程可能在"写完记忆"和"把 outbox 行
        标成 done"之间崩掉，那时再补偿一次就会写出重复记忆。所以这里先查
        一遍这个 scope 里有没有同 kind 同 text 的条目，有就直接返回，
        不再写第二条。

        这个检查只查**当前玩家自己的 scope**，所以它不会把别的玩家的记忆
        当成"已存在"而漏写。
        """

        scope_id = self.ensure_scope(player_id)
        body = text[:8192]

        existing = self._find_existing(scope_id, kind, body)
        if existing is not None:
            return {
                "scope_id": scope_id,
                "artifact_id": existing.get("artifact_id"),
                "revision": existing.get("revision"),
                "kind": kind,
                "deduplicated": True,
            }

        payload = self._request(
            "POST",
            "/v1/memory/remember",
            {"scope_id": scope_id, "kind": kind, "text": body},
        )
        records = payload.get("records") or []
        artifact = records[0].get("artifact", {}) if records else {}
        return {
            "scope_id": scope_id,
            "artifact_id": artifact.get("artifact_id"),
            "revision": artifact.get("revision"),
            "kind": kind,
            "deduplicated": False,
        }

    def _find_existing(
        self, scope_id: str, kind: str, text: str
    ) -> dict[str, Any] | None:
        """Look for an identical (kind, text) entry already in the scope."""

        try:
            payload = self._request(
                "POST",
                "/v1/memory/entries/list",
                {"scope_id": scope_id, "limit": 100},
            )
        except MemoryError:
            # 查不到就当没有 —— 宁可多写一条，也不要把一次成功的写入
            # 变成"静默丢弃"。
            return None
        for entry in payload.get("entries") or []:
            if entry.get("kind") != kind:
                continue
            if (entry.get("text") or "") != text:
                continue
            artifact = entry.get("artifact") or {}
            return {
                "artifact_id": artifact.get("artifact_id"),
                "revision": artifact.get("revision"),
            }
        return None

    def remember_key_event(self, player_id: str, text: str) -> dict[str, Any]:
        return self.remember(player_id, KIND_KEY_EVENT, text)

    def remember_npc_note(self, player_id: str, text: str) -> dict[str, Any]:
        return self.remember(player_id, KIND_NPC_NOTE, text)

    # ------------------------------------------------------------- recalls

    def recall(self, player_id: str, kind: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Read the player's memories back.

        Only the player's own scope is read, so a different player can never
        see them.
        """

        scope_id = self._scope_cache.get(player_id) or self.resolve_scope(player_id)
        if not scope_id:
            # 玩家还没有建立过记忆范围 —— 没有记忆可召回，这不是错误。
            return []

        payload = self._request(
            "POST",
            "/v1/memory/entries/list",
            {"scope_id": scope_id, "limit": limit},
        )

        entries = payload.get("entries") or []
        result = []
        for entry in entries:
            if kind is not None and entry.get("kind") != kind:
                continue
            artifact = entry.get("artifact") or {}
            result.append(
                {
                    "kind": entry.get("kind"),
                    "text": entry.get("text"),
                    "artifact_id": artifact.get("artifact_id"),
                    "revision": artifact.get("revision"),
                    "state": entry.get("state"),
                }
            )
        return result

    def recall_key_events(self, player_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.recall(player_id, KIND_KEY_EVENT, limit)

    def recall_npc_notes(self, player_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.recall(player_id, KIND_NPC_NOTE, limit)

    # ------------------------------------------------- V2: 检索与有界上下文

    def capabilities(self) -> dict[str, Any]:
        """What this PowerContext build can actually do.

        The backend reports the modes it supports so the caller can be
        honest about what it did and did not use.
        """

        try:
            payload = self._request("GET", "/v1/capabilities")
        except MemoryError as error:
            return {"available": False, "error": str(error)}
        return {
            "available": True,
            "search_modes": payload.get("search_modes") or [],
            "memory_extraction": payload.get("memory_extraction"),
        }

    def search(
        self,
        player_id: str,
        query: str,
        limit: int = 5,
        mode: str = "fts",
    ) -> list[dict[str, Any]]:
        """Full-text search inside the player's own scope.

        Only ``fts``/``auto`` are used. ``vector`` and ``hybrid`` exist in
        the schema but silently fall back to the text channel on this
        deployment (``matched_by`` stays ``["text"]``), so they are not
        requested and vector retrieval is never claimed.

        The 1.4.1 response is ``{"mode": ..., "hits": [{"memory": {...},
        "score": ..., "matched_by": [...]}]}`` — see ``AtomicMemorySearchHit``.
        """

        scope_id = self._scope_cache.get(player_id) or self.resolve_scope(player_id)
        if not scope_id:
            return []
        if mode not in AVAILABLE_SEARCH_MODES:
            mode = "fts"

        payload = self._request(
            "POST",
            "/v1/memory/search",
            {
                "scope_id": scope_id,
                "query": query[:200],
                "limit": max(1, min(int(limit), 50)),
                "mode": mode,
            },
        )

        results: list[dict[str, Any]] = []
        for hit in payload.get("hits") or []:
            record = hit.get("memory") or {}
            artifact = record.get("artifact") or {}
            results.append(
                {
                    "kind": record.get("kind"),
                    "text": record.get("text") or "",
                    "artifact_id": artifact.get("artifact_id"),
                    "revision": artifact.get("revision"),
                    "score": hit.get("score"),
                    "matched_by": hit.get("matched_by") or [],
                    "memory_id": artifact.get("artifact_id"),
                }
            )
        return results

    def prepare_context(
        self,
        player_id: str,
        query: str,
        max_bytes: int = MAX_CONTEXT_BYTES,
    ) -> dict[str, Any]:
        """Assemble a **bounded** context block for the prompt.

        ``/v1/context/prepare`` caps the result at ``max_bytes`` and marks
        the block as untrusted history. The block is reference material,
        never instructions — the caller wraps it accordingly.
        """

        scope_id = self._scope_cache.get(player_id) or self.resolve_scope(player_id)
        if not scope_id:
            return {"available": False, "reason": "no_scope", "content": "", "content_bytes": 0}

        payload = self._request(
            "POST",
            "/v1/context/prepare",
            {
                "scope_id": scope_id,
                "query": query[:200],
                "max_bytes": max(512, min(int(max_bytes), 32768)),
            },
        )
        return {
            "available": True,
            "status": payload.get("status"),
            "content": payload.get("content") or "",
            "content_bytes": int(payload.get("content_bytes") or 0),
        }

    def _candidate_pool(self, player_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """The scope's authoritative entry list — the retrieval candidate pool.

        FTS on this deployment only matches dictionary words, so a query
        alone silently under-recalls. Listing the scope's own entries
        guarantees the ranking step sees everything, and it is still
        scoped to one player.
        """

        scope_id = self._scope_cache.get(player_id) or self.resolve_scope(player_id)
        if not scope_id:
            return []
        payload = self._request(
            "POST",
            "/v1/memory/entries/list",
            {"scope_id": scope_id, "limit": max(1, min(int(limit), 100))},
        )
        pool: list[dict[str, Any]] = []
        for record in payload.get("entries") or []:
            artifact = record.get("artifact") or {}
            pool.append(
                {
                    "kind": record.get("kind"),
                    "text": record.get("text") or "",
                    "artifact_id": artifact.get("artifact_id"),
                    "revision": artifact.get("revision"),
                    "state": record.get("state"),
                    "memory_id": artifact.get("artifact_id"),
                    "score": 0.0,
                    "fts_rank": None,
                }
            )
        return pool

    def _rank(
        self,
        pool: list[dict[str, Any]],
        words: tuple[str, ...],
        npc_id: str = "",
    ) -> list[dict[str, Any]]:
        """Rank candidate memories by relevance, deterministically.

        Scoring combines: the FTS score (when the entry was found by a
        full-text query), how many distinct topic words the text
        contains, whether the text mentions this NPC, and the entry's
        position in the authoritative list (newer entries rank higher
        because the list is returned newest-first).

        The result is deterministic: no randomness, no dependence on dict
        ordering — ties break on the memory id.
        """

        scored: list[dict[str, Any]] = []
        total = len(pool)
        for index, entry in enumerate(pool):
            text = entry.get("text") or ""
            lowered = text.lower()
            hits = [word for word in words if word.lower() in lowered]
            score = len(hits) * 3.0
            fts = entry.get("fts_rank")
            if fts is not None:
                score += float(fts) * 100.0
            if npc_id and npc_id in text:
                score += 2.0
            # 越靠后（越新）的条目略微加权。
            score += (total - index) * 0.01
            scored.append((score, entry.get("memory_id") or "", entry, hits))

        scored.sort(key=lambda item: (-item[0], str(item[1])))
        return [
            {
                "text": entry.get("text") or "",
                "memory_id": entry.get("memory_id"),
                "artifact_id": entry.get("artifact_id"),
                "revision": entry.get("revision"),
                "kind": entry.get("kind"),
                "score": round(score, 4),
                "matched_words": hits,
            }
            for score, _key, entry, hits in scored
        ]

    def _bounded(
        self, ranked: list[dict[str, Any]], limit: int, max_bytes: int = MAX_CONTEXT_BYTES
    ) -> tuple[list[dict[str, Any]], int]:
        """Keep only the top entries that fit inside the byte budget."""

        items: list[dict[str, Any]] = []
        total = 0
        for entry in ranked:
            if len(items) >= limit:
                break
            size = len((entry.get("text") or "").encode("utf-8"))
            if items and total + size > max_bytes:
                break
            total += size
            items.append(entry)
        return items, total

    def recall_for_npc(
        self, player_id: str, npc_id: str, limit: int = MAX_RECALL_ITEMS
    ) -> dict[str, Any]:
        """Recall what is relevant to *this* NPC, ranked and bounded.

        Strategy:

        1. **Candidate pool** — the scope's authoritative entry list.
        2. **FTS** — each topic word is searched on its own (Chinese
           segmentation makes combined queries unreliable) to give a
           relevance signal.
        3. **Merge + rank** in the backend (see :meth:`_rank`).
        4. **Bound** to ``limit`` entries and ``MAX_CONTEXT_BYTES``.

        The returned dict reports which channel was used and which
        queries ran, so the caller never has to guess.
        """

        words = NPC_RECALL_TOPICS.get(npc_id, ())
        if not words:
            return {
                "items": [], "bytes": 0, "queries": [], "mode": "fts",
                "candidate_count": 0, "note": "no_topic_for_npc",
            }

        pool = self._candidate_pool(player_id)
        by_key = {str(e.get("memory_id")): e for e in pool}

        used_queries: list[str] = []
        for word in words:
            try:
                found = self.search(player_id, word, limit=10, mode="fts")
            except MemoryError:
                continue
            used_queries.append(word)
            for hit in found:
                key = str(hit.get("memory_id"))
                entry = by_key.get(key)
                if entry is None:
                    entry = dict(hit)
                    entry["memory_id"] = hit.get("memory_id")
                    by_key[key] = entry
                    pool.append(entry)
                entry["fts_rank"] = max(entry.get("fts_rank") or 0.0, float(hit.get("score") or 0.0))

        ranked = self._rank(pool, words, npc_id=npc_id)
        items, total_bytes = self._bounded(ranked, limit)

        return {
            "items": items,
            "bytes": total_bytes,
            "queries": used_queries,
            "mode": "fts",
            "candidate_count": len(pool),
            "note": "vector_mode_unavailable",
        }

    def recall_for_quest(
        self, player_id: str, quest_id: str, limit: int = MAX_RECALL_ITEMS
    ) -> dict[str, Any]:
        """Recall the memories relevant to one quest.

        Same strategy as :meth:`recall_for_npc`, keyed on the quest's
        subject words instead of the NPC's.
        """

        words = RECALL_TOPICS.get("investigation" if "case" in quest_id else "town", ())
        if quest_id == "quest_crown_case":
            words = ("金王冠", "偷走", "还给", "调查", "线索", "案卷", "镇长", "墨墨")

        pool = self._candidate_pool(player_id)
        by_key = {str(e.get("memory_id")): e for e in pool}

        used_queries: list[str] = []
        for word in words:
            try:
                found = self.search(player_id, word, limit=10, mode="fts")
            except MemoryError:
                continue
            used_queries.append(word)
            for hit in found:
                key = str(hit.get("memory_id"))
                entry = by_key.get(key)
                if entry is None:
                    entry = dict(hit)
                    entry["memory_id"] = hit.get("memory_id")
                    by_key[key] = entry
                    pool.append(entry)
                entry["fts_rank"] = max(entry.get("fts_rank") or 0.0, float(hit.get("score") or 0.0))

        ranked = self._rank(pool, words)
        items, total_bytes = self._bounded(ranked, limit)

        return {
            "items": items,
            "bytes": total_bytes,
            "queries": used_queries,
            "mode": "fts",
            "candidate_count": len(pool),
            "note": "vector_mode_unavailable",
        }

