# 赛题三：Pi 会话分支采集与断点恢复 - 需求分析与评分规范

## 一、题目概述

- **题目编号**：`source-02-pi-history`
- **题目名称**：Pi 会话分支采集与断点恢复
- **满分**：20 分（必测项全部通过得 20 分，任一失败得 0 分，不按子项计部分分）
- **冻结基线**：PowerContext v1.2.0 (`commit 9db1753434162c0aa7c9f1189a1722e617880a52`)
- **参赛基线分支**：`2026-competition` (`commit dab240063bfcfa7917898dc44da4baadb3747bd0`)
- **开发分支**：`competition/pi-session-branch-resume`
- **隔离工作目录**：`E:\OceanBaseContest\powercontext-pi-session`
- **交付形式**：产品仓库 HTTPS URL + 40 位完整 Commit SHA

---

## 二、功能契约要求

### 1. 模块接口规范 (`powercontext.sources.pi_session`)

- **导出类与对象**：
  - `PiSessionInput(content: bytes, leaf_id: str | None = None)`
  - `PiEventInput` (Pydantic 模型，包含 `session_id`, `event_id`, `parent_id`, `event_type`, `role`, `content`, `record`)
  - `parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]`
  - `PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput]`
  - `PiSessionConnector(path: str | Path, leaf_id: str | None = None)`
  - `pi_event_source_id(session_id: str, event_id: str) -> str`
- **元数据命名与版本**：
  - Source 命名：`pi-event`，版本：`1`
  - Connector 命名：`pi-session-history`，版本：`1`
  - Projection 命名：`powercontext.text-evidence`，版本：`1`

### 2. Pi 会话文件与分支解析要求

- **文件编码与会话头**：
  - 接收 UTF-8 字节流，支持可选的 UTF-8 BOM (`\xef\xbb\xbf`)。
  - 首条记录必须为会话头：`type="session"`，`version=3`，`id` 为非空字符串。
  - 后续记录均为字典，具备唯一 `id` 与可选 `parentId`。
  - 父节点约束：`parentId` 必须为空或指向已经出现的节点（严格防前向引用、自环引用和循环引用）。
  - 非法编码、非字典 JSON、重复 ID、缺失 parent、循环、缺失 leaf 等均原子抛出 `ValueError`，不返回部分结果。
  - 未指定 `leaf_id` 时，默认选择文件末尾最后一个节点。
- **分支路径回溯**：
  - 从指定的叶节点沿 `parentId` 回溯至根节点，生成完整的祖先链。
  - 结果以 `tuple[PiEventInput, ...]` 从根至叶严格保序返回。
  - 控制节点（如 `model_change`, `thinking_level_change` 等）维持图上的祖先父子拓扑，但不生成可见文本证据。
  - 压缩摘要事件（`compaction`, `branch_summary`）仅作为历史证据节点，不得截断或删除其前面的历史原始证据。
- **正文与事件格式规则**：
  - `message` 文本/字符串块：原样保留；多块以换行符 `\n` 连接。
  - `message` 中的 `toolCall` 块：`[tool_call NAME ID] COMPACT_SORTED_JSON_ARGUMENTS`（JSON 键排序、紧凑无多余空格、保留 Unicode 字符）。
  - `role="toolResult"`：`[tool_result TOOL_NAME TOOL_CALL_ID] TEXT`。
  - `role="bashExecution"`：`$ COMMAND` 后换行连接 `OUTPUT`。
  - `compaction` / `branch_summary`：role 为事件类型名称，正文为 `summary`。
  - `custom_message`：role 为 `"custom"`，正文为可见字符串/text 块。
  - 最终事件文本格式统一为：`ROLE: BODY`。
  - `thinking` 思考过程、`image` 图片数据及纯控制节点不进入文本正文。

### 3. Source 持久化与精确证据回查

- **Source 模型 (`PiEventSource`)**：
  - `materialization = SourceMaterialization.CAPTURED`。
  - `source_id` 与 `name` 严格一致，由 `pi_event_source_id(session_id, event_id)` 确定，长度不超过 256 字符。
  - 具有严格的唯一性和幂等性，相同会话相同事件 ID 身份唯一，同事件内容改写触发运行时冲突。
- **证据投影 (`TextEvidence`)**：
  - `source_type = "pi-event"`，`source_id` 匹配 Source name。
  - `content` 保存完整的事件正文。
  - `metadata` 精确保留 `session_id`, `event_id`, `parent_id`, `event_type`, `role`。
- **检索与回查**：
  - `registry.read(source)` 能完整还原对应的 `PiEventInput`。
  - 支持通过 Runtime ingestion 持久化，重启后依然可被 Memory FTS 检索并按精确 Citation 溯源回查完整事件。
  - 大工具结果必须完整保存在 Source 中，不得受 Memory 单条 8192 字节限制影响而发生截断。

### 4. 增量采集、Checkpoint 与重启恢复

- **ConnectorLifecycle 规范**：
  - `PiSessionConnector(path, leaf_id=None)` 在每次运行时先对文件做全局完整解析与校验。
  - 仅向当前 run 会话提交该分支上尚未采集的新事件 (`session.submit(...)`)。
  - 进度通过 `ConnectorLifecycle` 提交持久化 checkpoint，结构中记录已导入事件的身份与哈希摘要。
- **分支切换与追加去重**：
  - 切换分支时，多分支共享的历史祖先事件不重复导入，新分支的特有节点完整增量导入。
  - 重复对同一分支采集时具有幂等性（0 新增 items，checkpoint 保持不变）。
  - 文件追加新记录后继续采集新增节点。
- **断点一致性与防改写（Mutation Rejection）**：
  - 已导入的持久化事件如果在文件中被改写篡改，采集器立即检测并抛出 `ValueError`。
  - 失败或异常发生时，checkpoint 不得提前推进，保留已提交的持久化断点。
  - 修复文件后，系统能够无缝从原断点继续增量采集。

---

## 三、评分要求与测试对照

| 必测项分组 | 核心要求 | 官方验收测试 | 验证结果 |
| :--- | :--- | :--- | :--- |
| **完整解析** | 正确解析单分支/多分支，严格提取可见消息、工具调用、工具返回、摘要，排除控制节点与思考/图片内容 | `test_explicit_branch_preserves_tool_and_summary_events`<br>`test_invalid_graphs_fail_atomically`<br>`test_invalid_archives_fail`<br>`test_bom_bash_custom_and_control_parent_are_preserved` | **PASS** |
| **持久化与引用** | Source 身份稳定唯一，TextEvidence 投影字段完备，入库持久化后重启可通过 FTS 检索与 Citation 精确回查 | `test_public_sessions`<br>`test_reimport_rejects_changed_event_payload` | **PASS** |
| **增量与失败恢复** | 分支切换去重、追加采集、断点持久化、文件篡改与损坏原子拒绝、修复后断点恢复 | `test_branch_switch_restart_full_evidence_and_mutation_rejection` | **PASS** |
