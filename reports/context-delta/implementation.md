# 实现说明

## 修改

- `src/powercontext/builtin/runtime/context_pack.py`：新增 Pack/Delta 模型、规范 JSON 与 Base64 wire 编码、UTF-8 安全分块、SHA-256 和接收端校验重建。
- `src/powercontext/builtin/runtime/application.py`：新增 `ScopedContextApplication.prepare_incremental`。它调用现有 `prepare`，空结果转换为空文本 Pack；有 base 时生成 Delta。
- `tests/builtin/runtime/test_context_pack.py`：覆盖 wire oracle、中文/emoji/组合字符分块、任意有效公共前缀、序列化独立性、首/中/尾部变化、删除、重建空结果以及 tampering。
- `reports/`：保留赛题评分要求、基线、架构、实现、测试、字节测量与提交结果。

## 正确性边界

Delta 不携带完整 target，也不引用发送端进程状态。`apply_context_pack_delta` 仅通过 base Pack 的 digest 和 prefix、delta 后缀及 target digest 生成结果。每轮 prepare 的文本（包括实际 citation 身份和版本）原样分块，因此引用变化会出现在后缀中，无法复用时也不会被忽略。

完整 Pack 的 `byte_count` 包括它自身；Delta 的 `byte_count` 是 `len(delta.to_bytes())`，不进入 JSON。错误基础版本、非法 prefix、字段污染、错误 Base64、篡改摘要或计数均拒绝。

## 实测环境限制

公开 QMSum workload 只发布了 2 个 meeting turn，隐藏的 8-turn 起始及 40-round 官方字节序列没有随公开分支提供。当前机器的 WSL 返回 `Wsl/ERROR_ACCESS_DENIED`，Docker daemon 未连接；已用隔离 Python 3.12 环境运行公开验收，并用公开样例文本完成独立协议成本场景。此本地成本报告不能替代隐藏 workload 的官方 45% 判定。
