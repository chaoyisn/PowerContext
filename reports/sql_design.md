# PowerContext 赛题十一：SQL 设计与两路召回方案分析

## 一、方案对比与设计思路

在基线实现中，PowerContext 通过两个独立的查询获取全文与向量候选：
1. **全文检索语句（FTS Query）**：
   ```sql
   SELECT
       h.memory_artifact_id,
       h.head_revision,
       h.entry_id,
       h.entry_version_id,
       v.text
   FROM pc_memory_entry_heads AS h
   JOIN pc_memory_entry_versions AS v
     ON v.scope_id = h.scope_id
    AND v.memory_artifact_id = h.memory_artifact_id
    AND v.entry_version_id = h.entry_version_id
   WHERE h.scope_id = :scope_id
     AND h.memory_artifact_id IN :memory_artifact_ids
     AND MATCH(h.searchable_text) AGAINST(:analyzed_query)
   ORDER BY MATCH(h.searchable_text) AGAINST(:analyzed_query) DESC,
            h.memory_artifact_id, h.entry_id, h.entry_version_id
   LIMIT :candidate_limit;
   ```
2. **向量检索语句（Vector Query）**：
   ```sql
   SELECT
       m.memory_artifact_id,
       m.head_revision,
       m.entry_id,
       m.entry_version_id,
       v.text,
       l2_distance(m.embedding, :query_vector) AS distance
   FROM pc_memory_vector_entries AS m
   JOIN pc_memory_entry_versions AS v
     ON v.scope_id = m.scope_id
    AND v.memory_artifact_id = m.memory_artifact_id
    AND v.entry_version_id = m.entry_version_id
   WHERE m.scope_id = :scope_id
     AND m.memory_artifact_id IN :memory_artifact_ids
   ORDER BY l2_distance(m.embedding, :query_vector) APPROXIMATE
   LIMIT :candidate_limit;
   ```

### 痛点分析：
- 两次独立的数据库交互引入了额外的网络/Unix Socket Round-Trip 开销。
- 难以在一个原子事务/读取快照中完成两路候选的协调读取。
- 需要应用层发起并发或串行调用组织。

---

## 二、新单 SQL 混合检索架构设计

经过对 seekdb 1.4.0 引擎内核能力的实测分析，采用 **有序子查询 + `UNION ALL` 统一派生通道** 的单 SQL 设计：

```sql
(
SELECT
    f.memory_artifact_id,
    f.head_revision,
    f.entry_id,
    f.entry_version_id,
    v.text,
    'fts' AS channel,
    MATCH(f.searchable_text) AGAINST(:analyzed_query) AS score,
    NULL AS distance
FROM pc_memory_entry_heads AS f
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = f.scope_id
 AND v.memory_artifact_id = f.memory_artifact_id
 AND v.entry_version_id = f.entry_version_id
WHERE f.scope_id = :scope_id
  AND f.memory_artifact_id IN :memory_artifact_ids
  AND MATCH(f.searchable_text) AGAINST(:analyzed_query)
  {fts_tag_clause}
ORDER BY score DESC, f.memory_artifact_id, f.entry_id, f.entry_version_id
LIMIT :candidate_limit
)
UNION ALL
(
SELECT
    m.memory_artifact_id,
    m.head_revision,
    m.entry_id,
    m.entry_version_id,
    v.text,
    'vector' AS channel,
    NULL AS score,
    l2_distance(m.embedding, :query_vector) AS distance
FROM pc_memory_vector_entries AS m
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = m.scope_id
 AND v.memory_artifact_id = m.memory_artifact_id
 AND v.entry_version_id = m.entry_version_id
WHERE m.scope_id = :scope_id
  AND m.memory_artifact_id IN :memory_artifact_ids
  {vector_tag_clause}
ORDER BY l2_distance(m.embedding, :query_vector) {approximate_clause}
LIMIT :candidate_limit
)
```

### 设计关键点：
1. **多通道有序合并（UNION ALL）**：
   - 保证两路候选在数据库内各自利用自身的索引完成 TopK 截断与排序，不退化为全表扫描。
   - 增加 `'fts' AS channel` 和 `'vector' AS channel` 标识列，应用层单次读取后，可零拷贝分离为 `channels.fts` 和 `channels.vector`。
2. **两路非交集保留**：
   - 保留仅命中 FTS 的记录（`score > 0, distance IS NULL`）。
   - 保留仅命中 Vector 的记录（`score IS NULL, distance >= 0`）。
   - 同时命中两路的记录分别出现在两个通道中，交由上游 RRF 融合算法计算累加加权分数，与基线双 SQL 行为 100% 相同。
3. **参数绑定安全性**：
   - 使用 SQLAlchemy 统一绑参扩展：
     - `bindparam("memory_artifact_ids", expanding=True)`
     - `bindparam("query_vector", type_=VECTOR(dimension))`
     - `bindparam("tag_keys", expanding=True)`
     - `bindparam("tag_hashes", expanding=True)`
   - 杜绝字符串拼接，完全免疫 SQL 注入风险。
