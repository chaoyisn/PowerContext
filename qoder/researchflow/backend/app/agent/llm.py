"""OpenAI-compatible LLM gateway.

When no API key is configured the gateway reports ``enabled=False`` and the QA service
switches to an explicitly labelled retrieval-only mode - it never dresses retrieval
results up as a model answer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Sequence

from ..config import Settings, get_settings
from ..errors import LLMUnavailableError
from ..logging_setup import get_logger

logger = get_logger(__name__)

_TRANSIENT_MARKERS = (
    "connection error",
    "connection reset",
    "timed out",
    "timeout",
    "temporarily",
    "service unavailable",
    "rate limit",
    "429",
    "500",
    "502",
    "503",
    "504",
)


def _is_transient(exc: Exception) -> bool:
    """Retry only transport/server hiccups - never an auth or bad-request error."""
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    elapsed_ms: float
    provider: str


class LLMGateway:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None

    @property
    def enabled(self) -> bool:
        return self.settings.llm_enabled

    def info(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "base_url": self.settings.llm_base_url,
            "model": self.settings.llm_model,
            "provider": "openai-compatible",
            "reason": None if self.enabled else "RF_LLM_API_KEY is not set",
        }

    def _ensure_client(self):
        if not self.enabled:
            raise LLMUnavailableError(
                "no LLM configured: set RF_LLM_API_KEY (and optionally RF_LLM_BASE_URL / RF_LLM_MODEL)",
                detail=self.info(),
            )
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url or None,
                timeout=self.settings.llm_timeout,
            )
        return self._client

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        json_mode: bool = True,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        client = self._ensure_client()
        kwargs: dict[str, Any] = {
            "model": self.settings.llm_model,
            "messages": list(messages),
            "temperature": self.settings.llm_temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
        }
        started = time.perf_counter()
        attempts = 3
        last_error: Exception | None = None
        response = None
        for attempt in range(attempts):
            try:
                if json_mode:
                    try:
                        response = client.chat.completions.create(
                            **kwargs, response_format={"type": "json_object"}
                        )
                    except Exception as exc:
                        if _is_transient(exc):
                            raise
                        # Not every OpenAI-compatible endpoint implements response_format.
                        logger.warning(
                            "json response_format rejected, retrying in plain mode",
                            fields={"error": f"{type(exc).__name__}: {exc}"},
                        )
                        response = client.chat.completions.create(**kwargs)
                else:
                    response = client.chat.completions.create(**kwargs)
                break
            except Exception as exc:
                last_error = exc
                if not _is_transient(exc) or attempt == attempts - 1:
                    raise LLMUnavailableError(
                        f"LLM request failed: {type(exc).__name__}: {exc}",
                        detail={
                            "model": self.settings.llm_model,
                            "attempts": attempt + 1,
                            "transient": _is_transient(exc),
                        },
                    ) from exc
                delay = 1.5 * (attempt + 1)
                logger.warning(
                    "transient LLM failure, retrying",
                    fields={"attempt": attempt + 1, "error": f"{type(exc).__name__}: {exc}", "retry_in_s": delay},
                )
                time.sleep(delay)

        if response is None:
            raise LLMUnavailableError(
                f"LLM request failed after {attempts} attempts: {last_error}",
                detail={"model": self.settings.llm_model},
            )

        choice = response.choices[0] if response.choices else None
        content = (choice.message.content or "") if choice else ""
        usage = getattr(response, "usage", None)
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "llm call finished",
            fields={
                "model": getattr(response, "model", self.settings.llm_model),
                "ms": elapsed,
                "chars": len(content),
            },
        )
        return LLMResponse(
            content=content,
            model=str(getattr(response, "model", self.settings.llm_model)),
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            elapsed_ms=elapsed,
            provider="openai-compatible",
        )
