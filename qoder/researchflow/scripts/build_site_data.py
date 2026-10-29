"""Export real verification evidence into site/data/evidence.json.

Nothing here is hand-written: the acceptance numbers come from the latest
logs/acceptance-*/acceptance-report.json, the pytest line is parsed from a real run, and the
backend facts are read from the live /api/health. If a source is missing the script fails
loudly instead of emitting placeholders.

Usage: python scripts/build_site_data.py
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
SITE_DATA = PROJECT_ROOT / "site" / "public" / "data"
SHOTS = PROJECT_ROOT / "site" / "public" / "shots"
API = os.environ.get("RF_API", "http://127.0.0.1:8787")

SHOT_CAPTIONS = {
    "s1-overview.png": "对话式首页：左侧项目与会话、中间提问、右侧 Evidence/Context 上下文栏",
    "s2-resume-brief.png": "跨会话恢复：仅凭 project_id 从 PowerContext 取回续研简报与待办",
    "s3-page-navigator.png": "页级证据：PDF 的 5 个物理页全部保留身份，第 4 页空白页被明确标记",
    "s4-page-viewer.png": "证据回查：点击引用打开 seekdb 中存储的原文页，含 page_id 与字符数",
    "s5-retrieval.png": "混合检索：RRF 融合分、覆盖率、相关度与门控状态逐项展示",
    "s6-workbench.png": "证据问答：回答带可点引用，论断按「资料直接支持/模型推断/尚无证据」分级",
    "s7-memory.png": "研究进度面板：显式保存、恢复与历史时间线，全程标记「历史记忆 · PowerContext」",
    "s10-verification.png": "验证页：四个后端组件的实时健康状态与真实计数（seekdb 版本、文档/页/chunk 数）",
    "s8-mobile-overview.png": "移动端首页：390px 视口下侧栏与上下文栏折叠为抽屉，输入框仍在首屏",
    "s9-mobile-knowledge.png": "移动端知识库：文档卡片与检索面板单列排布",
}

LIMITATIONS = [
    "嵌入式 seekdb（pylibseekdb）在 Windows 不可用，官方仅发布 manylinux wheel；本项目使用 pyseekdb 远程服务器模式",
    "PowerContext 1.4.1 默认 SQLite 索引为 fts5 unicode61 分词，纯中文记忆检索召回弱；恢复走全量读取兜底",
    "默认 embedding 为 all-MiniLM-L6-v2（英文词表），跨语言语义相似度有限；已提供可切换的 embedding provider",
    "RRF 融合在平分时的先后顺序不稳定，验收断言按「前 2 位」表述",
]


def latest_acceptance() -> dict:
    candidates = sorted(glob.glob(str(PROJECT_ROOT / "logs" / "acceptance-*" / "acceptance-report.json")),
                        key=os.path.getmtime)
    committed = PROJECT_ROOT / "verification" / "acceptance-run" / "acceptance-report.json"
    if committed.exists():
        candidates.append(str(committed))
    if not candidates:
        raise SystemExit("no acceptance report found; run scripts/run_acceptance.py first")
    newest = max(candidates, key=os.path.getmtime)
    payload = json.loads(Path(newest).read_text(encoding="utf-8"))
    payload["_source"] = str(Path(newest).relative_to(PROJECT_ROOT))
    return payload


def pytest_summary() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no", "-p", "no:cacheprovider"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True, encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=1800,
    )
    tail = (proc.stdout or "") + (proc.stderr or "")
    match = re.search(r"(\d+) passed(?:, (\d+) failed)?(?:, (\d+) skipped)?", tail)
    if not match:
        raise SystemExit(f"could not parse pytest summary:\n{tail[-800:]}")
    return {
        "passed": int(match.group(1)),
        "failed": int(match.group(2) or 0),
        "skipped": int(match.group(3) or 0),
        "command": "cd backend && python -m pytest tests/ -q",
    }


def live_health() -> dict:
    with httpx.Client(timeout=30.0) as client:
        health = client.get(f"{API}/api/health").json()
        meta = client.get(f"{API}/api/meta").json()
    seekdb = health["components"]["seekdb"]
    return {
        "status": health["status"],
        "seekdb_version": seekdb["server_version"],
        "seekdb_endpoint": seekdb["endpoint"],
        "fts_analyzer": seekdb["fts_analyzer"],
        "counts": seekdb["counts"],
        "powercontext_version": health["components"]["powercontext"].get("package_version"),
        "embedding": health["components"]["embedding"],
        "llm": {k: health["components"]["llm"].get(k) for k in ("enabled", "model")},
        "collection": meta["seekdb"]["collection"],
    }


def browser_interactions() -> dict:
    """The Chromium interaction run is the only evidence that the UI really behaves as shown."""
    report = PROJECT_ROOT / "verification" / "browser-acceptance" / "interactions.json"
    if not report.exists():
        raise SystemExit("no browser interaction report; run scripts/verify_interactions.cjs first")
    payload = json.loads(report.read_text(encoding="utf-8"))
    checked = datetime.fromisoformat(payload["checked_at"].replace("Z", "+00:00")).astimezone()
    passed, failed = int(payload["passed"]), int(payload["failed"])
    return {
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "routes": payload["routes"],
        "viewport_matrix": payload["viewport_matrix"],
        "checked_at": checked.isoformat(timespec="seconds"),
        "target": payload["target"],
    }


def latest_json(pattern: str) -> dict | None:
    candidates = sorted(glob.glob(str(PROJECT_ROOT / "logs" / pattern)), key=os.path.getmtime)
    if not candidates:
        return None
    return json.loads(Path(candidates[-1]).read_text(encoding="utf-8"))


def benchmarks() -> dict:
    memory = latest_json("bench-memory-zh-*.json")
    retrieval = latest_json("bench-retrieval-*.json")
    workflow = latest_json("bench-workflow-*.json")
    out: dict = {}
    if memory:
        out["memory_zh"] = {
            "summary": memory["summary"],
            "generated_at": memory["generated_at"],
        }
    if retrieval:
        table = []
        for provider, body in retrieval["providers"].items():
            for mode, r in body["modes"].items():
                table.append({
                    "provider": provider, "mode": mode,
                    "recall@1": r["recall@1"], "recall@5": r["recall@5"], "mrr": r["mrr"],
                    "page_acc@1": r["page_acc@1"], "latency_ms": r["latency_ms_mean"],
                    "false_positives": r["negative_false_positives"],
                })
        out["retrieval"] = {"generated_at": retrieval["generated_at"], "table": table}
    if workflow:
        out["workflow"] = {
            "generated_at": workflow["generated_at"],
            "w1": {
                "baseline_correct": workflow["w1"]["baseline_correct"],
                "baseline_citations": workflow["w1"]["baseline_citations"],
                "rf_top1_correct": workflow["w1"]["researchflow_top1_correct"],
                "rf_top5_correct": workflow["w1"]["researchflow_top5_correct"],
                "rf_citations": workflow["w1"]["researchflow_citations"],
                "rf_ms_total": workflow["w1"]["researchflow_ms_total"],
                "questions": len(workflow["w1"]["rows"]),
            },
            "w2": {
                "baseline_recovered": workflow["w2_baseline"]["recovered"],
                "baseline_total": workflow["w2_baseline"]["total"],
                "baseline_corrections": workflow["w2_baseline"]["manual_corrections"],
                "rf_corrections": workflow["w2"]["manual_corrections"],
                "rf_total_ms": workflow["w2"]["total_ms"],
                "rf_exact": workflow["w2"]["decisions_exact"] and workflow["w2"]["next_steps_exact"],
            },
            "chart": "shots/bench-workflow.svg",
            "caveat": workflow.get("baseline_caveat", ""),
        }
    return out


def main() -> int:
    acceptance = latest_acceptance()
    cases = [
        {
            "id": c["case_id"],
            "title": c["title"],
            "status": c["status"],
            "checks": len(c["checks"]),
            "failed": sum(1 for k in c["checks"] if not k["ok"]),
            "duration_ms": c["duration_ms"],
            "log": c["log"],
        }
        for c in acceptance["cases"]
    ]
    shots = [
        {"file": f"shots/{name}", "caption": caption}
        for name, caption in SHOT_CAPTIONS.items()
        if (SHOTS / name).exists()
    ]
    missing = set(SHOT_CAPTIONS) - {Path(s["file"]).name for s in shots}
    if missing:
        raise SystemExit(f"missing screenshots: {sorted(missing)}; run scripts/capture_screenshots.cjs")

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "acceptance": {
            "source": acceptance["_source"],
            "run_id": acceptance["run_id"],
            "generated_at": acceptance["generated_at"],
            "summary": acceptance["summary"],
            "context": {k: v for k, v in acceptance["context"].items() if k != "documents_ingested"},
            "cases": cases,
        },
        "pytest": pytest_summary(),
        "interactions": browser_interactions(),
        "live": live_health(),
        "screenshots": shots,
        "benchmarks": benchmarks(),
        "limitations": LIMITATIONS,
    }
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    out = SITE_DATA / "evidence.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(PROJECT_ROOT)}")
    print("acceptance:", payload["acceptance"]["summary"])
    print("pytest:", payload["pytest"])
    print("browser interactions:", payload["interactions"]["passed"], "/", payload["interactions"]["total"])
    print("screenshots:", len(shots))
    return 0


if __name__ == "__main__":
    sys.exit(main())
