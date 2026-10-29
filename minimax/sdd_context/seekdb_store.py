"""seekdb storage for SDD engineering materials.

The store owns four tables that mirror the SDD artefacts the context module has
to retrieve:

``sdd_specification``   one row per specification revision.
``sdd_code_symbol``     one row per indexed code file / symbol.
``sdd_test``            one row per test file with its kind and requirements.
``sdd_relation``        edges that bind specifications to code and tests.

Retrieval runs real SQL against the live instance; nothing is answered from a
hardcoded fixture.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Sequence

import pymysql
from pymysql.cursors import DictCursor

from .config import Settings, load_settings

_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS sdd_specification (
        spec_id VARCHAR(128) NOT NULL,
        version VARCHAR(64) NOT NULL,
        revision VARCHAR(64) NOT NULL,
        title VARCHAR(512) NOT NULL,
        status VARCHAR(64) NOT NULL,
        content LONGTEXT NOT NULL,
        content_hash CHAR(64) NOT NULL,
        source_path VARCHAR(1024) NOT NULL,
        imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (spec_id, version),
        KEY ix_spec_status (status),
        KEY ix_spec_hash (content_hash)
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_code_symbol (
        symbol_id CHAR(64) NOT NULL,
        file_path VARCHAR(1024) NOT NULL,
        symbol_name VARCHAR(512) NOT NULL,
        qualified_name VARCHAR(1024) NOT NULL,
        kind VARCHAR(64) NOT NULL,
        language VARCHAR(32) NOT NULL,
        start_line BIGINT NOT NULL,
        end_line BIGINT NOT NULL,
        signature TEXT NOT NULL,
        content LONGTEXT NOT NULL,
        content_hash CHAR(64) NOT NULL,
        source_path VARCHAR(1024) NOT NULL,
        PRIMARY KEY (symbol_id),
        KEY ix_code_path (file_path(190)),
        KEY ix_code_name (symbol_name(190))
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_test (
        test_id CHAR(64) NOT NULL,
        file_path VARCHAR(1024) NOT NULL,
        test_name VARCHAR(512) NOT NULL,
        test_kind VARCHAR(64) NOT NULL,
        requirement_ids VARCHAR(1024) NOT NULL,
        content LONGTEXT NOT NULL,
        content_hash CHAR(64) NOT NULL,
        source_path VARCHAR(1024) NOT NULL,
        PRIMARY KEY (test_id),
        KEY ix_test_path (file_path(190)),
        KEY ix_test_kind (test_kind),
        KEY ix_test_name (test_name(190))
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
    """
    CREATE TABLE IF NOT EXISTS sdd_relation (
        relation_id CHAR(64) NOT NULL,
        spec_id VARCHAR(128) NOT NULL,
        spec_version VARCHAR(64) NOT NULL,
        target_kind VARCHAR(32) NOT NULL,
        target_id VARCHAR(512) NOT NULL,
        relation_type VARCHAR(64) NOT NULL,
        PRIMARY KEY (relation_id),
        KEY ix_relation_spec (spec_id, spec_version),
        KEY ix_relation_target (target_kind, target_id(190))
    ) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
    """,
)


class SeekDBUnavailableError(RuntimeError):
    """Raised when the seekdb instance cannot serve the request."""


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SeekDBStore:
    """Thin, explicit pymysql wrapper over the SDD material tables."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()
        self._local = threading.local()

    # ------------------------------------------------------------------ connect

    def _connect(self, *, database: str | None = None) -> pymysql.connections.Connection:
        return pymysql.connect(
            host=self.settings.seekdb_host,
            port=self.settings.seekdb_port,
            user=self.settings.seekdb_user,
            password=self.settings.seekdb_password,
            database=database,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=DictCursor,
            connect_timeout=10,
            read_timeout=60,
            write_timeout=60,
        )

    def connection(self) -> pymysql.connections.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            try:
                connection.ping(reconnect=True)
                return connection
            except Exception:
                self._local.connection = None
        try:
            connection = self._connect(database=self.settings.seekdb_database)
        except Exception as error:
            raise SeekDBUnavailableError(
                f"cannot connect to seekdb at {self.settings.seekdb_host}:{self.settings.seekdb_port}"
            ) from error
        self._local.connection = connection
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            try:
                connection.close()
            finally:
                self._local.connection = None

    # -------------------------------------------------------------------- query

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        try:
            with self.connection().cursor() as cursor:
                cursor.execute(sql, tuple(params))
                return list(cursor.fetchall())
        except pymysql.MySQLError as error:
            raise SeekDBUnavailableError(f"seekdb query failed: {error}") from error

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        try:
            connection = self.connection()
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
            connection.commit()
            return cursor.rowcount
        except pymysql.MySQLError as error:
            raise SeekDBUnavailableError(f"seekdb write failed: {error}") from error

    # ------------------------------------------------------------------- schema

    def initialize(self) -> None:
        """Create the database and the SDD tables if they do not exist yet."""

        try:
            connection = self._connect()
        except Exception as error:
            raise SeekDBUnavailableError(
                f"cannot connect to seekdb at {self.settings.seekdb_host}:{self.settings.seekdb_port}"
            ) from error
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.settings.seekdb_database}` "
                    "DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
                )
            connection.commit()
        except pymysql.MySQLError as error:
            raise SeekDBUnavailableError(f"cannot create seekdb database: {error}") from error
        finally:
            try:
                connection.close()
            except Exception:
                pass

        self._local.connection = None
        for statement in _SCHEMA:
            try:
                with self.connection().cursor() as cursor:
                    cursor.execute(statement)
                self.connection().commit()
            except pymysql.MySQLError as error:
                raise SeekDBUnavailableError(f"cannot create SDD schema: {error}") from error

    def server_version(self) -> str:
        rows = self.query("SELECT VERSION() AS version")
        return str(rows[0]["version"]) if rows else "unknown"

    # --------------------------------------------------------------- materials

    def upsert_specification(
        self,
        *,
        spec_id: str,
        version: str,
        revision: str,
        title: str,
        status: str,
        content: str,
        source_path: str,
    ) -> str:
        digest = content_hash(content)
        self.execute(
            """INSERT INTO sdd_specification
               (spec_id, version, revision, title, status, content, content_hash, source_path)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE revision = VALUES(revision), title = VALUES(title),
               status = VALUES(status), content = VALUES(content), content_hash = VALUES(content_hash),
               source_path = VALUES(source_path), imported_at = CURRENT_TIMESTAMP""",
            (spec_id, version, revision, title, status, content, digest, source_path),
        )
        return digest

    def upsert_code_symbol(
        self,
        *,
        file_path: str,
        symbol_name: str,
        qualified_name: str,
        kind: str,
        language: str,
        start_line: int,
        end_line: int,
        signature: str,
        content: str,
        source_path: str,
    ) -> str:
        digest = content_hash(content)
        symbol_id = content_hash(f"{file_path}::{qualified_name}")
        self.execute(
            """INSERT INTO sdd_code_symbol
               (symbol_id, file_path, symbol_name, qualified_name, kind, language,
                start_line, end_line, signature, content, content_hash, source_path)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE symbol_name = VALUES(symbol_name),
               qualified_name = VALUES(qualified_name), kind = VALUES(kind),
               language = VALUES(language), start_line = VALUES(start_line), end_line = VALUES(end_line),
               signature = VALUES(signature), content = VALUES(content),
               content_hash = VALUES(content_hash), source_path = VALUES(source_path)""",
            (
                symbol_id,
                file_path,
                symbol_name,
                qualified_name,
                kind,
                language,
                start_line,
                end_line,
                signature,
                content,
                digest,
                source_path,
            ),
        )
        return symbol_id

    def upsert_test(
        self,
        *,
        file_path: str,
        test_name: str,
        test_kind: str,
        requirement_ids: Sequence[str],
        content: str,
        source_path: str,
    ) -> str:
        digest = content_hash(content)
        test_id = content_hash(f"{file_path}::{test_name}")
        self.execute(
            """INSERT INTO sdd_test
               (test_id, file_path, test_name, test_kind, requirement_ids, content, content_hash, source_path)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE test_name = VALUES(test_name), test_kind = VALUES(test_kind),
               requirement_ids = VALUES(requirement_ids), content = VALUES(content),
               content_hash = VALUES(content_hash), source_path = VALUES(source_path)""",
            (
                test_id,
                file_path,
                test_name,
                test_kind,
                ",".join(requirement_ids),
                content,
                digest,
                source_path,
            ),
        )
        return test_id

    def upsert_relation(
        self,
        *,
        spec_id: str,
        spec_version: str,
        target_kind: str,
        target_id: str,
        relation_type: str,
    ) -> str:
        relation_id = content_hash(f"{spec_id}|{spec_version}|{target_kind}|{target_id}|{relation_type}")
        self.execute(
            """INSERT INTO sdd_relation
               (relation_id, spec_id, spec_version, target_kind, target_id, relation_type)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE relation_type = VALUES(relation_type)""",
            (relation_id, spec_id, spec_version, target_kind, target_id, relation_type),
        )
        return relation_id

    # ---------------------------------------------------------------- retrieval

    def latest_specification(self, spec_id: str) -> dict[str, Any] | None:
        rows = self.query(
            """SELECT spec_id, version, revision, title, status, content, content_hash, source_path
               FROM sdd_specification WHERE spec_id = %s
               ORDER BY imported_at DESC, version DESC LIMIT 1""",
            (spec_id,),
        )
        return rows[0] if rows else None

    def search_specifications(self, terms: Sequence[str]) -> list[dict[str, Any]]:
        if not terms:
            return []
        clauses = " OR ".join(["LOWER(title) LIKE %s OR LOWER(content) LIKE %s"] * len(terms))
        parameters: list[Any] = []
        for term in terms:
            pattern = f"%{term.lower()}%"
            parameters.extend((pattern, pattern))
        rows = self.query(
            f"""SELECT DISTINCT spec_id, version, revision, title, status, content, content_hash, source_path
               FROM sdd_specification WHERE {clauses}
               ORDER BY spec_id, version""",
            tuple(parameters),
        )
        return rows

    def code_symbols_for_paths(self, paths: Sequence[str]) -> list[dict[str, Any]]:
        if not paths:
            return []
        clauses = " OR ".join(["file_path = %s"] * len(paths))
        rows = self.query(
            f"""SELECT file_path, symbol_name, qualified_name, kind, language, start_line, end_line,
               signature, content, content_hash, source_path
               FROM sdd_code_symbol WHERE {clauses} ORDER BY file_path, start_line""",
            tuple(paths),
        )
        return rows

    def tests_for_paths(self, paths: Sequence[str]) -> list[dict[str, Any]]:
        if not paths:
            return []
        clauses = " OR ".join(["file_path = %s"] * len(paths))
        rows = self.query(
            f"""SELECT file_path, test_name, test_kind, requirement_ids, content, content_hash, source_path
               FROM sdd_test WHERE {clauses} ORDER BY file_path, test_name""",
            tuple(paths),
        )
        return rows

    def relations_for_spec(self, spec_id: str, spec_version: str) -> list[dict[str, Any]]:
        return self.query(
            """SELECT spec_id, spec_version, target_kind, target_id, relation_type
               FROM sdd_relation WHERE spec_id = %s AND spec_version = %s
               ORDER BY target_kind, target_id""",
            (spec_id, spec_version),
        )

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in ("sdd_specification", "sdd_code_symbol", "sdd_test", "sdd_relation"):
            rows = self.query(f"SELECT COUNT(*) AS total FROM {table}")
            result[table] = int(rows[0]["total"]) if rows else 0
        return result

    def dump_json(self, payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
