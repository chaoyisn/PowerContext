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

"""Comprehensive unit and integration tests for Pi session branch ingestion and recovery."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from selftest_support.runtime_fixture import run_connector_persisted

from powercontext.builtin.runtime import open_builtin_runtime
from powercontext.sources import ConnectorBinding, SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pi_session import (
    PI_EVENT_SOURCE_DEFINITION,
    PiEventInput,
    PiSessionConnector,
    PiSessionInput,
    parse_pi_session,
    pi_event_source_id,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

evidence_store = importlib.import_module("challenges.source-02-pi-history.acceptance.evidence_store")


def make_jsonl_bytes(session_id: str, records: list[dict], with_bom: bool = False) -> bytes:
    header = {"type": "session", "version": 3, "id": session_id}
    lines = [json.dumps(row, ensure_ascii=False) for row in [header, *records]]
    raw = ("\n".join(lines) + "\n").encode("utf-8")
    if with_bom:
        raw = b"\xef\xbb\xbf" + raw
    return raw


# ============================================================================
# 1. Structural & Parsing Tests
# ============================================================================


def test_parse_single_branch_full_history():
    records = [
        {"type": "message", "id": "m1", "parentId": None, "message": {"role": "user", "content": "Hello"}},
        {"type": "message", "id": "m2", "parentId": "m1", "message": {"role": "assistant", "content": "Hi there"}},
        {"type": "message", "id": "m3", "parentId": "m2", "message": {"role": "user", "content": "Help me code"}},
    ]
    raw = make_jsonl_bytes("sess-1", records)
    events = parse_pi_session(PiSessionInput(content=raw))

    assert len(events) == 3
    assert [e.event_id for e in events] == ["m1", "m2", "m3"]
    assert [e.content for e in events] == ["user: Hello", "assistant: Hi there", "user: Help me code"]
    assert events[0].session_id == "sess-1"
    assert events[0].parent_id is None
    assert events[1].parent_id == "m1"
    assert events[2].parent_id == "m2"


def test_parse_multi_branch_fork_intermediate():
    # Tree:
    #      r0
    #     /  \
    #    a1   b1
    #   /      \
    #  a2       b2
    records = [
        {"type": "message", "id": "r0", "parentId": None, "message": {"role": "user", "content": "Root"}},
        {"type": "message", "id": "a1", "parentId": "r0", "message": {"role": "assistant", "content": "Branch A1"}},
        {"type": "message", "id": "b1", "parentId": "r0", "message": {"role": "assistant", "content": "Branch B1"}},
        {"type": "message", "id": "a2", "parentId": "a1", "message": {"role": "user", "content": "Branch A2"}},
        {"type": "message", "id": "b2", "parentId": "b1", "message": {"role": "user", "content": "Branch B2"}},
    ]
    raw = make_jsonl_bytes("tree-session", records)

    events_a = parse_pi_session(PiSessionInput(content=raw, leaf_id="a2"))
    assert [e.event_id for e in events_a] == ["r0", "a1", "a2"]
    assert [e.content for e in events_a] == ["user: Root", "assistant: Branch A1", "user: Branch A2"]

    events_b = parse_pi_session(PiSessionInput(content=raw, leaf_id="b2"))
    assert [e.event_id for e in events_b] == ["r0", "b1", "b2"]
    assert [e.content for e in events_b] == ["user: Root", "assistant: Branch B1", "user: Branch B2"]

    # Shared root has identical content and stable identity
    assert events_a[0].event_id == events_b[0].event_id
    assert pi_event_source_id(events_a[0].session_id, events_a[0].event_id) == pi_event_source_id(
        events_b[0].session_id, events_b[0].event_id
    )


def test_tool_calls_unicode_and_sorting():
    records = [
        {
            "type": "message",
            "id": "t1",
            "parentId": None,
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "toolCall",
                        "name": "search",
                        "id": "call-unicode",
                        "arguments": {"zebra": "斑马", "alpha": "阿尔法", "count": 10},
                    }
                ],
            },
        },
        {
            "type": "message",
            "id": "t2",
            "parentId": "t1",
            "message": {
                "role": "toolResult",
                "toolName": "search",
                "toolCallId": "call-unicode",
                "content": [{"type": "text", "text": "找到 10 条结果: 数据库"}],
            },
        },
    ]
    raw = make_jsonl_bytes("sess-tools", records)
    events = parse_pi_session(PiSessionInput(content=raw))

    assert len(events) == 2
    # Ensure keys are sorted, unicode is not escaped (\uXXXX), and no extra whitespace
    expected_args = '{"alpha":"阿尔法","count":10,"zebra":"斑马"}'
    assert events[0].content == f"assistant: [tool_call search call-unicode] {expected_args}"
    assert events[1].content == "toolResult: [tool_result search call-unicode] 找到 10 条结果: 数据库"


def test_mixed_blocks_and_filtering():
    records = [
        {
            "type": "message",
            "id": "m_mixed",
            "parentId": None,
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "Let me think deeply..."},
                    {"type": "image", "data": "base64image..."},
                    {"type": "text", "text": "Step 1: Inspecting files"},
                    {"type": "toolCall", "name": "ls", "id": "call-ls", "arguments": {"dir": "/"}},
                    {"type": "text", "text": "Step 2: Analysis complete"},
                ],
            },
        }
    ]
    raw = make_jsonl_bytes("sess-mixed", records)
    events = parse_pi_session(PiSessionInput(content=raw))

    assert len(events) == 1
    expected_content = (
        'assistant: Step 1: Inspecting files\n[tool_call ls call-ls] {"dir":"/"}\nStep 2: Analysis complete'
    )
    assert events[0].content == expected_content


def test_control_nodes_skipped_without_breaking_chain():
    records = [
        {"type": "message", "id": "m1", "parentId": None, "message": {"role": "user", "content": "Start"}},
        {"type": "model_change", "id": "c1", "parentId": "m1", "model": "gpt-4"},
        {"type": "thinking_level_change", "id": "c2", "parentId": "c1", "level": 2},
        {"type": "message", "id": "m2", "parentId": "c2", "message": {"role": "assistant", "content": "Done"}},
    ]
    raw = make_jsonl_bytes("sess-ctrl", records)
    events = parse_pi_session(PiSessionInput(content=raw))

    assert len(events) == 2
    assert [e.event_id for e in events] == ["m1", "m2"]
    assert [e.content for e in events] == ["user: Start", "assistant: Done"]
    assert events[1].parent_id == "c2"


@pytest.mark.parametrize(
    "corrupt_raw",
    [
        b"",
        b"\n\n",
        b"not json\n",
        b'{"type": "not_session"}\n',
        b'{"type": "session", "version": 2, "id": "s"}\n',
        b'{"type": "session", "version": 3, "id": ""}\n',
        b'{"type": "session", "version": 3, "id": " "}\n',
    ],
)
def test_invalid_header_rejections(corrupt_raw):
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=corrupt_raw))


def test_missing_or_forward_parent_rejections():
    # Forward parent reference (p2 references p3 which appears after p2)
    records = [
        {"type": "message", "id": "p2", "parentId": "p3", "message": {"role": "user", "content": "Forward"}},
        {"type": "message", "id": "p3", "parentId": None, "message": {"role": "assistant", "content": "Target"}},
    ]
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=make_jsonl_bytes("s", records)))


def test_duplicate_record_id_rejection():
    records = [
        {"type": "message", "id": "dup", "parentId": None, "message": {"role": "user", "content": "One"}},
        {"type": "message", "id": "dup", "parentId": "dup", "message": {"role": "assistant", "content": "Two"}},
    ]
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=make_jsonl_bytes("s", records)))


def test_leaf_not_found_rejection():
    records = [
        {"type": "message", "id": "m1", "parentId": None, "message": {"role": "user", "content": "Hi"}},
    ]
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=make_jsonl_bytes("s", records), leaf_id="nonexistent"))


# ============================================================================
# 2. Source & Projection Integrity Tests
# ============================================================================


async def test_source_resolution_read_roundtrip():
    registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
    raw_record = {"type": "message", "id": "ev-1", "parentId": None, "message": {"role": "user", "content": "Test"}}
    event_input = PiEventInput(
        session_id="test-sess",
        event_id="ev-1",
        parent_id=None,
        event_type="message",
        role="user",
        content="user: Test",
        record=raw_record,
    )

    source = await registry.resolve(event_input)
    assert source.name == "pi:test-sess:ev-1"
    assert source.source_id == "pi:test-sess:ev-1"

    read_back = await registry.read(source)
    assert read_back == event_input
    assert read_back.record == raw_record

    observation = project_source_for_transport(registry, source)
    evidence = observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)
    assert evidence["source_type"] == "pi-event"
    assert evidence["source_id"] == source.name
    assert evidence["content"] == "user: Test"
    assert evidence["metadata"] == {
        "session_id": "test-sess",
        "event_id": "ev-1",
        "parent_id": None,
        "event_type": "message",
        "role": "user",
    }


async def test_large_tool_output_untruncated(tmp_path: Path):
    large_payload = "A" * 150000  # 150 KB
    records = [
        {
            "type": "message",
            "id": "t_large",
            "parentId": None,
            "message": {
                "role": "toolResult",
                "toolName": "fetch_huge",
                "toolCallId": "call-big",
                "content": [{"type": "text", "text": large_payload}],
            },
        }
    ]
    raw = make_jsonl_bytes("sess-big", records)
    events = parse_pi_session(PiSessionInput(content=raw))

    assert len(events) == 1
    assert len(events[0].content) > 150000
    assert events[0].content.startswith("toolResult: [tool_result fetch_huge call-big] ")

    registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
    observation = project_source_for_transport(registry, await registry.resolve(events[0]))
    config, scope_id, stored = await evidence_store.persist_events(tmp_path, PI_EVENT_SOURCE_DEFINITION, [observation])

    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        found = await evidence_store.search_events(memory, "toolResult", stored)
        assert observation.name in {s.name for s in found}
        stored_source = stored[observation.name]
        assert stored_source.projections[0].value["content"] == events[0].content


# ============================================================================
# 3. Incremental, Checkpoint & Recovery Tests
# ============================================================================


def write_session_file(path: Path, session_id: str, records: list[dict]):
    path.write_bytes(make_jsonl_bytes(session_id, records))


async def test_incremental_repeated_three_times(tmp_path: Path):
    """Verify stability across multiple repeated runs with branches and appends."""
    for iteration in range(3):
        iter_dir = tmp_path / f"iter_{iteration}"
        iter_dir.mkdir(parents=True, exist_ok=True)
        session_file = iter_dir / "session.jsonl"

        records = [
            {"type": "message", "id": "n0", "parentId": None, "message": {"role": "user", "content": "Init"}},
            {"type": "message", "id": "n1", "parentId": "n0", "message": {"role": "assistant", "content": "Left"}},
        ]
        write_session_file(session_file, f"sess-{iteration}", records)

        binding = ConnectorBinding(
            scope_id=f"scope-{iteration}",
            binding_id="pi-binding",
            connector_name="pi-session-history",
            connector_version="1",
        )

        async def run_conn(leaf, _dir=iter_dir, _file=session_file, _binding=binding):
            return await run_connector_persisted(
                _dir, PI_EVENT_SOURCE_DEFINITION, PiSessionConnector(_file, leaf), _binding
            )

        # 1. Initial capture
        res1, entries1 = await run_conn("n1")
        assert len(res1.items) == 2
        assert len(entries1) == 2

        # 2. Idempotent re-run
        res2, entries2 = await run_conn("n1")
        assert len(res2.items) == 0
        assert len(entries2) == 2
        assert res2.committed_checkpoint == res1.committed_checkpoint

        # 3. Switch branch
        records.append(
            {"type": "message", "id": "n2", "parentId": "n0", "message": {"role": "assistant", "content": "Right"}}
        )
        write_session_file(session_file, f"sess-{iteration}", records)
        res3, entries3 = await run_conn("n2")
        assert len(res3.items) == 1  # Only n2 submitted
        assert len(entries3) == 3

        # 4. Append to current branch
        records.append(
            {"type": "message", "id": "n3", "parentId": "n2", "message": {"role": "user", "content": "Followup"}}
        )
        write_session_file(session_file, f"sess-{iteration}", records)
        res4, entries4 = await run_conn("n3")
        assert len(res4.items) == 1
        assert len(entries4) == 4

        # 5. Mutate historical record n0 -> must fail atomically
        records[0]["message"]["content"] = "Mutated Init"
        write_session_file(session_file, f"sess-{iteration}", records)
        with pytest.raises(ValueError, match="mutated"):
            await run_conn("n3")

        # 6. Revert mutation -> resumes safely
        records[0]["message"]["content"] = "Init"
        write_session_file(session_file, f"sess-{iteration}", records)
        res_revert, entries_revert = await run_conn("n3")
        assert len(res_revert.items) == 0
        assert len(entries_revert) == 4
        assert res_revert.committed_checkpoint == res4.committed_checkpoint


async def test_scope_isolation(tmp_path: Path):
    session_file = tmp_path / "scope_test.jsonl"
    records = [
        {"type": "message", "id": "root", "parentId": None, "message": {"role": "user", "content": "Scope Root"}},
    ]
    write_session_file(session_file, "scope-session", records)

    binding_a = ConnectorBinding(
        scope_id="scope-A", binding_id="pi", connector_name="pi-session-history", connector_version="1"
    )
    binding_b = ConnectorBinding(
        scope_id="scope-B", binding_id="pi", connector_name="pi-session-history", connector_version="1"
    )

    res_a, entries_a = await run_connector_persisted(
        tmp_path, PI_EVENT_SOURCE_DEFINITION, PiSessionConnector(session_file), binding_a, database_name="db_a.db"
    )
    res_b, entries_b = await run_connector_persisted(
        tmp_path, PI_EVENT_SOURCE_DEFINITION, PiSessionConnector(session_file), binding_b, database_name="db_b.db"
    )

    assert len(res_a.items) == 1
    assert len(res_b.items) == 1
    assert len(entries_a) == 1
    assert len(entries_b) == 1
