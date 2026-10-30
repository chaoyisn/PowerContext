"""Create and verify a source/evidence ZIP without local weights, data, or credentials."""
from hashlib import sha256
from pathlib import Path
import argparse
import json
import os
import re
import tempfile
import zipfile

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--output", default="EdgeSeek-V4.zip", help="ZIP filename in deliverables")
parser.add_argument("--final-form", help="optional local form to include as FINAL_FORM.md")
args = parser.parse_args()
if Path(args.output).name != args.output or not args.output.endswith(".zip"):
    parser.error("--output must be a ZIP filename")
output = root / "deliverables" / args.output
manifest_path = root / "deliverables" / "package-manifest.json"
root_files = {".env.example", "README.md", "package.json", "package-lock.json", "model.json", "tsconfig.json", "vite.config.ts", "playwright.config.ts", "FINAL_SUBMISSION.md", "FORM_FIELDS.md", "FILES_TO_UPLOAD.md", "FINAL_AUDIT.md"}
source_dirs = {"frontend", "server", "scripts", "tests", "docs", "benchmark"}
forbidden = {"node_modules", ".git", ".data", "dist", "test-results", "playwright-report", "deliverables", "public"}
allowed_logs = {"api-sql-trace.log", "post-queue-build.log", "post-queue-unit.log", "queue-integration.log", "final-e2e.log", "disconnect-queue-final.log", "final-queue-e2e.log", "v41-build.log", "v41-unit.log", "v41-integration.log", "v41-chrome-recovery.log", "v41-edge-recovery.log"}
v3_quality = {"quality-int8.json", "quality-fp32.json", "quality-fp16.json"}
secret_pattern = re.compile(rb"(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|C:\\{1,2}Users\\{1,2})", re.IGNORECASE)

files = []
paths = []
for directory, subdirs, filenames in os.walk(root, followlinks=False):
    subdirs[:] = [name for name in subdirs if name not in forbidden and not (Path(directory) / name).is_symlink()]
    paths.extend(Path(directory) / name for name in filenames)
for path in paths:
    if not path.is_file() or path.is_symlink():
        continue
    rel = path.relative_to(root)
    if any(part in forbidden for part in rel.parts) or path.suffix.lower() in {".onnx", ".wasm", ".zip"} or path.name == ".env":
        continue
    if len(rel.parts) == 1:
        if rel.name not in root_files:
            continue
    elif rel.parts[0] not in source_dirs:
        continue
    if rel.parts[:2] == ("benchmark", "results"):
        if len(rel.parts) < 4 or not (rel.parts[2] == "v4" or (rel.parts[2] == "v3" and path.name in v3_quality)):
            continue
        if path.suffix.lower() not in {".json", ".png"} and path.name not in allowed_logs:
            continue
    data = path.read_bytes()
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg"} and secret_pattern.search(data):
        raise SystemExit(f"Potential credential or user profile path in {rel}; inspect before packaging")
    files.append((rel, data))

if args.final_form:
    form = Path(args.final_form).resolve()
    if form.parent != (root / "deliverables").resolve() or form.name != "FINAL_FORM.md":
        parser.error("--final-form must point to deliverables/FINAL_FORM.md")
    data = form.read_bytes()
    if secret_pattern.search(data):
        raise SystemExit("Potential credential or user profile path in FINAL_FORM.md")
    files.append((Path("FINAL_FORM.md"), data))

output.parent.mkdir(parents=True, exist_ok=True)
temporary = output.with_suffix(".zip.tmp")
with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for rel, data in sorted(files):
        archive.writestr(f"EdgeSeek/{rel.as_posix()}", data)

with zipfile.ZipFile(temporary) as archive, tempfile.TemporaryDirectory(prefix="edgeseek-v4-check-") as directory:
    if archive.testzip() is not None:
        raise SystemExit("ZIP CRC verification failed")
    names = archive.namelist()
    if any(not name.startswith("EdgeSeek/") or ".." in Path(name).parts for name in names):
        raise SystemExit("Unsafe ZIP member path")
    archive.extractall(directory)
    for rel, data in files:
        extracted = Path(directory) / "EdgeSeek" / rel
        if sha256(extracted.read_bytes()).digest() != sha256(data).digest():
            raise SystemExit(f"Extracted file mismatch: {rel}")

temporary.replace(output)
manifest = {"zip": output.name, "bytes": output.stat().st_size, "sha256": sha256(output.read_bytes()).hexdigest(), "fileCount": len(files), "crcAndExtractionVerified": True, "generation": f"python scripts/package-v4.py --output {output.name}" + (" --final-form deliverables/FINAL_FORM.md" if args.final_form else ""), "excluded": ["model and WASM binaries", "node_modules", "database data", "local .env", "cache", "Git", "historical evidence except three V3 quality records", "most raw logs"], "files": [{"path": rel.as_posix(), "bytes": len(data), "sha256": sha256(data).hexdigest()} for rel, data in sorted(files)]}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
print(json.dumps({key: manifest[key] for key in ("zip", "bytes", "sha256", "fileCount", "crcAndExtractionVerified")}, ensure_ascii=False))
