"""MiniMax coding agent.

The agent receives the real development context built from seekdb and
PowerContext and asks MiniMax for a unified diff that implements the
specification. The returned patch is applied to the working tree with
:mod:`patch`, so the resulting source change is exactly what the model
produced.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config import Settings, load_settings
from .context_builder import DevelopmentContext

SYSTEM_PROMPT = """You are a careful software engineer implementing a specification.

You receive a development context that contains:
- the applicable specification, including its requirement id and acceptance criteria;
- the exact code files and symbols that may be changed;
- the target functional tests and the regression tests that must keep passing.

Rules:
1. Only modify the files listed under "code" in the context.
2. Implement the specification exactly; keep every documented compatibility constraint.
3. Do not modify any test file, and do not change test assertions.
4. Respond with a single unified diff and nothing else. No prose, no code fences.

The unified diff must use the real repository-relative paths and the real current
line numbers, so that it applies cleanly with `git apply`."""


class MiniMaxError(RuntimeError):
    """Raised when the MiniMax request cannot produce a usable patch."""


@dataclass
class MiniMaxResult:
    """The evidence of one real MiniMax call."""

    model: str
    base_url: str
    request_id: str | None
    input_tokens: int
    output_tokens: int
    elapsed_seconds: float
    raw_response: str
    patch: str
    applied: bool
    applied_files: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "base_url": self.base_url,
            "request_id": self.request_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "applied": self.applied,
            "applied_files": self.applied_files,
            "error": self.error,
            "patch": self.patch,
        }


def extract_patch(text: str) -> str:
    """Pull the unified diff out of a model response."""

    fenced = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", text, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
        if "diff --git" in candidate or "--- " in candidate:
            return candidate.strip("\n") + "\n"
    start = text.find("diff --git")
    if start == -1:
        start = text.find("--- ")
    if start == -1:
        return ""
    return text[start:].strip("\n") + "\n"


class MiniMaxAgent:
    """Call the MiniMax model and apply the patch it returns."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def _prompt(self, context: DevelopmentContext) -> str:
        payload = {
            "task": context.task,
            "task_id": context.task_id,
            "specifications": [
                {
                    "spec_id": item["spec_id"],
                    "version": item["version"],
                    "revision": item["revision"],
                    "title": item["title"],
                    "status": item["status"],
                    "content": item["content"],
                }
                for item in context.specifications
            ],
            "code": [
                {
                    "file_path": item["file_path"],
                    "qualified_name": item["qualified_name"],
                    "signature": item["signature"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "content": item["content"],
                }
                for item in context.code
            ],
            "tests": [
                {
                    "file_path": item["file_path"],
                    "test_name": item["test_name"],
                    "test_kind": item["test_kind"],
                    "content": item["content"],
                }
                for item in context.tests
            ],
            "completed_items": context.state.get("completed", []),
            "todo_items": context.state.get("todos", []),
            "verification_results": context.state.get("verifications", []),
        }
        return (
            "Implement the task using the development context below.\n\n"
            "DEVELOPMENT CONTEXT (JSON):\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n\nReturn the unified diff now."
        )

    def run(self, context: DevelopmentContext, *, apply: bool = True) -> MiniMaxResult:
        """Ask MiniMax for a patch and apply it to the repository."""

        started = time.monotonic()
        prompt = self._prompt(context)
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self.settings.minimax_api_key,
            "authorization": f"Bearer {self.settings.minimax_api_key}",
        }
        body = {
            "model": self.settings.minimax_model,
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}],
            "system": SYSTEM_PROMPT,
        }
        raw = ""
        usage: dict[str, Any] = {}
        request_id: str | None = None
        error: str | None = None
        try:
            with httpx.Client(timeout=self.settings.minimax_timeout) as client:
                response = client.post(
                    f"{self.settings.minimax_base_url.rstrip('/')}/v1/messages",
                    headers=headers,
                    json=body,
                )
            request_id = response.headers.get("x-request-id")
            if response.status_code >= 400:
                error = f"HTTP {response.status_code}: {response.text[:600]}"
            else:
                payload = response.json()
                usage = payload.get("usage", {}) or {}
                raw = "".join(
                    block.get("text", "")
                    for block in payload.get("content", [])
                    if block.get("type") == "text"
                )
                if not raw:
                    raw = json.dumps(payload, ensure_ascii=False)
        except Exception as exception:
            error = f"{type(exception).__name__}: {exception}"

        elapsed = time.monotonic() - started
        patch = extract_patch(raw) if raw else ""
        applied = False
        applied_files: list[str] = []
        if error is None and not patch:
            error = "the model response did not contain a unified diff"

        if error is None and apply and patch:
            applied, applied_files = self._apply_patch(patch, context)
            if not applied:
                error = "the returned patch did not apply cleanly"

        return MiniMaxResult(
            model=self.settings.minimax_model,
            base_url=self.settings.minimax_base_url,
            request_id=request_id,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            elapsed_seconds=elapsed,
            raw_response=raw,
            patch=patch,
            applied=applied,
            applied_files=applied_files,
            error=error,
        )

    @staticmethod
    def _apply_patch(patch: str, context: DevelopmentContext) -> tuple[bool, list[str]]:
        """Apply the patch with git so the change shows up in the real diff."""

        import subprocess

        root = Path(context.retrieval.get("repository_root", "")) if context.retrieval else Path()
        if not root or not root.exists():
            root = Path.cwd()
        completed = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            input=patch.encode("utf-8"),
            cwd=str(root),
            capture_output=True,
        )
        if completed.returncode != 0:
            completed = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "--3way", "-"],
                input=patch.encode("utf-8"),
                cwd=str(root),
                capture_output=True,
            )
        if completed.returncode != 0:
            return False, []
        names = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        return True, [line for line in names.stdout.splitlines() if line]
