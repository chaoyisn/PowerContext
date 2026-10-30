"""《记仇小镇》后端 HTTP API。

Dify Chatflow 通过这些端点完成"读状态 → 判动作 → 写状态 → 写记忆"的循环。

端点一览
--------

===========================  ====================================================
``GET  /health``             健康检查（seekdb + PowerContext）
``POST /api/player/register`` 注册玩家 / 绑定会话 / 绑定身份
``GET  /api/state``          读取玩家的完整游戏状态（关系、道具、剧情、记忆）
``POST /api/action``         执行一次玩家动作（幂等）
``POST /api/intent/resolve`` 语义意图裁定（模型给候选，代码定案）
``GET  /api/quest``          当前任务与进度
``GET  /api/ending``         结局状态与成就
``GET  /api/memory/context`` 有界记忆召回（按 NPC / 按任务）
``POST /api/memory/retry``   记忆补偿：重试 outbox 里待写的关键事件
``GET  /api/players/{id}/events`` 玩家事件历史
===========================  ====================================================

安全约定（V2）
--------------
**三层认证。**

1. **服务凭据** ``X-Town-Token``：由 ``TOWN_BACKEND_TOKEN`` 配置。
   Dify 通过**密钥型环境变量** ``{{#env.TOWN_BACKEND_TOKEN#}}`` 注入，
   凭据本身**不出现在 DSL、源码、测试证据或日志里**。
   缺失或错误 → 401。

2. **玩家身份** ``X-Town-Identity``：Dify 侧的可信身份。
   * Service API / Web App：``{{#sys.user_id#}}``，也就是已认证终端用户的
     session id —— 调用方必须为每个真人提供不同的 ``user``。
   * Console 调试运行：``{{#sys.user_id#}}`` 是 Console 账号 id，
     属于**运维身份**，一个身份可以有多个存档。

   绑定规则：**一个玩家只属于一个身份**。首次带身份访问时绑定；
   此后换身份访问同一个玩家 → 403 ``identity_mismatch``。
   反过来，同一个身份可以有多个存档（同一真人开多个号）。

3. **玩家密令** ``X-Town-Secret``：玩家自己输入的口令。
   存在 ``town_player_identity.secret_hash``（只存哈希）。

   为什么要第三层：Console 调试模式下，**所有测试者共享同一个控制台
   身份**，只靠第 2 层挡不住一个人冒用另一个人的存档。密令才是
   "这把钥匙归我"的那一半 —— 拿到别人的 ``player_id`` 也没用，
   还得知道密令。

   密令一旦设定就不能被别的密令顶替（顶替 = 接管存档）；
   忘了密令就拿不回这个存档，这是密令的应有之义。

**因此：拿到别人的 ``player_id`` 也读不到别人的持久状态** ——
必须同时满足"身份对得上"且"密令对得上"（或持有签发时一次性返回的
玩家令牌）。

*Demo 模式*：设置 ``TOWN_ALLOW_ANONYMOUS=1`` 后可以不带身份访问，
  但每个响应都会带 ``"demo_mode": true`` 标记 —— **此时不具备玩家身份隔离**，
  只有服务凭据在把关。文档与证据里都如实标注，不宣称比实际更强的隔离。

**其它约定。**

* 所有按玩家的接口都要求 ``player_id``，且查询一律带上该 player_id，
  因此读不到别人的数据。
* ``/api/action`` 接受 ``Idempotency-Key``；重复提交返回第一次的结果，
  不会重复扣数值、重复落事件。
* 后端**不生成台词**——台词由 Dify 的 LLM 节点生成。后端只给状态与判定，
  避免模型输出直接改写游戏状态。
* 日志里不出现 API Key / Token，也不记录请求体。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from typing import Any

from flask import Flask, g, jsonify, request

from .config import Settings, load_settings
from .engine import (
    ACTION_LABELS,
    ACTION_TYPES,
    GameEngine,
    MemoryWriteError,
    request_hash,
)
from .memory import MemoryStore
from .store import SeekDBStore, StoreError

LOGGER = logging.getLogger("town_backend")

PLAYER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,64}$")
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")

#: 身份标识的长度上限，防止把超长字符串塞进数据库。
IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.@]{1,128}$")


class ApiError(Exception):
    """An error that maps to a 4xx response."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _hash_token(token: str) -> str:
    """Hash a player token before storing it.

    The raw token is shown to the player exactly once (at registration);
    only its hash is kept, so a database dump cannot be replayed.
    """

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _tokens_match(stored_hash: str, presented: str) -> bool:
    return hmac.compare_digest(stored_hash, _hash_token(presented))


def _hash_secret(secret: str) -> str:
    """Hash a player secret. Only the hash is stored."""

    return hashlib.sha256(("town-secret:" + secret).encode("utf-8")).hexdigest()


def _secret_matches(stored_hash: str, presented: str) -> bool:
    """Constant-time comparison of a presented secret against its hash."""

    if not stored_hash or not presented:
        return False
    return hmac.compare_digest(stored_hash, _hash_secret(presented))


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
        """Service-to-service credential.

        When ``TOWN_BACKEND_TOKEN`` is set it is **mandatory**. The token
        is compared in constant time and never written to the log.
        """

        expected = settings.backend_token
        if not expected:
            return
        provided = request.headers.get("X-Town-Token", "")
        if not provided or not hmac.compare_digest(provided, expected):
            raise ApiError(401, "unauthorized", "X-Town-Token 无效")

    def _presented_identity() -> str:
        """The trusted identity of this caller, if it sent one."""

        identity = str(
            request.headers.get("X-Town-Identity")
            or request.args.get("identity")
            or ""
        ).strip()
        if identity and not IDENTITY_PATTERN.match(identity):
            raise ApiError(400, "invalid_identity", "identity 格式非法")
        return identity

    def _presented_secret() -> str:
        """The player-held secret (access code), if the caller sent one."""

        return str(
            request.headers.get("X-Town-Secret")
            or request.args.get("secret")
            or ""
        ).strip()[:128]

    def _presented_player_token() -> str:
        return str(request.headers.get("X-Town-Player-Token") or "").strip()

    def _authorize_player(player_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Check that this caller may act as ``player_id``.

        Rules:

        * If the player is already bound to an identity, the caller must
          present **that** identity, plus the player's secret if one has
          been set. Otherwise → 403.
        * A player with no binding yet is bound to the caller's identity
          and secret on first use.
        * Demo mode (no identity at all) is allowed only when explicitly
          enabled, and is reported as such.

        The secret is what keeps isolation honest when several people
        share one console identity — the situation in a live demo, where
        everybody is "the operator" as far as ``sys.user_id`` is
        concerned. With a secret in place, knowing somebody's
        ``player_id`` is not enough to read their save.
        """

        identity = _presented_identity()
        secret = _presented_secret()
        player_token = _presented_player_token()

        record = store.fetch_identity(player_id) or {}
        owner = record.get("owner_identity") or ""
        stored_secret_hash = record.get("secret_hash") or ""

        if owner:
            if not identity or not hmac.compare_digest(identity, owner):
                raise ApiError(
                    403, "identity_mismatch",
                    "该玩家已绑定到另一个身份，无法访问",
                )
            if stored_secret_hash:
                if not secret:
                    raise ApiError(
                        401, "secret_required",
                        "该存档设了密令，请先提供密令",
                    )
                if not _secret_matches(stored_secret_hash, secret):
                    raise ApiError(403, "secret_mismatch", "密令不正确")
            elif secret:
                # 该存档还没有密令 —— 第一次提供密令的人把它定下来。
                store.bind_identity(player_id, identity, secret)
            if player_token and record.get("token_hash"):
                if _tokens_match(record["token_hash"], player_token):
                    return {"mode": "player_token", "identity": identity}
            return {"mode": "identity", "identity": identity}

        if identity:
            store.bind_identity(player_id, identity, secret)
            return {"mode": "identity", "identity": identity}

        if settings.allow_anonymous:
            # Demo 模式：没有身份隔离，只有服务凭据在把关。
            return {"mode": "demo", "demo_mode": True}

        raise ApiError(
            401, "identity_required",
            "缺少 X-Town-Identity；该后端未开启 demo 模式",
        )

    def _demo_flag() -> bool:
        """Is this request running without a trusted player identity?"""

        return bool(settings.allow_anonymous and not _presented_identity())

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
            "version": "2.0.0",
            "seekdb": {
                "available": seekdb_ok,
                "detail": seekdb_detail,
                "host": settings.seekdb_host,
                "port": settings.seekdb_port,
                "database": settings.seekdb_database,
            },
            "powercontext": memory_health,
            "auth": {
                # 只报告"是否要求凭据"，**绝不回显凭据本身**。
                "backend_token_required": bool(settings.backend_token),
                "identity_required": not settings.allow_anonymous,
            },
        }
        return jsonify(body), (200 if body["ok"] else 503)

    # ----------------------------------------------------- player register

    @app.post("/api/player/register")
    def register_player():
        """Create the player if needed, bind the session, the identity and the secret."""

        payload = _json_body()
        player_id = _require_player_id(payload)
        session_id = _require_session_id(payload)
        display_name = str(payload.get("display_name") or player_id).strip()[:128]
        identity = _presented_identity()
        secret = str(payload.get("secret") or _presented_secret()).strip()[:128]

        existing_identity = store.fetch_identity(player_id)
        if existing_identity:
            owner = existing_identity.get("owner_identity") or ""
            stored_secret_hash = existing_identity.get("secret_hash") or ""
            if identity and owner and not hmac.compare_digest(identity, owner):
                raise ApiError(
                    403, "identity_mismatch",
                    "该玩家已绑定到另一个身份，无法接管",
                )
            if stored_secret_hash:
                if not secret:
                    raise ApiError(
                        401, "secret_required",
                        "该存档设了密令，请先提供密令",
                    )
                if not _secret_matches(stored_secret_hash, secret):
                    raise ApiError(403, "secret_mismatch", "密令不正确")
            if not identity and not settings.allow_anonymous:
                raise ApiError(
                    401, "identity_required",
                    "缺少 X-Town-Identity；该后端未开启 demo 模式",
                )

        result = store.register_player(player_id, display_name, session_id)

        # 首次绑定身份与密令，并签发玩家令牌（只在令牌不存在时签发）。
        if identity:
            store.bind_identity(player_id, identity, secret)
        token = store.ensure_player_token(player_id)
        issued = token.get("issued", False)
        token_value = token.get("token", "")

        return jsonify({
            "ok": True,
            "player_id": player_id,
            "session_id": session_id,
            "created": result["created"],
            "player": result["player"],
            "identity_bound": bool(identity),
            "secret_set": bool(secret),
            # 令牌只在签发时返回一次；之后只有哈希被保存。
            "player_token": token_value if issued else "",
            "demo_mode": _demo_flag(),
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

        auth = _authorize_player(player_id)

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
                "faction": npc.get("faction", ""),
                "knowledge_tags": npc.get("knowledge_tags", ""),
                "affinity": relationship["affinity"],
                "trust": relationship["trust"],
                "grudge_level": relationship["grudge_level"],
                "last_action": relationship["last_action"],
                "items": store.list_items("npc", npc["npc_id"]),
            })

        # 当前位置的 NPC —— Dify 决定"这一轮跟谁说话"要用。
        present = [
            npc for npc in npcs
            if npc["home_location"] == player["current_location"]
        ]

        return jsonify({
            "ok": True,
            "player": player,
            "location": _location_view(store, player["current_location"]),
            "npcs": npcs,
            "npcs_present": [npc["npc_id"] for npc in present],
            "inventory": store.list_items("player", player_id),
            "events": events,
            "plots": plots,
            "quests": store.list_quests(player_id),
            "endings": store.list_endings(player_id),
            "achievements": store.list_achievements(player_id),
            "knowledge": store.list_knowledge(player_id),
            "memory": {
                "key_events": key_events,
                "npc_notes": npc_notes,
                "error": memory_error,
            },
            "auth_mode": auth.get("mode", "demo"),
            "demo_mode": _demo_flag(),
        })

    @app.get("/api/players/<player_id>/events")
    def player_events(player_id: str):
        """The player's own event history — scoped by player_id."""

        if not PLAYER_ID_PATTERN.match(player_id):
            raise ApiError(400, "invalid_player_id", "player_id 格式非法")
        _authorize_player(player_id)
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
        location_hint = payload.get("location_hint")
        model_intent = payload.get("model_intent")
        action_type = str(payload.get("action_type") or "").strip()
        idempotency_key = (
            request.headers.get("Idempotency-Key")
            or payload.get("idempotency_key")
            or ""
        ).strip()
        if idempotency_key and len(idempotency_key) > 190:
            raise ApiError(400, "invalid_idempotency_key", "Idempotency-Key 最长 190 字符")

        if store.fetch_player(player_id) is None:
            raise ApiError(404, "unknown_player", f"玩家 {player_id} 尚未注册")

        _authorize_player(player_id)

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

        # ---- 语义意图裁定（模型给候选，代码定案） -----------------------
        resolution = None
        if action_type or model_intent is not None:
            resolution = engine.resolve_intent(
                player_id,
                message,
                store.list_npcs(),
                model_intent=model_intent if isinstance(model_intent, (str, dict)) else None,
                default_npc_id=npc_id,
                # 调用方已经裁定的动作类型：模型没给候选时，关键词降级
                # 路径要听它的，而不是让"给""送"这类字眼盖掉它。
                requested_action=action_type,
            )
            action_type = resolution.action_type
            npc_id = resolution.npc_id or npc_id
            if resolution.item_id:
                item_hint = resolution.item_id
            if resolution.target_location:
                location_hint = resolution.target_location
        elif action_hint:
            action_type = str(action_hint)

        outcome = engine.perform_action(
            player_id=player_id,
            session_id=session_id,
            npc_id=npc_id,
            raw_text=message,
            action_hint=action_hint if isinstance(action_hint, str) else None,
            item_hint=item_hint if isinstance(item_hint, str) else None,
            location_hint=location_hint if isinstance(location_hint, str) else None,
            action_type=action_type if action_type in ACTION_TYPES else "",
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
            "quest": outcome.quest,
            "ending": outcome.ending,
            "key_event": outcome.key_event,
            "npc_note": outcome.npc_note,
            "notes": outcome.notes,
            "duplicate": outcome.duplicate,
            # 记忆写失败时**如实**报告，而不是假装成功。
            "memory_written": outcome.memory_written,
            "npc_note_written": outcome.npc_note_written,
            "memory_error": outcome.memory_error,
            "intent": resolution.to_dict() if resolution else None,
            "demo_mode": _demo_flag(),
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

    # ------------------------------------------------------- 语义意图裁定

    @app.post("/api/intent/resolve")
    def resolve_intent():
        """Decide what the player meant — the trust boundary.

        The Dify LLM node posts its JSON candidate here; this endpoint
        applies the deterministic rules (confidence, commitment, target
        existence) and returns the verdict. The **backend** is the only
        component allowed to turn a candidate into an executed action.
        """

        payload = _json_body()
        player_id = _require_player_id(payload)
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ApiError(400, "missing_message", "message 不能为空")
        if len(message) > settings.max_message_length:
            raise ApiError(400, "message_too_long", "message 长度超过上限")

        model_intent = payload.get("model_intent")
        if isinstance(model_intent, (str, dict)):
            pass
        elif model_intent is not None:
            model_intent = None

        resolution = engine.resolve_intent(
            player_id,
            message,
            store.list_npcs(),
            model_intent=model_intent,
            default_npc_id=str(payload.get("npc_id") or "mayor"),
            current_location=(store.fetch_player(player_id) or {}).get("current_location", ""),
        )
        return jsonify({
            "ok": True,
            "player_id": player_id,
            "intent": resolution.to_dict(),
        })

    # ------------------------------------------------------------- 任务/结局

    @app.get("/api/quest")
    def get_quest():
        """The player's current quest(s) and progress."""

        player_id = (request.args.get("player_id") or "").strip()
        if not PLAYER_ID_PATTERN.match(player_id or ""):
            raise ApiError(400, "invalid_player_id", "player_id 格式非法")
        _authorize_player(player_id)
        quests = store.list_quests(player_id)
        plots = store.list_plot_progress(player_id)
        return jsonify({
            "ok": True,
            "player_id": player_id,
            "quests": quests,
            "plots": plots,
            "demo_mode": _demo_flag(),
        })

    @app.get("/api/ending")
    def get_ending():
        """The player's ending state, achievements and quest summary."""

        player_id = (request.args.get("player_id") or "").strip()
        if not PLAYER_ID_PATTERN.match(player_id or ""):
            raise ApiError(400, "invalid_player_id", "player_id 格式非法")
        _authorize_player(player_id)
        player = store.fetch_player(player_id) or {}
        return jsonify({
            "ok": True,
            "player_id": player_id,
            "ending_id": player.get("ending_id", ""),
            "ending_claimed": bool(player.get("ending_claimed")),
            "coins": player.get("coins", 0),
            "endings": store.list_endings(player_id),
            "achievements": store.list_achievements(player_id),
            "quests": store.list_quests(player_id),
            "demo_mode": _demo_flag(),
        })

    # --------------------------------------------------------- 记忆与补偿

    @app.get("/api/memory/context")
    def memory_context():
        """Bounded memory recall — per NPC or per quest.

        The result is explicitly bounded (fixed item count + byte budget)
        and reports which retrieval channel was actually used.
        """

        player_id = (request.args.get("player_id") or "").strip()
        if not PLAYER_ID_PATTERN.match(player_id or ""):
            raise ApiError(400, "invalid_player_id", "player_id 格式非法")
        _authorize_player(player_id)

        npc_id = (request.args.get("npc_id") or "").strip()
        quest_id = (request.args.get("quest_id") or "").strip()
        query = (request.args.get("query") or "").strip()[:200]

        result: dict[str, Any]
        error = ""
        try:
            if npc_id:
                result = memory.recall_for_npc(player_id, npc_id)
            elif quest_id:
                result = memory.recall_for_quest(player_id, quest_id)
            else:
                result = {
                    "items": memory.recall_key_events(player_id, limit=8),
                    "bytes": 0,
                    "queries": [],
                    "mode": "entries_list",
                    "candidate_count": 0,
                    "note": "no_topic",
                }
        except Exception as exc:  # noqa: BLE001
            result = {"items": [], "bytes": 0, "queries": [], "mode": "fts"}
            error = f"{type(exc).__name__}: {exc}"

        return jsonify({
            "ok": True,
            "player_id": player_id,
            "context": result,
            "error": error,
            "demo_mode": _demo_flag(),
        })

    @app.post("/api/memory/retry")
    def memory_retry():
        """Compensate memory writes that failed.

        The outbox row was committed together with the game state, so a
        PowerContext outage leaves a retryable job rather than a lost
        event. This endpoint drains the pending jobs. It is idempotent:
        the dedupe key prevents a second copy of the same memory.
        """

        payload = _json_body()
        limit = max(1, min(int(payload.get("limit") or 20), 100))

        pending = store.list_pending_memory_jobs(limit=limit)
        results = []
        for job in pending:
            player_id = job["player_id"]
            try:
                memory.remember(player_id, job["kind"], job["payload"])
                store.mark_memory_done(job["dedupe_key"])
                results.append({"dedupe_key": job["dedupe_key"], "ok": True})
            except Exception as exc:  # noqa: BLE001
                store.mark_memory_failed(job["dedupe_key"], f"{type(exc).__name__}: {exc}")
                results.append({
                    "dedupe_key": job["dedupe_key"],
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        return jsonify({
            "ok": True,
            "attempted": len(results),
            "succeeded": sum(1 for r in results if r["ok"]),
            "results": results,
            "outbox": store.count_outbox_by_state(),
        })

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
