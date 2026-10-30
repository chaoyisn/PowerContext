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

import json
import re
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

import pymysql

from .config import Settings

PLAYER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-:.]{1,64}$")

ACTION_TYPES = ("talk", "prank", "gift", "steal", "investigate", "unknown")


class StoreError(RuntimeError):
    """Raised when a state change violates a game rule."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
                "SELECT player_id, display_name, current_location, session_id, turn_count "
                "FROM town_player WHERE player_id = %s",
                (player_id,),
            )
            return cursor.fetchone()

    def fetch_npc(self, npc_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT npc_id, name, title, persona, speech_style, home_location, grudge_focus "
                "FROM town_npc WHERE npc_id = %s",
                (npc_id,),
            )
            return cursor.fetchone()

    def list_npcs(self) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT npc_id, name, title, persona, speech_style, home_location, grudge_focus "
                "FROM town_npc ORDER BY npc_id"
            )
            return list(cursor.fetchall())

    def list_locations(self) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT location_id, name, description, is_start FROM town_location ORDER BY location_id"
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
                "affinity_delta, trust_delta, grudge_delta, session_id, created_at "
                "FROM town_event WHERE player_id = %s ORDER BY created_at DESC, event_id DESC LIMIT %s",
                (player_id, limit),
            )
            return list(cursor.fetchall())

    def fetch_event_by_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT event_id, player_id, npc_id, action_type, action_text, item_id, outcome, "
                "affinity_delta, trust_delta, grudge_delta, session_id, created_at "
                "FROM town_event WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            return cursor.fetchone()

    def list_items(self, owner_kind: str, owner_id: str) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable "
                "FROM town_item WHERE owner_kind = %s AND owner_id = %s ORDER BY item_id",
                (owner_kind, owner_id),
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
                    "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable "
                    "FROM town_item WHERE item_id = %s ORDER BY owner_kind, owner_id LIMIT 1",
                    (item_id,),
                )
            else:
                cursor.execute(
                    "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable "
                    "FROM town_item WHERE item_id = %s AND owner_kind = %s AND owner_id = %s",
                    (item_id, owner_kind, owner_id),
                )
            return cursor.fetchone()

    def list_plot_progress(self, player_id: str) -> list[dict[str, Any]]:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, plot_id, stage, triggered, detail "
                "FROM town_plot_progress WHERE player_id = %s ORDER BY plot_id",
                (player_id,),
            )
            return list(cursor.fetchall())

    def fetch_plot_progress(self, player_id: str, plot_id: str) -> dict[str, Any] | None:
        with self._cursor(self.settings.seekdb_database) as cursor:
            cursor.execute(
                "SELECT player_id, plot_id, stage, triggered, detail "
                "FROM town_plot_progress WHERE player_id = %s AND plot_id = %s",
                (player_id, plot_id),
            )
            return cursor.fetchone()

    def count_rows(self) -> dict[str, int]:
        """Row counts per table. Used by the verification report."""

        tables = (
            "town_location", "town_npc", "town_player", "town_relationship",
            "town_item", "town_event", "town_plot_progress", "town_request_log",
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
                    "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable "
                    "FROM town_item WHERE item_id = %s FOR UPDATE",
                    (item_id,),
                )
            else:
                cursor.execute(
                    "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable "
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
                "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable "
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
                    "(item_id, owner_kind, owner_id, name, description, quantity, is_transferable) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (item_id, to_kind, to_id, item["name"], item["description"], count,
                     item["is_transferable"]),
                )

            cursor.execute(
                "SELECT item_id, name, description, owner_kind, owner_id, quantity, is_transferable "
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
                " affinity_delta, trust_delta, grudge_delta, session_id, idempotency_key) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (event_id, player_id, npc_id, action_type, action_text[:1024], item_id,
                 outcome[:1024], affinity_delta, trust_delta, grudge_delta, session_id,
                 idempotency_key),
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
                "SELECT player_id, plot_id, stage, triggered, detail "
                "FROM town_plot_progress WHERE player_id = %s AND plot_id = %s",
                (player_id, plot_id),
            )
            row = cursor.fetchone()
        return dict(row) if row else {}

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
