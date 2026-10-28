# 实现说明

## 代码变更

- src/powercontext/builtin/artifacts/memory/http_reranker.py：新增 HTTPMemoryReranker、参数错误与响应错误类型。
- src/powercontext/builtin/artifacts/memory/__init__.py：从 Memory 公共包导出适配器。
- tests/builtin/artifacts/memory/test_http_reranker.py：新增 MockTransport 批次、协议、失败、身份和兼容性回归。

## 行为

适配器保留题面指定的构造与 MemoryReranker.rerank(query, candidates, limit) 契约。它按 batch_size 发送候选，使用完整输入的一基 rank，不重排或重建候选对象。所有批次响应进入一次全局排序；负数、零和整数分数可用，布尔值、NaN、Infinity、浮点溢出和非数值会被拒绝。

响应必须精确匹配协议字段。每批的 rank 必须与该批实际发送的 rank 一一对应；拒绝重复 JSON 键、重复/跨批 rank、缺失 rank、额外字段、错误类型、空响应和非法 JSON。错误不包含 query 或候选正文。

请求由调用方提供的 httpx.AsyncClient 发出。非 2xx、网络和超时异常不被吞掉、不被包装，也不会触发隐式重试。成功决策的 InferenceUsage.requests 来自实际发出的 POST 数。Memory Search 将这些 rank 映射回原 MemoryHit，并在原有 MemoryRerankTrace.usage 暴露请求数。

HTTP endpoint、timeout、headers 和 transport 通过部署应用已有设置构造 endpoint 与 caller-owned client，再通过 Runtime 的 memory_reranker 注入口接入；适配器不接管客户端生命周期。未注入时保持默认关闭。原有 LLMMemoryReranker、其 rank 规范化和 fallback 行为均未改。

## 持久化与安全

适配器只读候选并返回 rank 决策，不写数据库、不改索引、不更改候选证据。模块不会记录请求/响应正文或认证头；校验错误只包含结构原因和可选 rank。
