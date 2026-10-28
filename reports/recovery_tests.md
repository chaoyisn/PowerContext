# 赛题三：Pi 会话分支采集与断点恢复 - 断点、重启及失败重试验证报告

## 一、断点持久化与恢复设计原则

在分布式或长时运行的 AI 上下文管理系统中，网络抖动、进程中断、分支切换及外部数据篡改是常见的异常场景。为保证「赛题三：Pi 会话分支采集与断点恢复」的 20 分评分要求，本实现建立了基于以下原则的高可靠恢复体系：

1. **先入库后提断点**：数据事件必须先通过 `Runtime ingestion` 成功写入底层持久化存储，随后才由 `ConnectorLifecycle` 提交持久化 checkpoint。
2. **故障原子回滚**：当遇到文件格式错误、语法损坏、篡改或网络异常时，立即中断，不推进任何 checkpoint，保持上一次有效提交的状态。
3. **断点状态完备**：checkpoint 保存全量已摄入事件的身份及其 SHA-256 哈希摘要，保证跨进程重启时无需重新扫描全部历史即可快速判定增量。
4. **历史不可变性防线**：任何对已采集持久化历史的就地改写，在下一次采集时被立即侦测并阻止，防止数据一致性崩塌。

---

## 二、恢复与断点场景实测

### 1. 进程重启与重复采集幂等性

- **测试用例**：`test_incremental_repeated_three_times` / `test_branch_switch_restart_full_evidence_and_mutation_rejection`
- **操作步骤**：
  1. 首次采集 `tree.jsonl` 中的 `left` 分支，成功写入 2 个可见事件（`root` 与 `left`），生成 `first.committed_checkpoint`。
  2. 重复执行 `run("left")`，模拟进程重启或调度器重复触发。
- **实测结果**：
  - `session.submit` 被调用 0 次（`items == ()`）。
  - `replay.previous_checkpoint == first.committed_checkpoint`。
  - 存储内数据条目数保持 2 条，无任何冗余副本生成。
  - **结论：完全幂等，断点准确识别已导入集合。**

### 2. 多分支切换与共享祖先后继增量

- **操作步骤**：
  1. 从包含 `root -> left` 的状态，切换为指定采集 `right` 分支（路径为 `root -> control(跳过) -> right`）。
  2. 采集器读取 `checkpoint`，发现 `root` 已存在且哈希一致。
  3. 仅对 `right` 节点调用 `session.submit`。
- **实测结果**：
  - 本次运行提交 `items` 数量严格等于 1。
  - 存储中累积包含 `root`, `left`, `right` 三条记录，历史分支证据完整保留。
  - 新 checkpoint 累积包含 `root`, `left`, `right` 三个事件的指纹。
  - **结论：跨分支祖先复用正确，多分支历史互不污染且证据完备。**

### 3. 文件损坏与异常中途拦截

- **操作步骤**：
  1. 向已有正常会话的尾部追加破坏性文本 `{bad json}\n`。
  2. 触发采集操作。
- **实测结果**：
  - 采集器在初始全局解析阶段捕获异常，抛出 `ValueError`。
  - `session.checkpoint` 未被修改，仍然保留之前的有效进度。
  - 数据库中未增加任何脏数据。
  - **结论：输入校验具有全局原子性，损坏文件不推进进度。**

### 4. 损坏修复后的无缝续采

- **操作步骤**：
  1. 清除上一步追加的 `{bad json}\n`，还原文件内容。
  2. 再次执行采集。
- **实测结果**：
  - 采集器成功解析文件，读取原有 checkpoint。
  - 确认无新可见节点需要提交，正常完成。
  - `repaired.previous_checkpoint == added.committed_checkpoint` 且 `repaired.items == ()`。
  - **结论：故障修复后自动从原断点继续，无需人工干预或重建数据库。**

### 5. 历史记录篡改拒绝（Mutation Rejection）

- **操作步骤**：
  1. 将已入库的 `records[0]["message"]["content"]` 从 `"Shared request"` 改为 `"Changed request"`。
  2. 触发采集操作。
- **实测结果**：
  - 采集器在比对 `known_events` 时检测到 `records[0]` 的当前哈希与 checkpoint 中记录的哈希不符。
  - 抛出 `ValueError("Historical record 'root' was mutated")`。
  - 任何新节点（如追加的 `tail`）被阻止提交。
  - 将内容还原为 `"Shared request"` 后重新触发，测试立即恢复正常并通过。
  - **结论：严密防御历史回写，保证审计链路真实可信。**

### 6. 大体积工具事件持久化测试

- **测试用例**：`test_large_tool_output_untruncated`
- **操作步骤**：
  - 构造包含 150KB 巨型文本的 `toolResult` 事件。
  - 执行 `PiSessionConnector` 摄入与 `Runtime` 持久化。
  - 在 `EvidencePipeline` 对其按 1500 字节分片送入 Memory 的同时，验证底层 `Source` 存储。
- **实测结果**：
  - 底层 `Source.content` 完整保留 150KB 全部文本，长度未被截断为 8192 字节。
  - 重启 runtime 后通过 `memory.search("toolResult")` 成功命中，Citation 精确读回 150KB 完整数据。
  - **结论：完全突破单条 Memory 限制，Source 层保证大工具结果 100% 保真。**

### 7. 多 Scope 与多 Session 隔离测试

- **测试用例**：`test_scope_isolation`
- **操作步骤**：
  - 对相同会话文件分别绑定 `scope-A` 与 `scope-B`。
- **实测结果**：
  - 两个 Scope 分别拥有独立的 Checkpoint 与独立的底层存储。
  - 数据在各 Scope 内部严格增量，跨 Scope 无任何泄漏或冲突。
  - **结论：多租户隔离与安全边界符合 PowerContext 企业级要求。**
