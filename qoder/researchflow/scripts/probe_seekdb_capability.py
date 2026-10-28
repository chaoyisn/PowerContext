"""Live capability probe for pyseekdb against a running seekdb server.

Run: python scripts/probe_seekdb_capability.py
Creates throwaway collections prefixed ``rfprobe_`` and drops them at the end.
"""

from __future__ import annotations

import json
import sys
import time

import pyseekdb
from pyseekdb import (
    DefaultEmbeddingFunction,
    FulltextIndexConfig,
    HNSWConfiguration,
    Schema,
    VectorIndexConfig,
)

HOST = "127.0.0.1"
PORT = 2881
USER = "root"
PASSWORD = ""
DATABASE = "test"

DOCS = [
    ("d1", "OceanBase seekdb supports hybrid retrieval combining vector ANN search and full text search in one SQL statement."),
    ("d2", "PowerContext stores long term agent memory so a new session can resume prior decisions and next steps."),
    ("d3", "向量检索与全文检索可以在同一条 SQL 中完成，混合召回通过 RRF 排序融合。"),
    ("d4", "科研任务记忆需要保存研究目标、已确认决策、关键证据与下一步计划。"),
]


def _client() -> "pyseekdb.Client":
    return pyseekdb.Client(
        host=HOST, port=PORT, tenant="sys", database=DATABASE, user=USER, password=PASSWORD
    )


def probe_analyzer(client, analyzer: str, ef) -> dict:
    name = f"rfprobe_{analyzer}"
    result: dict = {"analyzer": analyzer}
    try:
        client.delete_collection(name)
    except Exception:
        pass
    try:
        schema = Schema(
            vector_index=VectorIndexConfig(
                hnsw=HNSWConfiguration(dimension=384, distance="cosine"),
                embedding_function=ef,
            ),
            fulltext_index=FulltextIndexConfig(analyzer=analyzer),
        )
        col = client.create_collection(name, schema=schema)
        result["create"] = "ok"
    except Exception as exc:
        result["create"] = f"FAIL {type(exc).__name__}: {exc}"
        return result

    try:
        t0 = time.time()
        col.add(ids=[d[0] for d in DOCS], documents=[d[1] for d in DOCS])
        result["add"] = f"ok ({time.time() - t0:.2f}s)"
        result["count"] = col.count()

        r = col.query(query_texts=["hybrid retrieval vector and full text"], n_results=3)
        result["vector_query_ids"] = r["ids"][0]
        result["vector_query_distances"] = [round(x, 4) for x in r["distances"][0]]

        r = col.query(query_texts=["科研任务记忆 决策"], n_results=3)
        result["vector_query_zh_ids"] = r["ids"][0]

        for needle, label in (("hybrid retrieval", "fts_en"), ("混合召回", "fts_zh")):
            try:
                h = col.hybrid_search(
                    query={"where_document": {"$contains": needle}, "n_results": 5},
                    knn={"query_texts": [needle], "n_results": 5},
                    rank={"rrf": {}},
                    n_results=5,
                    include=["documents", "metadatas"],
                )
                result[f"{label}_ids"] = h["ids"][0]
                result[f"{label}_distances"] = [round(x, 4) for x in (h.get("distances") or [[]])[0]]
            except Exception as exc:
                result[f"{label}_ids"] = f"FAIL {type(exc).__name__}: {str(exc)[:200]}"

        try:
            w = col.query(
                query_texts=["hybrid"],
                n_results=5,
                where={"tag": {"$eq": "kernel"}},
            )
            result["metadata_filter"] = f"ok ids={w['ids'][0]}"
        except Exception as exc:
            result["metadata_filter"] = f"FAIL {type(exc).__name__}: {str(exc)[:200]}"
    except Exception as exc:
        result["runtime"] = f"FAIL {type(exc).__name__}: {exc}"
    finally:
        try:
            client.delete_collection(name)
            result["cleanup"] = "ok"
        except Exception as exc:
            result["cleanup"] = f"FAIL {type(exc).__name__}: {exc}"
    return result


def main() -> int:
    print(f"pyseekdb={pyseekdb.__version__}")
    client = _client()
    print("connected:", type(client).__name__)
    ef = DefaultEmbeddingFunction()
    out = {"pyseekdb_version": pyseekdb.__version__, "probes": []}
    for analyzer in ("ik", "ngram", "space"):
        print(f"--- probing analyzer={analyzer} ---", flush=True)
        res = probe_analyzer(client, analyzer, ef)
        out["probes"].append(res)
        print(json.dumps(res, ensure_ascii=False, indent=2), flush=True)
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
