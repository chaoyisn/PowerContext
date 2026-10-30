"""V2 数据库迁移：**增量**、可重复执行、不破坏 V1 数据。

为什么需要单独的迁移器
----------------------
``data/schema_v2.sql`` 里同时有三种语句，而它们的幂等性只能靠数据库
自身判断：

* ``CREATE TABLE IF NOT EXISTS`` —— 幂等，直接执行。
* ``ALTER TABLE ... ADD COLUMN`` —— **OceanBase 不支持 ``ADD COLUMN IF NOT EXISTS``**
  （实测报错），因此必须先查 ``information_schema.COLUMNS`` 再决定是否执行。
* ``ALTER TABLE ... ADD CONSTRAINT ... CHECK`` —— 没有 ``IF NOT EXISTS``，
  需要先 ``DROP CHECK``（OceanBase 支持 ``DROP CHECK``，但**不支持**
  ``DROP CONSTRAINT``）。

迁移器因此把每条语句分类处理，保证：
1. V1 的 8 张表和它们的已有行**一列不动**；
2. 反复执行结果相同；
3. 不重建、不删除 ``memory_town`` 库。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .config import Settings
from .store import SeekDBStore

LOGGER = logging.getLogger("town_backend.migrate")

_ADD_COLUMN = re.compile(
    r"^ALTER\s+TABLE\s+`?(?P<table>\w+)`?\s+ADD\s+COLUMN\s+`?(?P<column>\w+)`?",
    re.IGNORECASE,
)
_ADD_CONSTRAINT = re.compile(
    r"^ALTER\s+TABLE\s+`?(?P<table>\w+)`?\s+ADD\s+CONSTRAINT\s+`?(?P<name>\w+)`?",
    re.IGNORECASE,
)
_DROP_CHECK = re.compile(
    r"^ALTER\s+TABLE\s+`?(?P<table>\w+)`?\s+DROP\s+CHECK\s+`?(?P<name>\w+)`?",
    re.IGNORECASE,
)
_CREATE_TABLE = re.compile(
    r"^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(?P<name>\w+)`?",
    re.IGNORECASE,
)


class MigrationError(RuntimeError):
    """A migration statement could not be applied."""


def split_statements(script: str) -> list[str]:
    """Split a SQL script into statements.

    The scripts are hand written and contain no stored procedures, so a
    semicolon split is enough — but comment-only lines are dropped first
    so a trailing ``--`` block cannot swallow the last statement.
    """

    statements: list[str] = []
    for raw in script.split(";"):
        lines = [
            part for part in raw.splitlines()
            if not part.strip().startswith("--")
        ]
        line = "\n".join(lines).strip()
        if line:
            statements.append(line)
    return statements


class Migrator:
    """Applies the V2 migration to an existing ``memory_town`` database."""

    def __init__(self, store: SeekDBStore) -> None:
        self.store = store
        self.database = store.settings.seekdb_database
        self.actions: list[dict[str, Any]] = []

    # --------------------------------------------------------------- helpers

    def _column_exists(self, table: str, column: str) -> bool:
        with self.store._cursor(self.database) as cursor:  # noqa: SLF001
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                (self.database, table, column),
            )
            row = cursor.fetchone()
        return bool(row) and int(row["n"]) > 0

    def _check_exists(self, table: str, name: str) -> bool:
        with self.store._cursor(self.database) as cursor:  # noqa: SLF001
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.TABLE_CONSTRAINTS "
                "WHERE CONSTRAINT_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s",
                (self.database, table, name),
            )
            row = cursor.fetchone()
        return bool(row) and int(row["n"]) > 0

    def _table_exists(self, table: str) -> bool:
        with self.store._cursor(self.database) as cursor:  # noqa: SLF001
            cursor.execute(
                "SELECT COUNT(*) AS n FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                (self.database, table),
            )
            row = cursor.fetchone()
        return bool(row) and int(row["n"]) > 0

    def _record(self, statement: str, action: str, detail: str = "") -> None:
        self.actions.append({"action": action, "detail": detail, "statement": statement[:200]})
        LOGGER.info("[migrate] %s %s %s", action, detail, statement[:120])

    def _execute(self, statement: str) -> None:
        with self.store._cursor(self.database) as cursor:  # noqa: SLF001
            cursor.execute(statement)

    # ------------------------------------------------------------------ run

    def apply_schema(self, script: str) -> list[dict[str, Any]]:
        """Apply every statement of ``script``, skipping what already holds."""

        for statement in split_statements(script):
            self._apply_one(statement)
        return self.actions

    def _apply_one(self, statement: str) -> None:
        create = _CREATE_TABLE.match(statement)
        if create:
            name = create.group("name")
            if self._table_exists(name):
                self._record(statement, "skipped", f"表 {name} 已存在")
                return
            self._execute(statement)
            self._record(statement, "created", f"表 {name}")
            return

        drop = _DROP_CHECK.match(statement)
        if drop:
            table, name = drop.group("table"), drop.group("name")
            if not self._check_exists(table, name):
                self._record(statement, "skipped", f"约束 {table}.{name} 不存在")
                return
            self._execute(statement)
            self._record(statement, "dropped", f"约束 {table}.{name}")
            return

        add_constraint = _ADD_CONSTRAINT.match(statement)
        if add_constraint:
            table, name = add_constraint.group("table"), add_constraint.group("name")
            # ADD CONSTRAINT 没有 IF NOT EXISTS：先删后加，保证最终状态
            # 与 V2 的定义一致，而且可以反复执行。
            if self._check_exists(table, name):
                self._execute(f"ALTER TABLE `{table}` DROP CHECK `{name}`")
                self._record(statement, "replaced", f"约束 {table}.{name}")
            self._execute(statement)
            self._record(statement, "added", f"约束 {table}.{name}")
            return

        add_column = _ADD_COLUMN.match(statement)
        if add_column:
            table, column = add_column.group("table"), add_column.group("column")
            if self._column_exists(table, column):
                self._record(statement, "skipped", f"列 {table}.{column} 已存在")
                return
            self._execute(statement)
            self._record(statement, "added", f"列 {table}.{column}")
            return

        self._execute(statement)
        self._record(statement, "executed")

    def apply_seed(self, script: str) -> list[dict[str, Any]]:
        """Apply the seed rows. The script itself is idempotent."""

        count = 0
        with self.store.transaction() as cursor:
            for statement in split_statements(script):
                cursor.execute(statement)
                count += 1
        self._record(f"<seed: {count} statements>", "seeded")
        return self.actions


def migrate(settings: Settings) -> dict[str, Any]:
    """Run the whole V2 migration: schema first, then seed."""

    store = SeekDBStore(settings)
    migrator = Migrator(store)

    schema_sql = settings.schema_v2_path.read_text(encoding="utf-8")
    seed_sql = settings.seed_v2_path.read_text(encoding="utf-8")

    migrator.apply_schema(schema_sql)
    migrator.apply_seed(seed_sql)

    return {
        "database": settings.seekdb_database,
        "actions": migrator.actions,
        "counts": store.count_rows(),
    }
