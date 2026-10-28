# Embedding 请求合并与缓存架构

## 修改文件

- `src/powercontext/builtin/inference/coalescing.py`：包装器、等待队列、批次调度、缓存、取消与结果校验。
- `tests/builtin/inference/test_coalescing.py`：顺序、usage、LRU、并发、取消、失败隔离、非法向量和查询/文档隔离测试。

## Singleflight 与批次调度

包装器在单一事件循环内维护 `_inflight` 和 `_pending` 两个字典，key 为 `(embedding_kind, text)`。新 key 在首次 await 之前进入 in-flight 表，因此并发调用会拿到同一个 Future；已有 key 直接等待，不会重复提交 Provider。Dispatcher 在 `coalesce_ms` 窗口后取出待处理 key，按 query/document 类型分组，并按 `max_batch_size` 切分。不同批次各自运行异步任务，不用全局锁串行化不同内容。

每个调用分别保留原始输入文本序列。待唯一 key 完成后按原序和重复位置重建结果；同一输入中的重复文本只等待、计算一次，但返回仍保留每个重复位置。空输入直接返回空向量和零 usage。

## 缓存 key、容量与淘汰

完成缓存是 `OrderedDict` LRU，访问时移动到最近端，写入后从最久未使用端淘汰，长度始终不超过 `cache_size`。容量为 0 时不保存完成结果，但 in-flight 去重仍生效。缓存属于包装器实例且不会跨实例共享；一个实例固定封装一个底层模型和 profile，所以 Provider、部署、模型及维度身份由实例边界隔离。`profile` 原样暴露给调用方。实现 query embedding 协议的底层模型采用独立 query key，避免将非对称 query 向量误作 document 向量。

Provider 响应先校验向量数、profile 维度和有限数值，再以不可变 tuple 写入缓存；不完整、错误维度或 NaN/Infinity 结果不会污染缓存。LRU 与 in-flight 映射均只保存当前有效条目。

## 取消、错误和 usage

共享 Future 通过 `asyncio.shield` 等待。单个或全部调用者取消，只取消该调用的等待，不取消共享批次；Provider 工作完成后仍可填充缓存。批次完成、异常和取消路径都会清理对应 in-flight 条目。失败按原异常传播给该批次等待者，不缓存，后续请求可重新发起；独立批次由独立任务运行。

批次结果携带该次底层调用的 usage。一个调用以批次身份去重后汇总自己等待过的每个不同批次一次；共享批次会按官方语义分别出现在各等待者的返回 usage 中。纯缓存命中 requests、input_tokens 和 output_tokens 为 0。

**未做的扩展：**没有增加 Redis、全局缓存或外部状态；官方接口只要求同一事件循环中共享包装器实例内协调。
