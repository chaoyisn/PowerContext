"""seekdb access layer.

Two doors into the same seekdb server/database:

* **pyseekdb** (official SDK, remote server mode) owns the ``rf_chunks`` collection -
  dense HNSW vector index + FULLTEXT index + ``hybrid_search``.
* **pymysql** owns the relational tables (``rf_documents``, ``rf_pages``, ``rf_projects``)
  which have no vector column.

Embedded mode is not used: ``pylibseekdb`` ships manylinux wheels only, so
``pyseekdb.Client(path=...)`` raises ``RuntimeError`` on Windows. See ARCHITECTURE.md 2.1.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

import pymysql
from pymysql.cursors import DictCursor

from ..config import Settings, get_settings
from ..errors import SeekDBUnavailableError
from ..logging_setup import get_logger

logger = get_logger(__name__)

# seekdb maps a NOWAIT DDL lock conflict to MySQL 1205; 1061 is "duplicate key name"
# raised when two initialisers create the same index concurrently. Both are retryable
# for idempotent DDL.
_DDL_RETRY_ERRORS = (1205, 1061)
_DDL_BACKOFF = (0.1, 0.25, 0.5, 1.0, 2.0)


class SeekDBStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._local = threading.local()
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    # ------------------------------------------------------------------ connect

    @property
    def _connect_kwargs(self) -> dict[str, Any]:
        s = self.settings
        return {
            "host": s.seekdb_host,
            "port": s.seekdb_port,
            "user": f"{s.seekdb_user}@{s.seekdb_tenant}",
            "password": s.seekdb_password,
            "database": s.seekdb_database,
            "charset": "utf8mb4",
            "autocommit": True,
            "cursorclass": DictCursor,
            "connect_timeout": s.seekdb_connect_timeout,
            "read_timeout": 60,
            "write_timeout": 60,
        }

    def sql_connection(self) -> pymysql.connections.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.ping(reconnect=True)
                return conn
            except Exception:
                self._local.conn = None
        try:
            conn = pymysql.connect(**self._connect_kwargs)
        except Exception as exc:
            raise SeekDBUnavailableError(
                f"cannot connect to seekdb at {self.settings.seekdb_host}:{self.settings.seekdb_port}",
                detail={"reason": f"{type(exc).__name__}: {exc}"},
            ) from exc
        self._local.conn = conn
        return conn

    def pyseekdb_client(self):
        import pyseekdb

        client = getattr(self._local, "client", None)
        if client is not None:
            return client
        s = self.settings
        if s.seekdb_mode == "embedded":
            client = pyseekdb.Client(path=s.seekdb_path, database=s.seekdb_database)
        else:
            client = pyseekdb.Client(
                host=s.seekdb_host,
                port=s.seekdb_port,
                tenant=s.seekdb_tenant,
                database=s.seekdb_database,
                user=s.seekdb_user,
                password=s.seekdb_password,
            )
        self._local.client = client
        return client

    def close_thread_resources(self) -> None:
        for attr in ("conn", "client"):
            obj = getattr(self._local, attr, None)
            if obj is None:
                continue
            try:
                if attr == "conn":
                    obj.close()
                else:
                    obj.close()
            except Exception:
                pass
            setattr(self._local, attr, None)

    # ------------------------------------------------------------------ raw sql

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        try:
            with self.sql_connection().cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        except SeekDBUnavailableError:
            raise
        except pymysql.err.OperationalError as exc:
            self._local.conn = None
            raise SeekDBUnavailableError(
                "seekdb query failed", detail={"reason": f"{type(exc).__name__}: {exc}", "sql": sql[:200]}
            ) from exc

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        try:
            with self.sql_connection().cursor() as cursor:
                return cursor.execute(sql, params)
        except pymysql.err.OperationalError as exc:
            self._local.conn = None
            raise SeekDBUnavailableError(
                "seekdb statement failed", detail={"reason": f"{type(exc).__name__}: {exc}", "sql": sql[:200]}
            ) from exc

    def execute_ddl(self, sql: str) -> None:
        """Idempotent DDL with retry on seekdb's DDL-lock conflict."""
        last: Exception | None = None
        for attempt, delay in enumerate((0.0, *_DDL_BACKOFF)):
            if delay:
                time.sleep(delay)
            try:
                self.execute(sql)
                return
            except pymysql.err.MySQLError as exc:
                code = exc.args[0] if exc.args else None
                if code in _DDL_RETRY_ERRORS:
                    last = exc
                    logger.warning(
                        "seekdb DDL contention, retrying",
                        fields={"attempt": attempt, "code": code},
                    )
                    continue
                raise
        raise SeekDBUnavailableError(
            "seekdb DDL kept hitting lock contention", detail={"reason": str(last)}
        )

    @contextmanager
    def transaction(self) -> Iterator[pymysql.connections.Connection]:
        conn = self.sql_connection()
        conn.begin()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ------------------------------------------------------------------ schema

    def _table_exists(self, table: str) -> bool:
        rows = self.query(
            "SELECT COUNT(*) AS c FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (self.settings.seekdb_database, table),
        )
        return bool(rows) and int(rows[0]["c"]) > 0

    def ensure_schema(self, *, embedding_dimension: int) -> dict[str, Any]:
        """Create tables and the chunk collection if absent. Safe to call repeatedly."""
        with self._schema_lock:
            if self._schema_ready:
                return {"created": False}
            s = self.settings
            created: list[str] = []

            if not self._table_exists(s.documents_table):
                self.execute_ddl(
                    f"""CREATE TABLE IF NOT EXISTS `{s.documents_table}` (
  `doc_id` CHAR(64) NOT NULL,
  `filename` VARCHAR(512) NOT NULL,
  `content_type` VARCHAR(32) NOT NULL,
  `size_bytes` BIGINT NOT NULL DEFAULT 0,
  `page_count` INT NOT NULL DEFAULT 0,
  `chunk_count` INT NOT NULL DEFAULT 0,
  `title` VARCHAR(512) NOT NULL DEFAULT '',
  `status` VARCHAR(16) NOT NULL DEFAULT 'ready',
  `error_message` TEXT NULL,
  `created_at` DATETIME(6) NOT NULL,
  `updated_at` DATETIME(6) NOT NULL,
  PRIMARY KEY (`doc_id`)
) DEFAULT CHARSET = utf8mb4"""
                )
                created.append(s.documents_table)

            if not self._table_exists(s.pages_table):
                self.execute_ddl(
                    f"""CREATE TABLE IF NOT EXISTS `{s.pages_table}` (
  `page_id` VARCHAR(96) NOT NULL,
  `doc_id` CHAR(64) NOT NULL,
  `page_no` INT NOT NULL,
  `char_count` INT NOT NULL DEFAULT 0,
  `is_empty` TINYINT(1) NOT NULL DEFAULT 0,
  `content` MEDIUMTEXT NULL,
  `created_at` DATETIME(6) NOT NULL,
  PRIMARY KEY (`page_id`),
  UNIQUE KEY `uk_{s.seekdb_prefix}pages_doc_page` (`doc_id`, `page_no`),
  KEY `ix_{s.seekdb_prefix}pages_doc` (`doc_id`)
) DEFAULT CHARSET = utf8mb4"""
                )
                created.append(s.pages_table)

            if not self._table_exists(s.projects_table):
                self.execute_ddl(
                    f"""CREATE TABLE IF NOT EXISTS `{s.projects_table}` (
  `project_id` VARCHAR(64) NOT NULL,
  `title` VARCHAR(256) NOT NULL,
  `objective` TEXT NULL,
  `powercontext_scope_id` VARCHAR(128) NULL,
  `created_at` DATETIME(6) NOT NULL,
  `updated_at` DATETIME(6) NOT NULL,
  PRIMARY KEY (`project_id`)
) DEFAULT CHARSET = utf8mb4"""
                )
                created.append(s.projects_table)

            if not self._table_exists(s.meta_table):
                self.execute_ddl(
                    f"""CREATE TABLE IF NOT EXISTS `{s.meta_table}` (
  `meta_key` VARCHAR(64) NOT NULL,
  `meta_value` VARCHAR(256) NOT NULL,
  `updated_at` DATETIME(6) NOT NULL,
  PRIMARY KEY (`meta_key`)
) DEFAULT CHARSET = utf8mb4"""
                )
                created.append(s.meta_table)

            client = self.pyseekdb_client()
            if not client.has_collection(s.chunks_collection):
                from pyseekdb import (
                    FulltextIndexConfig,
                    HNSWConfiguration,
                    Schema,
                    VectorIndexConfig,
                )

                schema = Schema(
                    vector_index=VectorIndexConfig(
                        hnsw=HNSWConfiguration(
                            dimension=embedding_dimension, distance=s.seekdb_vector_distance
                        ),
                        embedding_function=None,
                    ),
                    fulltext_index=FulltextIndexConfig(analyzer=s.seekdb_fts_analyzer),
                )
                client.create_collection(s.chunks_collection, schema=schema)
                created.append(s.chunks_collection)

            self._schema_ready = True
            logger.info(
                "seekdb schema ready",
                fields={"created": ",".join(created) or "none", "collection": s.chunks_collection},
            )
            return {"created": bool(created), "objects": created}

    def chunks(self):
        """The pyseekdb collection holding chunk text + metadata + vectors.

        ``embedding_function=None`` because ResearchFlow computes vectors itself; passing
        the sentinel default would make pyseekdb rebuild the ONNX model on every call.
        """
        client = self.pyseekdb_client()
        if not client.has_collection(self.settings.chunks_collection):
            raise SeekDBUnavailableError(
                f"seekdb collection '{self.settings.chunks_collection}' does not exist; "
                "call ensure_schema() first",
            )
        return client.get_collection(self.settings.chunks_collection, embedding_function=None)

    # ------------------------------------------------------------------ meta

    def get_meta(self, key: str) -> str | None:
        rows = self.query(
            f"SELECT meta_value FROM `{self.settings.meta_table}` WHERE meta_key = %s", (key,)
        )
        return rows[0]["meta_value"] if rows else None

    def set_meta(self, key: str, value: str) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        self.execute(
            f"""INSERT INTO `{self.settings.meta_table}` (meta_key, meta_value, updated_at)
VALUES (%s,%s,%s)
ON DUPLICATE KEY UPDATE meta_value=VALUES(meta_value), updated_at=VALUES(updated_at)""",
            (key, str(value)[:256], now),
        )

    # ------------------------------------------------------------------ health

    def health(self) -> dict[str, Any]:
        started = time.time()
        try:
            version_rows = self.query("SELECT VERSION() AS v")
            version = version_rows[0]["v"] if version_rows else "unknown"
            counts: dict[str, Any] = {}
            for label, table in (
                ("documents", self.settings.documents_table),
                ("pages", self.settings.pages_table),
                ("projects", self.settings.projects_table),
            ):
                if self._table_exists(table):
                    rows = self.query(f"SELECT COUNT(*) AS c FROM `{table}`")
                    counts[label] = int(rows[0]["c"])
                else:
                    counts[label] = None
            collection = self.settings.chunks_collection
            counts["chunks"] = self.chunks().count() if self.pyseekdb_client().has_collection(collection) else None
            return {
                "available": True,
                "mode": self.settings.seekdb_mode,
                "endpoint": f"{self.settings.seekdb_host}:{self.settings.seekdb_port}",
                "database": self.settings.seekdb_database,
                "server_version": version,
                "fts_analyzer": self.settings.seekdb_fts_analyzer,
                "counts": counts,
                "stored_embedding": {
                    "provider": self.get_meta("embedding_provider"),
                    "dimension": self.get_meta("embedding_dimension"),
                    "updated_at": self.get_meta("embedding_updated_at"),
                },
                "latency_ms": round((time.time() - started) * 1000, 2),
            }
        except Exception as exc:
            return {
                "available": False,
                "mode": self.settings.seekdb_mode,
                "endpoint": f"{self.settings.seekdb_host}:{self.settings.seekdb_port}",
                "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": round((time.time() - started) * 1000, 2),
            }
