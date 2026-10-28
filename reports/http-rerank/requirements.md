# 赛题五：官方评分项与接口要求

## 来源

- 官方题面：[retrieval-01-reranking/instruction.md](https://github.com/oceanbase/powercontext/blob/2026-competition/competition/challenges/retrieval-01-reranking/instruction.md)
- 官方公开验收：[acceptance/test_http_reranker.py](https://github.com/oceanbase/powercontext/blob/2026-competition/competition/challenges/retrieval-01-reranking/acceptance/test_http_reranker.py)
- 冻结基线：PowerContext v1.2.0，commit 9db1753434162c0aa7c9f1189a1722e617880a52

官方题目共 20 分，要求功能与质量条件全部通过，否则 0 分。

## 按验收重要性排列的要求

1. **排序质量门槛**：固定 173 篇 SciFact 摘要、20 条 claim、384 维 MiniLM 离线向量，batch_size=7，取前 10 项；平均 Recall@10 至少 0.95，平均 MRR@10 至少 0.80。结果须由服务分数决定的排序产生。
2. **全局跨批排序**：分数降序；相同分数按完整候选池原始 rank 升序。不得按批局部排序后拼接，也不得把批内序号当全局 rank。
3. **批次覆盖和实际请求数**：每批至多 batch_size 个候选；每个全局 rank 恰好发送一次；正常完成时请求数为 ceil(N / batch_size)，并在 InferenceUsage.requests 中报告实际 HTTP 请求数。
4. **协议与响应校验**：
   - 构造：HTTPMemoryReranker(endpoint, *, client, batch_size=32, policy_id="http-cross-encoder-v1")。
   - 请求为 POST JSON：包含 query 与 candidates；每个 candidate 包含 rank 和 text。
   - 响应恰有 scores 字段，每条记录恰有 rank 和 score。
   - score 是有限数值；响应可以乱序，但必须恰好覆盖本批 rank 一次。
5. **参数和故障语义**：候选非空、batch_size > 0、1 <= limit <= N；非法参数及非法 JSON/schema 抛 ValueError。HTTP 非 2xx 和传输错误保留 httpx 异常。题面未要求重试。
6. **Memory 原生集成与身份保留**：通过 Runtime 已有 memory_reranker 注入口使用适配器；仅选择/排序原 Memory 候选，不重建或改写 Memory artifact、entry ID、entry version ID 和正文。
7. **提交**：提交产品仓库 HTTPS URL 和完整 40 位 commit SHA；实现放在产品 src/；无需创建官方 PR，也不要求由 Agent 代替参赛者提交平台任务。

## 本地公开覆盖范围

官方公开测试覆盖批处理、响应校验、乱序响应、错误传播和原生 Memory 搜索；公开 SciFact 样例仅有 1 条 claim 和 8 篇摘要。公开自测命令为 make -C competition test-rerank。题面明确公开测试通过不代表正式质量门槛已通过。
