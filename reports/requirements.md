# PowerContext 赛题十：按查询和预算选择原文证据 - 需求分析与契约设计

## 一、题目概况

- **赛题名称**：赛题十：按查询和预算选择原文证据（`context-01-evidence-selection`）
- **分值**：20 分（满分 240 分体系）
- **官方基线版本**：PowerContext v1.2.0（commit `9db1753434162c0aa7c9f1189a1722e617880a52`）
- **比赛分支**：`competition/query-aware-evidence-budget`
- **核心任务**：根据用户查询（Query），从检索召回的 Memory 候选记忆正文中选择真正相关的原始文本证据片段，确保最终输出的正文、引用和信封格式整体满足 UTF-8 字节预算（`max_bytes`），并保持严格的字符位置回查与原有接口兼容性。

---

## 二、评分子项与通过门槛

依据官方赛题指导规范，本题评分实行全有或全无（All-or-Nothing，全部通过得 20 分，任一失败得 0 分）：

| 验收类别 | 官方通过条件 |
| :--- | :--- |
| **查询驱动选择** | 根据 Query 识别相关原文片段，支持长文档非开头（中间、末尾）命中，不得始终截取前缀；同一候选集合替换 query 后反映不同证据需求。 |
| **真实原文与不变量** | 片段直接取自原始文本，严禁模型摘要、改写或翻译；保持半开字符区间 `0 <= start < end <= len(entry.text)`，且 `entry.text[start:end] == fragment.text` 严格成立。 |
| **精确位置与回查** | 记录片段在原始 Memory entry 中的字符坐标（半开 Python 字符索引，禁止 float/bool）；保留 scope、revision、entry_id、entry_version_id 完整 Citation。 |
| **UTF-8 总预算** | 预算以最终实际输出的完整上下文字符串为准，必须计入 trust policy、envelope 标记、JSON 序列化、citation 及正文；`content_bytes == len(content.encode('utf-8')) <= max_bytes`。 |
| **接口兼容性** | 默认关闭 `evidence_selection=False` 时，完全保留原有普通 prepare、Memory 排序、Topic Memory 和其他 Family 的上下文组装行为。 |
| **质量基准（评测）** | 24 个原始 claim，每个请求包含 3 篇原始摘要，1400 / 1800 字节两档预算（共 48 次请求）：<br>1. **证据词项召回**：48 次请求平均 evidence token recall 不低于 **0.65**；<br>2. **完整证据比例**：至少 **40%** 请求完整覆盖官方标注证据的全部字符区间。 |

---

## 三、公开接口与数据契约映射表

### 3.1 请求扩展：`PrepareContextRequest`

在 `powercontext.builtin.runtime.models.PrepareContextRequest` 及 `powercontext.http._generated.models.PrepareContextRequest` 中新增字段：

```python
class PrepareContextRequest(_PreparedContextModel):
    query: Annotated[str, Field(min_length=1, max_length=8192)]
    max_bytes: Annotated[int, Field(ge=512, le=32768)] = 8000
    assembly: ContextAssembly | None = None
    include_code: bool = Field(default=False, strict=True)
    evidence_selection: bool = Field(default=False, strict=True)  # 新增，默认 False
```

### 3.2 产物扩展：`PreparedContextBuild.fragments`

在 `powercontext.builtin.runtime.prepared_context` 中新增片段元组定义：

```python
@dataclass(frozen=True)
class EvidenceFragment:
    """Selected original evidence fragment with exact character coordinates."""
    address: MemoryEntryAddress
    start: int
    end: int
    text: str

@dataclass(frozen=True)
class PreparedContextBuild:
    context: PreparedContext
    origins: tuple[PreparedContextOrigin, ...]
    omissions: PreparedContextOmissions = PreparedContextOmissions()
    code_origins: tuple[CodeEvidenceRef, ...] = ()
    fragments: tuple[EvidenceFragment, ...] = ()  # 新增片段字段
```

### 3.3 输出信封格式：`PreparedContext.content`

当 `evidence_selection=True` 且存在合法输出时，`content` 遵循以下标准化 envelope：

```
PowerContext prepared untrusted historical context.

BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1
{"trust":"untrusted_history","items":[{"citation":{"scope_id":"...","memory_ref":{...},"entry_id":"...","entry_version_id":"..."},"content":"...","start":12,"end":85}]}
END_POWERCONTEXT_PREPARED_CONTEXT_V1
```

- 信封包含既有 trust policy。
- 信封标记 `BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1` 和 `END_POWERCONTEXT_PREPARED_CONTEXT_V1`。
- 中间 JSON 携带 `trust: "untrusted_history"` 与 `items` 数组。
- 每个 item 携带：
  - `citation`: 包含 `scope_id`, `memory_ref` (JSON dict), `entry_id`, `entry_version_id`。
  - `content`: 精确切片原文。
  - `start`, `end`: 原文字符坐标。
- 当候选无匹配或预算无法容纳任何合法证据时，输出 `status="empty", content=None, content_bytes=0, fragments=(), origins=()`。

---

## 四、核心约束与设计原则

1. **零改写不变量**：不得使用模型生成摘要，不得标准化或清洗原文中的标点、换行、数字。
2. **多语言词项与字词边界**：兼顾英文单词提取与中文（CJK）单字与二元语法，支持中英文混排、特殊符号与 Emoji。
3. **真实端到端开销计算**：将 JSON 字符转义（如双引号、反斜杠）和信封包装严格纳入 UTF-8 字节计算，杜绝生成后硬截断导致的破损 JSON。
4. **贪心证据合并**：同文档相邻或相交的已选片段执行自动合并，消除冗余 Citation 开销（每个 Citation 约 160-200 字节），留出更多预算容纳完整证据。
