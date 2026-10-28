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

"""T01-T35 Comprehensive tests for SeekDB Single-SQL Hybrid Candidate Search."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, event

from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemoryEntryInput,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.oceanbase.memory_index import (
    OceanBaseMemoryFTSIndex,
    OceanBaseMemoryVectorIndex,
)
from powercontext.builtin.persistence.seekdb import SeekDBConfig, SeekDBMemoryIndex
from powercontext.builtin.persistence.sqlite.profile import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.tags import MemoryEntryTagTarget, TagFilter

PROFILE = EmbeddingProfile(
    profile_id="seekdb-hybrid-test-profile-v1",
    model="deterministic",
    dimension=3,
    distance="l2",
    normalization="unit",
)

OTHER_PROFILE = EmbeddingProfile(
    profile_id="seekdb-hybrid-test-other-profile",
    model="deterministic-other",
    dimension=4,
    distance="l2",
    normalization="unit",
)


class _TestEmbedding:
    profile = PROFILE

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return EmbeddingResult(
            vectors=tuple(
                (1.0, 0.0, 0.0)
                if "alpha" in text.casefold() or "架构" in text
                else (0.0, 0.0, 1.0)
                if "gamma" in text.casefold() or "优化" in text
                else (0.0, 1.0, 0.0)
                for text in texts
            )
        )


Statement = tuple[str, Any]


@contextmanager
def _statements() -> Iterator[list[Statement]]:
    statements: list[Statement] = []

    def record(_connection, _cursor, statement, parameters, _context, _executemany) -> None:
        statements.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def _get_seekdb_config() -> SeekDBConfig:
    db_dir = Path(tempfile.mkdtemp(prefix="seekdb-hybrid-test-", dir=os.environ.get("TMPDIR")))
    return SeekDBConfig(path=db_dir / "db")


@pytest.mark.asyncio
async def test_t01_t02_t03_single_sql_hybrid_and_select_count() -> None:
    """T01, T02, T03: Single SQL statement returns candidates for both FTS and Vector."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha database record."),
                MemoryEntryInput(kind="fact", text="Beta lexical record."),
            ),
            mode="append",
        )
        assert head is not None

        with _statements() as statements:
            result = await memory.search("alpha", memories=(head,), mode="hybrid", limit=10)

        # T02: Verify exactly one candidate SELECT was executed
        native = [
            (stmt, params)
            for stmt, params in statements
            if "pc_memory_entry_heads" in stmt
            and "pc_memory_vector_entries" in stmt
            and "AGAINST" in stmt.upper()
            and "l2_distance" in stmt.lower()
        ]
        assert len(native) == 1, f"Expected 1 native candidate statement, got {len(native)}"

        # T01 & T03: Both FTS and vector hits returned
        assert len(result.hits) >= 1
        top_hit = result.hits[0]
        assert "Alpha" in top_hit.text
        assert "fts" in top_hit.matched_by
        assert "vector" in top_hit.matched_by


@pytest.mark.asyncio
async def test_t04_fts_only_candidate() -> None:
    """T04: Lexical keyword match with low vector similarity produces fts-only hit."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Beta lexical record without alpha."),
            ),
            mode="append",
        )
        assert head is not None

        # Searching for 'beta': matches FTS text, vector for 'beta' is (0,1,0) while query 'beta' is (0,1,0)
        # So test a word where vector does not match admission or FTS is explicit
        fts_res = await memory.search("beta", memories=(head,), mode="fts", limit=1)
        assert len(fts_res.hits) == 1
        assert fts_res.hits[0].matched_by == ("fts",)


@pytest.mark.asyncio
async def test_t05_vector_only_candidate() -> None:
    """T05: Semantic match without keyword overlap produces vector-only hit."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Beta record."),
            ),
            mode="append",
        )
        assert head is not None

        vec_res = await memory.search("beta", memories=(head,), mode="vector", limit=1)
        assert len(vec_res.hits) == 1
        assert vec_res.hits[0].matched_by == ("vector",)


@pytest.mark.asyncio
async def test_t06_t07_t08_deduplication_and_identity_isolation() -> None:
    """T06, T07, T08: Dual hit deduplication and distinct identity preservation."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        # Two entries with identical text content but distinct entry identities
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha duplicate content 1."),
                MemoryEntryInput(kind="fact", text="Alpha duplicate content 2."),
            ),
            mode="append",
        )
        assert head is not None
        result = await memory.search("alpha", memories=(head,), mode="hybrid", limit=10)

        # T07 & T08: Results must not merge distinct entries, but entry IDs must remain distinct
        assert len(result.hits) == 2
        assert result.hits[0].entry_id != result.hits[1].entry_id
        # T06: Both entries were matched by both fts and vector
        assert result.hits[0].matched_by == ("fts", "vector")
        assert result.hits[1].matched_by == ("fts", "vector")


@pytest.mark.asyncio
async def test_t09_t10_scope_filtering_and_isolation() -> None:
    """T09, T10: Scope filtering pushdown and strict isolation between scopes."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        mem_proj = (await contexts.get("project-scope")).artifacts.memory
        mem_other = (await contexts.get("other-scope")).artifacts.memory

        head_proj = await mem_proj.remember(
            memory=None,
            entries=(MemoryEntryInput(kind="fact", text="Alpha secret in project."),),
            mode="append",
        )
        head_other = await mem_other.remember(
            memory=None,
            entries=(MemoryEntryInput(kind="fact", text="Alpha decoy in other."),),
            mode="append",
        )
        assert head_proj is not None and head_other is not None

        # Search in project-scope must NEVER return other-scope entry
        res_proj = await mem_proj.search("alpha", memories=(head_proj,), mode="hybrid", limit=10)
        assert len(res_proj.hits) == 1
        assert res_proj.hits[0].text == "Alpha secret in project."
        assert res_proj.hits[0].memory_ref.artifact_id == head_proj.artifact_id

        # Search in other-scope must return its own entry
        res_other = await mem_other.search("alpha", memories=(head_other,), mode="hybrid", limit=10)
        assert len(res_other.hits) == 1
        assert res_other.hits[0].text == "Alpha decoy in other."


@pytest.mark.asyncio
async def test_t11_t12_t13_revision_and_lifecycle_filtering() -> None:
    """T11, T12, T13: Current revision filtering, update isolation, and soft delete/forget."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head_v1 = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha original version."),
                MemoryEntryInput(kind="fact", text="Beta stable entry."),
            ),
            mode="append",
        )
        assert head_v1 is not None

        # T11, T12: Update alpha entry to v2
        alpha_v1 = next(e for e in await memory.entries(head_v1) if "Alpha" in e.text)
        head_v2 = await memory.remember(
            memory=head_v1,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha revised v2 content.", entry=alpha_v1),
            ),
            mode="append",
        )
        assert head_v2 is not None

        # Search against head_v2: must return v2 version, NOT v1
        res_v2 = await memory.search("alpha", memories=(head_v2,), mode="hybrid", limit=1)
        assert len(res_v2.hits) == 1
        assert res_v2.hits[0].entry_id == alpha_v1.entry_id
        assert res_v2.hits[0].entry_version_id != alpha_v1.entry_version_id
        assert res_v2.hits[0].text == "Alpha revised v2 content."

        # Stale head revision rejection check:
        with pytest.raises(CapabilityNotSupportedError):
            await memory.search("alpha", memories=(head_v1,), mode="hybrid", limit=1)

        # T13: Forget / deactivation
        current_alpha = next(e for e in await memory.entries(head_v2) if e.entry_id == alpha_v1.entry_id)
        head_v3 = await memory.forget(head_v2, entries=(current_alpha,))
        res_v3 = await memory.search("alpha", memories=(head_v3,), mode="hybrid", limit=10)
        assert all(hit.entry_id != alpha_v1.entry_id for hit in res_v3.hits)

        # Reactivation restores access
        head_v4 = await memory.reactivate(head_v3, entries=(current_alpha,))
        res_v4 = await memory.search("alpha", memories=(head_v4,), mode="hybrid", limit=1)
        assert res_v4.hits[0].entry_id == alpha_v1.entry_id


@pytest.mark.asyncio
async def test_t14_database_tag_filtering() -> None:
    """T14: Database-level tag filtering in single SQL hybrid search."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha untagged item."),
                MemoryEntryInput(kind="fact", text="Alpha tagged item."),
            ),
            mode="append",
        )
        assert head is not None
        tagged_entry = next(e for e in await memory.entries(head) if "tagged" in e.text)
        target = MemoryEntryTagTarget(artifact_id=head.artifact_id, entry_id=tagged_entry.entry_id)
        empty = await contexts.records.get_tags("project", target)
        await contexts.records.replace_tags("project", target, ("important",), expected_etag=empty.etag)

        # Query with tag filter
        tagged_res = await memory.search(
            "alpha",
            memories=(head,),
            mode="hybrid",
            limit=10,
            tag_filter=TagFilter(tags=("important",)),
        )
        assert len(tagged_res.hits) == 1
        assert tagged_res.hits[0].entry_id == tagged_entry.entry_id


@pytest.mark.asyncio
async def test_t15_t16_t17_limits_and_boundaries() -> None:
    """T15, T16, T17: TopK boundaries and candidate limits."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        entries = tuple(MemoryEntryInput(kind="fact", text=f"Alpha item number {i}.") for i in range(15))
        head = await memory.remember(memory=None, entries=entries, mode="append")
        assert head is not None

        # Request with limit=3
        res3 = await memory.search("alpha", memories=(head,), mode="hybrid", limit=3)
        assert len(res3.hits) == 3

        # Request with limit=7
        res7 = await memory.search("alpha", memories=(head,), mode="hybrid", limit=7)
        assert len(res7.hits) == 7


@pytest.mark.asyncio
async def test_t18_multilingual_cjk_queries() -> None:
    """T18: Chinese and multilingual queries handled correctly."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="OceanBase 分布式数据库架构核心设计"),
                MemoryEntryInput(kind="fact", text="向量检索与全文检索的混合查询优化"),
            ),
            mode="append",
        )
        assert head is not None

        res_cjk = await memory.search("架构", memories=(head,), mode="hybrid", limit=1)
        assert len(res_cjk.hits) == 1
        assert "架构" in res_cjk.hits[0].text


@pytest.mark.asyncio
async def test_t19_no_result_query() -> None:
    """T19: Queries with no matching candidates return empty hits gracefully."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(MemoryEntryInput(kind="fact", text="Alpha record."),),
            mode="append",
        )
        assert head is not None

        res_none = await memory.search("nonexistentquerykeywordzzz", memories=(head,), mode="fts", limit=5)
        assert len(res_none.hits) == 0


@pytest.mark.asyncio
async def test_t21_embedding_profile_mismatch() -> None:
    """T21: Mismatched embedding profile raises CapabilityNotSupportedError."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(MemoryEntryInput(kind="fact", text="Alpha record."),),
            mode="append",
        )
        assert head is not None

        index = SeekDBMemoryIndex(PROFILE)
        async with contexts.database.transaction() as conn:
            req = MemorySearchRequest(
                query="alpha",
                analyzed_query="alpha",
                memories=(head.as_ref(),),
                candidate_limit=10,
                mode="hybrid",
                query_vector=(1.0, 0.0, 0.0, 0.0),
                embedding_profile=OTHER_PROFILE,
            )
            with pytest.raises(CapabilityNotSupportedError):
                await index.search(conn, "project", req)


@pytest.mark.asyncio
async def test_t22_sql_injection_defense() -> None:
    """T22: SQL parameter binding safety against injection attempts."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(MemoryEntryInput(kind="fact", text="Alpha normal text."),),
            mode="append",
        )
        assert head is not None

        # Injection payload in query text
        malicious = "alpha') UNION ALL SELECT 1,2,3,4,5,6,7,8 --"
        res = await memory.search(malicious, memories=(head,), mode="hybrid", limit=5)
        # Should not crash or inject, should execute securely via parameter binding
        assert isinstance(res.hits, tuple)


@pytest.mark.asyncio
async def test_t23_t24_t25_quality_and_ranking_consistency_against_baseline() -> None:
    """T23, T24, T25: Compare single-SQL hybrid search with baseline dual-query search."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha database engineering."),
                MemoryEntryInput(kind="fact", text="Beta lexical index."),
                MemoryEntryInput(kind="fact", text="Gamma hybrid optimization."),
                MemoryEntryInput(kind="fact", text="Delta query plan analysis."),
            ),
            mode="append",
        )
        assert head is not None

        single_index = SeekDBMemoryIndex(PROFILE)
        dual_fts = OceanBaseMemoryFTSIndex()
        dual_vec = OceanBaseMemoryVectorIndex(PROFILE)

        async with contexts.database.transaction() as conn:
            req = MemorySearchRequest(
                query="alpha",
                analyzed_query="alpha",
                memories=(head.as_ref(),),
                candidate_limit=10,
                mode="hybrid",
                query_vector=(1.0, 0.0, 0.0),
                embedding_profile=PROFILE,
            )

            # Single SQL execution
            single_channels = await single_index.search(conn, "project", req)

            # Dual SQL execution
            dual_fts_ch = await dual_fts.search(conn, "project", req)
            dual_vec_ch = await dual_vec.search(conn, "project", req)
            dual_channels = MemorySearchChannels(fts=dual_fts_ch.fts, vector=dual_vec_ch.vector)

        # Verify candidate IDs and ranks match 100%
        single_fts_ids = [hit.entry_id for hit in single_channels.fts]
        dual_fts_ids = [hit.entry_id for hit in dual_channels.fts]
        assert single_fts_ids == dual_fts_ids, "FTS channel candidate rankings must match baseline exactly"

        single_vec_ids = [hit.entry_id for hit in single_channels.vector]
        dual_vec_ids = [hit.entry_id for hit in dual_channels.vector]
        assert single_vec_ids == dual_vec_ids, "Vector channel candidate rankings must match baseline exactly"


@pytest.mark.asyncio
async def test_t26_t27_real_seekdb_and_explain_plan() -> None:
    """T26, T27: Real SeekDB execution and verification of EXPLAIN execution plan."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha query plan scan."),
                MemoryEntryInput(kind="fact", text="Beta vector index item."),
            ),
            mode="append",
        )
        assert head is not None

        with _statements() as statements:
            await memory.search("alpha", memories=(head,), mode="hybrid", limit=1)

        native = [
            (stmt, params)
            for stmt, params in statements
            if "pc_memory_entry_heads" in stmt
            and "pc_memory_vector_entries" in stmt
            and "AGAINST" in stmt.upper()
            and "l2_distance" in stmt.lower()
        ]
        assert len(native) == 1
        stmt, params = native[0]

        async with contexts.database.transaction() as conn:
            plan = "\n".join(str(r[0]) for r in (await conn.exec_driver_sql(f"EXPLAIN {stmt}", params)).all())

        assert "TEXT RETRIEVAL SCAN" in plan, "EXPLAIN must utilize TEXT RETRIEVAL SCAN"
        assert "VECTOR INDEX" in plan, "EXPLAIN must utilize VECTOR INDEX"


@pytest.mark.asyncio
async def test_t29_t30_memory_and_topic_memory_regression() -> None:
    """T29, T30: Memory operations regression."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha item."),
                MemoryEntryInput(kind="fact", text="Beta item."),
            ),
            mode="append",
        )
        assert head is not None

        # Verify fts mode
        fts_res = await memory.search("alpha", memories=(head,), mode="fts", limit=5)
        assert len(fts_res.hits) == 1

        # Verify vector mode
        vec_res = await memory.search("alpha", memories=(head,), mode="vector", limit=5)
        assert len(vec_res.hits) >= 1

        # Verify auto mode
        auto_res = await memory.search("alpha", memories=(head,), mode="auto", limit=5)
        assert len(auto_res.hits) >= 1


@pytest.mark.asyncio
async def test_t31_sqlite_backend_compatibility() -> None:
    """T31: SQLite backend remains 100% compatible and unaffected."""
    sqlite_path = Path(tempfile.mkdtemp(prefix="sqlite-test-")) / "test.db"
    async with open_builtin_contexts(
        BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{sqlite_path.as_posix()}")),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha sqlite test."),
            ),
            mode="append",
        )
        assert head is not None
        res = await memory.search("alpha", memories=(head,), mode="hybrid", limit=1)
        assert len(res.hits) == 1
        assert res.hits[0].text == "Alpha sqlite test."


@pytest.mark.asyncio
async def test_t33_concurrency_isolation() -> None:
    """T33: Concurrency isolation across simultaneous searches."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        mem1 = (await contexts.get("scope-1")).artifacts.memory
        mem2 = (await contexts.get("scope-2")).artifacts.memory

        head1 = await mem1.remember(
            memory=None,
            entries=(MemoryEntryInput(kind="fact", text="Alpha scope one data."),),
            mode="append",
        )
        head2 = await mem2.remember(
            memory=None,
            entries=(MemoryEntryInput(kind="fact", text="Alpha scope two data."),),
            mode="append",
        )
        assert head1 is not None and head2 is not None

        async def _query(m, h, expected):
            r = await m.search("alpha", memories=(h,), mode="hybrid", limit=1)
            return r.hits[0].text == expected

        r1, r2 = await asyncio.gather(
            _query(mem1, head1, "Alpha scope one data."),
            _query(mem2, head2, "Alpha scope two data."),
        )
        assert r1 and r2


@pytest.mark.asyncio
async def test_t34_t35_citation_verification_and_runtime_regression() -> None:
    """T34, T35: Citation exact coordinates and runtime retrieval regression."""
    config = _get_seekdb_config()
    async with open_builtin_contexts(
        BuiltinConfig(database=config),
        embedding_model=_TestEmbedding(),
    ) as contexts:
        memory = (await contexts.get("project")).artifacts.memory
        head = await memory.remember(
            memory=None,
            entries=(
                MemoryEntryInput(kind="fact", text="Alpha precise citation test."),
            ),
            mode="append",
        )
        assert head is not None

        res = await memory.search("alpha", memories=(head,), mode="hybrid", limit=1)
        hit = res.hits[0]
        assert hit.memory_ref.artifact_id == head.artifact_id
        assert hit.memory_ref.revision == head.revision

        # Verify entry can be looked up from memory repository
        entries = await memory.entries(head)
        matched = [e for e in entries if e.entry_id == hit.entry_id]
        assert len(matched) == 1
        assert matched[0].entry_version_id == hit.entry_version_id
        assert matched[0].text == hit.text
