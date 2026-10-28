# PowerContext 赛题十：跨题兼容性与后续整合分析报告

本文档针对 OceanBase 第六届数据库大赛 PowerContext 各赛题的统一整合目标，深入分析「赛题十：按查询和预算选择原文证据（`context-01-evidence-selection`）」与赛题二、赛题三、赛题五、赛题六、赛题九之间的技术协同、潜在冲突点、数据契约风险，并制定明确的未来整合方案与冲突消解策略。

---

## 一、跨题概览与技术交汇矩阵

在 PowerContext 整体架构中，赛题十作用于 **Runtime Prepare 上下文组装阶段**（即检索后召回 Memory 候选，至最终格式化上下文字符串之间的精细化片段选择与预算控制）。

各赛题与赛题十的技术交汇矩阵如下：

| 赛题编号与主题 | 作用层级 / 模块 | 与赛题十的交汇点 | 风险等级 |
| :--- | :--- | :--- | :--- |
| **赛题二：CSV 数据源与列序** | Ingestion & Source 存储 | 表格/CSV 转化生成的 Memory entry 文本格式与字符坐标定位 | 低-中 |
| **赛题三：Pi 会话与工具事件** | Ingestion & Event 记忆 | 多轮对话、工具调用事件（JSON/Tool Call）的原文片段提取 | 低-中 |
| **赛题五：HTTP Rerank 重排** | Retrieval & Ranking | 候选 MemoryHits 评分重排，影响赛题十的候选输入排序与打分 | 中 |
| **赛题六：上下文增量分包** | Runtime Prepare / Context Assembly | 增量分包指纹、Token/Byte 预算计算、Citation 结构与客户端上下文重建 | **高（核心交汇）** |
| **赛题九：来源撤回与失效** | Memory Revision / Storage Retraction | 撤回或失效的 Source/Entry 不得被选入证据，历史快照与回查一致性 | 中 |

---

## 二、逐题冲突深度分析与整合方案

### 2.1 赛题二（CSV）：行级 Source 与原始列顺序下的证据定位

#### 1. 机制与表现
- 赛题二通常将 CSV、结构化表格解析为结构化或半结构化正文存储在 Memory entry 中，或者保留原始 CSV 行格式（如 RFC 4180、TSV 或 Markdown Table）。
- 赛题十基于 Python Unicode 原文字符串索引 `[start, end)` 进行切片：`entry.text[start:end]`。

#### 2. 潜在冲突与风险
- **换行符差异**：CSV 解析若在 Windows (`\r\n`) 与 POSIX (`\n`) 之间发生转换或清洗，会导致 Memory entry 的 `entry.text` 长度与原始上传文件产生字符偏移偏差。
- **列重排或格式化丢失**：若检索阶段将 CSV 重新排版为 `Column: Value` 形式，返回的 `start/end` 仅代表该 Memory entry 内部的坐标，无法直接映射回原始 CSV 文件的 byte offset 或 row number。

#### 3. 整合解决方案
- **坚持以存储层 Memory entry 正文为基准**：赛题十严格保证 `entry.text[start:end] == fragment.text` 不变量。无论上游是 CSV 还是纯文本，赛题十的分词器 `_tokenize_evidence_text` 支持英文/数字/CJK 符号，能自然对齐 CSV 中的字段值和单元格文本。
- **换行与定界符保护**：分句切分器中对 `,`、`\t`、`\r\n` 保持原样不变量，分词与打分时仅将标点视为边界，不改变原始文本切片。

---

### 2.2 赛题三（Pi）：会话消息、工具事件与原始证据定位

#### 1. 机制与表现
- 赛题三涉及 Agent 会话上下文，包括 `user`、`assistant`、`tool_use`、`tool_result` 等结构化 JSON 消息。
- 会话正文通常包含大段 JSON 参数或代码块。

#### 2. 潜在冲突与风险
- **JSON 语法截断风险**：赛题十通过句子级或子句级切片（基于句号、分号、换行符）选取高相关片段。若工具事件正文是一段大型 JSON，按换行或逗号切片可能会破坏 JSON 结构语法。
- **Tool call 嵌套格式**：若片段切片只截取了 JSON 的 `{"result": ...` 的一半，前端反序列化或大模型阅读时可能产生格式困惑。

#### 3. 整合解决方案
- **文本证据语义定位**：赛题十定位的是“证据文本片段”，外层通过标准的 envelope JSON 包装返回，输出信封保证外层 JSON 绝不破损。
- **信封内安全转义**：赛题十的 `_evidence_envelope_bytes` 精确计算了任何转义字符（如 `\"`、`\\`、`\n`）的开销，确保工具事件内的特殊符号和转义序列在输出 envelope 中 100% 格式合法且可被标准 JSON 解析器解析。

---

### 2.3 赛题五（HTTP Rerank）：候选重排与片段打分的协同

#### 1. 机制与表现
- 赛题五在检索层引入外部 HTTP Rerank 服务（如 bge-reranker、cross-encoder 等），对向量检索或 FTS 召回的候选进行语义重排，输出新的 `score`。
- 赛题十则在候选 Memory 内部针对当前 Query 进行句子级细粒度打分（BM25 + coverage + phrase + numeric boost）。

#### 2. 潜在冲突与风险
- **打分量纲不一致**：Rerank 返回的通常是全局语义相关度（Logits、归一化概率或浮点分数），而赛题十内部片段打分是局部词频与覆盖率分数。
- **排序覆盖偏置**：若过度偏向 Rerank 排名第一的 Memory，可能导致分配给排名前列文档的较弱片段，而忽略了排名第二文档中的极高相关关键证据。

#### 3. 整合解决方案
- **分层打分与动态加权**：
  在赛题五整合后，赛题十计算片段分数时可将 Memory 维度的 Reranker 分数作为文档级先验权重（Document Prior），例如：
  $$\text{FinalScore}(\text{fragment}) = \text{Score}_{\text{local}}(\text{fragment}) \times (1 + \alpha \cdot \text{NormalizedRerankScore}(\text{doc}))$$
- **全局候选贪心池**：赛题十在候选阶段将所有召回 Memory 的片段统一入池，按全局得分降序排列，不仅支持单文档命中，也能跨多个来源自然覆盖最高相关片段。

---

### 2.4 赛题六（上下文增量）：Prepare 模块、Citation 与分包重构（重点）

#### 1. 机制与表现
- 赛题六引入增量上下文同步（Context Delta Pack），只向客户端传输当前轮次新增或变更的上下文片段，避免重复发送历史上下文。
- 赛题六和赛题十都修改了 `PrepareContextRequest`、`PreparedContext` 和 `prepared_context.py` 中的装配管线。

#### 2. 核心冲突点分析
1. **Prepare 请求入参扩展冲突**：
   - 赛题六可能引入 `client_known_version`、`delta_token` 等增量协商参数。
   - 赛题十引入了 `evidence_selection: bool = False`。
   - **风险**：Pydantic 模型字段合并时可能发生参数冲突，或者校验规则 `extra="forbid"` 拒绝对方参数。
2. **Citation 与指纹结构冲突**：
   - 赛题六计算增量依赖稳定的块级指纹（Chunk Hash / Delta Fingerprint）。
   - 赛题十输出片段 `EvidenceFragment` 包含 `(start, end, text, address)`。
   - **风险**：若增量指纹以整篇 Memory 为颗粒度，而赛题十只输出了部分字符片段，增量缓存可能误判为整篇文档已同步。
3. **预算控制冲突**：
   - 赛题六的增量分包预算控制的是传输增量包的大小。
   - 赛题十的 `max_bytes` 控制的是最终组装上下文（信封 + 证据 JSON + 引用）的完整 UTF-8 字节数。

#### 3. 整合消解策略与技术契约
- **参数解耦**：
  在 `PrepareContextRequest` 中，`evidence_selection` 与 `incremental_sync` 作为独立的正交开关；两者可组合使用。
- **片段级增量指纹**：
  增量分包应以 `(entry_id, entry_version_id, start, end)` 四元组或其 Hash 作为增量基本单元。当客户端已知特定区间的证据片段时，增量包仅推送新选取的 `[start, end)` 片段。
- **分层装配管线设计**：
  在 `build_scopes_result` 中明确流程分工：
  ```
  Retrieval (召回)
     │
     ▼
  Evidence Selection (赛题十：按 Query 选出最相关的原始片段)
     │
     ▼
  Delta Filtering (赛题六：对照客户端缓存滤除已同步片段)
     │
     ▼
  Envelope Assembly & Budget Check (最终封包与预算校验)
  ```

---

### 2.5 赛题九（来源撤回）：失效 Source 过滤与历史精确回查

#### 1. 机制与表现
- 赛题九实现了来源撤回（Source Retraction / Tombstone），当数据源被删除或撤回时，对应的 Memory entry 必须被标记失效，不得在后续 Prepare 中被召回。
- 历史回查要求：在撤回前已生成的上下文快照（Snapshot）必须保留历史真实性，其 Citation 仍能追溯至历史版本。

#### 2. 潜在冲突与风险
- **脏数据渗漏**：若赛题十直接从未过滤失效状态的底层存储读取原文，可能将已撤回的敏感数据片段选入活跃上下文。
- **回查断言失败**：若来源被硬删除（物理删除），历史快照通过 `entry_id` 回查 `original_text[start:end]` 时可能报错 `NotFound`。

#### 3. 整合解决方案
- **前置生命周期守卫**：
  赛题十必须严格消费检索层输出的 `MemoryCandidate`（已经过 Scope 隔离与 Retraction 过滤），严禁绕过检索层直接扫描物理存储。
- **软删除与不可变版本快照**：
  赛题九必须采用 `entry_version_id` 的不可变快照机制。已撤回的数据对当前查询不可见（召回集为空），但历史 Citation 仍可通过版本镜像执行精确字符回查。

---

## 三、代码级冲突与合并防范清单

在将来合并至总比赛分支（`competition/powercontext-integrated`）时，需重点核验以下文件：

### 1. `src/powercontext/builtin/runtime/models.py`
- **核验内容**：`PrepareContextRequest`。
- **防范策略**：检查是否包含了所有题目新增字段（如 `evidence_selection: bool = False`），确保所有可选字段均提供默认值，避免破坏已有调用契约。

### 2. `src/powercontext/builtin/runtime/prepared_context.py`
- **核验内容**：`build_scopes_result`、`PreparedContextBuild`、`EvidenceFragment`。
- **防范策略**：
  - 保持 `evidence_selection=False` 时的旧装配路径完全原样运行（100% 行为保持不变）。
  - 当 `evidence_selection=True` 时，调用独立的 `_build_evidence_selection_result` 函数，尽量减少内联侵入式修改，便于 Git 三方合并。

### 3. `src/powercontext/http/_generated/models.py`
- **核验内容**：OpenAPI 生成的 HTTP 传输模型。
- **防范策略**：确保在合并后重新生成或手动核验 OpenAPI 契约，使 HTTP 端与内置运行时端的字段定义严格同步。

---

## 四、结论与交付保证

经过系统分析，赛题十的实现采用**高内聚、低耦合**的架构设计：
1. **接口正交**：通过独立的 `evidence_selection=False` 默认开关实现零侵入；
2. **纯函数运算**：片段抽取、分词打分、动态合并与预算模拟均为无副作用的纯计算逻辑；
3. **数据契约对齐**：完整复用系统既有的 `MemoryEntryAddress`、`Citation` 与 `Scope` 权限模型。

本实现完全具备在后续阶段无缝融入总分支的技术可行性，无任何阻碍性架构冲突。
