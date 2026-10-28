"""PowerContext gateway: connection lifecycle plus honest availability reporting.

A PowerContext outage must never be papered over - callers get
``PowerContextUnavailableError`` (mapped to HTTP 503) so acceptance test T7 can show the
difference between "memory available" and "memory down" while retrieval keeps working.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from ..config import Settings, get_settings
from ..errors import PowerContextUnavailableError
from ..logging_setup import get_logger

logger = get_logger(__name__)


class PowerContextGateway:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def url(self) -> str:
        return self.settings.powercontext_url

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        try:
            from powercontext.client import PowerContextClient
        except ImportError as exc:  # pragma: no cover
            raise PowerContextUnavailableError(
                "the powercontext[client] package is not installed", detail={"reason": str(exc)}
            ) from exc
        try:
            async with PowerContextClient(
                self.url,
                token=self.settings.powercontext_token or None,
                timeout=self.settings.powercontext_timeout,
            ) as client:
                yield client
        except PowerContextUnavailableError:
            raise
        except Exception as exc:
            raise PowerContextUnavailableError(
                f"PowerContext request to {self.url} failed",
                detail={"reason": f"{type(exc).__name__}: {exc}"},
            ) from exc

    async def health(self) -> dict[str, Any]:
        started = time.time()
        try:
            async with self.session() as client:
                live = await client.get_liveness()
                info = await client.get_server_info()
                ready = await client.get_readiness()
                payload = info.model_dump() if hasattr(info, "model_dump") else {}
                return {
                    "available": True,
                    "url": self.url,
                    "liveness": getattr(live, "status", "unknown"),
                    "readiness": getattr(ready, "status", "unknown"),
                    "package_version": payload.get("package_version"),
                    "api_contract_version": payload.get("api_contract_version"),
                    "server_id": payload.get("server_id"),
                    "database_ready": (ready.checks or {}).get("database")
                    if hasattr(ready, "checks") and ready.checks
                    else None,
                    "latency_ms": round((time.time() - started) * 1000, 2),
                }
        except Exception as exc:
            return {
                "available": False,
                "url": self.url,
                "error": f"{type(exc).__name__}: {exc}",
                "latency_ms": round((time.time() - started) * 1000, 2),
            }
