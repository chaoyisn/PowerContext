"""在 seekdb (OceanBase) 上建库、建表并灌入种子数据。

用法::

    python scripts/init_seekdb.py            # 建库 + 建表 + 种子（幂等，可重复执行）
    python scripts/init_seekdb.py --drop     # 先删库再建（会清空所有游戏数据）

连接参数来自环境变量（与 backend/town_backend/config.py 一致）：
``TOWN_SEEKDB_HOST`` / ``TOWN_SEEKDB_PORT`` / ``TOWN_SEEKDB_USER`` /
``TOWN_SEEKDB_PASSWORD`` / ``TOWN_SEEKDB_DATABASE``。

本脚本直连数据库，不经过 Flask 层，因此可以在后端没起来时单独执行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from town_backend.config import load_settings  # noqa: E402
from town_backend.store import SeekDBStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化《记仇小镇》seekdb 数据库")
    parser.add_argument("--drop", action="store_true", help="先 DROP DATABASE 再重建（会清空数据）")
    args = parser.parse_args()

    settings = load_settings()
    store = SeekDBStore(settings)

    print(f"seekdb 目标: {settings.seekdb_host}:{settings.seekdb_port}/{settings.seekdb_database}")

    if args.drop:
        store.drop_database()
        print("已删除旧数据库")

    report = store.initialize()
    print("表结构:")
    for table in report["tables"]:
        print(f"  - {table}")

    counts = store.count_rows()
    print("行数:")
    for table, count in counts.items():
        print(f"  - {table}: {count}")

    print(json.dumps({"database": report["database"], "tables": report["tables"], "counts": counts},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
