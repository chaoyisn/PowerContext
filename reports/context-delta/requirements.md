# 赛题六需求与评分

来源：仓库随 `2026-competition` 发布的 `competition/challenges/context-02-incremental-pack/instruction.md` 与公开验收测试。官方语雀页无法通过当前浏览器访问；本报告以公开仓库资产为准。

题目冻结基线为 PowerContext v1.2.0，commit `9db1753434162c0aa7c9f1189a1722e617880a52`；本分支从公开赛题分支创建，已验证冻结 commit 是其祖先。

## 评分门槛（20 分）

四类验收全部通过才得分，任一失败为 0 分：

1. **协议**：严格使用 `powercontext.context-pack.v1` 和 `powercontext.context-pack-delta.v1`；字段、标准 Base64、规范 JSON、摘要、字节计数与非法输入行为符合下列约定。
2. **重建**：首次完整包可独立解码；后续仅使用已序列化 base pack 与 delta 重建。首部、中部、尾部修改和空结果都要准确恢复。
3. **原生集成**：接入 `ScopedContextApplication`，每轮仍调用普通 `prepare` 选择上下文。保留现有正文和 citation 语义。
4. **传输成本**：40 轮测量序列从 8 个真实 meeting turn 开始，每轮非空、至少 4 种不同 Context；`1 - incremental_bytes / raw_full_bytes >= 45%`。

## 公共接口

- `ContextPack.build(items)`、`from_content(content, chunk_bytes=512)`、`to_bytes()`、`from_bytes(data)`。
- `ContextPackDelta.between(base, target)`、`to_bytes()`、`from_bytes(data)`。
- `apply_context_pack_delta(base, delta)` 与 `ContextPackError`。
- `ScopedContextApplication.prepare_incremental(request, base_pack=None)`：无 base 返回 pack，有合法 base 返回 delta。

## Wire 协议

- Pack 字段仅为 `schema`, `items`, `digest`, `byte_count`；delta 字段仅为 `schema`, `base_digest`, `target_digest`, `prefix_items`, `appended`。
- `items`/`appended` 在线路上是标准 Base64 字符串数组，内存中为 `bytes` 元组。
- JSON 使用 UTF-8、排序 key、`,` 和 `:` 分隔且不带空格。
- 摘要是只包含 `schema` 和 Base64 `items` 的规范 JSON 的 SHA-256，格式 `sha256:<hex>`。
- Pack `byte_count` 等于完整规范 Pack JSON 的 UTF-8 长度（包含字段本身）；delta 的 `byte_count` 是序列化长度属性，不写入 JSON。
- 分块保持原字节顺序；每个由 `from_content` 生成的块是完整 UTF-8 且不超过指定上限。空文本对应空 pack。
- 解码拒绝缺字段、额外字段、错误编码或摘要、base 不匹配、非整数/负数/越界 prefix、目标摘要不符。

## 成本定义

`raw_full_bytes` 是每轮普通 `prepare` 正文的 UTF-8 字节总数。`incremental_bytes` 是首轮完整 pack 与后续 delta 的 `len(to_bytes())` 之和，含全部 JSON、Base64、摘要和控制字段。还需报告累计完整 Pack、逐轮独立 gzip（level 9、mtime 0）及两项比较节省率。gzip 仅作观测对照。

公开验收命令：`make -C competition test-incremental`。公开 workload 提供 2 个 QMSum meeting turn；官方 40 轮隐藏测量不能从该 2-turn 样例直接替代。
