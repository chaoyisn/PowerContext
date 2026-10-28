"""Evidence-grounded QA tests.

The LLM is stubbed here so citation validation is tested deterministically; the live
end-to-end call against DeepSeek is exercised by scripts/run_acceptance.py.
"""

from __future__ import annotations

import json

import pytest

from app.agent import service as agent
from app.agent.llm import LLMGateway, LLMResponse
from app.agent.prompts import NO_EVIDENCE_ANSWER, build_messages, format_evidence
from app.agent.service import _extract_json, _page_exists

from .conftest import PDF_NAME, requires_seekdb

pytestmark = requires_seekdb

ANSWERABLE = "which full text analyzer segments Chinese correctly"
UNANSWERABLE = "这篇文档里有没有关于量子纠缠实验的测量结果"


class StubLLM:
    """Stand-in for LLMGateway with the same surface used by answer_question."""

    def __init__(self, payload, *, enabled: bool = True, raw: str | None = None) -> None:
        self.payload = payload
        self.enabled = enabled
        self.raw = raw if raw is not None else json.dumps(payload, ensure_ascii=False)
        self.calls: list[list[dict[str, str]]] = []

    def info(self) -> dict:
        return {"enabled": self.enabled, "provider": "stub", "model": "stub-model"}

    def chat(self, messages, **kwargs) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(
            content=self.raw,
            model="stub-model",
            prompt_tokens=10,
            completion_tokens=20,
            elapsed_ms=1.0,
            provider="stub",
        )


# --------------------------------------------------------------- retrieval-only


async def test_retrieval_only_mode_is_labelled_and_never_pretends_to_be_an_answer(
    store, embeddings, settings, ingested
):
    disabled = LLMGateway(settings)
    assert disabled.enabled is False, "tests run without RF_LLM_API_KEY"

    result = await agent.answer_question(
        store, embeddings, disabled, ANSWERABLE, mode="hybrid", top_k=3, settings=settings
    )
    assert result.mode == "retrieval_only"
    assert result.answer.startswith("【仅检索模式】")
    assert result.citations, "real evidence must still be returned"
    assert result.citations[0]["source"] == "document"
    assert result.citations[0]["filename"] == PDF_NAME
    assert result.citations[0]["page_no"] == 3
    assert result.llm["enabled"] is False
    assert result.llm["reason"], "the reason for retrieval-only mode must be stated"


async def test_unanswerable_question_yields_no_evidence_and_no_citation(
    store, embeddings, settings, ingested
):
    disabled = LLMGateway(settings)
    result = await agent.answer_question(
        store, embeddings, disabled, UNANSWERABLE, mode="hybrid", top_k=5, settings=settings
    )
    assert result.answerable is False
    assert result.citations == []
    assert result.used_citations == []
    assert result.answer == NO_EVIDENCE_ANSWER
    assert len(result.claims) == 1
    assert result.claims[0].label == "no_evidence"
    assert result.claims[0].citation_ids == []
    assert result.label_summary["no_evidence"] == 1
    assert result.missing, "the response must explain that nothing passed the gate"


# --------------------------------------------------------------- citation checks


async def test_valid_citations_are_accepted_and_reported(store, embeddings, settings, ingested):
    stub = StubLLM(
        {
            "answer": "ik 分析器能正确切分中文 [c1]。",
            "answerable": True,
            "claims": [
                {"statement": "ik 分析器能正确切分中文", "label": "supported", "citation_ids": ["c1"]}
            ],
            "missing": "",
        }
    )
    result = await agent.answer_question(
        store, embeddings, stub, ANSWERABLE, mode="hybrid", top_k=3, settings=settings
    )
    assert result.mode == "grounded"
    assert result.invalid_citations == []
    assert len(result.used_citations) == 1
    assert result.used_citations[0]["citation_id"] == "c1"
    assert result.claims[0].label == "supported"
    assert result.llm["json_parsed"] is True
    assert stub.calls, "the LLM must actually have been called"


async def test_invented_citations_are_rejected_and_stripped(store, embeddings, settings, ingested):
    stub = StubLLM(
        {
            "answer": "结论来自 [c1] 和 [c99]。",
            "answerable": True,
            "claims": [
                {"statement": "编造引用的论断", "label": "supported", "citation_ids": ["c99"]},
                {"statement": "真实引用的论断", "label": "supported", "citation_ids": ["c1"]},
            ],
            "missing": "",
        }
    )
    result = await agent.answer_question(
        store, embeddings, stub, ANSWERABLE, mode="hybrid", top_k=3, settings=settings
    )
    reasons = {item["citation_id"]: item["reason"] for item in result.invalid_citations}
    assert reasons.get("c99") == "not_in_retrieval_result"
    assert "[c99]" not in result.answer, "a fabricated citation marker must be removed"
    assert "[c1]" in result.answer

    downgraded = [claim for claim in result.claims if claim.downgraded]
    assert len(downgraded) == 1
    assert downgraded[0].label == "inferred"
    assert downgraded[0].citation_ids == []
    assert downgraded[0].downgrade_reason == "no_valid_citation_survived_validation"
    assert result.label_summary["supported"] == 1


async def test_inferred_and_no_evidence_claims_cannot_carry_citations(
    store, embeddings, settings, ingested
):
    stub = StubLLM(
        {
            "answer": "推断结论。",
            "answerable": True,
            "claims": [
                {"statement": "推断", "label": "inferred", "citation_ids": ["c1"]},
                {"statement": "无证据", "label": "no_evidence", "citation_ids": ["c1"]},
                {"statement": "未知标签", "label": "guessed", "citation_ids": []},
            ],
            "missing": "",
        }
    )
    result = await agent.answer_question(
        store, embeddings, stub, ANSWERABLE, mode="hybrid", top_k=3, settings=settings
    )
    by_statement = {claim.statement: claim for claim in result.claims}
    assert by_statement["推断"].citation_ids == []
    assert by_statement["无证据"].citation_ids == []
    assert by_statement["未知标签"].label == "inferred", "unknown labels fall back to inferred"


async def test_unparseable_llm_output_is_reported_not_hidden(store, embeddings, settings, ingested):
    stub = StubLLM(payload=None, raw="这不是 JSON，只是一段普通文本。")
    result = await agent.answer_question(
        store, embeddings, stub, ANSWERABLE, mode="hybrid", top_k=3, settings=settings
    )
    assert result.llm["json_parsed"] is False
    assert result.answer == "这不是 JSON，只是一段普通文本。"
    assert result.claims[0].downgrade_reason == "llm_json_parse_failed"
    assert result.claims[0].label == "inferred"


async def test_memory_is_passed_to_the_llm_as_a_separate_channel(
    store, embeddings, settings, ingested, gateway
):
    from app.memory import service as memory
    from app.memory.models import ResearchProgress

    project_id = "t-qa-memory"
    await memory.create_project(
        store, gateway, project_id=project_id, title="QA 记忆通道测试", settings=settings
    )
    await memory.save_progress(
        store,
        gateway,
        ResearchProgress(
            project_id=project_id,
            title="QA 记忆通道测试",
            decisions=["D9: 默认检索模式为 hybrid"],
            next_steps=["验证记忆与证据分通道"],
            confirmed_by="pytest",
        ),
        settings,
    )

    stub = StubLLM(
        {
            "answer": "ik [c1]",
            "answerable": True,
            "claims": [{"statement": "ik", "label": "supported", "citation_ids": ["c1"]}],
            "missing": "",
        }
    )
    result = await agent.answer_question(
        store,
        embeddings,
        stub,
        ANSWERABLE,
        mode="hybrid",
        top_k=3,
        project_id=project_id,
        gateway=gateway,
        settings=settings,
    )
    assert result.memory is not None
    assert result.memory["source"] == "memory"
    assert result.memory["memory_available"] is True
    user_message = stub.calls[0][1]["content"]
    assert "【文献证据】" in user_message and "【历史任务记忆】" in user_message
    assert "非文献原文" in user_message
    assert "D9: 默认检索模式为 hybrid" in user_message


async def test_qa_survives_a_powercontext_outage(store, embeddings, settings, ingested):
    from app.config import Settings
    from app.memory.client import PowerContextGateway

    dead = PowerContextGateway(
        Settings(
            **{
                **settings.model_dump(),
                "powercontext_url": "http://127.0.0.1:17999",
                "powercontext_timeout": 3.0,
            }
        )
    )
    stub = StubLLM(
        {
            "answer": "ik [c1]",
            "answerable": True,
            "claims": [{"statement": "ik", "label": "supported", "citation_ids": ["c1"]}],
            "missing": "",
        }
    )
    result = await agent.answer_question(
        store,
        embeddings,
        stub,
        ANSWERABLE,
        mode="hybrid",
        top_k=3,
        project_id="t-qa-memory",
        gateway=dead,
        settings=settings,
    )
    assert result.mode == "grounded", "QA must not depend on PowerContext"
    assert result.citations
    assert result.memory is not None and result.memory.get("memory_available") is False


# --------------------------------------------------------------- prompt & parsing


def test_extract_json_handles_fences_and_prose():
    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('here you go: {"a": 1} hope that helps') == {"a": 1}
    assert _extract_json("no json here") is None
    assert _extract_json("[1, 2, 3]") is None


def test_prompt_lists_evidence_with_real_page_numbers(ingested):
    citations = [
        {
            "citation_id": "c1",
            "filename": PDF_NAME,
            "page_no": 3,
            "chunk_id": "x:p0003:c000",
            "relevance": 0.8,
            "quote": "the ik analyzer segments Chinese",
        }
    ]
    rendered = format_evidence(citations)
    assert "物理页=3" in rendered and "chunk_id=x:p0003:c000" in rendered
    assert "---原文开始---" in rendered

    messages = build_messages("问题", citations, None)
    assert messages[0]["role"] == "system"
    assert "绝对不要编造证据编号" in messages[0]["content"]
    assert "no_evidence" in messages[0]["content"]
    assert "【历史任务记忆】" not in messages[1]["content"]


def test_page_exists_check_reads_seekdb(store, settings, ingested):
    pdf = ingested[PDF_NAME]
    assert _page_exists(store, pdf.doc_id, 5, settings) is True
    assert _page_exists(store, pdf.doc_id, 4, settings) is True, "the blank page still exists"
    assert _page_exists(store, pdf.doc_id, 6, settings) is False
    assert _page_exists(store, "0" * 64, 1, settings) is False


async def test_unused_evidence_is_reported(store, embeddings, settings, ingested):
    stub = StubLLM(
        {
            "answer": "ik [c1]",
            "answerable": True,
            "claims": [{"statement": "ik", "label": "supported", "citation_ids": ["c1"]}],
            "missing": "",
        }
    )
    result = await agent.answer_question(
        store, embeddings, stub, ANSWERABLE, mode="hybrid", top_k=5, settings=settings
    )
    unused = agent.unused_evidence(result)
    used_ids = {c["citation_id"] for c in result.used_citations}
    assert all(c["citation_id"] not in used_ids for c in unused)
    assert len(unused) + len(result.used_citations) == len(result.citations)
