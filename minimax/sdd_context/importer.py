"""Import SDD engineering materials into seekdb.

The importer parses the real files on disk with :mod:`ast`, so the symbols and
tests stored in the database always correspond to code that exists. Nothing is
invented: every row carries the file path it was read from.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .seekdb_store import SeekDBStore


@dataclass(frozen=True)
class ImportedSymbol:
    file_path: str
    symbol_name: str
    qualified_name: str
    kind: str
    language: str
    start_line: int
    end_line: int
    signature: str
    content: str


@dataclass(frozen=True)
class ImportedTest:
    file_path: str
    test_name: str
    test_kind: str
    requirement_ids: tuple[str, ...]
    content: str


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def parse_python_symbols(path: Path, root: Path) -> list[ImportedSymbol]:
    """Return every top-level and nested symbol defined in a Python file."""

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    symbols: list[ImportedSymbol] = []

    def signature_of(node: ast.AST) -> str:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments = [argument.arg for argument in node.args.args]
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            return f"{prefix} {node.name}({', '.join(arguments)})"
        if isinstance(node, ast.ClassDef):
            bases = [ast.unparse(base) for base in node.bases]
            return f"class {node.name}({', '.join(bases)})"
        if isinstance(node, ast.Assign):
            targets = [ast.unparse(target) for target in node.targets]
            return f"{', '.join(targets)} = <expression>"
        return type(node).__name__

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = f"{prefix}{child.name}"
                body = "\n".join(lines[child.lineno - 1 : child.end_lineno])
                symbols.append(
                    ImportedSymbol(
                        file_path=_relative(path, root),
                        symbol_name=child.name,
                        qualified_name=qualified,
                        kind="function" if not isinstance(child, ast.ClassDef) else "class",
                        language="python",
                        start_line=child.lineno,
                        end_line=child.end_lineno or child.lineno,
                        signature=signature_of(child),
                        content=body,
                    )
                )
                visit(child, f"{qualified}.")
            elif isinstance(child, ast.Assign):
                qualified = f"{prefix}{ast.unparse(child.targets[0])}"
                body = "\n".join(lines[child.lineno - 1 : child.end_lineno or child.lineno])
                symbols.append(
                    ImportedSymbol(
                        file_path=_relative(path, root),
                        symbol_name=ast.unparse(child.targets[0]),
                        qualified_name=qualified,
                        kind="variable",
                        language="python",
                        start_line=child.lineno,
                        end_line=child.end_lineno or child.lineno,
                        signature=signature_of(child),
                        content=body,
                    )
                )

    visit(tree, "")
    return symbols


def parse_python_tests(path: Path, root: Path, requirement_ids: Iterable[str]) -> list[ImportedTest]:
    """Return every test function defined in a test file."""

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    tests: list[ImportedTest] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        body = "\n".join(lines[node.lineno - 1 : node.end_lineno or node.lineno])
        kind = "regression" if "regression" in path.name else "functional"
        tests.append(
            ImportedTest(
                file_path=_relative(path, root),
                test_name=node.name,
                test_kind=kind,
                requirement_ids=tuple(requirement_ids),
                content=body,
            )
        )
    return tests


class MaterialImporter:
    """Import specifications, code symbols and tests into seekdb."""

    def __init__(self, store: SeekDBStore, root: Path) -> None:
        self.store = store
        self.root = root.resolve()

    def import_specification(self, path: Path, spec_id: str) -> dict[str, Any]:
        """Import one specification file, replacing its previous revision."""

        content = path.read_text(encoding="utf-8")
        version, revision, title, status = _parse_spec_header(content)
        digest = self.store.upsert_specification(
            spec_id=spec_id,
            version=version,
            revision=revision,
            title=title,
            status=status,
            content=content,
            source_path=_relative(path, self.root),
        )
        return {
            "spec_id": spec_id,
            "version": version,
            "revision": revision,
            "title": title,
            "status": status,
            "content_hash": digest,
            "source_path": _relative(path, self.root),
        }

    def import_code(self, path: Path) -> list[dict[str, Any]]:
        imported = []
        for symbol in parse_python_symbols(path, self.root):
            symbol_id = self.store.upsert_code_symbol(
                file_path=symbol.file_path,
                symbol_name=symbol.symbol_name,
                qualified_name=symbol.qualified_name,
                kind=symbol.kind,
                language=symbol.language,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                signature=symbol.signature,
                content=symbol.content,
                source_path=_relative(path, self.root),
            )
            imported.append({"symbol_id": symbol_id, "qualified_name": symbol.qualified_name})
        return imported

    def import_test(self, path: Path, requirement_ids: Iterable[str]) -> list[dict[str, Any]]:
        imported = []
        for test in parse_python_tests(path, self.root, requirement_ids):
            test_id = self.store.upsert_test(
                file_path=test.file_path,
                test_name=test.test_name,
                test_kind=test.test_kind,
                requirement_ids=test.requirement_ids,
                content=test.content,
                source_path=_relative(path, self.root),
            )
            imported.append({"test_id": test_id, "test_name": test.test_name})
        return imported

    def link(self, spec_id: str, spec_version: str, target_kind: str, target_id: str, relation: str) -> None:
        self.store.upsert_relation(
            spec_id=spec_id,
            spec_version=spec_version,
            target_kind=target_kind,
            target_id=target_id,
            relation_type=relation,
        )


def _parse_spec_header(content: str) -> tuple[str, str, str, str]:
    """Read the version, revision, title and status out of a specification file."""

    version = revision = title = status = ""
    for line in content.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        key, value = cells
        if key == "Spec version":
            version = value
        elif key == "Revision":
            revision = value
        elif key == "Title":
            title = value
        elif key == "Status":
            status = value
    return version or "0.0.0", revision or "r1", title or "untitled specification", status or "draft"
