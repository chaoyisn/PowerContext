"""Content hashing and upload safety helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath, PureWindowsPath

from ..config import Settings
from ..errors import FileTooLargeError, UnsupportedFileTypeError

_UNSAFE = re.compile(r"[\x00-\x1f]")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_filename(raw: str, *, fallback: str = "upload") -> str:
    """Strip any directory component and control characters.

    Uploads are stored under a content-addressed name, so this is defence in depth
    against path traversal (``../../etc/passwd``) and shell-hostile names.
    """
    name = (raw or "").replace("\\", "/").strip()
    for path_type in (PurePosixPath, PureWindowsPath):
        try:
            name = path_type(name).name
        except Exception:
            pass
    name = _UNSAFE.sub("", name)
    name = name.strip(". ")
    if not name or name in {".", ".."}:
        return fallback
    return name[:200]


def content_type_for(filename: str) -> str:
    ext = PurePosixPath(filename.lower()).suffix
    if ext == ".pdf":
        return "pdf"
    if ext in {".md", ".markdown"}:
        return "markdown"
    if ext == ".txt":
        return "text"
    raise UnsupportedFileTypeError(
        f"unsupported file extension '{ext or '(none)'}'",
        detail={"allowed": sorted({".pdf", ".md", ".markdown", ".txt"})},
    )


def validate_upload(filename: str, data: bytes, settings: Settings) -> str:
    """Validate extension, declared-allowed set and size. Returns the content type."""
    clean = safe_filename(filename)
    ext = PurePosixPath(clean.lower()).suffix
    if ext not in settings.allowed_extensions:
        raise UnsupportedFileTypeError(
            f"extension '{ext or '(none)'}' is not in the allow list",
            detail={"allowed": sorted(settings.allowed_extensions), "filename": clean},
        )
    if len(data) > settings.upload_max_bytes:
        raise FileTooLargeError(
            f"file is {len(data)} bytes, limit is {settings.upload_max_bytes}",
            detail={"size_bytes": len(data), "limit_bytes": settings.upload_max_bytes},
        )
    if not data:
        raise UnsupportedFileTypeError("uploaded file is empty", detail={"filename": clean})
    return content_type_for(clean)
