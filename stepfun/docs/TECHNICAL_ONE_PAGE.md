# EdgeSeek · 技术单页

**应用**：TXT/Markdown 在浏览器 Worker 分块并生成向量；Node API 不执行模型推理；seekdb 保存原文、向量与元数据，提供向量、全文和混合搜索。

**模型与量化**：Apache-2.0 的 `Xenova/all-MiniLM-L6-v2`，固定 revision `751bff37182d3f1213fa05d7196b954e230abad9`，384 维、mean pooling 和 L2 归一化。FP32、FP16、q8 权重实测分别为 90,387,606、45,297,825、22,972,370 字节，FP32/q8 为 3.94 倍。资产和 ONNX Runtime 均从本机提供。

**后端与空间**：有窗口 Edge 的 Intel Gen12LP 物理适配器已执行 WebGPU FP16；GPU 不可用或初始化失败的模拟场景已回退 WASM q8 并完成真实推理。集合按模型、revision、tokenizer/Transformers 版本、精度及后端隔离；未验证跨配置兼容性。旧版无精度标识的集合需新建并重新向量化。

**数据库与增量**：seekdb-js 1.4.0 使用 `embeddingFunction: null` 接收浏览器向量，`hybridSearch()` 调用数据库 `DBMS_HYBRID_SEARCH.GET_SQL` 并执行返回 SQL；SDK 执行边界的语句哈希与数据库行和 API 排序已交叉核对。按知识库和 SHA-256 去重；批量逐份 upsert 后统一刷新、回读，再标记完成。

**质量**：7 文档、5 查询、Top 10 的独立小样本中，FP32/q8/FP16 的向量和混合检索平均 Recall@5、Recall@10 均 1.0，nDCG@10 均 0.98394；包含英文、中文及跨语言样例。候选少于 10 条，Recall@10 不具区分力，不能代表通用质量。

**性能与环境**：Windows 11，Intel i7-12650H，Chrome 156.0.8078.73 headless、Edge 156.0.4314.50 有窗口。q8 Batch 1/4/8/16 每组 5 次中位吞吐为 69.23/47.92/44.57/45.95 条/秒。相同 4 条真实向量的 SDK 写入与刷新，逐条刷新中位 2492.75 ms，4 次写入后统一刷新 671.57 ms；均验证最终可检索，比较不含 API 和建表耗时。

**仍待验收**：GPU 推理中途故障与设备丢失、数据库断连恢复、有窗口 Chrome UI、冷热启动完整基准、浏览器峰值内存与更大独立质量集。详细步骤和原始记录见 `RUN.md`、`VERIFICATION.md`、`BENCHMARK.md` 与 `benchmark/results/v3/`。
