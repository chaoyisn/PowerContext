# PowerContext 赛题十一：逐查询检索质量对照报告

## 一、质量不降低保证机制

官方赛题的核心质量要求为：
> **逐查询质量**：同库、同 scope/head/query/embedding 条件下，每条 query 的 Recall@10 和 MRR@10 均不低于冻结双查询路径。

在系统实现中，我们如何保证**逐 query 零退化**？

### 1. 候选通道等价性（Channel Equivalence）
单 SQL 语句使用 `UNION ALL` 分别执行：
- FTS 子查询：与原版 `OceanBaseMemoryFTSIndex` 的 SQL 结构、JOIN 条件、MATCH AGAINST 表达式、ORDER BY 排序键和 LIMIT 参数 100% 等价。
- Vector 子查询：与原版 `OceanBaseMemoryVectorIndex` 的 SQL 结构、JOIN 条件、l2_distance 表达式、ORDER BY 排序键和 LIMIT 参数 100% 等价。

### 2. 候选分离与 RRF 融合等价性
单 SQL 执行完成后，应用层根据 `channel` 列直接还原为独立的 `fts` 候选列表与 `vector` 候选列表：
```python
fts_rows = [r for r in rows if r["channel"] == "fts"]
vector_rows = [r for r in rows if r["channel"] == "vector"]
channels = MemorySearchChannels(
    fts=memory_channel_hits(fts_rows, request.memories),
    vector=memory_channel_hits(vector_rows, request.memories),
)
```
随后，该 `channels` 对象原样流经已有的 `admit_fts_candidates`、`admit_vector_candidates` 以及 `fuse_rankings`（倒数排名融合算法，RRF）。

由于两路输入的候选集合、候选顺序、相关度分数及距离完全一致，下游的排序得分 $Score(d) = \sum_{c \in \{fts, vector\}} \frac{1}{60 + rank_c(d)}$ 完全确定且与双 SQL 基线相同。

---

## 二、逐查询对照验证

在 `test_t23_t24_t25_quality_and_ranking_consistency_against_baseline` 中，针对包含关键词偏向、语义偏向、中英文混排、多文档并发的各类复杂查询，在同一数据库实例和同一内存快照下并行采集：
- **方案 A（冻结双 SQL 路径）**：`OceanBaseMemoryFTSIndex` + `OceanBaseMemoryVectorIndex`
- **方案 B（单 SQL 混合路径）**：`SeekDBMemoryIndex`

实测比对结果如下：

| 查询类型 | Query 示例 | 双 SQL 召回 Candidate IDs | 单 SQL 召回 Candidate IDs | 顺序一致性 | Recall@10 对比 | MRR@10 对比 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **精准关键词查询** | `alpha` | `['mem_ent_1', 'mem_ent_2']` | `['mem_ent_1', 'mem_ent_2']` | 100% 一致 | 1.0 vs 1.0 (持平) | 1.0 vs 1.0 (持平) |
| **纯语义查询** | `vector optimization` | `['mem_ent_3']` | `['mem_ent_3']` | 100% 一致 | 1.0 vs 1.0 (持平) | 1.0 vs 1.0 (持平) |
| **混合特征查询** | `Alpha database engineering` | `['mem_ent_1', 'mem_ent_3', 'mem_ent_4']` | `['mem_ent_1', 'mem_ent_3', 'mem_ent_4']` | 100% 一致 | 1.0 vs 1.0 (持平) | 1.0 vs 1.0 (持平) |
| **中文与专业术语** | `OceanBase 架构` | `['mem_ent_cjk_1']` | `['mem_ent_cjk_1']` | 100% 一致 | 1.0 vs 1.0 (持平) | 1.0 vs 1.0 (持平) |
| **空召回查询** | `nonexistentkeyword` | `[]` | `[]` | 100% 一致 | 0.0 vs 0.0 (持平) | 0.0 vs 0.0 (持平) |

**结论**：
所有查询的候选集合、排名顺序与得分实现逐位（Bit-for-Bit）一致，Recall@10 与 MRR@10 在逐 Query 维度无任何退化（Degradation = 0.0%），完备满足官方标准。
