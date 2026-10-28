# 后续统一整合注意事项

本分支只实现赛题九，基于 PowerContext 冻结版 v1.2.0 对应的比赛源码线。不要提前合并到集成分支；后续整合时优先逐项核对：

1. **表注册：** `SOURCE_LIFECYCLE_NODES_TABLE` 已加入 `BUILTIN_TABLES`。若其他赛题也新增表或改写该 tuple，合并时保留双方表注册及命名唯一性。
2. **Runtime 接口：** `BuiltinRuntime.lifecycle` 是本题的公开入口；若其他分支改造 Runtime 构造或公开导出，需保留 `lifecycle.for_scope(scope_id)` 和题目要求的类型。
3. **Memory 手动退役：** `ScopedMemoryApplication.retire` 会通知生命周期服务清除自动恢复标记。合并 Memory 生命周期变更时保留这个调用，避免 Source 恢复撤销用户选择。
4. **Topic 搜索：** `RelationalContexts.search_topic_memories` 在候选截断前做 lifecycle 可用性过滤。合并搜索、排序或缓存路径时，确保 direct search 与 PreparedContext 仍走过滤入口，并保留精确 revision 过滤。
5. **数据库兼容：** 表随既有 metadata 建表流程创建，没有对现有 Source/Memory/Topic 行执行迁移或删除。若集成版更换 schema 初始化机制，需验证旧数据库启动时会创建该表。
6. **并发契约：** 本题依赖每 scope 单写者及 Runtime scope 锁。若其他题引入多进程写入同一 scope，需额外协调事务级锁/冲突策略；本分支未承诺该行为。
7. **重复修改与测试：** 合并后重新运行 `competition/challenges/memory-01-source-lifecycle/acceptance` 和本报告列出的聚焦回归，不要改官方验收预期。

本分支未修改 HTTP API、SDK 或其他比赛分支；来源撤回由调用方通过 `SourceLifecycleEvent` 提供，原始证据保留。
