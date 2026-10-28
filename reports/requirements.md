# PowerContext 赛题十一：官方评分要求与契约分析

## 一、题目概况

| 项目 | 说明 |
| :--- | :--- |
| **赛题编号** | `retrieval-02-hybrid-search` |
| **赛题名称** | 赛题十一：seekdb 混合检索的单 SQL 候选查询 |
| **分值** | 20 分（满分 240 分体系，实行 All-or-Nothing 评分） |
| **官方基线** | PowerContext v1.2.0（commit `9db1753434162c0aa7c9f1189a1722e617880a52` / `dab240063bfcfa7917898dc44da4baadb3747bd0`） |
| **工作分支** | `competition/seekdb-single-sql-hybrid` |
| **开发环境** | Windows 11 + WSL2 + Docker，使用共享环境中的 `pylibseekdb==1.3.0.post4` |

---

## 二、官方通过条件与验收细则

依据官方题目指导规范 `instruction.md`，验收包含功能门、候选访问成本、命中有效性、逐查询质量、平均召回和延迟等全部维度，任一要求失败得 0 分：

| 验收类别 | 官方通过条件 | 检查重点与验证手段 |
| :--- | :--- | :--- |
| **候选访问成本** | 每条 hybrid query 恰好执行一条包含全文与向量候选的 SQL | 使用 SQLAlchemy `before_cursor_execute` 监听执行的 SQL，确认 `len(native) == 1`，禁止先查 FTS 再查 Vector 在 Python 层面合并 |
| **原生索引使用** | 实际 SQL 的 EXPLAIN 同时显示 `TEXT RETRIEVAL SCAN` 和 `VECTOR INDEX` | 禁止全表扫描并在 Python 计算匹配或距离，确认倒排全文索引与 HNSW 向量索引在单 SQL 内被优化器双路选择 |
| **数据库内过滤** | scope、Memory artifact、tag filter 与 candidate limit 在数据库内生效 | 过滤条件必须推入子查询内部，防止跨 scope 召回或无关条目提前占据每路 TopK |
| **当前 head 与版本** | 沿用现有 backend 校验；历史 head 按现有 capability contract 拒绝 | 保持对已过时 head 的校验拒绝；未修改条目在新 revision 下保留有效引用 |
| **状态变化与正文** | 追加、修订、停用（forget）和恢复（reactivate）后，索引与状态一致 | 验证状态变迁下，单 SQL 混合检索返回的 entry_version_id、revision 与正文一致性 |
| **通道标识有效性** | `matched_by` 非空，标识取自 `fts`、`vector` | 保留两路命中元数据，两路同时命中返回 `("fts", "vector")`，单路命中返回单元素元组 |
| **逐查询检索质量** | 与同库冻结双查询路径相比，每条 query 的 Recall@10、MRR@10 均不降低 | 逐 query 比较，禁止“平均分合格但少数 query 严重退化” |
| **平均召回** | 60 次查询（20 query × 3 scope）的 `evidence_recall_at_10 >= 0.95` | 保证单 SQL 召回池完整保留双路候选能力 |
| **延迟** | 完整 `Memory.search` 调用的 `p50_latency_ms <= 500` | 索引与单 SQL 执行计划开销控制在 500ms 阈值内 |

---

## 三、接口契约与数据模型

### 3.1 沿用冻结 Schema
- 表 `pc_memory_entry_heads`：维护当前活跃 Head 对应的全文检索投影（字段包含 `scope_id`, `family`, `memory_artifact_id`, `head_revision`, `entry_id`, `entry_version_id`, `searchable_text`）。
- 表 `pc_memory_vector_entries`：维护向量条目（字段包含 `vector_id`, `scope_id`, `memory_artifact_id`, `head_revision`, `entry_id`, `entry_version_id`, `embedding`）。
- 表 `pc_memory_entry_versions`：存储不可变正文与元数据版本记录。
- 表 `pc_artifact_tags`：支持对 entry 维度的标签过滤。

### 3.2 运行时装配接口
- `open_builtin_contexts` 在检测到 `database=SeekDBConfig` 且配置了 `embedding_model` 时，装配专用 `SeekDBMemoryIndex`。
- 其他数据库配置（`OceanBaseConfig`, `SQLiteConfig`）保持完全隔离，100% 沿用既有实现。
