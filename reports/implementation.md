# 实现说明

## 主要修改

- `src/powercontext/builtin/persistence/tables.py`：增加 `SOURCE_LIFECYCLE_NODES_TABLE` 及约束，并纳入 `BUILTIN_TABLES`，随现有数据库建表流程持久化。
- `src/powercontext/builtin/runtime/source_lifecycle.py`：新增事件模型、错误类型、持久化 repository、scope-scoped API、绑定校验、状态传播、Memory 故障恢复和 generation/audit 解析。
- `src/powercontext/builtin/runtime/application.py`：Runtime 暴露 `lifecycle`；Runtime Memory 显式 retire 后通知生命周期服务，防止来源恢复覆盖用户停用。
- `src/powercontext/builtin/runtime/relational.py`：Topic 搜索过滤已登记的不可用精确 revision，PreparedContext 共用该查询路径。
- `src/powercontext/builtin/runtime/__init__.py`：导出题目要求的接口类型。
- `tests/builtin/runtime/test_source_lifecycle.py`：覆盖原生 Memory 写入失败后的同事件重试、用户主动停用后的恢复边界、scope 隔离。

## 关键入口

```python
runtime.lifecycle.for_scope(scope_id)
service.register_source(node_id, source_ref, revision=...)
service.register_memory(node_id, citation, parents=(...), policy="all" | "any")
service.register_topic(node_id, artifact_ref, parents=(...), policy="all" | "any")
service.apply(event)
service.resolve(node_id, purpose="generation" | "audit")
```

所有注册、事件操作使用现有 Runtime scope 锁及数据库事务；Memory 原生状态转换使用现有 `forget`/`reactivate` API，保留既有历史版本机制。未修改公开测试夹具或评分预期。
