"""Collect the database query evidence for the delivery package.

The script runs real SQL against the live seekdb instance and writes both the
statements and their results to ``evidence/seekdb_queries.json``, so the
database participation can be inspected without running anything.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from minimax.sdd_context.config import Settings, load_settings  # noqa: E402
from minimax.sdd_context.seekdb_store import SeekDBStore, SeekDBUnavailableError  # noqa: E402

SPEC_ID = "SPEC-REQ-001"


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _run(store: SeekDBStore, title: str, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any]:
    try:
        rows = store.query(sql, parameters)
    except SeekDBUnavailableError as error:
        return {"title": title, "sql": sql, "error": str(error), "rows": []}
    return {"title": title, "sql": sql, "parameters": list(parameters), "row_count": len(rows), "rows": rows}


def main() -> int:
    settings = load_settings()
    settings.ensure_directories()
    store = SeekDBStore(settings)

    try:
        store.initialize()
    except SeekDBUnavailableError as error:
        payload = {
            "database": settings.seekdb_database,
            "error": str(error),
            "queries": [],
        }
        (settings.evidence_dir / "seekdb_queries.json").write_text(_dump(payload), encoding="utf-8")
        print(_dump(payload))
        return 1

    queries = [
        _run(
            store,
            "服务器版本",
            "SELECT VERSION() AS version",
        ),
        _run(
            store,
            "四张表行数",
            "SELECT 'sdd_specification' AS table_name, COUNT(*) AS rows_count FROM sdd_specification"
            " UNION ALL SELECT 'sdd_code_symbol', COUNT(*) FROM sdd_code_symbol"
            " UNION ALL SELECT 'sdd_test', COUNT(*) FROM sdd_test"
            " UNION ALL SELECT 'sdd_relation', COUNT(*) FROM sdd_relation",
        ),
        _run(
            store,
            "规格的全部版本",
            "SELECT spec_id, version, revision, title, status, content_hash, source_path"
            " FROM sdd_specification WHERE spec_id = %s ORDER BY version",
            (SPEC_ID,),
        ),
        _run(
            store,
            "规格的绑定关系",
            "SELECT spec_id, spec_version, target_kind, target_id, relation_type"
            " FROM sdd_relation WHERE spec_id = %s ORDER BY spec_version, target_kind, target_id",
            (SPEC_ID,),
        ),
        _run(
            store,
            "按任务词检索规格",
            "SELECT spec_id, version, revision, title FROM sdd_specification"
            " WHERE LOWER(content) LIKE %s ORDER BY version",
            ("%status%",),
        ),
        _run(
            store,
            "样例代码的符号索引",
            "SELECT file_path, symbol_name, qualified_name, kind, start_line, end_line, signature"
            " FROM sdd_code_symbol WHERE file_path = %s ORDER BY start_line",
            ("sample/taskmanager.py",),
        ),
        _run(
            store,
            "测试索引",
            "SELECT file_path, test_name, test_kind, requirement_ids FROM sdd_test"
            " WHERE file_path IN (%s, %s) ORDER BY file_path, test_name",
            ("tests/test_list_tasks_status_filter.py", "tests/test_list_tasks_status_wildcard.py"),
        ),
    ]

    payload = {
        "database": settings.seekdb_database,
        "host": f"{settings.seekdb_host}:{settings.seekdb_port}",
        "server_version": store.server_version(),
        "queries": queries,
    }
    (settings.evidence_dir / "seekdb_queries.json").write_text(_dump(payload), encoding="utf-8")
    print(_dump(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
