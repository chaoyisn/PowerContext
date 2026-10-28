"""Evidence-grounded research QA.

The answer is produced from seekdb hits that already passed the relevance gate, and every
citation the model returns is re-validated against seekdb before it reaches the user:
unknown ids are dropped, and a ``supported`` claim left without a valid citation is
downgraded to ``inferred``. Document evidence and PowerContext memory are kept in
separate labelled channels throughout.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

from ..config import Settings, get_settings
from ..db.seekdb import SeekDBStore
from ..errors import NotFoundError
from ..logging_setup import get_logger
from ..memory import service as memory_service
from ..memory.client import PowerContextGateway
from ..retrieval import service as retrieval_service
from ..retrieval.embeddings import EmbeddingBackend
from .llm import LLMGateway
from .prompts import NO_EVIDENCE_ANSWER, build_messages

logger = get_logger(__name__)

AnswerMode = Literal["grounded", "retrieval_only"]
ClaimLabel = Literal["supported", "inferred", "no_evidence"]
_VALID_LABELS = {"supported", "inferred", "no_evidence"}
_CITATION_TOKEN = re.compile(r"\b(c\d{1,3})\b")


@dataclass
class Claim:
    statement: str
    label: str
    citation_ids: list[str] = field(default_factory=list)
    downgraded: bool = False
    downgrade_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnswerResult:
    question: str
    mode: AnswerMode
    answerable: bool
    answer: str
    claims: list[Claim] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    used_citations: list[dict[str, Any]] = field(default_factory=list)
    invalid_citations: list[dict[str, Any]] = field(default_factory=list)
    missing: str = ""
    retrieval: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] | None = None
    llm: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    @property
    def label_summary(self) -> dict[str, int]:
        summary = {label: 0 for label in _VALID_LABELS}
        for claim in self.claims:
            summary[claim.label] = summary.get(claim.label, 0) + 1
        return summary

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["claims"] = [claim.to_dict() for claim in self.claims]
        payload["label_summary"] = self.label_summary
        return payload


def _extract_json(content: str) -> dict[str, Any] | None:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _page_exists(store: SeekDBStore, doc_id: str, page_no: int, settings: Settings) -> bool:
    """Cross-check a citation against the stored page rows, so no phantom page can slip through."""
    try:
        rows = store.query(
            f"SELECT page_id FROM `{settings.pages_table}` WHERE doc_id = %s AND page_no = %s",
            (doc_id, page_no),
        )
        return bool(rows)
    except Exception:
        return False


async def answer_question(
    store: SeekDBStore,
    backend: EmbeddingBackend,
    llm: LLMGateway,
    question: str,
    *,
    mode: str = "hybrid",
    top_k: int | None = None,
    project_id: str | None = None,
    filters: dict[str, Any] | None = None,
    gateway: PowerContextGateway | None = None,
    settings: Settings | None = None,
) -> AnswerResult:
    from starlette.concurrency import run_in_threadpool

    settings = settings or get_settings()
    started = time.perf_counter()
    text = (question or "").strip()

    limit = int(top_k or settings.qa_max_evidence_chunks)
    retrieval = await run_in_threadpool(
        lambda: retrieval_service.search(
            store, backend, text, mode=mode, top_k=limit, filters=filters, apply_gate=True,
            settings=settings,
        )
    )
    citations = retrieval.citations
    result = AnswerResult(
        question=text,
        mode="grounded" if llm.enabled else "retrieval_only",
        answerable=bool(citations),
        answer="",
        citations=citations,
        retrieval=retrieval.to_dict(),
        llm=llm.info(),
    )

    memory_context: dict[str, Any] | None = None
    if project_id and gateway is not None:
        try:
            restored = await memory_service.restore_progress(
                store, gateway, project_id, query=text, settings=settings
            )
            memory_context = restored.to_dict()
        except NotFoundError as exc:
            memory_context = {"available": False, "error": str(exc), "source": "memory"}
        except Exception as exc:
            # Memory is an enhancement here, never a hard dependency of QA.
            memory_context = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
                "source": "memory",
            }
            logger.warning("memory context unavailable for QA", fields={"error": str(exc)})
    result.memory = memory_context

    if not citations:
        result.mode = "retrieval_only"
        result.answerable = False
        result.answer = NO_EVIDENCE_ANSWER
        result.missing = (
            f"检索模式 {mode} 在 {retrieval.backend.get('collection')} 中没有找到通过相关性门控的材料"
            f"（原始命中 {len(retrieval.hits) + retrieval.dropped_by_gate} 条，"
            f"被门控剔除 {retrieval.dropped_by_gate} 条）。"
        )
        result.claims = [
            Claim(statement=text, label="no_evidence", citation_ids=[]),
        ]
        result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "qa without evidence", fields={"question": text[:60], "mode": mode, "ms": result.elapsed_ms}
        )
        return result

    if not llm.enabled:
        result.mode = "retrieval_only"
        result.answer = (
            "【仅检索模式】未配置 LLM（RF_LLM_API_KEY 为空），以下是 seekdb 检索到的原始证据，"
            "不是模型生成的回答。\n\n"
            + "\n\n".join(
                f"[{c['citation_id']}] {c['filename']} 第 {c['page_no']} 页（相关度 {c['relevance']}）\n{c['quote']}"
                for c in citations
            )
        )
        result.claims = [
            Claim(
                statement=f"检索到 {len(citations)} 条通过门控的证据，未调用模型作答",
                label="supported",
                citation_ids=[c["citation_id"] for c in citations],
            )
        ]
        result.used_citations = citations
        result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return result

    messages = build_messages(text, citations, memory_context if memory_context and memory_context.get("memory_available") else None)
    response = await run_in_threadpool(lambda: llm.chat(messages))
    parsed = _extract_json(response.content)

    valid_ids = {c["citation_id"] for c in citations}
    if parsed is None:
        result.answer = response.content.strip()
        result.claims = [
            Claim(
                statement="模型未返回规定的 JSON 结构，以下为原始输出，未经论断分类",
                label="inferred",
                citation_ids=[],
                downgrade_reason="llm_json_parse_failed",
            )
        ]
        result.invalid_citations = [
            {"citation_id": token, "reason": "unparsed_response"}
            for token in sorted(set(_CITATION_TOKEN.findall(result.answer)) - valid_ids)
        ]
        result.llm.update(
            {
                "model_returned": response.model,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "elapsed_ms": response.elapsed_ms,
                "json_parsed": False,
            }
        )
        result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return result

    result.answer = str(parsed.get("answer", "")).strip()
    result.answerable = bool(parsed.get("answerable", bool(citations)))
    result.missing = str(parsed.get("missing", "") or "")

    by_id = {c["citation_id"]: c for c in citations}
    used_ids: set[str] = set()
    for raw_claim in parsed.get("claims") or []:
        if not isinstance(raw_claim, dict):
            continue
        label = str(raw_claim.get("label", "inferred")).strip().lower()
        if label not in _VALID_LABELS:
            label = "inferred"
        requested = [str(cid).strip() for cid in (raw_claim.get("citation_ids") or [])]
        accepted: list[str] = []
        for cid in requested:
            if cid in valid_ids:
                citation = by_id[cid]
                if _page_exists(store, citation["doc_id"], citation["page_no"], settings):
                    accepted.append(cid)
                    used_ids.add(cid)
                else:
                    result.invalid_citations.append(
                        {
                            "citation_id": cid,
                            "reason": "page_not_found_in_seekdb",
                            "doc_id": citation["doc_id"],
                            "page_no": citation["page_no"],
                        }
                    )
            else:
                result.invalid_citations.append(
                    {"citation_id": cid, "reason": "not_in_retrieval_result"}
                )
        claim = Claim(
            statement=str(raw_claim.get("statement", "")).strip(),
            label=label,
            citation_ids=accepted,
        )
        if label == "supported" and not accepted:
            claim.label = "inferred"
            claim.downgraded = True
            claim.downgrade_reason = "no_valid_citation_survived_validation"
        if claim.label != "supported" and accepted:
            # Only "supported" claims may carry citations; keep the contract tight.
            claim.citation_ids = []
        if claim.statement:
            result.claims.append(claim)

    # Strip citation markers that point at nothing.
    for invalid in result.invalid_citations:
        token = f"[{invalid['citation_id']}]"
        if token in result.answer:
            result.answer = result.answer.replace(token, "")

    result.used_citations = [by_id[cid] for cid in sorted(used_ids, key=lambda x: int(x[1:]))]
    result.llm.update(
        {
            "model_returned": response.model,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "elapsed_ms": response.elapsed_ms,
            "json_parsed": True,
        }
    )
    result.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "qa answered",
        fields={
            "question": text[:60],
            "evidence": len(citations),
            "used": len(result.used_citations),
            "invalid": len(result.invalid_citations),
            "labels": json.dumps(result.label_summary, ensure_ascii=False),
            "ms": result.elapsed_ms,
        },
    )
    return result


def retrieval_only_payload(result: AnswerResult) -> dict[str, Any]:
    """Compact view used by the UI when the LLM is disabled."""
    return {
        "mode": result.mode,
        "answer": result.answer,
        "citations": result.citations,
        "label_summary": result.label_summary,
    }


def unused_evidence(result: AnswerResult) -> Sequence[dict[str, Any]]:
    used = {c["citation_id"] for c in result.used_citations}
    return [c for c in result.citations if c["citation_id"] not in used]
