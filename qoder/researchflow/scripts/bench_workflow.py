"""D: real workflow efficiency measurement.

Two workflows, each measured against a scripted baseline that proxies the manual way:

* W1 "locate and cite": baseline = Ctrl-F style keyword scan over every extracted page of the
  demo corpus (PyMuPDF for the PDF); ResearchFlow = one hybrid retrieval call with the evidence
  gate. Recorded: wall time, located page vs the human-checked qrel, and how many questions
  would need manual correction.
* W2 "save and resume": baseline = regex-scanning the handwritten progress note
  (demo/progress_notes.md) for decisions and next steps; ResearchFlow = explicit save to
  PowerContext followed by a restore in a SEPARATE process. Recorded: wall time, field-level
  completeness and manual corrections.

The baseline is a proxy for manual work, not a human study; that limitation is stated in the
report. All numbers are measured on this machine and written to logs/bench-workflow-<ts>.json.

Usage: python scripts/bench_workflow.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DEMO_DIR = PROJECT_ROOT / "demo"
sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings  # noqa: E402
from app.db.seekdb import SeekDBStore  # noqa: E402
from app.ingestion import service as ingestion  # noqa: E402
from app.retrieval import service as retrieval  # noqa: E402
from app.retrieval.embeddings import build_embedding_backend  # noqa: E402

PDF = "seekdb_hybrid_retrieval_notes.pdf"
MD = "research_plan.md"

W1_QUESTIONS = [
    {"id": "w1-rrf", "question": "RRF 融合中两条腿都排第一的分数是多少", "keywords": ["0.0328"],
     "qrel": [[PDF, 5]]},
    {"id": "w1-hnsw", "question": "向量索引的距离度量和索引类型", "keywords": ["HNSW", "cosine"],
     "qrel": [[PDF, 2]]},
    {"id": "w1-ik", "question": "哪个全文分析器对中文分词最准", "keywords": ["ik"],
     "qrel": [[PDF, 3]]},
    # The version string genuinely appears in two documents, so both are acceptable answers.
    {"id": "w1-version", "question": "seekdb 服务器的版本号", "keywords": ["seekdb-v1.4.0.0"],
     "qrel": [[PDF, 1], [MD, 1]]},
    {"id": "w1-primary-key", "question": "文档主键的决策", "keywords": ["SHA-256"],
     "qrel": [[MD, 1]]},
    {"id": "w1-next", "question": "验收用例的下一步计划", "keywords": ["T1"],
     "qrel": [[MD, 1]]},
]

DECISIONS = [
    "D1: 文档主键使用文件内容 SHA-256，重复上传天然去重",
    "D2: 页号使用 PDF 物理页号，从 1 开始，空白页保留身份行",
    "D3: 默认检索模式为 hybrid（RRF 融合），全文分析器默认 ik",
    "D4: 一个科研项目 = 一个 PowerContext Scope，用 idempotency_key 绑定",
]
NEXT_STEPS = [
    "跑通 T1-T8 全部验收用例并记录真实结果",
    "为问答加上服务端 citation 回查校验",
    "输出 Qoder Sites 公开部署可行性分析",
]
# Key phrases a human scanner would have to find in the handwritten note.
W2_KEYS = {
    "D1": "SHA-256",
    "D2": "物理页号",
    "D3": "hybrid",
    "D4": "Scope",
    "N1": "T1",
    "N2": "引用回查",
    "N3": "Qoder Sites",
}


def _corpus_pages() -> dict[str, list[str]]:
    import fitz

    pages: dict[str, list[str]] = {}
    with fitz.open(DEMO_DIR / PDF) as document:
        pages[PDF] = [page.get_text("text") for page in document]
    pages[MD] = [(DEMO_DIR / MD).read_text(encoding="utf-8")]
    pages["experiment_log.txt"] = [(DEMO_DIR / "experiment_log.txt").read_text(encoding="utf-8")]
    return pages


def baseline_w1(pages: dict[str, list[str]], keywords: list[str]):
    started = time.perf_counter()
    for filename, page_texts in pages.items():
        for index, text in enumerate(page_texts, start=1):
            lowered = text.lower()
            if all(k.lower() in lowered for k in keywords):
                return (time.perf_counter() - started) * 1000, [filename, index]
    for filename, page_texts in pages.items():
        for index, text in enumerate(page_texts, start=1):
            lowered = text.lower()
            if any(k.lower() in lowered for k in keywords):
                return (time.perf_counter() - started) * 1000, [filename, index]
    return (time.perf_counter() - started) * 1000, None


def run_w1(store, backend, settings, pages) -> dict:
    backend.embed(["warmup"])  # exclude one-off model load from the timings
    rows = []
    for item in W1_QUESTIONS:
        acceptable = [list(q) for q in item["qrel"]]
        base_ms, base_loc = baseline_w1(pages, item["keywords"])
        started = time.perf_counter()
        result = retrieval.search(
            store, backend, item["question"], mode="hybrid", top_k=5,
            apply_gate=True, settings=settings,
        )
        rf_ms = (time.perf_counter() - started) * 1000
        ranked = [[h.filename, h.page_no] for h in result.hits]
        rf_top1 = ranked[0] if ranked else None
        ranks = [i + 1 for i, loc in enumerate(ranked) if loc in acceptable]
        rows.append({
            "id": item["id"],
            "question": item["question"],
            "qrel": acceptable,
            "baseline": {
                "ms": round(base_ms, 1), "located": base_loc,
                "correct": base_loc in acceptable,
                "produces_citation": False,
            },
            "researchflow": {
                "ms": round(rf_ms, 1),
                "top1": rf_top1,
                "top1_correct": rf_top1 in acceptable,
                "rank_of_first_correct": ranks[0] if ranks else None,
                "in_top5_correct": bool(ranks),
                "citation": bool(result.citations),
            },
        })
    base_wrong = sum(1 for r in rows if not r["baseline"]["correct"])
    rf_top1_wrong = sum(1 for r in rows if not r["researchflow"]["top1_correct"])
    rf_top5_wrong = sum(1 for r in rows if not r["researchflow"]["in_top5_correct"])
    return {
        "rows": rows,
        "baseline_ms_total": round(sum(r["baseline"]["ms"] for r in rows), 1),
        "researchflow_ms_total": round(sum(r["researchflow"]["ms"] for r in rows), 1),
        "baseline_manual_corrections": base_wrong,
        "researchflow_top1_corrections": rf_top1_wrong,
        "researchflow_top5_corrections": rf_top5_wrong,
        "baseline_correct": sum(1 for r in rows if r["baseline"]["correct"]),
        "researchflow_top1_correct": sum(1 for r in rows if r["researchflow"]["top1_correct"]),
        "researchflow_top5_correct": sum(1 for r in rows if r["researchflow"]["in_top5_correct"]),
        "researchflow_citations": sum(1 for r in rows if r["researchflow"]["citation"]),
        "baseline_citations": 0,
    }


def baseline_w2() -> dict:
    started = time.perf_counter()
    note = (DEMO_DIR / "progress_notes.md").read_text(encoding="utf-8")
    bullets = [line.strip("- ").strip() for line in note.splitlines() if line.strip().startswith("-")]
    blob = "\n".join(bullets)
    found = {key: (phrase in blob or phrase in note) for key, phrase in W2_KEYS.items()}
    ms = (time.perf_counter() - started) * 1000
    missing = [key for key, ok in found.items() if not ok]
    return {
        "ms": round(ms, 1),
        "recovered": sum(found.values()),
        "total": len(found),
        "missing": missing,
        "manual_corrections": len(missing),
        "structured": False,
        "source_pointers": False,
        "resumable_in_new_session": False,
        "note": "基线为对人工笔记的正则扫描代理；真实人工阅读耗时只会更长。"
                "笔记漏记的条目即人工修正次数。",
    }


def run_w2(store, gateway, settings, run_tag: str) -> dict:
    from app.memory import service as memory
    from app.memory.models import EvidencePointer, ResearchProgress
    import asyncio

    project_id = f"bench-wf-{run_tag}"

    async def _save():
        project, bound = await memory.create_project(
            store, gateway, project_id=project_id, title="工作流测量项目", settings=settings
        )
        assert bound
        started = time.perf_counter()
        saved = await memory.save_progress(
            store, gateway,
            ResearchProgress(
                project_id=project_id, title="工作流测量项目",
                objective="测量保存与恢复闭环",
                decisions=DECISIONS, next_steps=NEXT_STEPS,
                completed_work=["完成 seekdb 混合检索实测"],
                key_evidence=[EvidencePointer(
                    doc_id="d" * 64, filename=PDF, page_no=5, chunk_id=f"{'d' * 16}:p0005:c000",
                    quote="1/61 + 1/61 = 0.0328")],
                confirmed_by="bench",
            ),
            settings,
        )
        return (time.perf_counter() - started) * 1000, saved, project

    save_ms, saved, project = asyncio.new_event_loop().run_until_complete(_save())

    restore_code = (
        "import asyncio,json,sys;"
        f"sys.path.insert(0,r'{BACKEND_DIR}');"
        "from app.config import Settings;"
        "from app.db.seekdb import SeekDBStore;"
        "from app.memory.client import PowerContextGateway;"
        "from app.memory import service as m;"
        "s=Settings(embedding_provider='hashing');"
        "st=SeekDBStore(s);st.ensure_schema(embedding_dimension=s.embedding_dimension);"
        f"r=asyncio.run(m.restore_progress(st,PowerContextGateway(s),{project_id!r},settings=s));"
        "print(json.dumps({'available':r.memory_available,"
        "'decisions':(r.snapshot or {}).get('decisions'),"
        "'next_steps':(r.snapshot or {}).get('next_steps'),"
        "'evidence_pages':[(e or {}).get('page_no') for e in (r.snapshot or {}).get('key_evidence',[])]},"
        "ensure_ascii=False))"
    )
    started = time.perf_counter()
    proc = subprocess.run([sys.executable, "-c", restore_code], capture_output=True, text=True,
                          encoding="utf-8", cwd=str(BACKEND_DIR),
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}, timeout=300)
    restore_ms = (time.perf_counter() - started) * 1000
    line = next((ln for ln in (proc.stdout or "").splitlines() if ln.startswith("{")), "")
    restored = json.loads(line) if line else {}
    decisions_ok = restored.get("decisions") == DECISIONS
    steps_ok = restored.get("next_steps") == NEXT_STEPS
    evidence_ok = restored.get("evidence_pages") == [5]
    corrections = 0 if (decisions_ok and steps_ok and evidence_ok) else 3
    return {
        "save_ms": round(save_ms, 1),
        "restore_ms": round(restore_ms, 1),
        "total_ms": round(save_ms + restore_ms, 1),
        "written": saved.written,
        "snapshot_artifact_id": saved.snapshot_artifact_id,
        "decisions_exact": decisions_ok,
        "next_steps_exact": steps_ok,
        "evidence_page_exact": evidence_ok,
        "manual_corrections": corrections,
        "restored_in_separate_process": proc.returncode == 0,
        "structured": True,
        "source_pointers": True,
        "resumable_in_new_session": proc.returncode == 0 and restored.get("available") is True,
    }


def write_svg(w1: dict, w2: dict, baseline_w2_result: dict, path: Path) -> None:
    bars = [
        ("W1 基线（Ctrl-F 代理）", w1["baseline_ms_total"], "#94a3b8"),
        ("W1 ResearchFlow", w1["researchflow_ms_total"], "#1f5eff"),
        ("W2 基线（笔记扫描）", baseline_w2_result["ms"], "#94a3b8"),
        ("W2 ResearchFlow 保存+恢复", w2["total_ms"], "#6d28d9"),
    ]
    width = max(v for _, v, _ in bars) or 1
    rows = []
    y = 40
    for label, value, color in bars:
        length = 40 + 520 * (value / width)
        rows.append(
            f'<text x="12" y="{y + 14}" font-size="13" fill="#16202c">{label}</text>'
            f'<rect x="230" y="{y}" width="{length:.0f}" height="20" rx="4" fill="{color}"/>'
            f'<text x="{236 + length:.0f}" y="{y + 14}" font-size="12" fill="#46586c">{value:.0f} ms</text>'
        )
        y += 34
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="860" height="' + str(y + 30) + '" '
        'viewBox="0 0 860 ' + str(y + 30) + '" font-family="sans-serif">'
        '<rect width="860" height="' + str(y + 30) + '" fill="#ffffff"/>'
        '<text x="12" y="24" font-size="15" font-weight="700" fill="#16202c">'
        'ResearchFlow 工作流耗时对比（实测，本机）</text>'
        + "".join(rows)
        + f'<text x="12" y="{y + 18}" font-size="12" fill="#6b7c8f">'
        f'W1 定位正确率：基线 top1 {w1["baseline_correct"]}/{len(W1_QUESTIONS)}；ResearchFlow top1 '
        f'{w1["researchflow_top1_correct"]}/{len(W1_QUESTIONS)}、top5 {w1["researchflow_top5_correct"]}/'
        f'{len(W1_QUESTIONS)}；需人工修正：基线 {w1["baseline_manual_corrections"]}、ResearchFlow(top5) '
        f'{w1["researchflow_top5_corrections"]}；可点引用：基线 0、ResearchFlow {w1["researchflow_citations"]}/'
        f'{len(W1_QUESTIONS)}。W2 字段完整度：基线 {baseline_w2_result["recovered"]}/'
        f'{baseline_w2_result["total"]}（无结构、无来源指针），ResearchFlow '
        f'{"3/3 且逐字段精确" if w2["manual_corrections"] == 0 else "不完整"}。</text>'
        "</svg>"
    )
    path.write_text(svg, encoding="utf-8")


def main() -> int:
    settings = get_settings()
    store = SeekDBStore(settings)
    backend = build_embedding_backend(settings)
    store.ensure_schema(embedding_dimension=backend.dimension)
    from app.memory.client import PowerContextGateway

    gateway = PowerContextGateway(settings)
    run_tag = time.strftime("%H%M%S")

    pages = _corpus_pages()
    w1 = run_w1(store, backend, settings, pages)
    base2 = baseline_w2()
    w2 = run_w2(store, gateway, settings, run_tag)

    print("\n== W1 locate & cite ==")
    for row in w1["rows"]:
        rf = row["researchflow"]
        print(
            f"  {row['id']:16s} qrel={row['qrel']} base={row['baseline']['located']} "
            f"({row['baseline']['ms']:.0f}ms, {'ok' if row['baseline']['correct'] else 'WRONG'}) "
            f"rf top1={rf['top1']} rank_of_correct={rf['rank_of_first_correct']} "
            f"({rf['ms']:.0f}ms, cite={rf['citation']})"
        )
    print(
        f"  totals: base {w1['baseline_ms_total']}ms correct {w1['baseline_correct']}/{len(W1_QUESTIONS)} "
        f"corrections {w1['baseline_manual_corrections']}; "
        f"rf {w1['researchflow_ms_total']}ms top1 {w1['researchflow_top1_correct']}/{len(W1_QUESTIONS)} "
        f"top5 {w1['researchflow_top5_correct']}/{len(W1_QUESTIONS)} "
        f"corrections(top5) {w1['researchflow_top5_corrections']}"
    )
    print("\n== W2 save & resume ==")
    print(f"  baseline: {base2['ms']}ms recovered {base2['recovered']}/{base2['total']} "
          f"missing={base2['missing']} corrections={base2['manual_corrections']}")
    print(f"  researchflow: save {w2['save_ms']}ms + restore {w2['restore_ms']}ms = {w2['total_ms']}ms "
          f"exact(decisions={w2['decisions_exact']}, steps={w2['next_steps_exact']}, "
          f"evidence={w2['evidence_page_exact']}) corrections={w2['manual_corrections']}")

    svg_path = PROJECT_ROOT / "site" / "public" / "shots" / "bench-workflow.svg"
    write_svg(w1, w2, base2, svg_path)
    print("chart:", svg_path.relative_to(PROJECT_ROOT))

    out = PROJECT_ROOT / "logs" / f"bench-workflow-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "embedding_provider": backend.provider,
        "baseline_caveat": "基线为脚本代理（全文关键词扫描 / 笔记正则扫描），不是人工实测；"
                           "真实人工耗时只会更长，此处仅作为可复现的下界对照。",
        "w1": w1, "w2_baseline": base2, "w2": w2,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("report:", out.relative_to(PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
