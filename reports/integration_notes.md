# PowerContext 赛题十一：跨题兼容性与未来整合报告

## 一、跨题概览与技术交汇矩阵

赛题十一作用于 **SeekDB 存储后端的底层检索适配层（Storage / Retrieval Index Adapter）**，负责在数据库层以单条 SQL 统一提取全文与向量候选。

在 PowerContext 12 道赛题的完整体系中，赛题十一与相关赛题的技术交汇分析如下：

| 赛题编号与主题 | 作用层级 / 模块 | 与赛题十一的交汇点 | 风险等级 |
| :--- | :--- | :--- | :--- |
| **赛题二：CSV 行级数据摄入** | Ingestion / CSV Parsing | 表格行转化生成的 Memory entry 参与 FTS 倒排与向量索引 | 低 |
| **赛题三：Pi 会话与工具事件** | Ingestion / Agent History | 会话与分支采集产生的 entry 索引更新与多轮检索 | 低 |
| **赛题五：HTTP Rerank 跨批重排** | Retrieval / Scoring Pipeline | 单 SQL 产出的候选作为 Reranker 的输入候选集 | 低-中 |
| **赛题六：上下文增量分包** | Runtime Prepare / Context Assembly | 候选检索结果影响 PreparedContext 的生成与增量包比对 | 低 |
| **赛题八：Embedding 单飞缓存** | Inference / Embedding Cache | Query 向量缓存复用，影响 `query_vector` 的生成与传递 | 中 |
| **赛题九：来源撤回与失效恢复** | Storage / Lifecycle Retraction | 撤回（retracted）的 Source / Entry 严禁进入单 SQL 候选池 | **中-高** |
| **赛题十：原文证据与预算选择** | Runtime Prepare / Evidence Selection | 候选 `MemoryHit` 的 Citation 身份必须支持下游原文精确定位与回查 | 中 |

---

## 二、逐题冲突深度剖析与整合消解方案

### 2.1 赛题二（CSV）与赛题三（Pi）
- **协同机制**：CSV 转换和 Pi 会话生成的 Memory entry，最终均通过标准 `memory.remember()` 写入底层表 `pc_memory_entry_heads` 和 `pc_memory_vector_entries`。
- **兼容性验证**：单 SQL 检索不改变任何底层 schema，直接消费已入库的 `searchable_text` 和 `embedding`，对摄入来源的数据格式完全透明兼容。

### 2.2 赛题五（HTTP Rerank）
- **协同机制**：赛题五对 `MemoryHit` 候选列表调用外部 HTTP Rerank 服务进行二次打分。
- **兼容性验证**：`SeekDBMemoryIndex` 返回的 `MemorySearchChannels` 保持了与双 SQL 完全一致的数据契约。在 `service.py` 内部经 `fuse_rankings` 计算后，产出结构标准、分数连续的 `MemoryHit` 列表，为 Reranker 提供稳定候选输入。

### 2.3 赛题八（Embedding 单飞缓存）
- **协同机制**：赛题八优化了 Query 向量的计算开销（通过 Singleflight 与 LRU 缓存避免重复 Embedding）。
- **兼容性保证**：`SeekDBMemoryIndex` 消费由 `MemoryService._resolve_query_vector()` 传入的 `request.query_vector`，只要向量维度与 Profile 匹配，缓存的命中或未命中均不影响单 SQL 内部的 L2 距离计算。

### 2.4 赛题九（来源撤回）：重点关注
- **潜在冲突点**：
  若赛题九在底层引入了来源撤回标记（如 `tombstone` 或撤回状态列），被撤回的 Source 对应的 Memory 条目必须被排除。
- **整合消解方案**：
  赛题十一的单 SQL 子查询从 `pc_memory_entry_heads` 和 `pc_memory_vector_entries` 查询。
  在赛题九整合时，若底层 schema 增加了 `is_active` 或关联 `pc_sources` 状态，应在单 SQL 两路子查询的 WHERE 条件中同步增加撤回状态过滤：
  ```sql
  AND f.is_retracted = 0
  AND m.is_retracted = 0
  ```
  或者依赖赛题九在撤回时从 active head 移除条目的投影机制。

### 2.5 赛题十（按查询选择原文证据）
- **协同机制**：
  赛题十在 Prepare 阶段依赖检索返回的 `MemoryHit.memory_ref`、`entry_id` 和 `entry_version_id` 回查正文切片。
- **兼容性保证**：
  `SeekDBMemoryIndex` 严格保证了返回的 `memory_ref` 绑定为当前请求的合法权威 Head，`entry_version_id` 指向真实版本，支持赛题十以 `original_text[start:end]` 执行严格回查断言。

---

## 三、代码级冲突合并防范清单

在将来合并至比赛总分支（`competition/powercontext-integrated`）时，重点关注：

1. **`src/powercontext/builtin/runtime/composition.py`**：
   - 检查 `_resolve_memory_index` 辅助函数，确保 `database=SeekDBConfig` 时正确构造 `SeekDBMemoryIndex`，不覆盖其他题目的配置项。
2. **`src/powercontext/builtin/persistence/seekdb/memory_index.py`**：
   - 该文件为赛题十一独立新增文件，Git 合并时无任何三方冲突。
3. **`src/powercontext/builtin/persistence/seekdb/__init__.py`**：
   - 检查导出列表包含 `SeekDBMemoryIndex`。
