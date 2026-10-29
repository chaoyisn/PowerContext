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
            "raw_response": self.raw_response,
        }


def extract_patch(text: str) -> str:
    """Pull the unified diff out of a model response."""

    fenced = re.search(r"```(?:diff|patch)?\s*\n(.*?)```", text, re.DOTALL)
    candidates: list[str] = []
    if fenced:
        candidates.append(fenced.group(1))
    for marker in ("*** Begin Patch", "*** End Patch"):
        pass
    if "*** Begin Patch" in text:
        block = text.split("*** Begin Patch", 1)[1]
        if "*** End Patch" in block:
            block = block.split("*** End Patch", 1)[0]
        candidates.append(block)
    start = text.find("diff --git")
    if start != -1:
        candidates.append(text[start:])
    elif text.find("--- ") != -1:
        candidates.append(text[text.find("--- ") :])

    for candidate in candidates:
        cleaned = _strip_patch_markers(candidate)
        if "diff --git" in cleaned or "--- " in cleaned:
            return cleaned
    return ""


def _strip_patch_markers(text: str) -> str:
    """Remove the fence and patch-tool markers that surround a unified diff."""

    cleaned = text.replace("*** Begin Patch", "").replace("*** End Patch", "")
    cleaned = re.sub(r"^```[a-zA-Z]*\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^```\s*$", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip("\n")
    if not cleaned:
        return ""
    return cleaned + "\n"


class MiniMaxAgent:
    """Call the MiniMax model and apply the patch it returns."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def _prompt(self, context: DevelopmentContext) -> str:
        repository_root = Path(context.retrieval.get("repository_root", "") or Path.cwd())
        code_payload = []
        for item in context.code:
            # The diff must apply against the real file, so the model gets the
            # current file text next to the symbol the database located.
            file_text = ""
            for candidate in (
                repository_root / item["file_path"],
                repository_root.parent / item["file_path"],
                Path(item["source_path"]),
            ):
                if candidate.is_file():
                    file_text = candidate.read_text(encoding="utf-8")
                    break
            code_payload.append(
                {
                    "file_path": item["file_path"],
                    "repository_path": self._repository_path(repository_root, item["file_path"]),
                    "qualified_name": item["qualified_name"],
                    "signature": item["signature"],
                    "start_line": item["start_line"],
                    "end_line": item["end_line"],
                    "symbol_content": item["content"],
                    "file_content": file_text,
                }
            )
        payload = {
            "task": context.task,
            "task_id": context.task_id,
            "repository_root": str(repository_root),
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
            "code": code_payload,
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

    @staticmethod
    def _repository_path(repository_root: Path, file_path: str) -> str:
        """Return the path of a material relative to the git repository root."""

        candidate = repository_root / file_path
        if candidate.exists():
            return candidate.relative_to(repository_root).as_posix()
        return Path(file_path).as_posix()

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
    def _normalize_paths(patch: str, repository_root: Path, module_root: Path) -> str:
        """Rewrite diff paths to the real repository-relative paths.

        The model receives module-relative paths such as ``sample/taskmanager.py``.
        Git needs the path relative to the repository root, so the module
        directory prefix is restored when it is missing.
        """

        if not module_root.name:
            return patch
        try:
            prefix = module_root.relative_to(repository_root).as_posix() + "/"
        except ValueError:
            return patch

        def with_prefix(path: str) -> str:
            """Add the module prefix to a diff path, keeping its a/ or b/ marker."""

            for marker in ("a/", "b/"):
                if path.startswith(marker):
                    return marker + prefix + path[len(marker) :]
            return prefix + path

        def rewrite(match: re.Match[str]) -> str:
            body = match.group(2)
            if body.startswith(prefix) or body.startswith(("a/" + prefix, "b/" + prefix)):
                return match.group(0)
            return f"{match.group(1)}{with_prefix(body)}"

        patch = re.sub(r"(--- a/|\+\+\+ b/)([^\t\n]+)", rewrite, patch)

        def rewrite_header(match: re.Match[str]) -> str:
            first, second = match.group(1), match.group(2)
            new_first = first if first.startswith(prefix) else with_prefix(first)
            new_second = second if second.startswith(prefix) else with_prefix(second)
            return f"diff --git {new_first} {new_second}"

        return re.sub(r"diff --git (\S+) (\S+)", rewrite_header, patch)

    @staticmethod
    def _patch_targets(patch: str) -> list[str]:
        """Return the repository-relative files the patch touches."""

        targets: list[str] = []
        for match in re.finditer(r"^diff --git a/(\S+) b/(\S+)", patch, flags=re.MULTILINE):
            target = match.group(2)
            if target not in targets:
                targets.append(target)
        if targets:
            return targets
        for match in re.finditer(r"^\+\+\+ b/(\S+)", patch, flags=re.MULTILINE):
            target = match.group(1).strip()
            if target not in targets and target != "/dev/null":
                targets.append(target)
        return targets

    @staticmethod
    def _apply_patch(patch: str, context: DevelopmentContext) -> tuple[bool, list[str]]:
        """Apply the patch with git so the change shows up in the real diff."""

        import subprocess

        repository_root = Path(context.retrieval.get("repository_root", "")) or Path.cwd()
        module_root = Path(context.retrieval.get("module_root", "") or "")
        if module_root:
            patch = MiniMaxAgent._normalize_paths(patch, repository_root, module_root)
        attempts = (
            ["git", "apply", "--whitespace=nowarn", "--recount", "-"],
            ["git", "apply", "--whitespace=nowarn", "--recount", "--3way", "-"],
            ["git", "apply", "--whitespace=nowarn", "-"],
            ["git", "apply", "--whitespace=nowarn", "--3way", "-"],
        )
        for command in attempts:
            completed = subprocess.run(
                command,
                input=patch.encode("utf-8"),
                cwd=str(repository_root),
                capture_output=True,
            )
            if completed.returncode == 0:
                # Report the files the patch itself touches, not every file that
                # happens to differ in the working tree.
                return True, MiniMaxAgent._patch_targets(patch)
        return False, []
