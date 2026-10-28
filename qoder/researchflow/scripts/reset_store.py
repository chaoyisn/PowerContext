"""Reset only ResearchFlow's own seekdb objects.

Drops tables and collections that start with the configured ``RF_SEEKDB_PREFIX``
(default ``rf_``) and nothing else. The seekdb instance is shared with other competition
entries, so this script never touches un-prefixed objects and never drops the database.

Usage: python scripts/reset_store.py [--prefix rf_] [--yes]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db.seekdb import SeekDBStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", default=None, help="override RF_SEEKDB_PREFIX")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument(
        "--no-recreate", action="store_true", help="drop without recreating the schema"
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.prefix:
        settings.seekdb_prefix = args.prefix
    store = SeekDBStore(settings)

    tables = [
        settings.chunks_collection,
        settings.documents_table,
        settings.pages_table,
        settings.projects_table,
        settings.meta_table,
    ]
    unsafe = [name for name in tables if not name.startswith(settings.seekdb_prefix)]
    if unsafe:
        print(f"REFUSING: these names do not carry the prefix: {unsafe}")
        return 1

    print(f"target database : {settings.seekdb_database} @ {settings.seekdb_host}:{settings.seekdb_port}")
    print(f"prefix          : {settings.seekdb_prefix}")
    print("will drop       : " + ", ".join(tables))
    if not args.yes:
        answer = input("type 'yes' to continue: ").strip()
        if answer != "yes":
            print("aborted")
            return 0

    client = store.pyseekdb_client()
    for name in tables:
        try:
            if client.has_collection(name):
                client.delete_collection(name)
                print(f"  dropped collection {name}")
        except Exception as exc:
            print(f"  collection {name}: {type(exc).__name__}: {exc}")
    for name in (
        settings.documents_table,
        settings.pages_table,
        settings.projects_table,
        settings.meta_table,
    ):
        try:
            store.execute(f"DROP TABLE IF EXISTS `{name}`")
            print(f"  dropped table {name}")
        except Exception as exc:
            print(f"  table {name}: {type(exc).__name__}: {exc}")

    if args.no_recreate:
        print("reset done (schema not recreated)")
        return 0
    store._schema_ready = False
    print("reset done:", store.ensure_schema(embedding_dimension=settings.embedding_dimension))
    return 0


if __name__ == "__main__":
    sys.exit(main())
