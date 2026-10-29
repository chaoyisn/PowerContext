"""Build a real development context from seekdb and PowerContext.

``build_context`` answers a development task with the applicable specification,
the code files and symbols that must change, the target and regression tests,
and the persisted task state. Every section is produced by a real query against
the seekdb instance and a real read from the PowerContext server.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .importer import MaterialImporter
from .powercontext_store import PowerContextStateStore
from .seekdb_store import SeekDBStore

_STOPWORDS = {
    "add",
    "the",
    "a",
    "an",
    "to",
    "for",
    "of",
    "and",
    "in",
    "on",
    "by",
    "with",
    "support",
    "supports",
    "function",
    "functions",
    "method",
    "methods",
    "please",
    "implement",
    "实现",
    "增加",
    "支持",
    "函数",
    "功能",
    "请",
    "为",
}


def _terms(task: str) -> list[str]:
    """Extract meaningful retrieval terms from a task description."""

    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|[一-鿿]{2,}", task)
    seen: list[str] = []
    for word in words:
        lowered = word.lower()
        if lowered in _STOPWORDS or len(lowered) < 2:
            continue
        if lowered not in seen:
            seen.append(lowered)
    return seen[:24]


@dataclass
class DevelopmentContext:
    """The structured context handed to MiniMax for one development task."""

    task_id: str
    task: str
    specifications: list[dict[str, Any]] = field(default_factory=list)
    code: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Any] = field(default_factory=dict)
    retrieval: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task": self.task,
            "specifications": self.specifications,
            "code": self.code,
            "tests": self.tests,
            "state": self.state,
            "sources": self.sources,
            "retrieval": self.retrieval,
        }


class ContextBuilder:
    """Assemble a development context out of seekdb and PowerContext."""

    def __init__(
        self,
        store: SeekDBStore,
        state_store: PowerContextStateStore,
        root: Path,
    ) -> None:
        self.store = store
        self.state_store = state_store
        self.root = root.resolve()

    # ------------------------------------------------------------------ specs

    def resolve_specifications(self, task: str, spec_id: str | None = None) -> list[dict[str, Any]]:
        """Return the specifications that apply to the task.

        An explicit ``spec_id`` wins; otherwise the specification table is
        searched with the task terms.
        """

        if spec_id:
            row = self.store.latest_specification(spec_id)
            return [self._spec_payload(row)] if row else []
        rows = self.store.search_specifications(_terms(task))
        return [self._spec_payload(row) for row in rows]

    @staticmethod
    def _spec_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "spec_id": row["spec_id"],
            "version": row["version"],
            "revision": row["revision"],
            "title": row["title"],
            "status": row["status"],
            "content": row["content"],
            "content_hash": row["content_hash"],
            "source_path": row["source_path"],
        }

    # ------------------------------------------------------------------ code

    def resolve_code(
        self, specifications: list[dict[str, Any]], task: str
    ) -> list[dict[str, Any]]:
        """Return the code symbols that the specifications point at."""

        paths: list[str] = []
        for specification in specifications:
            for relation in self.store.relations_for_spec(
                specification["spec_id"], specification["version"]
            ):
                if relation["target_kind"] == "code" and relation["target_id"] not in paths:
                    paths.append(relation["target_id"])
        if not paths:
            for symbol in self.store.code_symbols_for_paths([]):
                pass
        rows = self.store.code_symbols_for_paths(paths)
        return [
            {
                "file_path": row["file_path"],
                "symbol_name": row["symbol_name"],
                "qualified_name": row["qualified_name"],
                "kind": row["kind"],
                "language": row["language"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "signature": row["signature"],
                "content": row["content"],
                "content_hash": row["content_hash"],
                "source_path": row["source_path"],
            }
            for row in rows
        ]

    # ----------------------------------------------------------------- tests

    def resolve_tests(self, specifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return the target and regression tests bound to the specifications."""

        paths: list[str] = []
        for specification in specifications:
            for relation in self.store.relations_for_spec(
                specification["spec_id"], specification["version"]
            ):
                if relation["target_kind"] == "test" and relation["target_id"] not in paths:
                    paths.append(relation["target_id"])
        rows = self.store.tests_for_paths(paths)
        return [
            {
                "file_path": row["file_path"],
                "test_name": row["test_name"],
                "test_kind": row["test_kind"],
                "requirement_ids": [item for item in (row["requirement_ids"] or "").split(",") if item],
                "content": row["content"],
                "content_hash": row["content_hash"],
                "source_path": row["source_path"],
            }
            for row in rows
        ]

    # ----------------------------------------------------------------- build

    def build(self, task_id: str, task: str, spec_id: str | None = None) -> DevelopmentContext:
        specifications = self.resolve_specifications(task, spec_id)
        code = self.resolve_code(specifications, task)
        tests = self.resolve_tests(specifications)
        state = self.state_store.load_task_state(task_id)

        sources = {
            "specifications": [item["source_path"] for item in specifications],
            "code": sorted({item["source_path"] for item in code}),
            "tests": sorted({item["source_path"] for item in tests}),
            "state": {
                "powercontext_url": self.state_store.settings.powercontext_url,
                "scope_id": self.state_store.scope_id(),
                "artifact_ids": state.get("artifact_ids", {}),
            },
        }
        retrieval = {
            "terms": _terms(task),
            "database": self.store.settings.seekdb_database,
            "database_counts": self.store.counts(),
            "server_version": self.store.server_version(),
            "state_records_found": bool(state.get("has_state")),
        }
        return DevelopmentContext(
            task_id=task_id,
            task=task,
            specifications=specifications,
            code=code,
            tests=tests,
            state=state,
            sources=sources,
            retrieval=retrieval,
        )


def link_materials(
    importer: MaterialImporter,
    store: SeekDBStore,
    *,
    spec_id: str,
    spec_version: str,
    code_paths: list[str],
    test_paths: list[str],
) -> dict[str, Any]:
    """Bind the imported code and test paths to a specification revision."""

    linked_code: list[str] = []
    for path in code_paths:
        importer.link(spec_id, spec_version, "code", path, "applies-to")
        linked_code.append(path)
    linked_tests: list[str] = []
    for path in test_paths:
        importer.link(spec_id, spec_version, "test", path, "verified-by")
        linked_tests.append(path)
    return {
        "spec_id": spec_id,
        "spec_version": spec_version,
        "linked_code": linked_code,
        "linked_tests": linked_tests,
        "relations": len(store.relations_for_spec(spec_id, spec_version)),
    }
