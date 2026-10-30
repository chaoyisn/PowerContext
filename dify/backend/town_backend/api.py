"""《记仇小镇》后端 HTTP API。

Dify Chatflow 通过这些端点完成"读状态 → 判动作 → 写状态 → 写记忆"的循环。

端点一览
--------

===========================  ====================================================
``GET  /health``             健康检查（seekdb + PowerContext）
``POST /api/player/register`` 注册玩家 / 绑定会话
``GET  /api/state``          读取玩家的完整游戏状态（关系、道具、剧情、记忆）
``POST /api/action``         执行一次玩家动作（幂等）
``GET  /api/players/{id}/events`` 玩家事件历史
===========================  ====================================================

安全与健壮性约定
----------------

* 所有按玩家的接口都要求 ``player_id``，且查询一律带上该 player_id，
  因此读不到别人的数据。
* ``/api/action`` 接受 ``Idempotency-Key``；重复提交返回第一次的结果，
  不会重复扣数值、重复落事件。
* 后端**不生成台词**——台词由 Dify 的 LLM 节点生成。后端只给状态与判定，
  避免模型输出直接改写游戏状态。
* 日志里不出现 API Key / Token。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from flask import Flask, g, jsonify, request

from .config import Settings, load_settings
from .engine import ACTION_LABELS, GameEngine, MemoryWriteError, request_hash
from .memory import MemoryStore
from .store import SeekDBStore, StoreError

LOGGER = logging.getLogger("town_backend")

PLAYER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,64}$")
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")


class ApiError(Exception):
    """An error that maps to a 4xx response."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def create_app(settings: Settings | None = None) -> Flask:
    """Build the Flask application."""

    settings = settings or load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    app = Flask(__name__)
    app.config["SETTINGS"] = settings
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    store = SeekDBStore(settings)
    memory = MemoryStore(settings)
    engine = GameEngine(store, memory)

    app.extensions["town_store"] = store
    app.extensions["town_memory"] = memory
    app.extensions["town_engine"] = engine

    # ------------------------------------------------------------- helpers

    def _json_body() -> dict[str, Any]:
        raw = request.get_data(cache=False)
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ApiError(400, "invalid_json", f"请求体不是合法 JSON: {error}") from error
        if not isinstance(payload, dict):
            raise ApiError(400, "invalid_json", "请求体必须是 JSON 对象")
        return payload

    def _require_player_id(payload: dict[str, Any]) -> str:
        player_id = str(payload.get("player_id") or "").strip()
        if not player_id:
            raise ApiError(400, "missing_player_id", "player_id 不能为空")
        if not PLAYER_ID_PATTERN.match(player_id):
            raise ApiError(400, "invalid_player_id", "player_id 只能包含字母、数字、下划线、连字符、点和冒号，长度 1-64")
        return player_id

    def _require_session_id(payload: dict[str, Any]) -> str:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            raise ApiError(400, "missing_session_id", "session_id 不能为空")
        if not SESSION_ID_PATTERN.match(session_id):
            raise ApiError(400, "invalid_session_id", "session_id 只能包含字母、数字、下划线、连字符、点和冒号，长度 1-128")
        return session_id

    def _check_backend_token() -> None:
        expected = settings.backend_token
        if not expected:
            return
        provided = request.headers.get("X-Town-Token", "")
        if provided != expected:
            raise ApiError(401, "unauthorized", "X-Town-Token 无效")

    @app.before_request
    def _guard():
        if request.path in ("/health", "/healthz"):
            return None
        try:
            _check_backend_token()
        except ApiError as error:
            return jsonify({"ok": False, "error": {"code": error.code, "message": error.message}}), error.status
        return None

    @app.after_request
    def _log_request(response):
        # 只记录方法、路径、状态码与耗时；不记录请求体，避免把玩家输入
        # 或任何凭据写进日志。
        LOGGER.info(
            "%s %s -> %s (%.0fms)",
            request.method, request.path, response.status_code,
            (time.time() - g.get("_start", time.time())) * 1000,
        )
        return response

    @app.before_request
    def _mark_start():
        g._start = time.time()

    # -------------------------------------------------------------- health

    @app.get("/health")
    def health():
        """Report the availability of both backing services."""

        seekdb_ok = True
        seekdb_detail = "ok"
        try:
            store.count_rows()
        except Exception as error:
            seekdb_ok = False
            seekdb_detail = f"{type(error).__name__}: {error}"

        memory_health = memory.health()
        body = {
            "ok": seekdb_ok and bool(memory_health.get("available")),
            "service": "memory-town-backend",
            "version": "1.0.0",
            "seekdb": {
                "available": seekdb_ok,
                "detail": seekdb_detail,
                "host": settings.seekdb_host,
                "port": settings.seekdb_port,
                "database": settings.seekdb_database,
            },
            "powercontext": memory_health,
        }
        return jsonify(body), (200 if body["ok"] else 503)

    # ----------------------------------------------------- player register

    @app.post("/api/player/register")
    def register_player():
        """Create the player if needed and bind the current session."""

        payload = _json_body()
        player_id = _require_player_id(payload)
        session_id = _require_session_id(payload)
        display_name = str(payload.get("display_name") or player_id).strip()[:128]

        result = store.register_player(player_id, display_name, session_id)
        return jsonify({
            "ok": True,
            "player_id": player_id,
            "session_id": session_id,
            "created": result["created"],
            "player": result["player"],
        })

    # ---------------------------------------------------------- game state

    @app.get("/api/state")
    def get_state():
        """Return the full game state of one player."""

        player_id = (request.args.get("player_id") or "").strip()
        if not player_id:
            raise ApiError(400, "missing_player_id", "player_id 不能为空")
        if not PLAYER_ID_PATTERN.match(player_id):
            raise ApiError(400, "invalid_player_id", "player_id 格式非法")

        player = store.fetch_player(player_id)
        if player is None:
            raise ApiError(404, "unknown_player", f"玩家 {player_id} 尚未注册")

        relationships = store.list_relationships(player_id)
        events = store.list_events(player_id, limit=10)
        plots = store.list_plot_progress(player_id)

        key_events = []
        npc_notes = []
        memory_error = None
        try:
            key_events = memory.recall_key_events(player_id, limit=10)
            npc_notes = memory.recall_npc_notes(player_id, limit=10)
        except Exception as error:
            # 读记忆失败不应该让整个状态接口挂掉，但要如实报告。
            memory_error = f"{type(error).__name__}: {error}"

        npcs = []
        for relationship in relationships:
            npc = store.fetch_npc(relationship["npc_id"])
            if npc is None:
                continue
            npcs.append({
                "npc_id": npc["npc_id"],
                "name": npc["name"],
                "title": npc["title"],
                "persona": npc["persona"],
                "speech_style": npc["speech_style"],
                "home_location": npc["home_location"],
                "grudge_focus": npc["grudge_focus"],
                "affinity": relationship["affinity"],
                "trust": relationship["trust"],
                "grudge_level": relationship["grudge_level"],
                "last_action": relationship["last_action"],
                "items": store.list_items("npc", npc["npc_id"]),
            })

        return jsonify({
            "ok": True,
            "player": player,
            "location": _location_view(store, player["current_location"]),
            "npcs": npcs,
            "inventory": store.list_items("player", player_id),
            "events": events,
            "plots": plots,
            "memory": {
                "key_events": key_events,
                "npc_notes": npc_notes,
                "error": memory_error,
            },
        })

    @app.get("/api/players/<player_id>/events")
    def player_events(player_id: str):
        """The player's own event history — scoped by player_id."""

        if not PLAYER_ID_PATTERN.match(player_id):
            raise ApiError(400, "invalid_player_id", "player_id 格式非法")
        limit = min(int(request.args.get("limit") or 20), 100)
        return jsonify({
            "ok": True,
            "player_id": player_id,
            "events": store.list_events(player_id, limit=limit),
        })

    # -------------------------------------------------------------- action

    @app.post("/api/action")
    def perform_action():
        """Perform one player action. Idempotent on ``Idempotency-Key``."""

        payload = _json_body()
        player_id = _require_player_id(payload)
        session_id = _require_session_id(payload)
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ApiError(400, "missing_message", "message 不能为空")
        if len(message) > settings.max_message_length:
            raise ApiError(
                400, "message_too_long",
                f"message 长度超过 {settings.max_message_length}",
            )

        npc_id = str(payload.get("npc_id") or "").strip()
        action_hint = payload.get("action_hint")
        item_hint = payload.get("item_hint")
        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or payload.get("idempotency_key")
            or ""
        ).strip()
        if idempotency_key and len(idempotency_key) > 190:
            raise ApiError(400, "invalid_idempotency_key", "Idempotency-Key 最长 190 字符")

        if store.fetch_player(player_id) is None:
            raise ApiError(404, "unknown_player", f"玩家 {player_id} 尚未注册")

        if not npc_id:
            npcs = store.list_npcs()
            npc_id = npcs[0]["npc_id"] if npcs else "mayor"

        # ---- 幂等：同 key 同请求 → 回放上次结果 --------------------------
        if idempotency_key:
            cached = store.load_request(idempotency_key, player_id)
            if cached is not None:
                fingerprint = request_hash({
                    "player_id": player_id,
                    "session_id": session_id,
                    "npc_id": npc_id,
                    "message": message,
                })
                if cached.get("request_hash") == fingerprint:
                    replayed = dict(cached["response"])
                    replayed["replayed"] = True
                    return jsonify(replayed)
                raise ApiError(
                    409, "idempotency_conflict",
                    "同一 Idempotency-Key 被用于不同的请求内容",
                )

        outcome = engine.perform_action(
            player_id=player_id,
            session_id=session_id,
            npc_id=npc_id,
            raw_text=message,
            action_hint=action_hint if isinstance(action_hint, str) else None,
            item_hint=item_hint if isinstance(item_hint, str) else None,
            idempotency_key=idempotency_key,
        )

        response = {
            "ok": True,
            "player_id": player_id,
            "session_id": session_id,
            "action": outcome.to_dict(),
            "action_label": ACTION_LABELS.get(outcome.action_type, outcome.action_type),
            "relationship": outcome.relationship,
            "plot": outcome.plot,
            "key_event": outcome.key_event,
            "notes": outcome.notes,
            "duplicate": outcome.duplicate,
        }

        if idempotency_key:
            fingerprint = request_hash({
                "player_id": player_id,
                "session_id": session_id,
                "npc_id": npc_id,
                "message": message,
            })
            store.save_request(idempotency_key, player_id, fingerprint, {
                "request_hash": fingerprint,
                "response": response,
            })

        return jsonify(response)

    # --------------------------------------------------------------- errors

    @app.errorhandler(ApiError)
    def _handle_api_error(error: ApiError):
        return jsonify({"ok": False, "error": {"code": error.code, "message": error.message}}), error.status

    @app.errorhandler(StoreError)
    def _handle_store_error(error: StoreError):
        # 规则冲突属于 409：请求本身合法，但当前状态不允许。
        return jsonify({"ok": False, "error": {"code": error.code, "message": error.message}}), 409

    @app.errorhandler(MemoryWriteError)
    def _handle_memory_error(error: MemoryWriteError):
        # 关键事件没能写进记忆库 —— 绝不能报告为成功。
        LOGGER.error("关键事件写入 PowerContext 失败: %s", error)
        return jsonify({
            "ok": False,
            "error": {"code": "memory_write_failed", "message": str(error)},
        }), 502

    @app.errorhandler(Exception)
    def _handle_unexpected(error: Exception):
        LOGGER.exception("未处理异常")
        return jsonify({
            "ok": False,
            "error": {"code": "internal_error", "message": f"{type(error).__name__}: {error}"},
        }), 500

    return app


def _location_view(store: SeekDBStore, location_id: str) -> dict[str, Any]:
    for location in store.list_locations():
        if location["location_id"] == location_id:
            return location
    return {"location_id": location_id, "name": location_id, "description": ""}


def main() -> None:
    settings = load_settings()
    app = create_app(settings)
    app.run(host="0.0.0.0", port=settings.backend_port, threaded=True)


if __name__ == "__main__":
    main()
