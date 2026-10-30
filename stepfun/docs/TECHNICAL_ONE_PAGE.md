# EdgeSeek · 技术单页

**方案与模型**：TXT/Markdown 在浏览器 Worker 分块、向量化；Node 仅传输与访问 seekdb，不执行 Embedding。模型为 Apache-2.0 的 `Xenova/all-MiniLM-L6-v2`，revision `751bff37182d3f1213fa05d7196b954e230abad9`，384 维、mean pooling、L2 归一化。FP32/FP16/q8 实测文件分别为 90,387,606 / 45,297,825 / 22,972,370 字节，FP32/q8 为 3.94 倍。模型和 WASM 均由本机提供。

**后端与恢复**：Intel Gen12LP 物理 GPU 的有窗口 Edge 已实际执行 WebGPU FP16；不可用或受控推理故障后回退 WASM q8。集合按模型、revision、tokenizer/运行时版本、精度及后端隔离；回退后不匹配的查询被阻止。真实硬件 Device Lost 未复现。

**seekdb**：seekdb-js 1.4.0 使用 `embeddingFunction: null`；数据库 `DBMS_HYBRID_SEARCH.GET_SQL` 生成 SQL 并实际执行内部向量、全文与 RRF，执行边界哈希和结果已核对。批次逐份 upsert 后统一刷新并回读；按知识库和 SHA-256 去重。数据库故障返回 503，未确认文档保留 processing，恢复后以稳定 ID 重试；批次不是跨文档事务。

**质量**：原创合成集 100 文档、30 查询，英文/中文/跨语言各 10，gold 在评测前固定且产品不读取。FP32/q8/FP16 向量 Recall@5 为 0.633/0.600/0.633，nDCG@10 为 0.595/0.606/0.595；混合 Recall@5 均为 0.667，nDCG@10 为 0.659/0.658/0.659。跨语言向量 Recall@10 均为 0.10；合成标签按构造生成，不能代表通用数据。

**性能**：Windows 11、i7-12650H、Chrome/Edge 156、seekdb 1.4.0.0。冷初始化 FP32/q8/FP16 分别 3157/2351/3266 ms，同 context 新 Worker 热初始化 2726/2027/1827 ms；冷/热各单次，缓存可用性另经阻断模型 HTTP 验证。4 文档应用导入各 5 次：逐条刷新中位 4169 ms，统一刷新 1413 ms，两批刷新 1800 ms，全部可检索。32 文档 q8 Batch 1/4/8/16 中位吞吐 34.08/38.57/37.69/37.60 条/秒，保留 Batch 4 默认值。

**范围与限制**：q8 查询页面可见端到端中位数 173 ms、P95 248 ms（5 次，同机）；最终队列版 Chrome/Edge E2E 和有窗口隔离代理断连恢复通过。GPU 内存及进程真实峰值为 UNKNOWN，工作集为采样最大值；提交表单字段需人工核对。详细方法、原始数据和结果见 `VERIFICATION.md`、`BENCHMARK.md` 与 `benchmark/results/v4/`。
