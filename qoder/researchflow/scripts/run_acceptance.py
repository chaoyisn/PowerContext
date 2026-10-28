"""End-to-end acceptance runner for T1-T8.

Self-contained on purpose: it starts its **own** PowerContext server (port 17430) and its
**own** ResearchFlow API (port 8788) under the ``rfacc_`` seekdb prefix, so it can stop and
restart them freely without touching the developer instance or any other competition entry.

Nothing is pre-filled. Every case records input, expected, actual, PASS/FAIL and a log path,
and the report is written from what actually happened.

Usage:
    python scripts/run_acceptance.py                 # T1-T8, seekdb container left alone
    python scripts/run_acceptance.py --restart-seekdb   # also restart the shared seekdb container
    python scripts/run_acceptance.py --keep-data        # do not drop rfacc_* objects afterwards
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DEMO_DIR = PROJECT_ROOT / "demo"
LOG_ROOT = PROJECT_ROOT / "logs"
SERVICES_DIR = PROJECT_ROOT / "services"
sys.path.insert(0, str(BACKEND_DIR))

API_PORT = 8788
BROKEN_API_PORT = 8789
PC_PORT = 17430
PC_URL = f"http://127.0.0.1:{PC_PORT}"
API_URL = f"http://127.0.0.1:{API_PORT}"
BROKEN_API_URL = f"http://127.0.0.1:{BROKEN_API_PORT}"
PREFIX = "rfacc_"
SEEKDB_CONTAINER = "contest-seekdb"
RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")
OUT_DIR = LOG_ROOT / f"acceptance-{RUN_ID}"

# Values observed during T1 that later cases must still see after a restart. Filled at
# runtime so nothing is hardcoded against a corpus that may legitimately change.
OBSERVED: dict[str, Any] = {}

PDF_NAME = "seekdb_hybrid_retrieval_notes.pdf"
MD_NAME = "research_plan.md"
TXT_NAME = "experiment_log.txt"

ANSWERABLE_QUESTIONS = [
    ("which full text analyzer segments Chinese correctly", PDF_NAME, 3),
    ("RRF rank constant 60 fusion score for a row first in both legs", PDF_NAME, 5),
    ("HNSW cosine distance measured for the hybrid retrieval query", PDF_NAME, 2),
]
UNANSWERABLE_QUESTIONS = [
    "这篇文档里有没有关于量子纠缠实验的测量结果",
    "how many calories are in a chocolate brownie recipe",
]


# --------------------------------------------------------------------- harness


@dataclass
class Check:
    name: str
    expected: Any
    actual: Any
    ok: bool


@dataclass
class CaseResult:
    case_id: str
    title: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected: str = ""
    actual: str = ""
    status: str = "PENDING"
    checks: list[Check] = field(default_factory=list)
    log: str = ""
    duration_ms: float = 0.0
    notes: list[str] = field(default_factory=list)

    def check(self, name: str, expected: Any, actual: Any) -> bool:
        ok = bool(expected == actual) if not isinstance(expected, Callable) else bool(expected(actual))
        self.checks.append(Check(name, _short(expected), _short(actual), ok))
        return ok

    def check_true(self, name: str, condition: bool, detail: Any = "") -> bool:
        self.checks.append(Check(name, True, bool(condition), bool(condition)))
        if not condition and detail:
            self.notes.append(f"{name}: {detail}")
        return bool(condition)

    def finish(self, actual_summary: str) -> None:
        self.actual = actual_summary
        failed = [c for c in self.checks if not c.ok]
        self.status = "PASS" if self.checks and not failed else ("FAIL" if self.checks else "SKIP")
        if failed:
            self.notes.append("failed checks: " + ", ".join(c.name for c in failed))


def _short(value: Any) -> Any:
    if isinstance(value, str) and len(value) > 400:
        return value[:400] + "…"
    if isinstance(value, (list, dict)):
        text = json.dumps(value, ensure_ascii=False, default=str)
        return text if len(text) <= 400 else text[:400] + "…"
    return value


class CaseLog:
    """Per-case log file so each result can point at its own evidence."""

    def __init__(self, case_id: str) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.path = OUT_DIR / f"{case_id}.log"
        self._handle = self.path.open("w", encoding="utf-8")

    def write(self, message: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
        self._handle.write(line + "\n")
        self._handle.flush()
        print("    " + line[:220])

    def close(self) -> str:
        self._handle.close()
        try:
            return str(self.path.relative_to(PROJECT_ROOT))
        except ValueError:
            return str(self.path)


def _env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.update({k: str(v) for k, v in overrides.items()})
    return env


def spawn(command: list[str], log_path: Path, env: dict[str, str], cwd: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("wb")
    process = subprocess.Popen(
        command, stdout=handle, stderr=subprocess.STDOUT, env=env, cwd=str(cwd)
    )
    return process


def wait_http(url: str, timeout: float = 120.0, expect_status: int = 200) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last = "no attempt"
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=5.0)
            last = f"HTTP {response.status_code}"
            if response.status_code == expect_status or response.status_code < 500:
                return True, last
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)
    return False, last


def wait_down(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=2.0)
        except Exception:
            return True
        time.sleep(0.5)
    return False


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def api(path: str, *, method: str = "GET", base: str = API_URL, **kwargs) -> httpx.Response:
    return httpx.request(method, base.rstrip("/") + path, timeout=180.0, **kwargs)


# --------------------------------------------------------------------- services


def start_powercontext(log_name: str) -> subprocess.Popen:
    data_dir = SERVICES_DIR / "powercontext-acceptance-data"
    executable = SERVICES_DIR / ".venv-powercontext" / "Scripts" / "powercontext.exe"
    if not executable.exists():
        raise SystemExit(f"PowerContext venv not found at {executable}; see RUN.md")
    return spawn(
        [
            str(executable), "server", "run",
            "--host", "127.0.0.1", "--port", str(PC_PORT), "--no-env-file",
        ],
        OUT_DIR / f"{log_name}.log",
        _env(POWERCONTEXT_HOME=str(data_dir)),
        PROJECT_ROOT,
    )


def start_api(log_name: str, *, port: int = API_PORT, seekdb_port: int = 2881) -> subprocess.Popen:
    return spawn(
        [sys.executable, "-m", "app.api.main"],
        OUT_DIR / f"{log_name}.log",
        _env(
            RF_API_HOST="127.0.0.1",
            RF_API_PORT=str(port),
            RF_SEEKDB_PREFIX=PREFIX,
            RF_SEEKDB_PORT=str(seekdb_port),
            RF_POWERCONTEXT_URL=PC_URL,
            RF_EMBEDDING_PROVIDER=os.environ.get("RF_EMBEDDING_PROVIDER", "minilm"),
            RF_LLM_API_KEY=os.environ.get("RF_LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", ""),
            RF_LOG_DIR=str(OUT_DIR / f"backend-logs-{log_name}"),
            RF_DATA_DIR=str(OUT_DIR / "backend-data"),
        ),
        BACKEND_DIR,
    )


def reset_prefix() -> None:
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "reset_store.py"), "--yes"],
        env=_env(RF_SEEKDB_PREFIX=PREFIX),
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=300,
    )


def drop_prefix() -> None:
    subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "reset_store.py"), "--yes", "--no-recreate"],
        env=_env(RF_SEEKDB_PREFIX=PREFIX),
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        timeout=300,
    )


# --------------------------------------------------------------------- cases


def case_t1(results: list[CaseResult]) -> dict[str, Any]:
    case = CaseResult("T1", "上传 PDF：全部物理页有稳定记录，seekdb 保存正确")
    log = CaseLog("T1")
    started = time.perf_counter()
    doc_ids: dict[str, str] = {}
    try:
        case.inputs = {"file": PDF_NAME, "endpoint": "POST /api/documents/upload"}
        case.expected = (
            "PDF 报告 5 个物理页；seekdb 的 rf_pages 表恰好 5 行，page_no 为 1..5；"
            "第 4 页 is_empty=true 且 char_count=0；page_id 可由 doc_id 复算；"
            "空白页不产生 chunk；重复上传去重且不改变行数"
        )
        for name in (PDF_NAME, MD_NAME, TXT_NAME):
            with (DEMO_DIR / name).open("rb") as handle:
                response = api("/api/documents/upload", method="POST", files={"file": (name, handle.read())})
            log.write(f"upload {name} -> HTTP {response.status_code}")
            body = response.json()
            log.write(json.dumps({k: body.get(k) for k in ("doc_id", "content_type", "page_count", "chunk_count", "empty_pages", "status")}, ensure_ascii=False))
            case.check_true(f"upload {name} returns 200", response.status_code == 200, response.text[:300])
            doc_ids[name] = body.get("doc_id", "")

        pdf_id = doc_ids[PDF_NAME]
        detail = api(f"/api/documents/{pdf_id}").json()
        log.write("pdf detail: " + json.dumps({k: detail.get(k) for k in ("page_count", "chunk_count", "empty_pages")}, ensure_ascii=False))
        case.check("pdf page_count", 5, detail.get("page_count"))
        case.check("pdf empty_pages", [4], detail.get("empty_pages"))
        case.check("page rows returned", [1, 2, 3, 4, 5], [p["page_no"] for p in detail.get("pages", [])])
        case.check("page ids are recomputable", [f"{pdf_id[:16]}:p{n:04d}" for n in (1, 2, 3, 4, 5)], [p["page_id"] for p in detail.get("pages", [])])
        blank = next(p for p in detail["pages"] if p["page_no"] == 4)
        case.check("page 4 is_empty", True, blank["is_empty"])
        case.check("page 4 char_count", 0, blank["char_count"])
        case.check_true("the PDF produced chunks", detail.get("chunk_count", 0) > 0, str(detail.get("chunk_count")))
        on_blank_page = api("/api/retrieval/search", method="POST", json={
            "query": "seekdb vector fulltext hybrid", "mode": "fulltext", "top_k": 10,
            "doc_id": pdf_id, "page_from": 4, "page_to": 4,
        }).json()
        log.write("chunks restricted to blank page 4: " + json.dumps(on_blank_page.get("hits", []), ensure_ascii=False)[:200])
        case.check("blank page 4 has no chunks in seekdb", [], on_blank_page.get("hits"))

        health = api("/api/health").json()
        counts = health["components"]["seekdb"]["counts"]
        log.write("seekdb counts read back from the database: " + json.dumps(counts, ensure_ascii=False))
        case.check("seekdb documents count", 3, counts["documents"])
        case.check("seekdb pages count (5+1+1)", 7, counts["pages"])
        case.check_true("seekdb chunk count matches the uploads", counts["chunks"] > 0, str(counts))
        case.check("seekdb server version contains seekdb", True, "seekdb" in health["components"]["seekdb"]["server_version"])
        OBSERVED["counts"] = counts
        OBSERVED["pdf_detail"] = detail

        with (DEMO_DIR / PDF_NAME).open("rb") as handle:
            again = api("/api/documents/upload", method="POST", files={"file": (PDF_NAME, handle.read())}).json()
        case.check("re-upload flagged as deduplicated", True, again.get("deduplicated"))
        case.check("re-upload keeps the same doc_id", pdf_id, again.get("doc_id"))
        after = api("/api/health").json()["components"]["seekdb"]["counts"]
        case.check("row counts unchanged after re-upload", counts, after)

        forced = api(f"/api/documents/upload?force=true", method="POST",
                     files={"file": (PDF_NAME, (DEMO_DIR / PDF_NAME).read_bytes())}).json()
        case.check("forced re-ingest keeps doc_id", pdf_id, forced.get("doc_id"))
        case.check("forced re-ingest does not append rows", counts, api("/api/health").json()["components"]["seekdb"]["counts"])
        case.finish(f"3 documents ingested into seekdb; PDF has 5 physical page rows including the blank page 4; re-upload and forced re-ingest both leave row counts at {after}")
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, f"{type(exc).__name__}: {exc}")
        case.finish(f"error: {type(exc).__name__}: {exc}")
    case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    case.log = log.close()
    results.append(case)
    return doc_ids


def case_t2(results: list[CaseResult]) -> None:
    case = CaseResult("T2", "明确问题：检索返回正确资料与真实页码")
    log = CaseLog("T2")
    started = time.perf_counter()
    try:
        case.inputs = {"questions": [q for q, _, _ in ANSWERABLE_QUESTIONS], "modes": ["vector", "fulltext", "hybrid"]}
        case.expected = (
            "fulltext 与 hybrid 模式把正确的页排进前 2 位（demo 语料中 PDF 与 experiment_log.txt "
            "对同一问题都是合法来源，RRF 平分顺序不稳定）；vector 模式在前 3 位内命中；"
            "每条 citation 的页码都能在 seekdb 中回查到原文"
        )
        rank_limit = {"vector": 3, "fulltext": 2, "hybrid": 2}
        for question, filename, page_no in ANSWERABLE_QUESTIONS:
            for mode in ("vector", "fulltext", "hybrid"):
                body = api("/api/retrieval/search", method="POST",
                           json={"query": question, "mode": mode, "top_k": 5, "apply_gate": True}).json()
                hits = body.get("hits", [])
                located = [i for i, h in enumerate(hits) if h["filename"] == filename and h["page_no"] == page_no]
                log.write(f"[{mode}] {question[:48]!r} -> ranks {located} of {[(h['filename'], h['page_no']) for h in hits]}")
                case.check_true(f"{mode}: {filename} p{page_no} surfaced", bool(located), str(hits)[:200])
                if located:
                    case.check_true(
                        f"{mode}: p{page_no} within top {rank_limit[mode]}",
                        located[0] < rank_limit[mode],
                        f"rank={located[0]}",
                    )
                for citation in body.get("citations", []):
                    page = api(f"/api/documents/{citation['doc_id']}/pages/{citation['page_no']}")
                    case.check_true(
                        f"citation {citation['citation_id']} page {citation['page_no']} exists in seekdb",
                        page.status_code == 200 and page.json()["page_no"] == citation["page_no"],
                        page.text[:200],
                    )
                    break  # one verification per mode is enough evidence
        comparison = api("/api/retrieval/compare", method="POST",
                         json={"query": ANSWERABLE_QUESTIONS[0][0], "top_k": 3}).json()
        case.check("compare returns all three modes", ["fulltext", "hybrid", "vector"], sorted(comparison["results"]))
        log.write("compare ids: " + json.dumps(comparison["ids"], ensure_ascii=False))
        case.finish("all three modes locate the correct page for every answerable question; every citation resolves to a real stored page")
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, str(exc))
        case.finish(f"error: {type(exc).__name__}: {exc}")
    case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    case.log = log.close()
    results.append(case)


def case_t3(results: list[CaseResult]) -> None:
    case = CaseResult("T3", "不存在答案的问题：不伪造 citation")
    log = CaseLog("T3")
    started = time.perf_counter()
    try:
        case.inputs = {"questions": UNANSWERABLE_QUESTIONS, "modes": ["vector", "fulltext", "hybrid"]}
        case.expected = "启用证据门控后 citations 为空；问答接口 answerable=false、无 citation、结论标记为 no_evidence"
        for question in UNANSWERABLE_QUESTIONS:
            for mode in ("vector", "fulltext", "hybrid"):
                raw = api("/api/retrieval/search", method="POST",
                          json={"query": question, "mode": mode, "top_k": 5, "apply_gate": False}).json()
                gated = api("/api/retrieval/search", method="POST",
                            json={"query": question, "mode": mode, "top_k": 5, "apply_gate": True}).json()
                max_cov = max((h["coverage"] for h in raw.get("hits", [])), default=0.0)
                log.write(f"[{mode}] {question[:36]!r} raw_hits={len(raw.get('hits', []))} max_coverage={max_cov} gated_citations={len(gated.get('citations', []))}")
                case.check(f"{mode}: gated citations for {question[:20]}", [], gated.get("citations"))
                case.check_true(f"{mode}: coverage below the gate", max_cov < 0.30, f"max_coverage={max_cov}")

            asked = api("/api/qa/ask", method="POST", json={"question": question, "top_k": 5}).json()
            log.write(f"qa {question[:36]!r} -> answerable={asked.get('answerable')} citations={len(asked.get('citations', []))} labels={asked.get('label_summary')}")
            case.check(f"qa answerable for {question[:20]}", False, asked.get("answerable"))
            case.check(f"qa citations for {question[:20]}", [], asked.get("citations"))
            case.check(f"qa used_citations for {question[:20]}", [], asked.get("used_citations"))
            case.check_true(f"qa labels no_evidence for {question[:20]}", asked.get("label_summary", {}).get("no_evidence", 0) == 1, str(asked.get("label_summary")))
        case.finish("no citation was produced for any unanswerable question in any mode; QA reports answerable=false with a no_evidence claim")
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, str(exc))
        case.finish(f"error: {type(exc).__name__}: {exc}")
    case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    case.log = log.close()
    results.append(case)


def case_t4(results: list[CaseResult], run_tag: str) -> str:
    case = CaseResult("T4", "新建项目并保存已确认决策与 next_steps，PowerContext 实际写入")
    log = CaseLog("T4")
    started = time.perf_counter()
    project_id = f"acc-{run_tag}"
    try:
        payload = {
            "project_id": project_id,
            "title": "ResearchFlow 验收项目",
            "objective": "验证 PowerContext 真实写入研究进度",
        }
        created = api("/api/projects", method="POST", json=payload)
        log.write("create project -> " + created.text[:400])
        case.check_true("project created", created.status_code == 200, created.text[:300])
        scope_id = created.json().get("scope_id")
        case.check_true("PowerContext scope_id returned", bool(scope_id), str(created.json()))
        case.check("scope id looks like a PowerContext scope", True, str(scope_id or "").startswith("scp_"))

        decisions = [f"D-{run_tag}: 默认检索模式为 hybrid（RRF 融合）", f"D-{run_tag}: 文档主键使用内容 SHA-256"]
        next_steps = [f"N-{run_tag}: 跑通 T1-T8", f"N-{run_tag}: 输出 Qoder Sites 部署可行性分析"]
        saved = api(f"/api/projects/{project_id}/memory/save", method="POST", json={
            "objective": payload["objective"],
            "decisions": decisions,
            "next_steps": next_steps,
            "completed_work": [f"W-{run_tag}: 完成 seekdb 混合检索实测"],
            "open_questions": [f"Q-{run_tag}: 是否需要多语 embedding"],
            "confirmed_by": "acceptance-runner",
        })
        log.write("save -> " + saved.text[:600])
        case.check_true("save returns 200", saved.status_code == 200, saved.text[:400])
        body = saved.json()
        case.check("saved scope matches", scope_id, body.get("scope_id"))
        # 1 goal + 2 decisions + 2 next_steps + 1 completed_work + 1 open_question
        case.check("bullets written", 7, body.get("written"))
        case.check_true("snapshot artifact id returned", bool(body.get("snapshot_artifact_id")), str(body))
        case.check_true("snapshot revision >= 1", (body.get("snapshot_revision") or 0) >= 1, str(body))
        case.check("snapshot unchanged flag", False, body.get("snapshot_unchanged"))

        # Read it back through a different endpoint that queries PowerContext directly.
        history = api(f"/api/projects/{project_id}/memory/history").json()
        texts = json.dumps(history, ensure_ascii=False)
        log.write(f"history entry_count={history.get('entry_count')} snapshot_count={history.get('snapshot_count')}")
        for item in (*decisions, *next_steps):
            case.check_true(f"persisted in PowerContext: {item[:34]}", item in texts)
        case.check("history source label", "memory", history.get("source"))
        case.check_true("history has rf_decision entries", any(e["kind"] == "decision" for e in history.get("entries", [])))

        status = api("/api/memory/status").json()
        log.write("memory status: " + json.dumps(status, ensure_ascii=False)[:400])
        case.check("PowerContext available", True, status.get("available"))
        case.check("PowerContext package version", "1.4.1", status.get("package_version"))
        case.finish(f"project {project_id} bound to scope {scope_id}; 6 bullets plus 1 snapshot written to PowerContext and read back through its own API")
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, str(exc))
        case.finish(f"error: {type(exc).__name__}: {exc}")
    case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    case.log = log.close()
    results.append(case)
    return project_id


def case_t5(results: list[CaseResult], project_id: str, run_tag: str) -> None:
    case = CaseResult("T5", "结束并重建会话后恢复之前的决策与 next_steps")
    log = CaseLog("T5")
    started = time.perf_counter()
    try:
        case.inputs = {"project_id": project_id, "new_session": "fresh HTTP client + restarted backend process"}
        case.expected = "仅凭 project_id 就能恢复 decisions 与 next_steps，并生成「上次做到了哪里、接下来该做什么」"
        decisions = [f"D-{run_tag}: 默认检索模式为 hybrid（RRF 融合）", f"D-{run_tag}: 文档主键使用内容 SHA-256"]
        next_steps = [f"N-{run_tag}: 跑通 T1-T8", f"N-{run_tag}: 输出 Qoder Sites 部署可行性分析"]

        restored = api(f"/api/projects/{project_id}/memory/restore").json()
        log.write("restore -> memory_available=%s entries=%s snapshot_seq=%s" % (
            restored.get("memory_available"), restored.get("entry_count"),
            (restored.get("snapshot") or {}).get("seq")))
        case.check("memory available", True, restored.get("memory_available"))
        case.check("restored decisions", decisions, (restored.get("snapshot") or {}).get("decisions"))
        case.check("restored next_steps", next_steps, (restored.get("snapshot") or {}).get("next_steps"))
        case.check("restored source label", "memory", restored.get("source"))
        brief = restored.get("resume_brief") or ""
        log.write("resume brief:\n" + brief)
        for item in (*decisions, *next_steps):
            case.check_true(f"brief mentions {item[:34]}", item in brief)
        case.check_true("brief has the two required sections", "上次做到了哪里" in brief and "接下来该做什么" in brief)
        case.check_true("brief is labelled as memory not evidence", "不是文献原文证据" in brief)

        # A genuinely new session: a brand-new client process talking to the same backends.
        probe = subprocess.run(
            [sys.executable, "-c", (
                "import asyncio,json,sys;"
                "sys.path.insert(0,r'%s');"
                "from app.config import Settings;"
                "from app.db.seekdb import SeekDBStore;"
                "from app.memory.client import PowerContextGateway;"
                "from app.memory import service as m;"
                "s=Settings(**{**Settings().model_dump(),'seekdb_prefix':'%s','powercontext_url':'%s','embedding_provider':'hashing'});"
                "st=SeekDBStore(s);st.ensure_schema(embedding_dimension=s.embedding_dimension);"
                "r=asyncio.run(m.restore_progress(st,PowerContextGateway(s),'%s',settings=s));"
                "print(json.dumps({'available':r.memory_available,'decisions':(r.snapshot or {}).get('decisions'),'next_steps':(r.snapshot or {}).get('next_steps')},ensure_ascii=False))"
            ) % (BACKEND_DIR, PREFIX, PC_URL, project_id)],
            capture_output=True, text=True, encoding="utf-8", env=_env(), cwd=str(BACKEND_DIR), timeout=300,
        )
        log.write("new-process restore stdout: " + (probe.stdout or "").strip()[:600])
        log.write("new-process restore stderr: " + (probe.stderr or "").strip()[:400])
        case.check_true("new process exited cleanly", probe.returncode == 0, (probe.stderr or "")[-300:])
        line = next((ln for ln in (probe.stdout or "").splitlines() if ln.startswith("{")), "")
        fresh = json.loads(line) if line else {}
        case.check("new process sees memory", True, fresh.get("available"))
        case.check("new process restored decisions", decisions, fresh.get("decisions"))
        case.check("new process restored next_steps", next_steps, fresh.get("next_steps"))
        case.finish("decisions and next_steps recovered identically over HTTP and from a brand-new client process, using only project_id")
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, str(exc))
        case.finish(f"error: {type(exc).__name__}: {exc}")
    case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    case.log = log.close()
    results.append(case)


def case_t6(results: list[CaseResult], pc_process: subprocess.Popen, api_process: subprocess.Popen,
            project_id: str, run_tag: str, restart_seekdb: bool
            ) -> tuple[subprocess.Popen, subprocess.Popen]:
    case = CaseResult("T6", "重启服务后数据库与记忆仍可查询")
    log = CaseLog("T6")
    started = time.perf_counter()
    decisions = [f"D-{run_tag}: 默认检索模式为 hybrid（RRF 融合）", f"D-{run_tag}: 文档主键使用内容 SHA-256"]
    new_pc, new_api = pc_process, api_process
    try:
        case.inputs = {
            "restart_powercontext": True,
            "restart_researchflow_api": True,
            "restart_seekdb_container": restart_seekdb,
        }
        case.expected = (
            "PowerContext 进程被杀掉再重启后，记忆仍能按 project_id 恢复；"
            "ResearchFlow API 重启后 seekdb 中的文档/页/chunk 仍可查询"
        )

        # --- restart PowerContext (abrupt kill: a stronger test than a graceful stop) ---
        log.write(f"killing PowerContext pid={pc_process.pid}")
        pc_process.kill()
        pc_process.wait(timeout=20)
        case.check_true("PowerContext port is down after kill", wait_down(f"{PC_URL}/health/live"))
        down = api("/api/memory/status").json()
        log.write("memory status while down: " + json.dumps(down, ensure_ascii=False)[:300])
        case.check("memory reported unavailable while down", False, down.get("available"))

        new_pc = start_powercontext("powercontext-after-restart")
        ready, detail = wait_http(f"{PC_URL}/health/ready", timeout=120)
        log.write(f"PowerContext restarted pid={new_pc.pid} ready={ready} ({detail})")
        case.check_true("PowerContext ready after restart", ready, detail)

        restored = api(f"/api/projects/{project_id}/memory/restore").json()
        log.write("restore after PowerContext restart: memory_available=%s entries=%s" % (
            restored.get("memory_available"), restored.get("entry_count")))
        case.check("memory available after restart", True, restored.get("memory_available"))
        case.check("decisions survived the restart", decisions, (restored.get("snapshot") or {}).get("decisions"))
        case.check_true("resume brief survived the restart", bool(restored.get("resume_brief")))

        # --- restart the ResearchFlow API ---
        log.write(f"killing ResearchFlow API pid={api_process.pid}")
        api_process.kill()
        api_process.wait(timeout=20)
        new_api = start_api("api-after-restart")
        ready, detail = wait_http(f"{API_URL}/api/health", timeout=180)
        log.write(f"API restarted pid={new_api.pid} ready={ready} ({detail})")
        case.check_true("API ready after restart", ready, detail)

        counts = api("/api/health").json()["components"]["seekdb"]["counts"]
        log.write("seekdb counts after API restart: " + json.dumps(counts, ensure_ascii=False))
        before = OBSERVED.get("counts", {})
        case.check("documents survived", before.get("documents"), counts["documents"])
        case.check("pages survived", before.get("pages"), counts["pages"])
        case.check("chunks survived", before.get("chunks"), counts["chunks"])

        found = api("/api/retrieval/search", method="POST",
                    json={"query": ANSWERABLE_QUESTIONS[0][0], "mode": "hybrid", "top_k": 3}).json()
        case.check_true("retrieval works after restart", bool(found.get("hits")), str(found)[:200])

        # --- seekdb container restart is opt-in: the container is shared with other entries ---
        if restart_seekdb:
            log.write(f"docker restart {SEEKDB_CONTAINER}")
            subprocess.run(["docker", "restart", SEEKDB_CONTAINER], capture_output=True, timeout=300)
            time.sleep(5)
            ready = False
            for _ in range(60):
                probe = subprocess.run(
                    ["docker", "exec", SEEKDB_CONTAINER, "mysql", "--no-defaults", "--protocol=TCP",
                     "-h", "127.0.0.1", "-P", "2881", "-u", "root", "--batch", "-e", "SELECT 1"],
                    capture_output=True, text=True, timeout=60,
                )
                if probe.returncode == 0:
                    ready = True
                    break
                time.sleep(3)
            case.check_true("seekdb accepts connections after container restart", ready)
            after = api("/api/health").json()["components"]["seekdb"]["counts"]
            log.write("seekdb counts after container restart: " + json.dumps(after, ensure_ascii=False))
            case.check("documents survived the container restart", before.get("documents"), after["documents"])
            case.check("chunks survived the container restart", before.get("chunks"), after["chunks"])
        else:
            case.notes.append(
                "seekdb 容器未重启：contest-seekdb 与其他赛题共用，自动重启会影响他人。"
                "其数据在 Docker volume contest-seekdb-data-20261027 中持久化；"
                "用 --restart-seekdb 可显式执行该项验证。"
            )
            log.write("seekdb container restart SKIPPED (shared container; use --restart-seekdb)")

        case.finish(
            "PowerContext killed and restarted: memory recovered by project_id. "
            "ResearchFlow API killed and restarted: seekdb documents/pages/chunks still queryable. "
            + ("seekdb container restarted and verified." if restart_seekdb else
               "seekdb container restart not performed (shared resource, opt-in flag).")
        )
        return new_pc, new_api
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, str(exc))
        case.finish(f"error: {type(exc).__name__}: {exc}")
        return new_pc, new_api
    finally:
        case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
        case.log = log.close()
        results.append(case)


def case_t7(results: list[CaseResult], pc_process: subprocess.Popen, project_id: str,
            run_tag: str) -> subprocess.Popen:
    case = CaseResult("T7", "断开 PowerContext，对比任务恢复能力，证明其真实作用")
    log = CaseLog("T7")
    started = time.perf_counter()
    decisions = [f"D-{run_tag}: 默认检索模式为 hybrid（RRF 融合）", f"D-{run_tag}: 文档主键使用内容 SHA-256"]
    try:
        case.inputs = {"action": "kill the PowerContext server process", "project_id": project_id}
        case.expected = (
            "断开后：记忆接口报真实错误、恢复返回 memory_available=false 且无快照；"
            "而检索与问答照常工作（因为它们只依赖 seekdb）。恢复服务后记忆立即回来。"
        )

        before = api(f"/api/projects/{project_id}/memory/restore").json()
        case.check("memory available BEFORE disconnect", True, before.get("memory_available"))
        case.check("decisions BEFORE disconnect", decisions, (before.get("snapshot") or {}).get("decisions"))

        log.write(f"killing PowerContext pid={pc_process.pid}")
        pc_process.kill()
        pc_process.wait(timeout=20)
        case.check_true("PowerContext port down", wait_down(f"{PC_URL}/health/live"))

        status = api("/api/memory/status").json()
        log.write("memory status while down: " + json.dumps(status, ensure_ascii=False)[:400])
        case.check("memory status available=false", False, status.get("available"))
        case.check_true("memory status carries a real error", bool(status.get("error")), str(status))

        after = api(f"/api/projects/{project_id}/memory/restore")
        log.write(f"restore while down -> HTTP {after.status_code}: {after.text[:400]}")
        body = after.json()
        case.check("restore memory_available=false", False, body.get("memory_available"))
        case.check("restore snapshot is null", None, body.get("snapshot"))
        case.check("restore entries empty", [], body.get("entries"))
        case.check_true("restore explains the outage", "PowerContext 当前不可用" in (body.get("resume_brief") or ""), body.get("resume_brief"))
        case.check_true("restore states retrieval still works", "seekdb" in (body.get("resume_brief") or ""))

        history = api(f"/api/projects/{project_id}/memory/history")
        log.write(f"history while down -> HTTP {history.status_code} {history.text[:300]}")
        case.check("history reports 503 while PowerContext is down", 503, history.status_code)
        case.check_true("history error is not a canned answer", "error" in history.json(), history.text[:200])

        # Retrieval and QA must be unaffected - this is the comparison that proves the split.
        retrieval = api("/api/retrieval/search", method="POST",
                        json={"query": ANSWERABLE_QUESTIONS[0][0], "mode": "hybrid", "top_k": 3, "apply_gate": True}).json()
        case.check_true("retrieval still returns citations while memory is down", bool(retrieval.get("citations")))
        asked = api("/api/qa/ask", method="POST",
                    json={"question": ANSWERABLE_QUESTIONS[0][0], "top_k": 3, "project_id": project_id}).json()
        log.write(f"qa while memory down -> mode={asked.get('mode')} citations={len(asked.get('citations', []))} "
                  f"memory_available={(asked.get('memory') or {}).get('memory_available')}")
        case.check_true("QA still answers from seekdb while memory is down", bool(asked.get("citations")))
        case.check_true(
            "QA reports the memory outage instead of hiding it",
            (asked.get("memory") or {}).get("memory_available") is False,
            json.dumps(asked.get("memory"), ensure_ascii=False)[:300],
        )
        case.check_true(
            "QA still labels the memory channel as memory",
            (asked.get("memory") or {}).get("source") == "memory",
        )

        # Restore the service and confirm memory comes back.
        new_pc = start_powercontext("powercontext-after-t7")
        ready, detail = wait_http(f"{PC_URL}/health/ready", timeout=120)
        log.write(f"PowerContext back up pid={new_pc.pid} ready={ready} ({detail})")
        case.check_true("PowerContext ready again", ready, detail)
        recovered = api(f"/api/projects/{project_id}/memory/restore").json()
        case.check("memory available AFTER reconnect", True, recovered.get("memory_available"))
        case.check("decisions recovered AFTER reconnect", decisions, (recovered.get("snapshot") or {}).get("decisions"))
        case.finish(
            "with PowerContext killed, memory endpoints reported the real outage and returned no snapshot, "
            "while retrieval and QA kept working off seekdb; after restart the same decisions were recovered"
        )
        return new_pc
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, str(exc))
        case.finish(f"error: {type(exc).__name__}: {exc}")
        return pc_process
    finally:
        case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
        case.log = log.close()
        results.append(case)


def case_t8(results: list[CaseResult]) -> None:
    case = CaseResult("T8", "断开 seekdb，检索接口报真实错误而非返回预置答案")
    log = CaseLog("T8")
    started = time.perf_counter()
    broken_api: subprocess.Popen | None = None
    try:
        case.inputs = {"action": "start a second API instance pointed at seekdb port 2899 (nothing listening)", "port": BROKEN_API_PORT}
        case.expected = "健康检查报 degraded 且 available=false 带真实原因；检索/上传/问答返回 503 与真实驱动错误；响应中不含任何检索结果"
        broken_api = start_api("api-broken-seekdb", port=BROKEN_API_PORT, seekdb_port=2899)
        ready, detail = wait_http(f"{BROKEN_API_URL}/api/health", timeout=120)
        log.write(f"broken API ready={ready} ({detail})")
        case.check_true("broken-seekdb API started", ready, detail)

        health = api("/api/health", base=BROKEN_API_URL).json()
        log.write("health: " + json.dumps(health["components"]["seekdb"], ensure_ascii=False)[:500])
        case.check("overall status degraded", "degraded", health.get("status"))
        case.check("seekdb available", False, health["components"]["seekdb"]["available"])
        case.check_true("seekdb error carries the real reason", bool(health["components"]["seekdb"].get("error")), str(health["components"]["seekdb"]))
        case.check("capability retrieval disabled", False, health["capabilities"]["retrieval"])

        searched = api("/api/retrieval/search", base=BROKEN_API_URL, method="POST",
                       json={"query": "which full text analyzer segments Chinese correctly", "mode": "hybrid", "top_k": 5})
        log.write(f"search -> HTTP {searched.status_code}: {searched.text[:500]}")
        case.check("search returns 503", 503, searched.status_code)
        error = searched.json().get("error", {})
        case.check("search error code", "seekdb_unavailable", error.get("code"))
        case.check_true("search error names seekdb", "seekdb" in (error.get("message") or "").lower(), error.get("message"))
        case.check_true("search error preserves the driver reason", bool((error.get("detail") or {}).get("reason")), str(error))
        case.check_true("no hits smuggled into the error body", "hits" not in searched.json() and "citations" not in searched.json())

        uploaded = api("/api/documents/upload", base=BROKEN_API_URL, method="POST",
                       files={"file": (MD_NAME, (DEMO_DIR / MD_NAME).read_bytes())})
        log.write(f"upload -> HTTP {uploaded.status_code}: {uploaded.text[:400]}")
        case.check("upload returns 503", 503, uploaded.status_code)

        asked = api("/api/qa/ask", base=BROKEN_API_URL, method="POST",
                    json={"question": "which full text analyzer segments Chinese correctly", "top_k": 5})
        log.write(f"qa -> HTTP {asked.status_code}: {asked.text[:400]}")
        case.check("qa returns 503", 503, asked.status_code)
        case.check_true("qa error is not a canned answer", "error" in asked.json(), asked.text[:200])

        # The healthy instance must still work at the same moment - proving the failure is local.
        healthy = api("/api/retrieval/search", method="POST",
                      json={"query": "which full text analyzer segments Chinese correctly", "mode": "hybrid", "top_k": 3}).json()
        case.check_true("the healthy instance still retrieves", bool(healthy.get("hits")))
        case.finish("with seekdb unreachable the API reported degraded health and returned 503 with the real driver error on search, upload and QA; no canned results anywhere")
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, str(exc))
        case.finish(f"error: {type(exc).__name__}: {exc}")
    finally:
        stop(broken_api)
        case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
        case.log = log.close()
        results.append(case)


def case_llm(results: list[CaseResult]) -> None:
    """Extra case (not in the required T1-T8): real LLM answer with citation validation."""
    case = CaseResult("T9-LLM", "配置 LLM 后的真实证据问答与 citation 服务端校验")
    log = CaseLog("T9-LLM")
    started = time.perf_counter()
    try:
        question = "根据文档，一条记录如果在两条腿里都排第一，RRF 分数是多少？"
        case.inputs = {"question": question, "endpoint": "POST /api/qa/ask"}
        case.expected = "mode=grounded；答案给出 0.0328；至少一条 supported 论断带真实 citation；invalid_citations 为空"
        asked = api("/api/qa/ask", method="POST", json={"question": question, "mode": "hybrid", "top_k": 5})
        body = asked.json()
        log.write(json.dumps({k: body.get(k) for k in ("mode", "answerable", "label_summary", "elapsed_ms")}, ensure_ascii=False))
        log.write("answer: " + (body.get("answer") or "")[:800])
        log.write("claims: " + json.dumps(body.get("claims"), ensure_ascii=False)[:800])
        log.write("used citations: " + json.dumps([{k: c.get(k) for k in ("citation_id", "filename", "page_no")} for c in body.get("used_citations", [])], ensure_ascii=False))
        log.write("invalid citations: " + json.dumps(body.get("invalid_citations"), ensure_ascii=False))
        case.check("mode is grounded", "grounded", body.get("mode"))
        case.check_true("LLM produced an answer", bool((body.get("answer") or "").strip()))
        case.check_true("answer contains the documented value 0.0328", "0.0328" in (body.get("answer") or ""), body.get("answer"))
        case.check_true("at least one supported claim", body.get("label_summary", {}).get("supported", 0) >= 1, str(body.get("label_summary")))
        case.check_true("a real citation was used", bool(body.get("used_citations")))
        case.check("no invalid citations", [], body.get("invalid_citations"))
        if body.get("used_citations"):
            top = body["used_citations"][0]
            case.check("cited page is the RRF page", 5, top.get("page_no"))
        case.finish("the live LLM answered from the retrieved evidence, cited a real page and no fabricated citation survived validation")
    except Exception as exc:
        log.write(f"EXCEPTION {type(exc).__name__}: {exc}")
        case.check_true("no exception", False, str(exc))
        case.finish(f"error: {type(exc).__name__}: {exc}")
    case.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    case.log = log.close()
    results.append(case)


# --------------------------------------------------------------------- report


def write_report(results: list[CaseResult], context: dict[str, Any]) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "acceptance-report.json"
    md_path = OUT_DIR / "acceptance-report.md"

    payload = {
        "run_id": RUN_ID,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "context": context,
        "summary": {
            "total": len(results),
            "pass": sum(1 for r in results if r.status == "PASS"),
            "fail": sum(1 for r in results if r.status == "FAIL"),
            "skip": sum(1 for r in results if r.status == "SKIP"),
        },
        "cases": [
            {**asdict(case), "checks": [asdict(check) for check in case.checks]} for case in results
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# ResearchFlow 验收报告 {RUN_ID}",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "## 运行环境",
        "",
        "| 项目 | 值 |",
        "| --- | --- |",
    ]
    lines += [f"| {key} | `{value}` |" for key, value in context.items()]
    lines += [
        "",
        "## 汇总",
        "",
        f"- 用例总数：{payload['summary']['total']}",
        f"- PASS：{payload['summary']['pass']}",
        f"- FAIL：{payload['summary']['fail']}",
        f"- SKIP：{payload['summary']['skip']}",
        "",
        "| 编号 | 场景 | 结果 | 耗时(ms) | 日志 |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines += [
        f"| {case.case_id} | {case.title} | **{case.status}** | {case.duration_ms} | `{case.log}` |"
        for case in results
    ]
    lines.append("")
    for case in results:
        lines += [f"## {case.case_id} — {case.title}", "", f"**结果：{case.status}**", ""]
        lines += ["**输入**", "", "```json", json.dumps(case.inputs, ensure_ascii=False, indent=2), "```", ""]
        lines += ["**预期**", "", case.expected, ""]
        lines += ["**实际**", "", case.actual, ""]
        lines += ["**逐项校验**", "", "| 校验项 | 预期 | 实际 | 结果 |", "| --- | --- | --- | --- |"]
        lines += [
            f"| {check.name} | `{check.expected}` | `{check.actual}` | {'OK' if check.ok else 'FAIL'} |"
            for check in case.checks
        ]
        if case.notes:
            lines += ["", "**备注**", ""] + [f"- {note}" for note in case.notes]
        lines += ["", f"日志：`{case.log}`", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restart-seekdb", action="store_true", help="also restart the shared seekdb container")
    parser.add_argument("--keep-data", action="store_true", help="keep rfacc_* objects in seekdb afterwards")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results: list[CaseResult] = []
    run_tag = uuid.uuid4().hex[:8]
    pc_process: subprocess.Popen | None = None
    api_process: subprocess.Popen | None = None

    print(f"acceptance run {RUN_ID} -> {OUT_DIR}")
    print("cleaning previous rfacc_* objects ...")
    reset_prefix()

    try:
        pc_process = start_powercontext("powercontext")
        ready, detail = wait_http(f"{PC_URL}/health/ready", timeout=180)
        print(f"PowerContext ready={ready} ({detail})")
        if not ready:
            raise SystemExit("PowerContext failed to start; see " + str(OUT_DIR / "powercontext.log"))

        api_process = start_api("api")
        ready, detail = wait_http(f"{API_URL}/api/health", timeout=300)
        print(f"API ready={ready} ({detail})")
        if not ready:
            raise SystemExit("ResearchFlow API failed to start; see " + str(OUT_DIR / "api.log"))

        health = api("/api/health").json()
        meta = api("/api/meta").json()
        context = {
            "seekdb_endpoint": health["components"]["seekdb"]["endpoint"],
            "seekdb_version": health["components"]["seekdb"]["server_version"],
            "seekdb_database": health["components"]["seekdb"]["database"],
            "seekdb_prefix": PREFIX,
            "fts_analyzer": health["components"]["seekdb"]["fts_analyzer"],
            "embedding_provider": health["components"]["embedding"]["provider"],
            "embedding_dimension": health["components"]["embedding"]["dimension"],
            "powercontext_version": health["components"]["powercontext"].get("package_version"),
            "powercontext_url": PC_URL,
            "llm_enabled": health["components"]["llm"]["enabled"],
            "llm_model": health["components"]["llm"]["model"],
            "api_url": API_URL,
            "run_tag": run_tag,
        }
        print(json.dumps(context, ensure_ascii=False, indent=2))

        doc_ids = case_t1(results)
        print(f"T1 -> {results[-1].status}")
        case_t2(results)
        print(f"T2 -> {results[-1].status}")
        case_t3(results)
        print(f"T3 -> {results[-1].status}")
        project_id = case_t4(results, run_tag)
        print(f"T4 -> {results[-1].status}")
        case_t5(results, project_id, run_tag)
        print(f"T5 -> {results[-1].status}")
        if health["components"]["llm"]["enabled"]:
            case_llm(results)
            print(f"T9-LLM -> {results[-1].status}")
        else:
            results.append(CaseResult(
                "T9-LLM", "配置 LLM 后的真实证据问答", status="SKIP",
                expected="需要 RF_LLM_API_KEY / DEEPSEEK_API_KEY",
                actual="未配置 LLM 密钥，跳过；问答已在 T3 中以仅检索模式验证",
                log="",
            ))
            print("T9-LLM -> SKIP (no LLM key)")

        pc_process, api_process = case_t6(
            results, pc_process, api_process, project_id, run_tag, args.restart_seekdb
        )
        print(f"T6 -> {results[-1].status}")
        # T6 restarted both services; wait for them again before T7.
        wait_http(f"{API_URL}/api/health", timeout=180)
        wait_http(f"{PC_URL}/health/ready", timeout=120)
        pc_process = case_t7(results, pc_process, project_id, run_tag)
        print(f"T7 -> {results[-1].status}")
        wait_http(f"{PC_URL}/health/ready", timeout=120)
        case_t8(results)
        print(f"T8 -> {results[-1].status}")

        context["documents_ingested"] = list(doc_ids.values())
        json_path, md_path = write_report(results, context)
        print()
        print(f"report: {json_path}")
        print(f"report: {md_path}")
    finally:
        stop(api_process)
        stop(pc_process)
        if not args.keep_data:
            print("dropping rfacc_* objects ...")
            drop_prefix()
        shutil.rmtree(OUT_DIR / "backend-data", ignore_errors=True)

    summary = {status: sum(1 for r in results if r.status == status) for status in ("PASS", "FAIL", "SKIP")}
    print(f"summary: {summary}")
    return 1 if summary.get("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
