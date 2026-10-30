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
        """Write one memory record into the player's scope."""

        scope_id = self.ensure_scope(player_id)
        payload = self._request(
            "POST",
            "/v1/memory/remember",
            {"scope_id": scope_id, "kind": kind, "text": text[:8192]},
        )
        records = payload.get("records") or []
        artifact = records[0].get("artifact", {}) if records else {}
        return {
            "scope_id": scope_id,
            "artifact_id": artifact.get("artifact_id"),
            "revision": artifact.get("revision"),
            "kind": kind,
        }

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
