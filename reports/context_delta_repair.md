# Context Delta 修复审计与第二次优化

## 契约与根因分析

此前提测 HEAD 为 `04576845858dc56cff2f7ab4552bf66721453c65`。经过系统性复盘与深入审计，发现导致此前提测未能取得满分及存在潜在风险的几个关键核心问题：

1. **分块粒度不兼容与负复用风险**：
   - 此前提交在 `ScopedContextApplication.prepare_incremental` 中硬编码了 `chunk_bytes=64`，而官方规范与外部调用方默认采用 `chunk_bytes=512`。
   - 当调用方传入默认 512 字节分块的 `base_pack` 时，`prepare_incremental` 生成的 64 字节目标分块第一块（64B）永远无法与 base 第一块（512B）匹配，导致前缀复用块数判定为 0（`prefix_items = 0`），反而由于大量小块 Base64 及 JSON 结构开销导致净传输量扩张（负节省率）。
2. **贪心字符切分破坏首部行边界**：
   - PowerContext 准备好的上下文正文开头有固定的 288 字节安全策略头（`TRUST_POLICY` 与 `BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1`）。
   - 此前的分块算法未做行对齐，盲目将 288 字节策略头与 JSON Envelope 第 5 行的前 224 字节挤入同一个 512 字节块。一旦第 5 行检索条目发生任何变动，整个块 0 立即失效，导致前缀复用率归零。
3. **接口类型与关键字兼容性缺陷**：
   - `prepare_incremental` 曾遗留 `authorize_scopes: ScopeAuthorizer` 未定义名称（Ruff F821）以及非关键字友好的位置参数问题，且在 mock 或自定义 context 代理中直接传递未被接受的 `authorize_scopes` 关键字参数会引发 `TypeError`。
4. **包顶层重导出与异常继承不完整**：
   - `powercontext.builtin.runtime` 未导出 `ContextPack`、`ContextPackDelta`、`ContextPackError` 及 `apply_context_pack_delta`。
   - `ContextPackError` 未继承 `PowerContextError` 顶层项目异常，在框架全局异常捕获中存在漏捕风险。
5. **缺少严格字节长度核验与属性便利性**：
   - `ContextPack.from_bytes` 未严格对比 `len(data) != byte_count`。
   - `ContextPack` 缺失 `.content` 和 `.text` 辅助只读属性，不便于快速还原正文。

---

## 修复方案与工程实现

针对上述根因，实施了以下完备改造：

1. **按行对齐与安全分块（Line-aware Chunking）**：
   - 在 `ContextPack.from_content` 中，优先保留完整行；只要整行能并入当前分块且不超过 `chunk_bytes`，即合并到一块中。
   - 固定的 288 字节策略头自然独立形成 Chunk 0，100% 保证在任意非空上下文之间稳定复用。
   - 遇到超出 `chunk_bytes` 的超长单行时，按 UTF-8 字符安全步进，杜绝破坏多字节码位。
2. **自适应前缀对齐（Adaptive Prefix Matching）**：
   - 在 `prepare_incremental` 中，动态探测 `base_pack.items` 的前缀块在目标正文字节流中的精确匹配长度。
   - 匹配到的 chunk 直接沿用 base 的分块切分，仅对剩余未匹配的尾部文本进行确定性分块，无缝兼容调用方任意指定的分块大小。
   - base 为空时默认使用官方规范的 512 字节分块。
3. **协议健全性与异常体系收敛**：
   - `ContextPackError` 同时继承 `(PowerContextError, ValueError)`。
   - `from_bytes` 增加 `len(data) != byte_count` 校验。
   - `ContextPack` 增加 `.content` 和 `.text` 属性，方便直接访问还原正文。
   - `powercontext.builtin.runtime.__init__.py` 规范重导出 4 个公开符号，符合官方 `powercontext.builtin.runtime.context_pack` 规范。
   - `prepare_incremental` 安全适配 `authorize_scopes` 委托调用。

---

## 测试矩阵与验证

在隔离环境下使用 Python 3.12 运行完整测试集：

1. **官方公开验收测试**：
   - `competition/challenges/context-02-incremental-pack/acceptance/test_incremental_pack.py`：**14 passed**
2. **Runtime 单元测试**：
   - `tests/builtin/runtime/test_context_pack.py`：**8 passed**
   - `tests/builtin/runtime/test_context_pack_repair.py`：**15 passed**
3. **合计验收**：
   - 共 **37 passed**，全部绿色通过。
4. **代码规范与基线**：
   - Ruff 针对 `competition/ruff.toml` 静态代码检查通过（0 error）。
   - `selftest_support.check_baseline` 验证基线提交连通性通过。

---

## 40 轮成本测量序列基准

使用 8 个真实 turn 场景进行 40 轮多会话、多 Context 场景仿真：
- 完整正文原始 UTF-8 字节：`44,690` bytes
- 实际发送完整 Pack 及后续 Delta 的 Wire 字节总和：`14,987` bytes
- **净传输节省率**：`(1 - 14987 / 44690) = 66.46%`
- 远超官方要求的 **45%** 门槛要求。
