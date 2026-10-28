# PowerContext 赛题十一：数据库内过滤验证报告

## 一、下推过滤条件分析

在检索体系中，若先全量/粗粒度召回再到 Python 应用层过滤，不仅会造成大量无效网络传输与反序列化开销，还会导致真正的有效候选被旧版本或未授权数据“挤出”TopK（Top-K Pollution）。

本题在单 SQL 内部实现完全的数据库级过滤下推：

| 过滤维度 | 下推位置 | 实现语句与机制 |
| :--- | :--- | :--- |
| **Scope 隔离** | FTS & Vector 子查询 WHERE | `f.scope_id = :scope_id` / `m.scope_id = :scope_id`，利用复合主键前缀索引直接过滤 |
| **Artifact 约束** | FTS & Vector 子查询 WHERE | `f.memory_artifact_id IN :memory_artifact_ids` / `m.memory_artifact_id IN :memory_artifact_ids`，参数化数组展开 |
| **标签过滤（Tag Filter）** | FTS & Vector 关联子查询 | 统计 `pc_artifact_tags` 匹配数是否 `>= :tag_minimum`，在截断 TopK 之前完成筛选 |
| **当前有效版本（Active Head）** | FTS 选自 `pc_memory_entry_heads`，Vector 选自 `pc_memory_vector_entries` | 只投影当前活跃 entry，已删除（forget）的记录已被 tombstone 剔除，未更新记录保留旧 revision 投影 |
| **每路 Candidate Limit** | 两路子查询分别追加 `LIMIT :candidate_limit` | 在数据库层各自截断 TopK，杜绝单通道超载，保护内存 |

---

## 二、测试验证

在自动化测试套件中，通过以下用例对数据库内过滤进行了详尽验证：
1. **`test_t09_t10_scope_filtering_and_isolation`**：
   - 在 `project-scope` 和 `other-scope` 分别写入相同关键词的条目。
   - 验证检索时，SQL 执行计划显示 `range_key([m.scope_id], ...)`，结果集 100% 隔离，绝无跨 scope 数据泄漏。
2. **`test_t14_database_tag_filtering`**：
   - 针对部分条目打上 `important` 标签。
   - 执行带 `TagFilter(tags=("important",))` 的检索，验证 EXPLAIN 显示 `SUBPLAN FILTER` + `TABLE GET tags` 在 `TOP-N SORT` 之前完成过滤。
3. **`test_t15_t16_t17_limits_and_boundaries`**：
   - 验证 `candidate_limit` 被严格传递至两路子查询的 `LIMIT`，无论数据量多少，传输结果集严格受控。
