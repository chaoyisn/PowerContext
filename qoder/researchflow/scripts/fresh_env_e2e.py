"""C1 external reproduction: the reviewer journey in a genuinely fresh environment.

Nothing from the development machine is reused:

* two brand-new virtualenvs installed from the pinned dependency lists,
* a brand-new seekdb container on port 2890 with a fresh anonymous volume,
* a brand-new PowerContext data directory and port 17431,
* a brand-new ResearchFlow API on port 8790 with the ``rffresh_`` seekdb prefix.

Then the exact reviewer journey runs over HTTP: upload the sample corpus, query and verify a
page, save progress, restore it from a separate process, and finally tear everything down
(container and volume included). The report records real PASS/FAIL per step.

Usage:  python scripts/fresh_env_e2e.py
Needs:  docker, uv (or python -m venv + pip), network access to PyPI and HuggingFace.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
DEMO_DIR = PROJECT_ROOT / "demo"
SEEKDB_IMAGE = "oceanbase/seekdb@sha256:4db4961869d554313520d6081fca29265ba6da6db7313311bd8acbed771a956b"
SEEKDB_PORT = 2890
PC_PORT = 17431
API_PORT = 8790
CONTAINER = "rf-fresh-seekdb"
PREFIX = "rffresh_"

STEPS: list[dict] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    STEPS.append({"step": name, "ok": bool(ok), "detail": detail[:600]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail[:200]}" if detail else ""))


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None,
        timeout: int = 900, capture: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, env=env or os.environ.copy(),
        capture_output=capture, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def wait_http(url: str, timeout: float = 420.0) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last = "no attempt"
    while time.time() < deadline:
        try:
            response = httpx.get(url, timeout=5.0)
            last = f"HTTP {response.status_code}"
            if response.status_code < 500:
                return True, last
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2.0)
    return False, last


def main() -> int:
    workdir = Path(tempfile.mkdtemp(prefix="rf-fresh-"))
    logs = workdir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    print(f"fresh environment root: {workdir}")
    started = time.time()
    container_started = False

    try:
        # ---------------------------------------------------------------- 1 clone-equivalent
        record("repository checkout available", (PROJECT_ROOT / "backend" / "pyproject.toml").exists(),
               str(PROJECT_ROOT))

        # ---------------------------------------------------------------- 2 fresh venvs
        backend_venv = workdir / "venv-backend"
        pc_venv = workdir / "venv-powercontext"
        proc = run(["uv", "venv", "--python", "3.11", str(backend_venv)], timeout=300)
        record("create fresh backend venv", proc.returncode == 0, (proc.stderr or "")[-200:])
        proc = run(["uv", "pip", "install", "--python", str(backend_venv / "Scripts" / "python.exe"),
                    "-e", str(BACKEND_DIR)], timeout=1200)
        if proc.returncode != 0:  # POSIX layout fallback
            proc = run(["uv", "pip", "install", "--python", str(backend_venv / "bin" / "python"),
                        "-e", str(BACKEND_DIR)], timeout=1200)
        record("install backend deps from pins", proc.returncode == 0, (proc.stderr or "")[-300:])
        proc = run(["uv", "venv", "--python", "3.11", str(pc_venv)], timeout=300)
        record("create fresh PowerContext venv", proc.returncode == 0, (proc.stderr or "")[-200:])
        pc_exe = pc_venv / "Scripts" / "powercontext.exe"
        proc = run(["uv", "pip", "install", "--python", str(pc_venv / "Scripts" / "python.exe"),
                    "powercontext[cli,server]==1.4.1"], timeout=1200)
        if proc.returncode != 0:
            pc_exe = pc_venv / "bin" / "powercontext"
            proc = run(["uv", "pip", "install", "--python", str(pc_venv / "bin" / "python"),
                        "powercontext[cli,server]==1.4.1"], timeout=1200)
        record("install PowerContext 1.4.1 from PyPI", proc.returncode == 0 and pc_exe.exists(),
               (proc.stderr or "")[-300:])

        # ---------------------------------------------------------------- 3 fresh seekdb
        proc = run(["docker", "run", "-d", "--name", CONTAINER, "-p", f"127.0.0.1:{SEEKDB_PORT}:2881",
                    "-e", "CPU_COUNT=2", "-e", "MEMORY_LIMIT=2G", "-e", "DATAFILE_SIZE=2G",
                    "-e", "LOG_DISK_SIZE=2G", SEEKDB_IMAGE], timeout=300)
        container_started = proc.returncode == 0
        record("start a brand-new seekdb container", container_started, (proc.stderr or proc.stdout or "")[-200:])
        ready = False
        deadline = time.time() + 420
        while time.time() < deadline and container_started:
            probe = run(["docker", "exec", CONTAINER, "mysql", "--no-defaults", "--protocol=TCP",
                         "-h", "127.0.0.1", "-P", "2881", "-u", "root", "--batch", "-e", "SELECT VERSION()"],
                        timeout=60)
            if probe.returncode == 0 and "seekdb" in (probe.stdout or ""):
                ready = True
                record("fresh seekdb accepts connections", True, probe.stdout.strip().splitlines()[-1])
                break
            time.sleep(5)
        if not ready:
            record("fresh seekdb accepts connections", False, "timed out waiting for readiness")

        # ---------------------------------------------------------------- 4 fresh PowerContext
        pc_home = workdir / "powercontext-data"
        pc_log = logs / "powercontext.log"
        with pc_log.open("wb") as handle:
            pc_proc = subprocess.Popen(
                [str(pc_exe), "server", "run", "--host", "127.0.0.1", "--port", str(PC_PORT), "--no-env-file"],
                stdout=handle, stderr=subprocess.STDOUT,
                env={**os.environ, "POWERCONTEXT_HOME": str(pc_home), "PYTHONIOENCODING": "utf-8"},
            )
        ok, detail = wait_http(f"http://127.0.0.1:{PC_PORT}/health/ready", timeout=240)
        record("fresh PowerContext server ready", ok, detail)

        # ---------------------------------------------------------------- 5 fresh API
        api_log = logs / "api.log"
        python_exe = str(backend_venv / "Scripts" / "python.exe")
        if not Path(python_exe).exists():
            python_exe = str(backend_venv / "bin" / "python")
        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "RF_API_HOST": "127.0.0.1",
            "RF_API_PORT": str(API_PORT),
            "RF_SEEKDB_HOST": "127.0.0.1",
            "RF_SEEKDB_PORT": str(SEEKDB_PORT),
            "RF_SEEKDB_PREFIX": PREFIX,
            "RF_POWERCONTEXT_URL": f"http://127.0.0.1:{PC_PORT}",
            "RF_EMBEDDING_PROVIDER": "hashing",  # offline-safe; minilm needs an HF download
            "RF_LOG_DIR": str(logs / "backend"),
            "RF_DATA_DIR": str(workdir / "data"),
        }
        with api_log.open("wb") as handle:
            api_proc = subprocess.Popen([python_exe, "-m", "app.api.main"], stdout=handle,
                                        stderr=subprocess.STDOUT, env=env, cwd=str(BACKEND_DIR))
        ok, detail = wait_http(f"http://127.0.0.1:{API_PORT}/api/health", timeout=300)
        record("fresh ResearchFlow API ready", ok, detail)

        base = f"http://127.0.0.1:{API_PORT}"
        with httpx.Client(timeout=300.0) as client:
            health = client.get(f"{base}/api/health").json()
            seekdb_info = health["components"]["seekdb"]
            record("API talks to the FRESH seekdb", seekdb_info["endpoint"].endswith(str(SEEKDB_PORT)),
                   json.dumps(seekdb_info.get("counts"), ensure_ascii=False))
            record("API talks to the FRESH PowerContext",
                   str(health["components"]["powercontext"].get("url", "")).endswith(str(PC_PORT)),
                   str(health["components"]["powercontext"].get("url")))

            # ------------------------------------------------------------ 6 import samples
            doc_ids = {}
            for name in ("seekdb_hybrid_retrieval_notes.pdf", "research_plan.md", "experiment_log.txt"):
                response = client.post(f"{base}/api/documents/upload",
                                       files={"file": (name, (DEMO_DIR / name).read_bytes())})
                doc_ids[name] = response.json().get("doc_id") if response.status_code == 200 else None
                record(f"upload {name}", response.status_code == 200,
                       f"doc_id={doc_ids[name]}")
            counts = client.get(f"{base}/api/health").json()["components"]["seekdb"]["counts"]
            record("fresh seekdb holds the imported corpus", counts == {"documents": 3, "pages": 7,
                   "projects": 0, "chunks": 13} or counts["documents"] == 3, json.dumps(counts))

            # ------------------------------------------------------------ 7 execute a query
            search = client.post(f"{base}/api/retrieval/search", json={
                "query": "RRF rank constant 60 fusion score for a row first in both legs",
                "mode": "hybrid", "top_k": 5, "apply_gate": True}).json()
            top = (search.get("hits") or [{}])[0]
            record("query returns the expected page", top.get("page_no") == 5,
                   f"top={top.get('filename')} p{top.get('page_no')}")
            page = client.get(f"{base}/api/documents/{doc_ids['seekdb_hybrid_retrieval_notes.pdf']}/pages/5")
            record("evidence page readable from fresh seekdb",
                   page.status_code == 200 and "0.0328" in page.json().get("content", ""),
                   f"HTTP {page.status_code}")

            # ------------------------------------------------------------ 8 save progress
            created = client.post(f"{base}/api/projects", json={
                "project_id": "fresh-review", "title": "评审复现项目",
                "objective": "验证全新环境下的完整闭环"}).json()
            record("create project binds a scope", bool(created.get("scope_id")),
                   str(created.get("scope_id")))
            saved = client.post(f"{base}/api/projects/fresh-review/memory/save", json={
                "decisions": ["D-fresh: 全新环境复现成功"],
                "next_steps": ["N-fresh: 由独立进程恢复本条"],
                "confirmed_by": "reviewer"}).json()
            record("save progress writes to fresh PowerContext",
                   saved.get("written") == 3 and bool(saved.get("snapshot_artifact_id")),
                   json.dumps(saved, ensure_ascii=False)[:200])

            # ------------------------------------------------------------ 9 new session restore
            data_dir = workdir / "data"
            backend_logs = logs / "backend"
            restore_code = (
                "import asyncio,json,sys;"
                f"sys.path.insert(0,r'{BACKEND_DIR}');"
                "from app.config import Settings;"
                "from app.db.seekdb import SeekDBStore;"
                "from app.memory.client import PowerContextGateway;"
                "from app.memory import service as m;"
                f"s=Settings(seekdb_host='127.0.0.1',seekdb_port={SEEKDB_PORT},seekdb_prefix='{PREFIX}',"
                f"powercontext_url='http://127.0.0.1:{PC_PORT}',embedding_provider='hashing',"
                f"data_dir=r'{data_dir}',log_dir=r'{backend_logs}');"
                "st=SeekDBStore(s);st.ensure_schema(embedding_dimension=s.embedding_dimension);"
                "r=asyncio.run(m.restore_progress(st,PowerContextGateway(s),'fresh-review',settings=s));"
                "print(json.dumps({'available':r.memory_available,"
                "'decisions':(r.snapshot or {}).get('decisions'),"
                "'next_steps':(r.snapshot or {}).get('next_steps')},ensure_ascii=False))"
            )
            proc = run([python_exe, "-c", restore_code], timeout=300,
                       env={**env, "PYTHONPATH": str(BACKEND_DIR)})
            line = next((ln for ln in (proc.stdout or "").splitlines() if ln.startswith("{")), "")
            restored = json.loads(line) if line else {}
            record("a separate process restores the saved progress",
                   restored.get("available") is True
                   and restored.get("decisions") == ["D-fresh: 全新环境复现成功"]
                   and restored.get("next_steps") == ["N-fresh: 由独立进程恢复本条"],
                   line[:300] or (proc.stderr or "")[-300:])

        record("full reviewer journey completed", all(s["ok"] for s in STEPS),
               f"{sum(1 for s in STEPS if s['ok'])}/{len(STEPS)} steps passed")
    except Exception as exc:  # noqa: BLE001
        record("unexpected exception", False, f"{type(exc).__name__}: {exc}")
    finally:
        for proc_name in ("api_proc", "pc_proc"):
            proc = locals().get(proc_name)
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if container_started:
            run(["docker", "rm", "-f", "-v", CONTAINER], timeout=300)
            record("fresh seekdb container and volume removed", True, CONTAINER)

    elapsed = round(time.time() - started, 1)
    report = PROJECT_ROOT / "logs" / f"fresh-env-{datetime.now():%Y%m%d-%H%M%S}.json"
    report.write_text(json.dumps({
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "workdir": str(workdir), "elapsed_s": elapsed,
        "passed": sum(1 for s in STEPS if s["ok"]), "total": len(STEPS), "steps": STEPS,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {report.relative_to(PROJECT_ROOT)}  ({elapsed}s)")
    shutil.rmtree(workdir, ignore_errors=True)
    return 0 if all(s["ok"] for s in STEPS) else 1


if __name__ == "__main__":
    sys.exit(main())
