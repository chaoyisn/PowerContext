"""Structured logging: one JSON object per line, correlated by request_id."""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from .config import get_settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
            + f".{int(record.msecs):03d}",
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "message": record.getMessage(),
        }
        extra = getattr(record, "rf_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        extra = getattr(record, "rf_fields", None)
        suffix = ""
        if isinstance(extra, dict) and extra:
            suffix = " " + " ".join(f"{k}={v}" for k, v in extra.items())
        base = f"{record.levelname:<7} {record.name}: {record.getMessage()}{suffix}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


class StructuredAdapter(logging.LoggerAdapter):
    def process(self, msg: Any, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        fields = kwargs.pop("fields", None)
        if fields:
            kwargs["extra"] = {"rf_fields": fields}
        return msg, kwargs


ROOT_LOGGER_NAME = "researchflow"


def get_logger(name: str) -> StructuredAdapter:
    """Return a logger under the ``researchflow`` namespace so setup_logging() applies.

    Module names are ``app.retrieval.service`` etc.; without this prefix they would attach
    to the root logger and every structured record would be dropped.
    """
    suffix = name.removeprefix("app.")
    return StructuredAdapter(logging.getLogger(f"{ROOT_LOGGER_NAME}.{suffix}"), {})


def setup_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.setLevel(level)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(ConsoleFormatter())
    console.setLevel(level)
    root.addHandler(console)

    log_file: Path = settings.log_path / "researchflow.log"
    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        file_handler.setLevel(level)
        root.addHandler(file_handler)
    except OSError as exc:  # pragma: no cover - read-only filesystem
        root.warning("file logging disabled: %s", exc)

    logging.getLogger("researchflow").info(
        "logging configured", extra={"rf_fields": {"level": settings.log_level, "file": str(log_file)}}
    )
    _CONFIGURED = True
