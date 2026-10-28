# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# ruff: noqa: RUF001

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryCitation
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    TextEvidence,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    csv_row_source_id,
    parse_csv_document,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


def test_chinese_and_unicode_fields_and_headers() -> None:
    """Validate Unicode headers, CJK content, and emoji handling without loss."""
    content = (
        "城市代码,城市名称,描述,备注\n"
        "BJ,北京,\"首都，中国 🇨🇳\",\"历史文化 名城\"\n"
        "SH,上海,\"魔都，金融中心\",\"东方明珠 🗼\"\n"
    ).encode()

    rows = parse_csv_document(
        CSVDocumentInput(
            document_id="china-cities",
            primary_key="城市代码",
            content=content,
        )
    )
    assert len(rows) == 2
    assert rows[0].columns == ("城市代码", "城市名称", "描述", "备注")
    assert rows[0].values == ("BJ", "北京", "首都，中国 🇨🇳", "历史文化 名城")
    assert rows[0].primary_key_value == "BJ"

    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    source = asyncio.run(registry.resolve(rows[0]))
    assert source.source_id == f"csv:china-cities:{quote('BJ', safe='')}"

    evidence = TextEvidence.model_validate(registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY))
    data = json.loads(evidence.content)
    assert data["城市名称"] == "北京"
    assert data["描述"] == "首都，中国 🇨🇳"
    assert evidence.metadata["primary_key"] == "城市代码"


def test_empty_string_and_null_like_fields_preservation() -> None:
    """Non-primary-key fields can be empty strings and should not be coerced to None or omitted."""
    content = b"id,name,extra,num\n1,,null,0\n2,\"\",,\n"
    rows = parse_csv_document(CSVDocumentInput(document_id="doc-empty", primary_key="id", content=content))
    assert len(rows) == 2
    assert rows[0].values == ("1", "", "null", "0")
    assert rows[1].values == ("2", "", "", "")

    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    source0 = asyncio.run(registry.resolve(rows[0]))
    evidence0 = TextEvidence.model_validate(registry.project(source0, TEXT_EVIDENCE_PROJECTION_KEY))
    assert evidence0.metadata["row"] == {"id": "1", "name": "", "extra": "null", "num": "0"}


def test_same_primary_key_across_different_documents_isolated() -> None:
    """Identical primary key values in different documents must generate distinct source identities."""
    doc1 = CSVDocumentInput(document_id="dataset-alpha", primary_key="pk", content=b"pk,val\nitem-1,A\n")
    doc2 = CSVDocumentInput(document_id="dataset-beta", primary_key="pk", content=b"pk,val\nitem-1,B\n")

    row1 = parse_csv_document(doc1)[0]
    row2 = parse_csv_document(doc2)[0]

    assert row1.primary_key_value == row2.primary_key_value == "item-1"
    id1 = csv_row_source_id(row1.document_id, row1.primary_key_value)
    id2 = csv_row_source_id(row2.document_id, row2.primary_key_value)
    assert id1 != id2
    assert id1 == "csv:dataset-alpha:item-1"
    assert id2 == "csv:dataset-beta:item-1"


def test_primary_key_length_boundary() -> None:
    """Identity calculation enforces the 256 character limit precisely."""
    # "csv:" is 4 chars, followed by {doc}, followed by ":", followed by {pk}.
    # If doc is 10 chars, prefix "csv:{doc}:" is 4 + 10 + 1 = 15 chars.
    # Therefore pk can be up to 256 - 15 = 241 chars.
    doc = "d" * 10
    pk_exact = "p" * 241
    identity = csv_row_source_id(doc, pk_exact)
    assert len(identity) == 256

    pk_overflow = "p" * 242
    with pytest.raises(ValueError):
        csv_row_source_id(doc, pk_overflow)


def test_scope_isolation_and_restart(tmp_path: Path) -> None:
    """Ensure different scopes remain strictly isolated during ingestion and citation retrieval."""
    content_a = b"id,dept,desc\nE101,Engineering,Core Database Developer\n"
    content_b = b"id,dept,desc\nE101,Marketing,Global Product Evangelist\n"

    rows_a = parse_csv_document(CSVDocumentInput(document_id="staff-tech", primary_key="id", content=content_a))
    rows_b = parse_csv_document(CSVDocumentInput(document_id="staff-biz", primary_key="id", content=content_b))

    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    obs_a = [project_source_for_transport(registry, asyncio.run(registry.resolve(r))) for r in rows_a]
    obs_b = [project_source_for_transport(registry, asyncio.run(registry.resolve(r))) for r in rows_b]

    database = tmp_path / "scope_isolation.db"
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database}"))

    class ScopePipeline:
        async def extract(self, request, /) -> tuple[MemoryEntryInput, ...]:
            entries = []
            for source in request.sources:
                projection = source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
                entries.append(MemoryEntryInput(kind="csv-row", text=projection["content"], sources=(source,)))
            return tuple(entries)

    scope_id_a: str | None = None
    scope_id_b: str | None = None

    async def ingest() -> None:
        nonlocal scope_id_a, scope_id_b
        async with open_builtin_runtime(config) as runtime:
            scope_a = await runtime.scopes.create(ScopeDraft(title="Tech Staff", summary="Engineering scope", idempotency_key="scope-tech-staff"))
            scope_b = await runtime.scopes.create(ScopeDraft(title="Biz Staff", summary="Business scope", idempotency_key="scope-biz-staff"))
            scope_id_a = scope_a.scope_id
            scope_id_b = scope_b.scope_id

            await runtime.ingestion.register(manifest_for_definition(CSV_ROW_SOURCE_DEFINITION))
            for obs in obs_a:
                await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope_id_a, observation=obs))
            for obs in obs_b:
                await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope_id_b, observation=obs))

    asyncio.run(ingest())

    async def verify() -> None:
        assert scope_id_a and scope_id_b
        async with open_builtin_runtime(config, candidate_pipeline=ScopePipeline()) as runtime:
            mem_a = runtime.memory.for_scope(scope_id_a)
            mem_b = runtime.memory.for_scope(scope_id_b)

            await mem_a.flush()
            await mem_b.flush()

            # Search in Scope A
            search_a = await mem_a.search(SearchMemoryRequest(query="Database", mode="fts", limit=10))
            assert len(search_a.hits) >= 1
            hit_a = search_a.hits[0]
            entry_a = await mem_a.get(GetMemoryEntryRequest(citation=MemoryCitation(
                memory_ref=hit_a.memory_ref, entry_id=hit_a.entry_id, entry_version_id=hit_a.entry_version_id
            )))
            assert "Core Database Developer" in entry_a.entry.text
            assert "Evangelist" not in entry_a.entry.text

            # Search in Scope B
            search_b = await mem_b.search(SearchMemoryRequest(query="Evangelist", mode="fts", limit=10))
            assert len(search_b.hits) >= 1
            hit_b = search_b.hits[0]
            entry_b = await mem_b.get(GetMemoryEntryRequest(citation=MemoryCitation(
                memory_ref=hit_b.memory_ref, entry_id=hit_b.entry_id, entry_version_id=hit_b.entry_version_id
            )))
            assert "Global Product Evangelist" in entry_b.entry.text
            assert "Database" not in entry_b.entry.text

    asyncio.run(verify())
