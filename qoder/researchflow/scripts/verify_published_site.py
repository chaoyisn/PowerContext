"""Fetch the published showcase anonymously and prove it byte-matches the local build.

Nothing is pre-filled: every hash is computed from the bytes actually returned by the live
host, using a credential-free client (no cookies, no cache reuse).

Usage: python scripts/verify_published_site.py [base_url]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLIC = PROJECT_ROOT / "site" / "public"
BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://researchflow-5esfsogn38f.qoder.zone").rstrip("/")

files = sorted(p.relative_to(PUBLIC).as_posix() for p in PUBLIC.rglob("*") if p.is_file())

# Qoder Sites injects its own watermark <script> into every served HTML document. It is added
# by the platform, not shipped from site/public, so HTML is compared after removing exactly
# that block; every other asset is compared as-is.
WATERMARK = re.compile(r'<script data-qoder-watermark="v1"[^>]*>.*?</script>\s*', re.S)


def normalize(rel: str, body: bytes) -> bytes:
    if rel.endswith(".html"):
        return WATERMARK.sub("", body.decode("utf-8")).encode("utf-8")
    return body


def fetch(rel: str) -> dict:
    url = f"{BASE}/{rel}"
    req = urllib.request.Request(url, headers={
        "Cache-Control": "no-cache", "Pragma": "no-cache", "User-Agent": "researchflow-release-check/1.0",
    })
    row = {"file": rel, "url": url}
    local = (PUBLIC / rel).read_bytes()
    row["local_sha256"] = hashlib.sha256(local).hexdigest()
    row["local_bytes"] = len(local)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read()
            row["status"] = resp.status
            row["content_type"] = resp.headers.get("content-type")
            row["cache_status"] = resp.headers.get("x-cache") or resp.headers.get("cf-cache-status") or ""
            row["set_cookie"] = bool(resp.headers.get("set-cookie"))
            row["live_sha256_raw"] = hashlib.sha256(body).hexdigest()
            row["live_sha256"] = hashlib.sha256(normalize(rel, body)).hexdigest()
            row["live_bytes_raw"] = len(body)
            body = normalize(rel, body)
            row["live_bytes"] = len(body)
    except Exception as exc:  # noqa: BLE001 - report the real transport failure
        row["status"] = f"error: {type(exc).__name__}: {exc}"
    row["match"] = row.get("live_sha256") == row["local_sha256"]
    return row


with ThreadPoolExecutor(max_workers=5) as pool:
    rows = list(pool.map(fetch, files))

passed = sum(1 for r in rows if r["match"] and r["status"] == 200)
report = {
    "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "base": BASE,
    "method": "credential-free HTTP GET (urllib, no cookie jar, no-cache headers)",
    "html_normalization": "Qoder Sites injects <script data-qoder-watermark> into served HTML; "
                          "that block alone is removed before hashing, everything else is compared as-is",
    "files_total": len(rows),
    "files_match": passed,
    "rows": rows,
}
out = PROJECT_ROOT / "verification" / "site-public" / "published-site-check.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

for r in rows:
    flag = "PASS" if r["match"] and r["status"] == 200 else "FAIL"
    print(f"{flag}  {r['file']:<32} {r['status']} local={r['local_bytes']:>8}B live={r.get('live_bytes', 0):>8}B sha={str(r.get('live_sha256'))[:12]}")
print(f"\n{passed}/{len(rows)} files byte-identical to the local build")
sys.exit(0 if passed == len(rows) else 1)
