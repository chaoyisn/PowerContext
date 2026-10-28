"""Domain exceptions. Nothing is swallowed: every failure surfaces with a real reason."""

from __future__ import annotations


class ResearchFlowError(Exception):
    """Base class. ``status_code`` drives the HTTP mapping in api/errors.py."""

    status_code = 500
    error_code = "internal_error"

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class DependencyUnavailableError(ResearchFlowError):
    """A backing service (seekdb / PowerContext / LLM) could not be reached."""

    status_code = 503


class SeekDBUnavailableError(DependencyUnavailableError):
    error_code = "seekdb_unavailable"


class PowerContextUnavailableError(DependencyUnavailableError):
    error_code = "powercontext_unavailable"


class LLMUnavailableError(DependencyUnavailableError):
    error_code = "llm_unavailable"


class NotFoundError(ResearchFlowError):
    status_code = 404
    error_code = "not_found"


class UnsupportedFileTypeError(ResearchFlowError):
    status_code = 415
    error_code = "unsupported_file_type"


class FileTooLargeError(ResearchFlowError):
    status_code = 413
    error_code = "file_too_large"


class DocumentParseError(ResearchFlowError):
    status_code = 422
    error_code = "document_parse_error"


class RequestValidationError(ResearchFlowError):
    status_code = 422
    error_code = "validation_error"
