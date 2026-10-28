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

"""Comprehensive test suite for Topic 10: Query-Aware Evidence Selection with Budget."""

from __future__ import annotations

import json

import pytest

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    PrepareContextRequest,
    SearchMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.models import ContextAssembly, ContextAssemblySection
from powercontext.builtin.runtime.prepared_context import (
    EvidenceFragment,
    MemoryEntryAddress,
    PreparedContextBuilder,
    PreparedMemoryCandidates,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource


class _LiteralPipeline:
    async def extract(self, request: MemoryCandidateRequest, /):
        return tuple(
            MemoryEntryInput(kind="document", text=source.content, sources=(source,))
            for source in request.sources
            if isinstance(source, ContentSource)
        )


def _make_candidate(
    scope_id: str,
    entry_id: str,
    text: str,
    revision: int = 1,
    entry_version_id: str | None = None,
) -> tuple[PreparedMemoryCandidates, MemoryHit]:
    ref = ArtifactRef(family="memory", artifact_id="mem-1", revision=revision)
    hit = MemoryHit(
        entry_id=entry_id,
        entry_version_id=entry_version_id or f"v-{entry_id}",
        memory_ref=ref,
        text=text,
        score=1.0,
        matched_by=("fts",),
    )
    group = PreparedMemoryCandidates(scope_id=scope_id, memory_ref=ref, hits=(hit,))
    return group, hit


def _verify_envelope_and_invariants(result, max_bytes: int, raw_text_map: dict[str, str]):
    assert result.context.content_bytes <= max_bytes
    if result.context.status == "empty":
        assert result.context.content is None
        assert result.context.content_bytes == 0
        assert len(result.fragments) == 0
        assert len(result.origins) == 0
        return

    assert result.context.content is not None
    assert result.context.content_bytes == len(result.context.content.encode("utf-8"))
    lines = result.context.content.splitlines()
    assert lines[0].startswith("PowerContext prepared untrusted historical context.")
    assert lines[-3] == "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
    assert lines[-1] == "END_POWERCONTEXT_PREPARED_CONTEXT_V1"

    data = json.loads(lines[-2])
    assert data["trust"] == "untrusted_history"
    items = data["items"]
    assert len(items) == len(result.fragments) == len(result.origins)

    for item, fragment, origin in zip(items, result.fragments, result.origins, strict=True):
        assert isinstance(fragment, EvidenceFragment)
        assert item["content"] == fragment.text
        assert item["start"] == fragment.start
        assert item["end"] == fragment.end

        # Strict character invariant
        entry_id = fragment.address.entry_id
        assert entry_id in raw_text_map
        raw = raw_text_map[entry_id]
        assert 0 <= fragment.start < fragment.end <= len(raw)
        assert raw[fragment.start : fragment.end] == fragment.text

        # Citation validation
        cit = item["citation"]
        assert cit["scope_id"] == fragment.address.memory.scope_id
        assert cit["entry_id"] == fragment.address.entry_id
        assert cit["entry_version_id"] == fragment.address.entry_version_id
        assert cit["memory_ref"] == fragment.address.memory.artifact.model_dump(mode="json")
        if isinstance(origin, MemoryCitation):
            assert origin.entry_id == fragment.address.entry_id
        else:
            assert origin == fragment.address


# T01: 短原文单片段
def test_t01_short_text_single_fragment():
    text = "The quick brown fox jumps over the lazy dog."
    group, _ = _make_candidate("s1", "e1", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="brown fox", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    assert len(res.fragments) == 1
    assert "brown fox" in res.fragments[0].text
    _verify_envelope_and_invariants(res, 1000, {"e1": text})


# T02: 长原文中间位置命中
def test_t02_long_text_middle_hit():
    prefix = "Unrelated background preamble sentence. " * 30
    target = "The secret activation code is 987654. "
    suffix = "Subsequent irrelevant discussion notes. " * 30
    text = prefix + target + suffix
    group, _ = _make_candidate("s1", "e2", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="secret activation code 987654", max_bytes=1500, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    assert any("987654" in f.text for f in res.fragments)
    # Must not just take the prefix
    assert not any(f.text.startswith("Unrelated background preamble") and "987654" not in f.text for f in res.fragments)
    _verify_envelope_and_invariants(res, 1500, {"e2": text})


# T03: 长原文末尾位置命中
def test_t03_long_text_end_hit():
    prefix = "Routine system heartbeat status healthy. " * 60
    target = "Critical failover occurs at threshold 42. "
    text = prefix + target
    group, _ = _make_candidate("s1", "e3", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="critical failover threshold 42", max_bytes=1200, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    assert any("threshold 42" in f.text for f in res.fragments)
    _verify_envelope_and_invariants(res, 1200, {"e3": text})


# T04: 多个相关片段
def test_t04_multiple_relevant_fragments():
    s1 = "Component Alpha operates at 100 MHz. "
    filler = "Administrative noise. " * 15
    s2 = "Component Alpha backup operates at 120 MHz. "
    text = s1 + filler + s2
    group, _ = _make_candidate("s1", "e4", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="Component Alpha operates MHz", max_bytes=1800, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    assert len(res.fragments) >= 2
    assert any("100 MHz" in f.text for f in res.fragments)
    assert any("120 MHz" in f.text for f in res.fragments)
    _verify_envelope_and_invariants(res, 1800, {"e4": text})


# T05: 多个不同 Source
def test_t05_multiple_distinct_sources():
    t1 = "Primary database port is 3306. "
    t2 = "Replica database port is 3307. "
    g1, _ = _make_candidate("s1", "doc-1", t1)
    g2, _ = _make_candidate("s1", "doc-2", t2)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="database port", max_bytes=1600, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[g1, g2])

    assert res.context.status == "ready"
    doc_ids = {f.address.entry_id for f in res.fragments}
    assert "doc-1" in doc_ids and "doc-2" in doc_ids
    _verify_envelope_and_invariants(res, 1600, {"doc-1": t1, "doc-2": t2})


# T06: 同一关键词重复出现
def test_t06_repeated_keyword_not_duplicate_exact_spans():
    text = "Telemetry reading valid. " * 30
    group, _ = _make_candidate("s1", "e6", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="telemetry reading", max_bytes=1200, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    # Spans must not have identical start and end coordinates
    coords = [(f.start, f.end) for f in res.fragments]
    assert len(coords) == len(set(coords))
    _verify_envelope_and_invariants(res, 1200, {"e6": text})


# T07: 重叠片段合并
def test_t07_overlapping_fragments_merged():
    t = "Deep neural networks learn representations. Neural networks learn representations efficiently."
    group, _ = _make_candidate("s1", "e7", t)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="neural networks learn representations", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    # Check that any selected fragments do not overlap without being merged
    for i in range(len(res.fragments) - 1):
        f1 = res.fragments[i]
        f2 = res.fragments[i + 1]
        assert f1.end <= f2.start
    _verify_envelope_and_invariants(res, 1000, {"e7": t})


# T08: 相邻片段
def test_t08_adjacent_fragments_merged():
    t = "Step one initializes the buffer. Step two loads the weights."
    group, _ = _make_candidate("s1", "e8", t)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="Step initializes buffer loads weights", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    # Adjacent sentences merged into single contiguous evidence
    assert any("Step one" in f.text and "Step two" in f.text for f in res.fragments)
    _verify_envelope_and_invariants(res, 1000, {"e8": t})


# T09: 中文字符 offset
def test_t09_chinese_character_offset():
    chinese_text = "海洋观测站记录温度数据。观测设备部署在东海海域。"
    group, _ = _make_candidate("s1", "e9", chinese_text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="海洋观测站 温度数据", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    f = res.fragments[0]
    # Python Unicode character slice
    assert chinese_text[f.start : f.end] == f.text
    assert f.text.startswith("海洋观测站")
    _verify_envelope_and_invariants(res, 1000, {"e9": chinese_text})


# T10: Emoji 和多字节字符
def test_t10_emoji_and_multibyte():
    text = "🛰️ Satellite telemetry recorded 25 degrees. 🔬 Laboratory analysis confirmed stability."
    group, _ = _make_candidate("s1", "e10", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="Satellite telemetry 25 degrees", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    f = res.fragments[0]
    assert text[f.start : f.end] == f.text
    assert "🛰️" in f.text
    _verify_envelope_and_invariants(res, 1000, {"e10": text})


# T11: 换行、空格和特殊符号
def test_t11_newlines_spaces_and_quotes():
    text = 'Line 1: "First configuration".\n\nLine 2: Path is C:\\OceanBase\\Data.\n\nLine 3: Status is OK.'
    group, _ = _make_candidate("s1", "e11", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="Path C:\\OceanBase\\Data", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    assert any("C:\\OceanBase\\Data" in f.text for f in res.fragments)
    _verify_envelope_and_invariants(res, 1000, {"e11": text})


# T12: 大小写与 Unicode normalization
def test_t12_case_and_normalization():
    text = "Mutations in BRCA2 and PALB2 confer high cancer risk. Symptoms include anemia."
    group, _ = _make_candidate("s1", "e12", text)
    builder = PreparedContextBuilder()
    # Query in lowercase
    req = PrepareContextRequest(query="brca2 palb2 cancer risk", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    # Preserves exact uppercase in original text
    assert "BRCA2" in res.fragments[0].text
    _verify_envelope_and_invariants(res, 1000, {"e12": text})


# T13: 原始 Source 精确回查
@pytest.mark.asyncio
async def test_t13_runtime_source_verification():
    raw_doc = "Quantum dots and magnetic nanoparticles track stem cells in vivo."
    async with open_builtin_runtime(BuiltinConfig(), candidate_pipeline=_LiteralPipeline()) as runtime:
        scope = await runtime.scopes.create(ScopeDraft(title="T13 Scope", summary="T13 summary", idempotency_key="t13-key"))
        sources = runtime.sources.for_scope(scope.scope_id)
        memory = runtime.memory.for_scope(scope.scope_id)
        await sources.capture(CaptureSource(source_id="src-13", content=raw_doc, metadata={"document_id": "13"}))
        while (await memory.flush()).processed:
            pass

        page = await memory.search(SearchMemoryRequest(query="nanoparticles stem cells", mode="fts"))
        groups = (PreparedMemoryCandidates(scope_id=scope.scope_id, memory_ref=page.memory_ref, hits=page.hits),)
        req = PrepareContextRequest(query="nanoparticles stem cells", max_bytes=1200, evidence_selection=True)
        res = PreparedContextBuilder().build_scopes_result(
            request=req, current_scope_id=scope.scope_id, memory_candidates=groups
        )

        assert res.context.status == "ready"
        assert len(res.fragments) > 0
        frag = res.fragments[0]
        # Query memory entry directly using citation
        cit = MemoryCitation(
            memory_ref=frag.address.memory.artifact,
            entry_id=frag.address.entry_id,
            entry_version_id=frag.address.entry_version_id,
        )
        got = await memory.get(GetMemoryEntryRequest(citation=cit))
        assert got.entry.text[frag.start : frag.end] == frag.text
        _verify_envelope_and_invariants(res, 1200, {got.entry.entry_id: got.entry.text})


# T14: 片段 start/end 完全正确
def test_t14_start_end_half_open_invariants():
    t = "Sentence alpha. Sentence beta. Sentence gamma."
    group, _ = _make_candidate("s1", "e14", t)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="alpha gamma", max_bytes=1200, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    for f in res.fragments:
        assert isinstance(f.start, int)
        assert isinstance(f.end, int)
        assert 0 <= f.start < f.end <= len(t)
        assert t[f.start : f.end] == f.text


# T15: 不同 Revision 不混淆
def test_t15_distinct_revisions_preserved():
    t = "Configuration parameter timeout is 30s."
    g1, _ = _make_candidate("s1", "e15", t, revision=1, entry_version_id="v1")
    g2, _ = _make_candidate("s1", "e15", t, revision=2, entry_version_id="v2")
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="parameter timeout 30s", max_bytes=1500, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[g1, g2])

    assert res.context.status == "ready"
    for f in res.fragments:
        assert f.address.entry_version_id in {"v1", "v2"}
        assert f.address.memory.artifact.revision in {1, 2}


# T16: 预算恰好容纳
def test_t16_exact_budget_boundary():
    text = "Specific diagnostic test confirmed negative."
    group, _ = _make_candidate("s1", "e16", text)
    builder = PreparedContextBuilder()
    # First build with large budget to discover exact required bytes
    req_probe = PrepareContextRequest(query="diagnostic test negative", max_bytes=2000, evidence_selection=True)
    res_probe = builder.build_scopes_result(request=req_probe, current_scope_id="s1", memory_candidates=[group])
    exact_bytes = res_probe.context.content_bytes

    # Now request with exact budget
    req_exact = PrepareContextRequest(query="diagnostic test negative", max_bytes=exact_bytes, evidence_selection=True)
    res_exact = builder.build_scopes_result(request=req_exact, current_scope_id="s1", memory_candidates=[group])

    assert res_exact.context.status == "ready"
    assert res_exact.context.content_bytes == exact_bytes


# T17: 预算差 1 字节
def test_t17_budget_off_by_one():
    text = "Specific diagnostic test confirmed negative."
    group, _ = _make_candidate("s1", "e17", text)
    builder = PreparedContextBuilder()
    req_probe = PrepareContextRequest(query="diagnostic test negative", max_bytes=2000, evidence_selection=True)
    res_probe = builder.build_scopes_result(request=req_probe, current_scope_id="s1", memory_candidates=[group])
    exact_bytes = res_probe.context.content_bytes

    # Request with exact_bytes - 1
    req_tight = PrepareContextRequest(query="diagnostic test negative", max_bytes=exact_bytes - 1, evidence_selection=True)
    res_tight = builder.build_scopes_result(request=req_tight, current_scope_id="s1", memory_candidates=[group])

    # Must NOT exceed budget
    assert res_tight.context.content_bytes <= exact_bytes - 1
    if res_tight.context.status == "ready":
        assert len(res_tight.fragments[0].text) < len(res_probe.fragments[0].text)


# T18: Citation 开销导致片段放不下
def test_t18_citation_overhead_exceeds_budget():
    text = "Short evidence."
    group, _ = _make_candidate("s1", "e18", text)
    builder = PreparedContextBuilder()
    # 512 bytes: envelope (366 bytes) + citation overhead (~180 bytes) > 512 bytes
    req = PrepareContextRequest(query="Short evidence", max_bytes=512, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "empty"
    assert res.context.content is None
    assert res.context.content_bytes == 0


# T19: 中文导致字符数与字节数不同
def test_t19_chinese_utf8_byte_expansion():
    # 20 Chinese characters = 60 UTF-8 bytes
    chinese = "这是一段非常标准的中文字符测试文本用来验证字节计数准确性。"
    group, _ = _make_candidate("s1", "e19", chinese)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="中文字符测试文本", max_bytes=800, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    assert res.context.content_bytes == len(res.context.content.encode("utf-8"))
    _verify_envelope_and_invariants(res, 800, {"e19": chinese})


# T20: 多个片段与引用合计超预算
def test_t20_multiple_candidates_budget_enforcement():
    docs = [f"Target record number {i} contains key metrics. " * 3 for i in range(10)]
    groups = [_make_candidate("s1", f"doc-{i}", docs[i])[0] for i in range(10)]
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="Target record metrics", max_bytes=1100, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=groups)

    assert res.context.status == "ready"
    assert res.context.content_bytes <= 1100
    assert len(res.fragments) < 10
    _verify_envelope_and_invariants(res, 1100, {f"doc-{i}": docs[i] for i in range(10)})


# T21: 极小合法预算
def test_t21_minimal_legal_budget():
    group, _ = _make_candidate("s1", "e21", "Important note.")
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="Important note", max_bytes=512, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "empty"
    assert res.context.content_bytes == 0


# T22: 空候选
def test_t22_empty_candidates():
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="anything", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[])

    assert res.context.status == "empty"
    assert res.context.content is None
    assert res.context.content_bytes == 0
    assert len(res.fragments) == 0


# T23: 无关 Query
def test_t23_unrelated_query():
    text = "Database engines process structured relational records."
    group, _ = _make_candidate("s1", "e23", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="quantum astrophysics telescope galaxies", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "empty"
    assert res.context.content is None
    assert res.context.content_bytes == 0


# T24: 稳定排序 (连续运行三次结果一致)
def test_t24_deterministic_ranking():
    t1 = "Alpha node status: operational."
    t2 = "Beta node status: operational."
    g1, _ = _make_candidate("s1", "d1", t1)
    g2, _ = _make_candidate("s1", "d2", t2)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="node status operational", max_bytes=1500, evidence_selection=True)

    res1 = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[g1, g2])
    res2 = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[g1, g2])
    res3 = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[g1, g2])

    assert res1.context.content == res2.context.content == res3.context.content
    assert res1.fragments == res2.fragments == res3.fragments


# T25: 不同 Scope 隔离
def test_t25_scope_isolation():
    t1 = "Scope A facts."
    t2 = "Scope B facts."
    g1, _ = _make_candidate("scope-A", "dA", t1)
    g2, _ = _make_candidate("scope-B", "dB", t2)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="facts", max_bytes=1500, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="scope-A", memory_candidates=[g1, g2])

    assert res.context.status == "ready"
    assert len(res.fragments) == 2
    # Current scope uses MemoryCitation, other scope uses MemoryEntryAddress
    assert isinstance(res.origins[0], MemoryCitation)
    assert isinstance(res.origins[1], MemoryEntryAddress)
    assert res.origins[1].memory.scope_id == "scope-B"


# T26: 完整 HTTP 端到端
@pytest.mark.asyncio
async def test_t26_http_e2e_api():
    from powercontext.client import PowerContextClient
    from powercontext.server.app import create_app

    raw_text = "OceanBase distributed database provides high availability and consistency."
    async with open_builtin_runtime(BuiltinConfig(), candidate_pipeline=_LiteralPipeline()) as runtime:
        app = create_app(application=runtime)
        scope = await runtime.scopes.create(ScopeDraft(title="HTTP Scope", summary="HTTP summary", idempotency_key="http-test-key"))
        sources = runtime.sources.for_scope(scope.scope_id)
        memory = runtime.memory.for_scope(scope.scope_id)
        await sources.capture(CaptureSource(source_id="http-src", content=raw_text, metadata={"document_id": "http-1"}))
        while (await memory.flush()).processed:
            pass

        from httpx import ASGITransport, AsyncClient

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
            client = PowerContextClient("http://127.0.0.1:8000", http_client=http_client)
            from powercontext.http import PrepareContextRequest as HttpPrepareContextRequest

            req = HttpPrepareContextRequest(
                scope_id=scope.scope_id,
                query="OceanBase distributed database availability",
                max_bytes=1500,
                evidence_selection=True,
            )
            prepared = await client.prepare_context(req)
            assert prepared.status == "ready"
            assert prepared.content is not None
            assert "OceanBase distributed database" in prepared.content
            assert prepared.content_bytes == len(prepared.content.encode("utf-8"))


# T27: JSON 结构完整性
def test_t27_json_structure_integrity():
    text = "Validating JSON envelope and escaping: quotes \"here\" and slashes \\there\\."
    group, _ = _make_candidate("s1", "e27", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="envelope escaping quotes", max_bytes=1000, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    _verify_envelope_and_invariants(res, 1000, {"e27": text})


# T28: content_bytes 与真实 UTF-8 长度一致
def test_t28_content_bytes_exact_utf8_match():
    text = "Measurement verification with mixed languages: 简体中文, English, and symbols: ∑ ≠ ∞."
    group, _ = _make_candidate("s1", "e28", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="Measurement mixed languages", max_bytes=1200, evidence_selection=True)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    assert res.context.content_bytes == len(res.context.content.encode("utf-8"))


# T29: 原有 prepare 回归
def test_t29_default_prepare_regression():
    text = "Original standard prepare behavior without evidence selection."
    group, _ = _make_candidate("s1", "e29", text)
    builder = PreparedContextBuilder()
    req = PrepareContextRequest(query="standard prepare", max_bytes=1000, evidence_selection=False)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    # In default mode, fragments is empty tuple
    assert len(res.fragments) == 0
    # Uses standard items with truncated: false
    data = json.loads(res.context.content.splitlines()[-2])
    assert data["items"][0]["truncated"] is False
    assert data["items"][0]["content"] == text


# T30: Assembly 与多 Family 回归
def test_t30_assembly_multi_family_regression():
    text = "Memory candidate under assembly."
    group, _ = _make_candidate("s1", "e30", text)
    builder = PreparedContextBuilder()
    assembly = ContextAssembly(sections=(ContextAssemblySection(family="memory", limit=2),))
    req = PrepareContextRequest(query="assembly", max_bytes=1000, assembly=assembly, evidence_selection=False)
    res = builder.build_scopes_result(request=req, current_scope_id="s1", memory_candidates=[group])

    assert res.context.status == "ready"
    assert len(res.fragments) == 0
    assert "Memory candidate" in res.context.content


# Property-based tests
@pytest.mark.parametrize("repeat", [1, 2, 3])
def test_property_exact_reconstruction_and_invariants(repeat: int):
    cases = [
        ("Short claim", "Short claim is fully supported.", 1000),
        ("Late fact", "Noise. " * 40 + "The golden key is 12345.", 1200),
        ("CJK query", "北京观测中心报告空气质量指数良好。", 1000),
    ]
    builder = PreparedContextBuilder()
    for q, doc, budget in cases:
        group, _ = _make_candidate("s-prop", "doc-prop", doc)
        req = PrepareContextRequest(query=q, max_bytes=budget, evidence_selection=True)
        res = builder.build_scopes_result(request=req, current_scope_id="s-prop", memory_candidates=[group])
        _verify_envelope_and_invariants(res, budget, {"doc-prop": doc})
