# 来源依赖传播设计

## 持久化图

新增 `pc_source_lifecycle_nodes`，以 `(scope_id, node_id)` 为主键保存节点类型、规范化引用、父节点、传播策略和当前可用状态。Source 行额外保存生命周期 revision、最新事件 sequence/内容；Memory 行记录系统管理的停用标记和跨存储写入的待完成状态。没有进程内 Map 作为唯一状态来源。

注册引用直接保存 `SourceRef`、`MemoryCitation` 或 `ArtifactRef` 的序列化值。重复提交完全相同的绑定可重试；同一节点编号绑定到不同对象时拒绝。父节点必须已注册，所以新绑定只能指向 DAG 中已有节点。

## 状态传播

Source 初始可用。派生节点注册时按父节点状态计算：`all` 要求所有父节点可用，`any` 要求至少一个父节点可用。Source 事件先在 scope 锁和数据库事务内校验 revision/sequence 并更新根节点，再沿拓扑顺序重算派生节点。

每个失效 Memory 通过原生 Memory 服务 `forget` 进入 inactive；恢复仅对仍由生命周期传播管理的 inactive 条目调用 `reactivate`。用户通过 Runtime 显式停用条目时会清除系统管理标记，后续 Source 恢复不会覆盖这一决定。原正文、Entry ID 与 Citation 保持原样。

Memory 状态与 DAG 状态位于不同原生写路径。传播前先持久化目标状态和来源 revision；重试会检查原生 Memory 当前状态，完成尚未提交的转换或清除已经过期的待处理状态。完成后清除 pending 并保存管理 revision，因此故障不会让同一事件永久漏传。

## Topic 与读取用途

Topic 节点的状态关联精确 `(artifact_id, revision)`。RelationalContexts 的 Topic 搜索先取该 API 支持的最多 20 个候选，再过滤已绑定但不可用的精确 revision，最后截取调用方 limit。未登记的 Topic 保持既有行为。PreparedContext 复用此搜索入口。

`resolve(..., purpose="generation")` 在不可用时拒绝；Memory generation 还检查其原生条目仍为 active，以尊重显式停用。`purpose="audit"` 返回绑定时的原始引用，不改写或删除历史 Artifact revision。

## 并发边界

赛题定义每个 scope 单写者。Runtime 的 scope operation/lock 串行化同一 Runtime 内的注册、事件和 Memory 生命周期操作；数据库中的绑定和事件状态在重启后继续生效。多进程同时写同一 scope 不属于赛题保证范围。
