"""Prompts for evidence-constrained research QA."""

from __future__ import annotations

from typing import Any, Sequence

SYSTEM_PROMPT = """你是 ResearchFlow 的科研问答助手。你只能依据下面提供的「文献证据」回答问题。

硬性规则：
1. 只能引用给出的证据编号（例如 c1、c2）。绝对不要编造证据编号、文件名或页码。
2. 每条论断必须标注类型：
   - "supported"：证据原文直接支持，必须在 citation_ids 中给出至少一个真实存在的证据编号。
   - "inferred"：由证据合理推断，但原文没有直说。citation_ids 必须为空，并在 statement 中说明推断依据。
   - "no_evidence"：证据中没有相关材料。citation_ids 必须为空。
3. 如果证据不足以回答问题，就明确说"知识库中没有相关材料"，不要凭常识或记忆补全。
4. 页码、数值、专有名词必须与证据原文完全一致，不得改写。
5. 回答用中文，简洁、准确、可核对。不要输出 markdown 标题以外的装饰性内容。

输出必须是严格的 JSON 对象，不要包裹代码块，格式如下：
{
  "answer": "对问题的直接回答，可以在句中用 [c1] 这样的标记指向证据",
  "answerable": true,
  "claims": [
    {"statement": "一条可核对的论断", "label": "supported", "citation_ids": ["c1"]}
  ],
  "missing": "如果 answerable 为 false，说明缺什么材料；否则为空字符串"
}"""

MEMORY_SYSTEM_NOTE = """另外提供了「历史任务记忆」（来自 PowerContext，标注为 memory）。
这部分是研究者此前保存的进度、决策与计划，**不是文献原文**。
使用规则：
- 可以把历史记忆用于说明"上次做到哪里、接下来做什么"。
- 绝对不要把历史记忆当作文献证据，也不要在 claims 的 citation_ids 中引用它。
- 如果历史记忆与文献证据冲突，以文献证据为准，并在 answer 中指出冲突。"""


def format_evidence(citations: Sequence[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for item in citations:
        blocks.append(
            f"[{item['citation_id']}] 文件={item['filename']} 物理页={item['page_no']} "
            f"chunk_id={item['chunk_id']} 相关度={item.get('relevance')}\n"
            f"---原文开始---\n{item['quote']}\n---原文结束---"
        )
    return "\n\n".join(blocks) if blocks else "（无）"


def format_memory(memory_context: dict[str, Any] | None) -> str:
    if not memory_context:
        return "（无历史记忆，或 PowerContext 不可用）"
    brief = memory_context.get("resume_brief") or ""
    hits = memory_context.get("prepared_context", {}).get("search_hits") or []
    parts = [f"项目：{memory_context.get('title', '')}", f"scope_id：{memory_context.get('scope_id')}"]
    if brief:
        parts.append("恢复摘要：\n" + brief)
    if hits:
        parts.append("PowerContext 记忆检索命中：")
        parts += [f"  - [{h.get('kind')}] {h.get('text')}" for h in hits[:6]]
    return "\n".join(parts)


def build_messages(
    question: str,
    citations: Sequence[dict[str, Any]],
    memory_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    system = SYSTEM_PROMPT
    if memory_context:
        system += "\n\n" + MEMORY_SYSTEM_NOTE
    user = f"【文献证据】（来自 seekdb，可点开原文核对）\n{format_evidence(citations)}"
    if memory_context:
        user += f"\n\n【历史任务记忆】（来自 PowerContext，非文献原文）\n{format_memory(memory_context)}"
    user += f"\n\n【问题】\n{question}\n\n请按规定 JSON 格式作答。"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


NO_EVIDENCE_ANSWER = (
    "知识库中没有与该问题相关的材料，因此无法给出有证据支撑的回答。\n"
    "这不代表答案不存在，只代表当前已上传的文档里检索不到相关内容。"
)
