# Embedding 赛题需求核对

题目来源：`competition/challenges/memory-02-embedding-batches/instruction.md`，冻结基线 `9db1753434162c0aa7c9f1189a1722e617880a52`。官方要求公开验收和平台必测组全部通过才得 20 分。

| 官方要求 | 实现与验证 |
| --- | --- |
| `CoalescingEmbeddingModel(model, *, max_batch_size=64, coalesce_ms=5.0, cache_size=1024)`，暴露 `profile`，`embed` 返回 `EmbeddingResult` | `src/powercontext/builtin/inference/coalescing.py` 实现；配置边界和公开接口单测通过 |
| 跨调用共享同文本的执行中计算，允许晚到等待者加入 | 同一包装器实例中按 embedding 类型和文本登记 in-flight Future；公开并发验收通过 |
| 去重文本批次不超过 `max_batch_size`，空输入不请求模型 | Dispatcher 按类型分组并限长切批；单测和公开验收通过 |
| 去重后恢复每个调用的原始顺序和重复位置 | 对调用输入保留原序，等待唯一 Key 后重建向量 tuple；公开验收通过 |
| 成功结果进入有界 LRU；容量为 0 时只关闭完成缓存 | `OrderedDict` 命中刷新顺序、超限淘汰；0 容量行为由单测验证 |
| 失败传递给相关等待者、失败结果不缓存、独立批次继续 | 批次级异常解析与 in-flight 清理；失败重试、独立批次测试通过 |
| 向量数不匹配抛 `ValueError` | Provider 响应按批次文本数校验；公开验收和单测通过 |
| 取消一个等待者不能取消共享底层工作 | 等待 Future 使用 `asyncio.shield`；单个及全部等待者取消后后台完成的测试通过 |
| usage 按每个调用等待的不同物理批次汇总，纯缓存命中 requests 为 0 | 通过批次身份去重 usage；公开验收和 usage 单测通过 |
| 原生 Memory 写入和向量搜索正确，6 个 scope、24 条文本、批次上限 6 时底层恰好 4 次请求，后续缓存查询不新增请求 | 官方 `test_native_request_budget.py` 实际调用计数断言通过；整套公开验收 8/8 |

本地实现针对 profile 隔离采用包装器实例边界：每个包装器只封装一个底层模型及其 `profile`，缓存不在包装器间共享。对于实现 `QueryEmbeddingModel` 的非对称模型，query 与 document 使用不同 key；对称模型共用 document key。

**本地验证状态：**官方公开 Embedding 验收 PASS（8/8）。平台必测环境尚未运行，因此官方得分仍待提测。
