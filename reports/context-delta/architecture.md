# 分包、增量与重建设计

## 数据路径

```text
ScopedContextApplication.prepare(request)
        │ 完整 PreparedContext.content（含原顺序和 citation）
        ▼
ContextPack.from_content(content or "")
        │ 首轮完整 Pack；后续对调用方传入的 base_pack 求公共前缀
        ▼
ContextPackDelta(base_digest, target_digest, prefix_items, appended)
        │ JSON / Base64 序列化后交给传输层
        ▼
接收端 from_bytes(base) + from_bytes(delta) + apply_context_pack_delta
        │ 仅使用两份序列化输入
        ▼
完整 target ContextPack，拼接 items 得到本轮完整正文
```

## 协议规则

- 正文按 Unicode code point 编码为 UTF-8，再装入不超过 512 字节的确定性连续块。块边界不落在字符编码中间；拼接后逐字节等于 `PreparedContext.content.encode("utf-8")`。空 `content` 对应 `items=()`。
- 完整 Pack 用规范 JSON 和标准 Base64 表示，摘要覆盖 `schema` 与 `items` 两字段；`byte_count` 由含自身字段的最终 JSON 长度计算。
- Delta 使用最长相同分块前缀，其余目标块作为后缀。应用时校验 base 摘要、prefix 上限、目标摘要和字段类型。
- Decoder 对字段集合、schema、重复 JSON key、Base64、SHA-256 格式、`byte_count` 和整数边界失败即抛出 `ContextPackError`。

## 状态边界与兼容

- `prepare_incremental` 每轮先执行原有 `prepare`；不改变检索选择、citation、Source/Artifact/Revision 或普通 `PreparedContext` 返回值。
- 上一轮 Pack 由调用者显式传入。Runtime 不保存全局缓存、对象地址、数据库指针或隐式会话状态；新进程只需收到合法 base Pack 与 delta。
- 解码后拼接的是原始 prepare 文本，顺序和全部引用信息都随原文保留。正文开头发生变化时只能复用其前面的稳定字节，这是前缀协议本身的限制；实现优先保证精确重建。
- 没有新增 HTTP schema 或调整现有 `prepare` API；新能力位于赛题要求的 Runtime application 和 `context_pack` 模块。
