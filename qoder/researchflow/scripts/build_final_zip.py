"""Build and self-verify the contest submission ZIP.

The archive is written outside the git worktree on purpose (default
``D:/OceanBase/deliverables/researchflow-final/``), so a 6.5 MB video and a set of run
screenshots can never be committed by accident.  Nothing is claimed here that the script
does not actually check: it (1) collects the explicit include list, (2) scans every member
for credentials and local user paths, (3) writes the archive, then (4) extracts it into a
fresh temporary directory and compares every file byte-for-byte against the source tree.

Usage:  python scripts/build_final_zip.py [output.zip]
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = Path("D:/OceanBase/deliverables/researchflow-final/ResearchFlow-Qoder-Final.zip")
TOP = "ResearchFlow"

# What a reviewer needs to re-run and audit the work: sources, the demo corpus, the showcase
# site, the evidence produced by real runs, and the submission package itself.
INCLUDE_FILES = [
    "README.md", "RUN.md", "VERIFICATION.md", "ARCHITECTURE.md", "SECURITY.md",
    "BENCHMARK.md", "SUBMISSION.md", "DEMO_SCRIPT.md", "QODER_LOG.md", "PLAN.md",
    "SITE_DEPLOYMENT.md", "PUSH_PRECHECK.md", ".env.example",
    "backend/pyproject.toml", "frontend/index.html", "frontend/package.json",
    "frontend/tsconfig.json", "frontend/tsconfig.node.json", "frontend/vite.config.ts",
    "submission-package/FORM_FIELDS.md", "submission-package/FILES_TO_UPLOAD.md",
    "submission-package/FINAL_AUDIT.md", "submission-package/MANUAL_ONLY.md",
]
INCLUDE_DIRS = [
    "backend/app", "backend/tests", "frontend/src", "scripts", "demo",
    "site/public", "verification", "submission-package",
]
# logs/ stays out except the pytest tail the video card quotes: the other run transcripts
# embed the local machine's user-home paths, which have no business in a submitted archive.
INCLUDE_LOGS = ["logs/pytest-20261029T140102.log"]

SKIP_DIRS = {"__pycache__", "node_modules", ".venv", ".venv-powercontext", "build", "dist",
             ".git", ".pytest_cache", ".vite", "preview", "preview-local",
             "services", "site"}
# Only meaningful at the repository root: ``site/public/data/`` is the showcase's own
# evidence export and must ship, while ``data/`` is runtime state and must not.
SKIP_ROOT_PREFIX = ("data/", "uploads/", "logs/", "backend/data/")
SKIP_SUFFIX = {".pyc", ".pyo", ".db", ".db-wal", ".wal", ".shm", ".env", ".qoder.site"}
# This manifest and the checksum sidecar describe the archive, so they live *beside* it:
# an archive cannot carry its own checksum, and a stale copy inside would be misleading.
SKIP_NAMES = {".env", ".DS_Store", "final-zip-manifest.json", "SHA256SUMS.txt"}
# Screenshots and the finished video are our own binary artefacts; running credential regexes
# over them only produces false positives, so the scan covers text-ish members.
BINARY_SUFFIX = {".png", ".jpg", ".jpeg", ".mp4", ".webm", ".gif", ".ico", ".woff", ".woff2",
                 ".zip", ".ttf", ".ass", ".webp"}

# Evidence we keep in the repository but do not ship inside the archive, with the reason.
# Never rewritten — excluding is the only honest option for a real run transcript.
PRIVACY_SKIPPED = {
    "verification/browser-acceptance/interactions-run.log":
        "line 2 records the local Chromium install path, which contains the Windows user folder",
}

# A full account UID is personal; the release/action UUIDs elsewhere are platform bookkeeping
# and are deliberately not matched here.
SCANNERS = [
    ("openai-style key", re.compile(rb"sk-[A-Za-z0-9]{20,}")),
    ("generic api key assignment", re.compile(rb"(?i)api[_-]?key['\"]?\s*[=:]\s*['\"]?[A-Za-z0-9]{20,}")),
    ("generic secret assignment", re.compile(rb"(?i)(secret|password|token)['\"]?\s*[=:]\s*['\"][^'\"]{8,}['\"]")),
    ("bearer token", re.compile(rb"(?i)bearer\s+[A-Za-z0-9._-]{24,}")),
    ("private key block", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("full qoder uid", re.compile(rb"01a175e3-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")),
    ("local user path", re.compile(rb"(?i)(c:\\+users\\+|/home/)[a-z0-9_.-]{3,}")),
]


def walk(rel: str) -> list[Path]:
    base = ROOT / rel
    if base.is_file():
        return [base]
    out: list[Path] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        parts = p.relative_to(base).parts[:-1]
        if any(part in SKIP_DIRS for part in parts):
            continue
        if p.name in SKIP_NAMES or p.suffix in SKIP_SUFFIX:
            continue
        out.append(p)
    return out


def collect() -> list[tuple[Path, str]]:
    members: list[tuple[Path, str]] = []
    seen: set[str] = set()
    for rel in INCLUDE_FILES:
        if not (ROOT / rel).is_file():
            raise SystemExit(f"required member missing: {rel}")
    for rel in INCLUDE_DIRS + INCLUDE_FILES:
        for path in walk(rel):
            arc = f"{TOP}/{path.relative_to(ROOT).as_posix()}"
            rel_posix = path.relative_to(ROOT).as_posix()
            if rel_posix in PRIVACY_SKIPPED or rel_posix.startswith(SKIP_ROOT_PREFIX) or arc in seen:
                continue
            seen.add(arc)
            members.append((path, arc))
    for rel in INCLUDE_LOGS:
        path = ROOT / rel
        arc = f"{TOP}/evidence-logs/{Path(rel).name}"
        assert path.is_file(), f"missing {rel}"
        members.append((path, arc))
    for must in ("site/public/index.html", "site/public/data/evidence.json",
                 "submission-package/demo/researchflow-demo.mp4",
                 "verification/acceptance-run/acceptance-report.json",
                 "verification/browser-acceptance/interactions.json"):
        if f"{TOP}/{must}" not in {a for _, a in members}:
            raise SystemExit(f"required member not collected: {must}")
    return sorted(members, key=lambda m: m[1])


def scan(members: list[tuple[Path, str]]) -> list[str]:
    problems: list[str] = []
    scanned = 0
    for path, arc in members:
        if path.suffix.lower() in BINARY_SUFFIX:
            continue
        scanned += 1
        body = path.read_bytes()
        for label, pattern in SCANNERS:
            hit = pattern.search(body)
            if hit:
                problems.append(f"{arc}: {label} -> {hit.group()[:60]!r}")
    print(f"scanned {scanned} text members ({len(members) - scanned} binary members skipped)")
    return problems


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    members = collect()
    print(f"collected {len(members)} files, "
          f"{sum(p.stat().st_size for p, _ in members):,} raw bytes")

    problems = scan(members)
    for line in problems:
        print("  SCAN HIT", line)
    if problems:
        print("REFUSING TO WRITE THE ARCHIVE — resolve the hits above first.")
        return 1
    print("secret / local-path scan: 0 hits")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path, arc in members:
            zf.write(path, arc)
    size = out.stat().st_size
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    sidecar = out.with_suffix(".zip.sha256")
    # LF, not CRLF: ``sha256sum -c`` on the delivered file chokes on a trailing \r.
    sidecar.write_bytes(f"{digest}  {out.name}\n".encode("utf-8"))
    print(f"wrote {out}  {size:,} bytes  sha256={digest}")
    print(f"sidecar {sidecar}")

    # ---- extract into a clean temporary directory and compare every byte
    with tempfile.TemporaryDirectory(prefix="rf-zipcheck-") as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(out) as zf:
            bad = zf.testzip()
            assert bad is None, f"corrupt member {bad}"
            zf.extractall(root)
        extracted = sorted(p for p in root.rglob("*") if p.is_file())
        missing, differing = [], []
        for path, arc in members:
            target = root / arc
            if not target.is_file():
                missing.append(arc)
            elif target.read_bytes() != path.read_bytes():
                differing.append(arc)
        extra = [p.relative_to(root).as_posix() for p in extracted
                 if p.relative_to(root).as_posix() not in {a for _, a in members}]
        print(f"extract check: {len(extracted)} files on disk vs {len(members)} listed")
        print(f"  missing={len(missing)} differing={len(differing)} unexpected={len(extra)}")
        for arc in (missing + differing + extra)[:10]:
            print("   !", arc)
        ok = not (missing or differing or extra)

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "archive": str(out), "archive_bytes": size, "archive_sha256": digest,
        "members": len(members), "raw_bytes": sum(p.stat().st_size for p, _ in members),
        "compression_ratio": round(size / sum(p.stat().st_size for p, _ in members), 4),
        "scan_hits": problems, "extract_ok": ok,
        "privacy_skipped": PRIVACY_SKIPPED,
        "tree": {},
    }
    for arc, path in {a: p for p, a in members}.items():
        parts = arc.split("/")
        key = "/".join(parts[:2]) if len(parts) > 2 else parts[0]
        entry = report["tree"].setdefault(key, {"files": 0, "bytes": 0})
        entry["files"] += 1
        entry["bytes"] += path.stat().st_size
    manifest = ROOT / "submission-package" / "final-zip-manifest.json"
    body = json.dumps(report, ensure_ascii=False, indent=2)
    manifest.write_text(body, encoding="utf-8")
    # Keep a copy beside the archive: the ZIP deliberately does not contain its own checksum
    # manifest, so the delivered folder must carry it.
    beside = out.with_name("final-zip-manifest.json")
    beside.write_text(body, encoding="utf-8")
    print(f"manifest -> {manifest.relative_to(ROOT).as_posix()} and {beside}")

    # The delivery folder is self-contained: reviewers get the finished video beside the
    # archive too, so a platform that only accepts a media upload never has to reach into the repo.
    video = ROOT / "submission-package" / "demo" / "researchflow-demo.mp4"
    if video.is_file():
        import shutil
        target = out.with_name(video.name)
        if not target.is_file() or target.stat().st_size != video.stat().st_size:
            shutil.copyfile(video, target)
        print(f"video copy -> {target} ({target.stat().st_size:,} B)")

    print("ZIP OK" if ok else "ZIP INCOMPLETE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
