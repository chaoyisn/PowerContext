"""seekdb (OceanBase) 游戏状态存储层。

这一层负责三件事：

1. **建库建表 + 种子数据**（``initialize``）。
2. **带规则校验的 CRUD**（``register_player`` / ``transfer_item`` / ``record_event`` …）。
3. **玩家隔离**：所有按玩家的查询都以 ``player_id`` 作为索引前缀，
   读不到别的玩家的数据。

写操作的并发安全依赖 seekdb 的 InnoDB 事务与唯一键：

* ``town_event.idempotency_key`` 唯一键保证同一动作重复提交只落一条事件。
* ``town_request_log`` 唯一键把重复请求映射回同一份响应。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import pymysql

from .config import Settings

PLAYER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,64}$")

#: V2 的动作类型。比 V1 多出"归还/道歉/移动/求助/贿赂"，
#: 以便剧情分支和结局判定有确定性的判定依据。
ACTION_TYPES = (
    "talk", "prank", "gift", "steal", "investigate", "unknown",
    "return_item", "apologize", "move", "help", "bribe",
)


class StoreError(RuntimeError):
    """Raised when a state change violates a game rule."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _hash_secret(secret: str) -> str:
    """Hash a player secret. Only the hash is ever stored."""

    return hashlib.sha256(("town-secret:" + secret).encode("utf-8")).hexdigest()


def _secret_matches(stored_hash: str, presented: str) -> bool:
    """Constant-time comparison of a presented secret against its hash."""

    if not stored_hash or not presented:
        return False
    return hmac.compare_digest(stored_hash, _hash_secret(presented))


class SeekDBStore:
    """Game state in seekdb."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        #: Ambient transaction, when one is open. Flask serves requests on
        #: threads, so the cursor must be thread-local.
        self._local = threading.local()

    # ------------------------------------------------------------- transport

    def _connect(self, database: str | None = None):
        return pymysql.connect(
            host=self.settings.seekdb_host,
            port=self.settings.seekdb_port,
            user=self.settings.seekdb_user,
            password=self.settings.seekdb_password,
            database=database,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
            charset="utf8mb4",
            autocommit=False,
        )

    @contextmanager
    def _cursor(self, database: str | None = None) -> Iterator[Any]:
        """Yield a cursor.

        Inside an open transaction the ambient cursor is reused, so several
        calls join the *same* transaction. Outside one, the statement runs
        on its own and is committed immediately.
        """

        ambient = getattr(self._local, "cursor", None)
        if ambient is not None:
            yield ambient
            return

        connection = self._connect(database)
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Open one transaction; every write inside it commits or rolls back together."""

        existing = getattr(self._local, "cursor", None)
        if existing is not None:
            # Nested transaction → join the outer one.
            yield existing
            return

        connection = self._connect(self.settings.seekdb_database)
        cursor = connection.cursor(pymysql.cursors.DictCursor)
        self._local.cursor = cursor
        self._local.connection = connection
        try:
            yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._local.cursor = None
            self._local.connection = None
            cursor.close()
            connection.close()

    def in_transaction(self) -> bool:
        return getattr(self._local, "cursor", None) is not None

    # ------------------------------------------------------------ bootstrap

    def initialize(self) -> dict[str, Any]:
        """Create the database, the tables and the seed rows.

        Returns a small report so the caller can show what actually happened
        instead of assuming success.
        """

        schema_sql = self.settings.schema_path.read_text(encoding="utf-8")
        report: dict[str, Any] = {"database": self.settings.seekdb_database, "tables": []}

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.settings.seekdb_database}` "
                               f"DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_bin")
            connection.commit()
        finally:
            connection.close()

        with self._cursor(self.settings.seekdb_database) as cursor:
            for statement in _split_sql(schema_sql):
                cursor.execute(statement)
                if statement.upper().startswith("CREATE TABLE"):
                    name = statement.split("`")[1]
                    report["tables"].append(name)

        seed_sql = self.settings.seed_path.read_text(encoding="utf-8")
        with self._cursor(self.settings.seekdb_database) as cursor:
            for statement in _split_sql(seed_sql):
                cursor.execute(statement)

        report["tables"] = sorted(set(report["tables"]))
        return report

    def drop_database(self) -> None:
        """Drop the whole database. Used by the reset script only."""

        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS `{self.settings.seekdb_database}`")
            connection.commit()
        finally:
            connection.close()

    # ------------------------------------------------------------------ read

    def fetch_player(self, player_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, display_name, current_location, session_id, turn_count, "
                "coins, current_quest, ending_id, ending_claimed "
                "FROM town_player WHERE player_id = %s",
                (player_id,),
            )
            return cursor.fetchone()

    def fetch_npc(self, npc_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT npc_id, name, title, persona, speech_style, home_location, grudge_focus, "
                "faction, ally_npc_id, knowledge_tags "
                "FROM town_npc WHERE npc_id = %s",
                (npc_id,),
            )
            return cursor.fetchone()

    def list_npcs(self) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT npc_id, name, title, persona, speech_style, home_location, grudge_focus, "
                "faction, ally_npc_id, knowledge_tags "
                "FROM town_npc ORDER BY npc_id"
            )
            return list(cursor.fetchall())

    def list_locations(self) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT location_id, name, description, is_start, is_reachable "
                "FROM town_location ORDER BY location_id"
            )
            return list(cursor.fetchall())

    def list_location_ids(self) -> set[str]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute("SELECT location_id FROM town_location")
            return {row["location_id"] for row in cursor.fetchall()}

    def location_link_exists(self, from_location: str, to_location: str) -> bool:
        """Can the player walk from one location to the other?

        The link table is the authority. It is what makes "神秘后巷" a
        place you have to walk to rather than a place you can teleport to.
        """

        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT 1 AS ok FROM town_location_link "
                "WHERE from_location = %s AND to_location = %s",
                (from_location, to_location),
            )
            return cursor.fetchone() is not None

    def list_location_links(self) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT from_location, to_location, travel_cost FROM town_location_link "
                "ORDER BY from_location, to_location"
            )
            return list(cursor.fetchall())

    def fetch_relationship(self, player_id: str, npc_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, npc_id, affinity, trust, grudge_level, last_action "
                "FROM town_relationship WHERE player_id = %s AND npc_id = %s",
                (player_id, npc_id),
            )
            return cursor.fetchone()

    def list_relationships(self, player_id: str) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, npc_id, affinity, trust, grudge_level, last_action "
                "FROM town_relationship WHERE player_id = %s ORDER BY npc_id",
                (player_id,),
            )
            return list(cursor.fetchall())

    def list_events(self, player_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT event_id, npc_id, action_type, action_text, item_id, outcome, "
                "affinity_delta, trust_delta, grudge_delta, session_id, is_committed, "
                "location_id, confidence, created_at "
                "FROM town_event WHERE player_id = %s ORDER BY created_at DESC, event_id DESC LIMIT %s",
                (player_id, limit),
            )
            return list(cursor.fetchall())

    def fetch_event_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT event_id, player_id, npc_id, action_type, action_text, item_id, outcome, "
                "affinity_delta, trust_delta, grudge_delta, session_id, is_committed, "
                "location_id, confidence, created_at "
                "FROM town_event WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            return cursor.fetchone()

    def list_items(self, owner_kind: str, owner_id: str) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable, "
                "item_kind, is_evidence "
                "FROM town_item WHERE owner_kind = %s AND owner_id = %s ORDER BY item_id",
                (owner_kind, owner_id),
            )
            return list(cursor.fetchall())

    def list_all_items(self) -> list[dict[str, Any]]:
        """Every item row, whoever holds it.

        道具是**可移动**的：王冠被偷走以后，它那一行的 owner 变成
        player。只按 NPC / town 去列会漏掉"玩家手上的王冠"，
        于是"把王冠还给镇长"会被误判成"世界上没有王冠"。
        """

        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable, "
                "item_kind, is_evidence "
                "FROM town_item ORDER BY item_id, owner_kind, owner_id"
            )
            return list(cursor.fetchall())

    def fetch_item(
        self, item_id: str, owner_kind: str | None = None, owner_id: str | None = None
    ) -> dict[str, Any] | None:
        """Fetch one item.

        A row is identified by ``(item_id, owner_kind, owner_id)``. When the
        owner is not given, the first row carrying that ``item_id`` is
        returned — for unique items like the crown that is unambiguous.
        """

        with self._cursor(self.settings.seekdb_database) as cursor:
            if owner_kind is None or owner_id is None:
                cursor.execute(
                    "SELECT item_id, name, description, owner_kind, owner_id, quantity, "
                    "is_transferable, item_kind, is_evidence "
                    "FROM town_item WHERE item_id = %s ORDER BY owner_kind, owner_id LIMIT 1",
                    (item_id,),
                )
            else:
                cursor.execute(
                    "SELECT item_id, name, description, owner_kind, owner_id, quantity, "
                    "is_transferable, item_kind, is_evidence "
                    "FROM town_item WHERE item_id = %s AND owner_kind = %s AND owner_id = %s",
                    (item_id, owner_kind, owner_id),
                )
            return cursor.fetchone()

    def list_evidence_items(self, player_id: str) -> list[dict[str, Any]]:
        """The evidence the player is currently carrying.

        The "悬案大师" ending is gated on this list, so it is read from the
        authoritative item table rather than from anything the model said.
        """

        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT item_id, name, description, owner_kind, owner_id, quantity, "
                "is_transferable, item_kind, is_evidence "
                "FROM town_item WHERE owner_kind = 'player' AND owner_id = %s AND is_evidence = 1 "
                "ORDER BY item_id",
                (player_id,),
            )
            return list(cursor.fetchall())

    def player_has_item(self, player_id: str, item_id: str) -> bool:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT 1 AS ok FROM town_item "
                "WHERE item_id = %s AND owner_kind = 'player' AND owner_id = %s",
                (item_id, player_id),
            )
            return cursor.fetchone() is not None

    def list_plot_progress(self, player_id: str) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, plot_id, stage, triggered, detail, stage_flags, ending_id "
                "FROM town_plot_progress WHERE player_id = %s ORDER BY plot_id",
                (player_id,),
            )
            return list(cursor.fetchall())

    def fetch_plot_progress(self, player_id: str, plot_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, plot_id, stage, triggered, detail, stage_flags, ending_id "
                "FROM town_plot_progress WHERE player_id = %s AND plot_id = %s",
                (player_id, plot_id),
            )
            return cursor.fetchone()

    def update_plot_ending(self, player_id: str, plot_id: str, ending_id: str) -> None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "UPDATE town_plot_progress SET ending_id = %s WHERE player_id = %s AND plot_id = %s",
                (ending_id, player_id, plot_id),
            )

    def count_rows(self) -> dict[str, int]:
        """Row counts per table. Used by the verification report."""

        tables = (
            "town_location", "town_npc", "town_player", "town_relationship",
            "town_item", "town_event", "town_plot_progress", "town_request_log",
            "town_location_link", "town_knowledge", "town_quest", "town_ending",
            "town_achievement", "town_outbox", "town_player_identity",
        )
        counts: dict[str, int] = {}
        with self._cursor(self.settings.seekdb_database) as cursor:
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                counts[table] = int(cursor.fetchone()["n"])
        return counts

    # ----------------------------------------------------------------- write

    def register_player(self, player_id: str, display_name: str, session_id: str) -> dict[str, Any]:
        """Create the player if absent; always bind it to the new session.

        An existing player keeps its accumulated state — that is what makes
        the cross-session memory loop observable.
        """

        if not PLAYER_ID_PATTERN.match(player_id or ""):
            raise StoreError("invalid_player_id", "player_id 只能包含字母、数字、下划线、连字符、点和冒号，长度 1-64")
        if not (display_name or "").strip():
            raise StoreError("invalid_display_name", "display_name 不能为空")
        if not (session_id or "").strip():
            raise StoreError("invalid_session_id", "session_id 不能为空")

        created = False
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT player_id, display_name, current_location, session_id, turn_count "
                "FROM town_player WHERE player_id = %s FOR UPDATE",
                (player_id,),
            )
            existing = cursor.fetchone()

            if existing is None:
                cursor.execute(
                    "SELECT location_id FROM town_location WHERE is_start = 1 ORDER BY location_id LIMIT 1"
                )
                start = cursor.fetchone()
                location_id = start["location_id"] if start else "town_square"
                cursor.execute(
                    "INSERT INTO town_player "
                    "(player_id, display_name, current_location, session_id, turn_count) "
                    "VALUES (%s, %s, %s, %s, 0)",
                    (player_id, display_name.strip()[:128], location_id, session_id),
                )
                created = True
                cursor.execute(
                    "SELECT npc_id FROM town_npc ORDER BY npc_id"
                )
                for row in cursor.fetchall():
                    cursor.execute(
                        "INSERT IGNORE INTO town_relationship "
                        "(player_id, npc_id, affinity, trust, grudge_level, last_action) "
                        "VALUES (%s, %s, 0, %s, 0, '')",
                        (player_id, row["npc_id"], _initial_trust(row["npc_id"])),
                    )
            else:
                cursor.execute(
                    "UPDATE town_player SET session_id = %s WHERE player_id = %s",
                    (session_id, player_id),
                )

            cursor.execute(
                "SELECT player_id, display_name, current_location, session_id, turn_count "
                "FROM town_player WHERE player_id = %s",
                (player_id,),
            )
            row = cursor.fetchone()

        return {"created": created, "player": row}

    def set_player_location(self, player_id: str, location_id: str) -> None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "UPDATE town_player SET current_location = %s WHERE player_id = %s",
                (location_id, player_id),
            )

    def increment_turn(self, player_id: str) -> int:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "UPDATE town_player SET turn_count = turn_count + 1 WHERE player_id = %s", (player_id,)
            )
            cursor.execute("SELECT turn_count FROM town_player WHERE player_id = %s", (player_id,))
            row = cursor.fetchone()
            return int(row["turn_count"]) if row else 0

    def apply_relationship_delta(
        self,
        player_id: str,
        npc_id: str,
        affinity_delta: int,
        trust_delta: int,
        grudge_delta: int,
        last_action: str,
    ) -> dict[str, Any]:
        """Move the relationship numbers, clamped to their legal range.

        The CHECK constraints on the table are the last line of defence; the
        clamp here keeps the numbers meaningful instead of failing the write.
        """

        with self.transaction() as cursor:
            cursor.execute(
                "SELECT affinity, trust, grudge_level FROM town_relationship "
                "WHERE player_id = %s AND npc_id = %s FOR UPDATE",
                (player_id, npc_id),
            )
            current = cursor.fetchone()
            if current is None:
                raise StoreError("no_relationship", f"玩家 {player_id} 与 {npc_id} 之间没有关系记录")

            affinity = _clamp(int(current["affinity"]) + affinity_delta, -100, 100)
            trust = _clamp(int(current["trust"]) + trust_delta, 0, 100)
            grudge = _clamp(int(current["grudge_level"]) + grudge_delta, 0, 100)

            cursor.execute(
                "UPDATE town_relationship SET affinity = %s, trust = %s, grudge_level = %s, "
                "last_action = %s WHERE player_id = %s AND npc_id = %s",
                (affinity, trust, grudge, last_action, player_id, npc_id),
            )

        return {"affinity": affinity, "trust": trust, "grudge_level": grudge}

    def transfer_item(
        self,
        item_id: str,
        to_kind: str,
        to_id: str,
        *,
        from_kind: str | None = None,
        from_id: str | None = None,
        count: int = 1,
    ) -> dict[str, Any]:
        """Move ``count`` units of one item to a new owner.

        The source row keeps its remaining quantity; a row for the
        destination is created or topped up. Unique items (quantity 1)
        simply change owner. Ownership rules are enforced here.
        """

        if to_kind not in ("npc", "player", "town"):
            raise StoreError("invalid_owner_kind", "owner_kind 只能是 npc / player / town")
        if count < 1:
            raise StoreError("invalid_count", "转移数量必须大于 0")

        with self.transaction() as cursor:
            if from_kind is None or from_id is None:
                cursor.execute(
                    "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable, "
                    "item_kind, is_evidence "
                    "FROM town_item WHERE item_id = %s FOR UPDATE",
                    (item_id,),
                )
            else:
                cursor.execute(
                    "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable, "
                    "item_kind, is_evidence "
                    "FROM town_item WHERE item_id = %s AND owner_kind = %s AND owner_id = %s FOR UPDATE",
                    (item_id, from_kind, from_id),
                )
            item = cursor.fetchone()
            if item is None:
                raise StoreError("unknown_item", f"道具 {item_id} 不存在")
            if not int(item["is_transferable"]):
                raise StoreError("item_not_transferable", f"道具「{item['name']}」无法被转手")
            if item["owner_kind"] == to_kind and item["owner_id"] == to_id:
                raise StoreError("item_already_owned", f"道具「{item['name']}」已经在该持有者手中")

            available = int(item["quantity"])
            if count > available:
                raise StoreError(
                    "not_enough_items",
                    f"道具「{item['name']}」只剩 {available} 件，无法给出 {count} 件",
                )

            remaining = available - count

            # 目标持有者可能已经有同款道具 —— 那就并入它的数量。
            cursor.execute(
                "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable, "
                "item_kind, is_evidence "
                "FROM town_item WHERE item_id = %s AND owner_kind = %s AND owner_id = %s FOR UPDATE",
                (item_id, to_kind, to_id),
            )
            target = cursor.fetchone()

            if target is not None:
                # 目标已有同款：源行只扣数量（不够就整行删掉），目标行累加。
                if remaining == 0:
                    cursor.execute(
                        "DELETE FROM town_item WHERE item_id = %s AND owner_kind = %s AND owner_id = %s",
                        (item_id, item["owner_kind"], item["owner_id"]),
                    )
                else:
                    cursor.execute(
                        "UPDATE town_item SET quantity = %s WHERE item_id = %s "
                        "AND owner_kind = %s AND owner_id = %s",
                        (remaining, item_id, item["owner_kind"], item["owner_id"]),
                    )
                cursor.execute(
                    "UPDATE town_item SET quantity = quantity + %s "
                    "WHERE item_id = %s AND owner_kind = %s AND owner_id = %s",
                    (count, item_id, to_kind, to_id),
                )
            elif remaining == 0:
                # 源行整体转手：直接改归属。
                cursor.execute(
                    "UPDATE town_item SET owner_kind = %s, owner_id = %s WHERE item_id = %s "
                    "AND owner_kind = %s AND owner_id = %s",
                    (to_kind, to_id, item_id, item["owner_kind"], item["owner_id"]),
                )
            else:
                # 源行还剩存货：扣掉转出的部分，再为目标新建一行。
                cursor.execute(
                    "UPDATE town_item SET quantity = %s WHERE item_id = %s "
                    "AND owner_kind = %s AND owner_id = %s",
                    (remaining, item_id, item["owner_kind"], item["owner_id"]),
                )
                cursor.execute(
                    "INSERT INTO town_item "
                    "(item_id, owner_kind, owner_id, name, description, quantity, is_transferable, "
                    " item_kind, is_evidence) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (item_id, to_kind, to_id, item["name"], item["description"], count,
                     item["is_transferable"], item["item_kind"], item["is_evidence"]),
                )

            cursor.execute(
                "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable, "
                "item_kind, is_evidence "
                "FROM town_item WHERE item_id = %s AND owner_kind = %s AND owner_id = %s",
                (item_id, to_kind, to_id),
            )
            row = cursor.fetchone()

        return dict(row) if row else {}

    def record_event(
        self,
        player_id: str,
        npc_id: str,
        action_type: str,
        action_text: str,
        outcome: str,
        session_id: str,
        idempotency_key: str,
        item_id: str = "",
        affinity_delta: int = 0,
        trust_delta: int = 0,
        grudge_delta: int = 0,
        is_committed: int = 1,
        location_id: str = "",
        confidence: int = 0,
    ) -> dict[str, Any]:
        """Append one game event.

        Returns ``{"duplicate": True, ...}`` when the idempotency key was
        already used — the event is *not* written twice.
        """

        if action_type not in ACTION_TYPES:
            raise StoreError("invalid_action_type", f"action_type 只能是 {'/'.join(ACTION_TYPES)}")

        event_id = f"evt_{uuid.uuid4().hex[:24]}"
        with self.transaction() as cursor:
            cursor.execute(
                "SELECT event_id, player_id, npc_id, action_type, outcome, session_id "
                "FROM town_event WHERE idempotency_key = %s FOR UPDATE",
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if existing is not None:
                return {"duplicate": True, "event": dict(existing)}

            cursor.execute(
                "INSERT INTO town_event "
                "(event_id, player_id, npc_id, action_type, action_text, item_id, outcome, "
                " affinity_delta, trust_delta, grudge_delta, session_id, idempotency_key, "
                " is_committed, location_id, confidence) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (event_id, player_id, npc_id, action_type, action_text[:1024], item_id,
                 outcome[:1024], affinity_delta, trust_delta, grudge_delta, session_id,
                 idempotency_key, 1 if is_committed else 0, location_id[:64], confidence),
            )
            cursor.execute(
                "SELECT event_id, player_id, npc_id, action_type, action_text, item_id, outcome, "
                "affinity_delta, trust_delta, grudge_delta, session_id, created_at "
                "FROM town_event WHERE event_id = %s",
                (event_id,),
            )
            row = cursor.fetchone()

        return {"duplicate": False, "event": dict(row)}

    def upsert_plot_progress(
        self, player_id: str, plot_id: str, stage: str, triggered: bool, detail: str
    ) -> dict[str, Any]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "INSERT INTO town_plot_progress (player_id, plot_id, stage, triggered, detail) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE stage = VALUES(stage), triggered = VALUES(triggered), "
                "detail = VALUES(detail)",
                (player_id, plot_id, stage, 1 if triggered else 0, detail[:1024]),
            )
            cursor.execute(
                "SELECT player_id, plot_id, stage, triggered, detail, stage_flags, ending_id "
                "FROM town_plot_progress WHERE player_id = %s AND plot_id = %s",
                (player_id, plot_id),
            )
            row = cursor.fetchone()
        return dict(row) if row else {}

    # ---------------------------------------------------------- V2: 玩家身份

    def fetch_identity(self, player_id: str) -> dict[str, Any] | None:
        """The identity binding of a player, if any."""

        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, owner_identity, secret_hash, token_hash, created_at, updated_at "
                "FROM town_player_identity WHERE player_id = %s",
                (player_id,),
            )
            return cursor.fetchone()

    def bind_identity(
        self, player_id: str, identity: str, secret: str = ""
    ) -> dict[str, Any]:
        """Bind a player to a trusted identity and (optionally) a secret.

        Two independent things are stored:

        * ``owner_identity`` — *who* owns the player. It comes from
          ``{{#sys.user_id#}}``: the authenticated end user on the Service
          API, or the console account during a debug run.
        * ``secret_hash`` — a *player-held* secret (the access code the
          player types in). It is what makes isolation hold even when
          several people share one console identity, which is exactly the
          situation in a demo where everyone is "the operator".

        The rules are:

        * Binding an already-bound player to a *different* identity is
          refused — ownership is never silently transferred.
        * The same identity may own *several* players (one person keeping
          more than one save file).
        * A secret, once set, is never replaced by a different one. A
          player who forgets it cannot take the save over — that is the
          point of a secret.

        So knowing a ``player_id`` is not enough to read that player's
        state; the caller must also present the owning identity **and**
        the secret.
        """

        secret_hash = _hash_secret(secret) if secret else ""

        with self.transaction() as cursor:
            cursor.execute(
                "SELECT owner_identity, secret_hash FROM town_player_identity "
                "WHERE player_id = %s FOR UPDATE",
                (player_id,),
            )
            row = cursor.fetchone()
            if row is not None and row["owner_identity"]:
                if row["owner_identity"] != identity:
                    raise StoreError(
                        "identity_conflict",
                        f"玩家 {player_id} 已绑定到另一个身份",
                    )
                if secret_hash and row["secret_hash"] and not _secret_matches(
                    row["secret_hash"], secret
                ):
                    raise StoreError("secret_conflict", "密令与该存档不符")
                if secret_hash and not row["secret_hash"]:
                    cursor.execute(
                        "UPDATE town_player_identity SET secret_hash = %s WHERE player_id = %s",
                        (secret_hash, player_id),
                    )
            else:
                cursor.execute(
                    "INSERT INTO town_player_identity "
                    "(player_id, owner_identity, secret_hash, token_hash) "
                    "VALUES (%s, %s, %s, '') "
                    "ON DUPLICATE KEY UPDATE owner_identity = VALUES(owner_identity), "
                    "secret_hash = VALUES(secret_hash)",
                    (player_id, identity, secret_hash),
                )
            cursor.execute(
                "SELECT player_id, owner_identity, secret_hash, token_hash "
                "FROM town_player_identity WHERE player_id = %s",
                (player_id,),
            )
            bound = cursor.fetchone()
        return dict(bound) if bound else {}

    def ensure_player_token(self, player_id: str) -> dict[str, Any]:
        """Issue a player token once; afterwards only the hash is kept.

        Returns ``{"token": ..., "issued": bool}``. ``issued`` is False on
        every call after the first, and the raw token is empty then — the
        plaintext exists exactly once, in the registration response.
        """

        import secrets as _secrets

        with self.transaction() as cursor:
            cursor.execute(
                "SELECT token_hash FROM town_player_identity WHERE player_id = %s FOR UPDATE",
                (player_id,),
            )
            row = cursor.fetchone()
            if row is not None and row["token_hash"]:
                return {"token": "", "issued": False}

            token = _secrets.token_urlsafe(24)
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            cursor.execute(
                "INSERT INTO town_player_identity (player_id, owner_identity, token_hash) "
                "VALUES (%s, '', %s) "
                "ON DUPLICATE KEY UPDATE token_hash = VALUES(token_hash)",
                (player_id, token_hash),
            )
        return {"token": token, "issued": True}

    # ---------------------------------------------------------- V2: 玩家状态

    def add_coins(self, player_id: str, amount: int) -> int:
        """Add (or subtract) coins and return the new balance."""

        with self.transaction() as cursor:
            cursor.execute(
                "UPDATE town_player SET coins = GREATEST(0, coins + %s) WHERE player_id = %s",
                (amount, player_id),
            )
            cursor.execute("SELECT coins FROM town_player WHERE player_id = %s", (player_id,))
            row = cursor.fetchone()
        return int(row["coins"]) if row else 0

    def set_player_ending(self, player_id: str, ending_id: str) -> None:
        """Record which ending the player reached.

        The row is the "one ending per player" guard: once it is set, no
        further ending can be reached, and no reward can be claimed twice.
        """

        with self.transaction() as cursor:
            cursor.execute(
                "UPDATE town_player SET ending_id = %s, ending_claimed = "
                "CASE WHEN %s = '' THEN ending_claimed ELSE 1 END WHERE player_id = %s",
                (ending_id, ending_id, player_id),
            )

    # ---------------------------------------------------------- V2: 知情传播

    def record_knowledge(
        self, player_id: str, subject_id: str, topic: str, detail: str
    ) -> dict[str, Any]:
        """Record that ``subject_id`` now knows ``topic``.

        NPCs never cite a fact that is not in this table. That is the rule
        that stops them from knowing things nobody told them.
        """

        knowledge_id = f"kn_{uuid.uuid4().hex[:24]}"
        with self.transaction() as cursor:
            cursor.execute(
                "INSERT INTO town_knowledge "
                "(knowledge_id, player_id, subject_kind, subject_id, topic, detail) "
                "VALUES (%s, %s, 'npc', %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE detail = VALUES(detail), learned_at = CURRENT_TIMESTAMP",
                (knowledge_id, player_id, subject_id, topic, detail[:512]),
            )
            cursor.execute(
                "SELECT knowledge_id, subject_id, topic, detail, learned_at FROM town_knowledge "
                "WHERE player_id = %s AND subject_id = %s AND topic = %s",
                (player_id, subject_id, topic),
            )
            row = cursor.fetchone()
        return dict(row) if row else {}

    def list_knowledge(self, player_id: str, subject_id: str = "") -> list[dict[str, Any]]:
        """What the player knows, and what each NPC knows."""

        with self._cursor(self.settings.seekdb_database) as cursor:
            if subject_id:
                cursor.execute(
                    "SELECT knowledge_id, subject_id, topic, detail, learned_at FROM town_knowledge "
                    "WHERE player_id = %s AND subject_id = %s ORDER BY learned_at DESC",
                    (player_id, subject_id),
                )
            else:
                cursor.execute(
                    "SELECT knowledge_id, subject_id, topic, detail, learned_at FROM town_knowledge "
                    "WHERE player_id = %s ORDER BY subject_id, learned_at DESC",
                    (player_id,),
                )
            return list(cursor.fetchall())

    # ---------------------------------------------------------- V2: 任务

    def upsert_quest(
        self,
        player_id: str,
        quest_id: str,
        title: str,
        stage: str,
        progress: int,
        required: int,
        state: str,
        detail: str = "",
    ) -> dict[str, Any]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "INSERT INTO town_quest "
                "(player_id, quest_id, title, stage, progress, required, state, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE title = VALUES(title), stage = VALUES(stage), "
                "progress = VALUES(progress), required = VALUES(required), "
                "state = VALUES(state), detail = VALUES(detail)",
                (player_id, quest_id, title[:128], stage[:64], progress, required,
                 state, detail[:512]),
            )
            cursor.execute(
                "SELECT player_id, quest_id, title, stage, progress, required, state, detail "
                "FROM town_quest WHERE player_id = %s AND quest_id = %s",
                (player_id, quest_id),
            )
            row = cursor.fetchone()
        return dict(row) if row else {}

    def fetch_quest(self, player_id: str, quest_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, quest_id, title, stage, progress, required, state, detail "
                "FROM town_quest WHERE player_id = %s AND quest_id = %s",
                (player_id, quest_id),
            )
            return cursor.fetchone()

    def list_quests(self, player_id: str) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, quest_id, title, stage, progress, required, state, detail "
                "FROM town_quest WHERE player_id = %s ORDER BY quest_id",
                (player_id,),
            )
            return list(cursor.fetchall())

    def advance_quest(self, player_id: str, quest_id: str, delta: int) -> int:
        """Move a quest's progress forward, never below zero."""

        with self.transaction() as cursor:
            cursor.execute(
                "UPDATE town_quest SET progress = GREATEST(0, progress + %s) "
                "WHERE player_id = %s AND quest_id = %s",
                (delta, player_id, quest_id),
            )
            cursor.execute(
                "SELECT progress FROM town_quest WHERE player_id = %s AND quest_id = %s",
                (player_id, quest_id),
            )
            row = cursor.fetchone()
        return int(row["progress"]) if row else 0

    def set_quest_stage(self, player_id: str, quest_id: str, stage: str, state: str = "") -> None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            if state:
                cursor.execute(
                    "UPDATE town_quest SET stage = %s, state = %s "
                    "WHERE player_id = %s AND quest_id = %s",
                    (stage, state, player_id, quest_id),
                )
            else:
                cursor.execute(
                    "UPDATE town_quest SET stage = %s WHERE player_id = %s AND quest_id = %s",
                    (stage, player_id, quest_id),
                )

    def player_has_quest_stage(self, player_id: str, quest_id: str, stage: str) -> bool:
        quest = self.fetch_quest(player_id, quest_id)
        return bool(quest) and quest["stage"] == stage

    # ---------------------------------------------------------- V2: 结局

    def fetch_ending(self, player_id: str, ending_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, ending_id, ending_kind, title, summary, reward_coins, "
                "reward_claimed, reached_at FROM town_ending "
                "WHERE player_id = %s AND ending_id = %s",
                (player_id, ending_id),
            )
            return cursor.fetchone()

    def list_endings(self, player_id: str) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, ending_id, ending_kind, title, summary, reward_coins, "
                "reward_claimed, reached_at FROM town_ending WHERE player_id = %s ORDER BY ending_id",
                (player_id,),
            )
            return list(cursor.fetchall())

    def insert_ending(
        self,
        player_id: str,
        ending_id: str,
        ending_kind: str,
        title: str,
        summary: str,
        reward_coins: int,
    ) -> dict[str, Any]:
        """Record that the player reached an ending.

        The primary key is ``(player_id, ending_id)``, so a second attempt
        cannot create a second row — the reward can only ever be claimed
        once.
        """

        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "INSERT INTO town_ending "
                "(player_id, ending_id, ending_kind, title, summary, reward_coins, reward_claimed) "
                "VALUES (%s, %s, %s, %s, %s, %s, 0) "
                "ON DUPLICATE KEY UPDATE title = VALUES(title), summary = VALUES(summary)",
                (player_id, ending_id, ending_kind[:64], title[:128], summary[:512], reward_coins),
            )
            cursor.execute(
                "SELECT player_id, ending_id, ending_kind, title, summary, reward_coins, "
                "reward_claimed, reached_at FROM town_ending "
                "WHERE player_id = %s AND ending_id = %s",
                (player_id, ending_id),
            )
            row = cursor.fetchone()
        return dict(row) if row else {}

    def claim_ending_reward(self, player_id: str, ending_id: str) -> bool:
        """Claim an ending's reward exactly once.

        Returns ``False`` when the reward was already claimed, so the caller
        can avoid paying it twice.
        """

        with self.transaction() as cursor:
            cursor.execute(
                "UPDATE town_ending SET reward_claimed = 1 "
                "WHERE player_id = %s AND ending_id = %s AND reward_claimed = 0",
                (player_id, ending_id),
            )
            return cursor.rowcount > 0

    # ---------------------------------------------------------- V2: 成就

    def add_achievement(self, player_id: str, achievement_id: str, title: str, detail: str = "") -> bool:
        """Unlock an achievement. Returns False when it was already unlocked."""

        with self.transaction() as cursor:
            cursor.execute(
                "INSERT IGNORE INTO town_achievement (player_id, achievement_id, title, detail) "
                "VALUES (%s, %s, %s, %s)",
                (player_id, achievement_id, title[:128], detail[:512]),
            )
            return cursor.rowcount > 0

    def list_achievements(self, player_id: str) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT achievement_id, title, detail, unlocked_at FROM town_achievement "
                "WHERE player_id = %s ORDER BY achievement_id",
                (player_id,),
            )
            return list(cursor.fetchall())

    # ---------------------------------------------------------- V2: Outbox

    def enqueue_memory(
        self, player_id: str, dedupe_key: str, kind: str, payload: str
    ) -> dict[str, Any]:
        """Queue a memory write in the same transaction as the state change.

        This is what makes "seekdb committed but PowerContext did not" a
        recoverable state instead of a lost event. The unique dedupe key
        means a retry cannot create a second memory.
        """

        outbox_id = f"ob_{uuid.uuid4().hex[:24]}"
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "INSERT INTO town_outbox "
                "(outbox_id, player_id, dedupe_key, kind, payload, state, attempts) "
                "VALUES (%s, %s, %s, %s, %s, 'pending', 0) "
                "ON DUPLICATE KEY UPDATE payload = VALUES(payload)",
                (outbox_id, player_id, dedupe_key, kind, payload[:2048]),
            )
            cursor.execute(
                "SELECT outbox_id, player_id, dedupe_key, kind, payload, state, attempts, "
                "last_error, created_at, updated_at FROM town_outbox WHERE dedupe_key = %s",
                (dedupe_key,),
            )
            row = cursor.fetchone()
        return dict(row) if row else {}

    def mark_memory_done(self, dedupe_key: str) -> None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "UPDATE town_outbox SET state = 'done', last_error = '', attempts = 0 "
                "WHERE dedupe_key = %s",
                (dedupe_key,),
            )

    def mark_memory_failed(self, dedupe_key: str, error: str) -> None:
        """Record a failed memory write.

        The row stays visible with its error, and it stays **retryable**:
        ``list_pending_memory_jobs`` picks up both ``pending`` and ``failed``
        rows. A write that failed while PowerContext was down is not lost —
        it is a debt the compensation flow repays.

        The ``state <> 'done'`` guard matters: the real-time write and the
        compensation flow can touch the same row concurrently, and a late
        failure must not flip an already-delivered row back to ``failed``.
        """

        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "UPDATE town_outbox SET attempts = attempts + 1, last_error = %s, "
                "state = 'failed' WHERE dedupe_key = %s AND state <> 'done'",
                (error[:512], dedupe_key),
            )

    def list_pending_memory_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Memory writes that still need to be delivered to PowerContext.

        ``failed`` rows are included on purpose: ``failed`` means "the last
        delivery attempt failed", not "this memory is void". Excluding them
        would strand every memory that was written while PowerContext was
        down — exactly the case compensation exists for.
        """

        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT outbox_id, player_id, dedupe_key, kind, payload, state, attempts, "
                "last_error, created_at FROM town_outbox WHERE state <> 'done' "
                "ORDER BY created_at ASC LIMIT %s",
                (limit,),
            )
            return list(cursor.fetchall())

    def count_outbox_by_state(self) -> dict[str, int]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT state, COUNT(*) AS n FROM town_outbox GROUP BY state"
            )
            return {row["state"]: int(row["n"]) for row in cursor.fetchall()}

    def save_request(self, idempotency_key: str, player_id: str, request_hash: str, response: dict[str, Any]) -> None:
        """Persist the outcome of a request so a repeat returns the same thing."""

        payload = json.dumps(response, ensure_ascii=False)
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "INSERT INTO town_request_log (idempotency_key, player_id, request_hash, response_json) "
                "VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE response_json = VALUES(response_json)",
                (idempotency_key, player_id, request_hash, payload),
            )

    def load_request(self, idempotency_key: str, player_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT idempotency_key, player_id, request_hash, response_json "
                "FROM town_request_log WHERE idempotency_key = %s AND player_id = %s",
                (idempotency_key, player_id),
            )
            row = cursor.fetchone()
        if not row:
            return None
        try:
            return json.loads(row["response_json"])
        except (TypeError, ValueError):
            return None


def _initial_trust(npc_id: str) -> int:
    """The cat detective starts suspicious; the mayor starts friendly."""

    return 30 if npc_id == "cat_detective" else 50


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _split_sql(script: str) -> list[str]:
    """Split a SQL script into executable statements.

    The scripts in ``data/`` are hand written and contain no stored
    procedures, so a semicolon split is sufficient.
    """

    statements: list[str] = []
    for raw in script.split(";"):
        line = "\n".join(
            part for part in raw.splitlines()
            if not part.strip().startswith("--")
        ).strip()
        if line:
            statements.append(line)
    return statements
