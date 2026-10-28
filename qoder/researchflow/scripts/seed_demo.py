"""Seed the demo dataset through the public HTTP API.

Uploads the three demo documents, creates a research project, runs a retrieval, and saves a
progress snapshot whose key evidence pointers come from real seekdb hits (not hand-written).

Usage: python scripts/seed_demo.py [--api http://127.0.0.1:8787] [--project demo-seekdb-hybrid]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = PROJECT_ROOT / "demo"
UPLOADS = [
    "seekdb_hybrid_retrieval_notes.pdf",
    "research_plan.md",
    "experiment_log.txt",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8787")
    parser.add_argument("--project", default="demo-seekdb-hybrid")
    args = parser.parse_args()
    base = args.api.rstrip("/")

    with httpx.Client(timeout=300.0) as client:
        health = client.get(f"{base}/api/health").json()
        print("health:", health["status"], json.dumps(health["capabilities"], ensure_ascii=False))
        if not health["components"]["seekdb"]["available"]:
            print("seekdb unavailable:", health["components"]["seekdb"].get("error"))
            return 1

        print("\n-- upload --")
        doc_ids: dict[str, str] = {}
        for name in UPLOADS:
            with (DEMO_DIR / name).open("rb") as handle:
                response = client.post(f"{base}/api/documents/upload", files={"file": (name, handle.read())})
            response.raise_for_status()
            body = response.json()
            doc_ids[name] = body["doc_id"]
            print(
                f"  {name}: doc_id={body['doc_id'][:16]}… pages={body['page_count']} "
                f"chunks={body['chunk_count']} empty_pages={body['empty_pages']} dedup={body['deduplicated']}"
            )

        print("\n-- counts read back from seekdb --")
        print(" ", json.dumps(client.get(f"{base}/api/health").json()["components"]["seekdb"]["counts"], ensure_ascii=False))

        print("\n-- retrieval used to build real evidence pointers --")
        search = client.post(
            f"{base}/api/retrieval/search",
            json={"query": "RRF rank constant 60 融合分数是多少", "mode": "hybrid", "top_k": 3, "apply_gate": True},
        ).json()
        for citation in search["citations"]:
            print(f"  {citation['citation_id']} {citation['filename']} p{citation['page_no']} rel={citation['relevance']}")
        evidence = [
            {
                "doc_id": c["doc_id"],
                "filename": c["filename"],
                "page_no": c["page_no"],
                "chunk_id": c["chunk_id"],
                "quote": c["quote"][:200],
            }
            for c in search["citations"][:2]
        ]

        print("\n-- project --")
        created = client.post(
            f"{base}/api/projects",
            json={
                "project_id": args.project,
                "title": "seekdb 混合检索在科研知识库中的效果验证",
                "objective": "确认 seekdb 的向量 + 全文混合检索能否为科研问答提供可核对的页级证据",
            },
        ).json()
        print(f"  project_id={created['project_id']} scope_id={created.get('scope_id')} memory_bound={created.get('memory_bound')}")

        print("\n-- save progress (explicit, user confirmed) --")
        saved = client.post(
            f"{base}/api/projects/{args.project}/memory/save",
            json={
                "objective": "确认 seekdb 的向量 + 全文混合检索能否为科研问答提供可核对的页级证据",
                "title": created["title"],
                "completed_work": [
                    "实测 pyseekdb 1.4.0.post1 远程服务器模式连通 seekdb v1.4.0.0",
                    "实测 ik / ngram / space 三种全文分析器，确认 ik 对中文排序最准",
                    "上传 3 份 demo 文档，PDF 5 个物理页（含第 4 页空白页）全部落库",
                ],
                "decisions": [
                    "D1: 文档主键使用文件内容 SHA-256，重复上传天然去重",
                    "D2: 页号使用 PDF 物理页号，从 1 开始，空白页保留身份行",
                    "D3: 默认检索模式为 hybrid（RRF 融合），全文分析器默认 ik",
                    "D4: 一个科研项目 = 一个 PowerContext Scope，用 idempotency_key 绑定",
                ],
                "key_evidence": evidence,
                "open_questions": [
                    "Q1: all-MiniLM-L6-v2 是英文词表，中文查询命中英文原文时语义相似度偏低，是否切换多语模型",
                    "Q2: PowerContext 的 SQLite 索引用 fts5 unicode61 分词，纯中文记忆检索命中不到",
                ],
                "next_steps": [
                    "跑通 T1-T8 全部验收用例并记录真实结果",
                    "为问答加上服务端 citation 回查校验",
                    "输出 Qoder Sites 公开部署可行性分析",
                ],
                "note": "由 scripts/seed_demo.py 写入，证据指针来自真实检索结果",
                "confirmed_by": "user",
            },
        ).json()
        print(" ", json.dumps(saved, ensure_ascii=False))

        print("\n-- restore in a fresh call --")
        restored = client.get(f"{base}/api/projects/{args.project}/memory/restore").json()
        print(f"  memory_available={restored['memory_available']} entries={restored['entry_count']} source={restored['source']}")
        print("  resume brief:\n" + "\n".join("    " + line for line in restored["resume_brief"].splitlines()))

        print("\n-- grounded QA --")
        qa_response = client.post(
            f"{base}/api/qa/ask",
            json={
                "question": "根据文档，一条记录如果在两条腿里都排第一，RRF 融合分数是多少？",
                "mode": "hybrid",
                "top_k": 5,
                "project_id": args.project,
            },
        )
        if qa_response.status_code != 200:
            # A real failure is reported as-is; the seeded data above is still valid.
            print(f"  QA FAILED HTTP {qa_response.status_code}: {qa_response.text[:600]}")
            print("\nSEED COMPLETED WITH A QA FAILURE (documents and memory were seeded)")
            return 1
        asked = qa_response.json()
        print(f"  mode={asked['mode']} answerable={asked['answerable']} labels={asked['label_summary']}")
        print(f"  invalid_citations={asked['invalid_citations']}")
        print("  answer:", asked["answer"][:500])
        print("  used:", [(c["citation_id"], c["filename"], c["page_no"]) for c in asked["used_citations"]])
        print("  memory channel:", (asked.get("memory") or {}).get("memory_available"), (asked.get("memory") or {}).get("source"))

    print("\nSEED OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
