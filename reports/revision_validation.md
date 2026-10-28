# PowerContext 赛题十一：当前版本及 Citation 检查报告

## 一、当前 Head 校验机制

PowerContext 的内存系统（Memory）以不可变快照（Immutable Revisions）为核心设计原则：
1. **增量投影（Incremental Projection）**：
   - 当向 Memory 追加（append）或修订（revise）条目时，未修改的条目不会被重新写入。其在 `pc_memory_entry_heads` 和 `pc_memory_vector_entries` 中的 `head_revision` 可能维持先前的 revision 数字。
   - 官方契约规定：返回的引用（`hit.memory_ref`）必须统一使用当前请求中已验证的权威 Memory Head Revision，而不是底层投影行保留的历史数字。
   - 实现方案：通过 `memory_channel_hits` 映射：
     ```python
     requested = {memory.artifact_id: memory for memory in memories}
     # 使用 requested[row["memory_artifact_id"]] 填充 hit.memory_ref
     ```
2. **过期 Head 校验拒绝（Stale Head Rejection）**：
   - 若客户端使用已经被更新的历史 Head（如 revision 1 已被推进到 revision 2）发起检索，系统必须在数据库校验层面抛出 `CapabilityNotSupportedError("head")`。
   - 实现方案：`SeekDBMemoryIndex` 严密继承 `OceanBaseMemoryVectorIndex.vector_complete` 的快照校验逻辑，在执行单 SQL 前，严格比对 `ARTIFACT_HEADS_TABLE.c.revision == memory.revision`，检测到过时则立即拒绝。

---

## 二、生命周期与 Citation 正确性验证

在 `test_t11_t12_t13_revision_and_lifecycle_filtering` 和 `test_t34_t35_citation_verification_and_runtime_regression` 中进行了完备验证：
1. **正文修订（Text Revision）**：
   - 修订后的条目生成新的 `entry_version_id`。
   - 单 SQL 检索返回命中条目后，其 `entry_version_id` 与最新版本完全吻合，旧版本的 `entry_version_id` 不再出现在 TopK 中。
2. **条目停用（Forget / Inactivation）**：
   - 停用条目后，对应条目被移出 active head。
   - 检索时即使全文完全匹配，返回列表中也不包含该 entry_id。
3. **条目恢复（Reactivation）**：
   - 恢复条目后，再次发起混合检索，准确找回对应条目，且其 `entry_version_id` 与最初的历史版本严格一致。
4. **精确 Citation 回查**：
   - 所有单 SQL 检索产出的 `MemoryHit`，均可通过 `await memory.entries(head)` 按 `(artifact_id, entry_id, entry_version_id)` 执行逐字校验（`assert matched[0].text == hit.text`），不变量 100% 成立。
