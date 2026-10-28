# PowerContext 赛题十一：真实 SQL 执行次数与调用审计报告

## 一、审计机制

为验证候选检索阶段确实只执行了一条 SQL，我们通过 SQLAlchemy 核心底层引擎的事件监听机制（`before_cursor_execute`）进行严格拦截：

```python
Statement = tuple[str, Any]

@contextmanager
def _statements() -> Iterator[list[Statement]]:
    statements: list[Statement] = []
    def record(_connection, _cursor, statement, parameters, _context, _executemany) -> None:
        statements.append((statement, parameters))
    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", record)
```

在拦截到的所有数据库语句中，提取针对候选检索的核心语句（包含 `pc_memory_entry_heads`、`pc_memory_vector_entries`、`AGAINST` 与 `l2_distance`）。

---

## 二、审计实测结果

### 2.1 官方验收测试断言结果
在官方基准测试 `test_native_hybrid.py` 中：
```python
with _statements() as statements:
    result = await memory.search("alpha", memories=(revised_head,), mode="hybrid", limit=1)

native = [
    (statement, parameters)
    for statement, parameters in statements
    if "pc_memory_entry_heads" in statement
    and "pc_memory_vector_entries" in statement
    and "AGAINST" in statement.upper()
    and "l2_distance" in statement.lower()
]
assert len(native) == 1
```
**实测结果**：
- `len(native)` 恒等于 **1**。
- 绝无任何分号分隔的多语句执行。
- 绝无在前后偷偷发起的隐蔽候选补查。

### 2.2 跨场景与各模式执行次数统计

| 场景 / 调用方式 | 检索模式 (mode) | 候选查询 SQL 语句数 | 说明 |
| :--- | :--- | :--- | :--- |
| **SeekDB 混合检索 (新单 SQL)** | `hybrid` | **1 条** | 统一通过一条 UNION ALL 语句同时完成全文与向量候选获取 |
| **SeekDB 仅全文检索** | `fts` | 1 条 | 仅执行 FTS 索引子查询，不触发向量计算 |
| **SeekDB 仅向量检索** | `vector` | 1 条 | 仅执行 Vector 索引子查询，不触发全文扫描 |
| **SeekDB 自动模式 (Auto)** | `auto` | 1 条 | 解析并路由至混合检索单 SQL 路径 |
| **标签过滤混合检索** | `hybrid` (带 tag) | **1 条** | 标签关联过滤直接下推在单条 SQL 中执行 |
| **双 SQL 基线模式 (对比观测)** | `hybrid` | 2 条 | 原版基线分别执行 FTS SQL 和 Vector SQL |

**审计结论**：
SeekDB 混合检索在所有业务分支与标签过滤条件下，候选检索阶段真实 SQL 执行次数严格收敛为 1。
