# EdgeSeek · 技术单页（V1 初稿）

## 目标

提供一个本地优先的文本知识库。用户导入 TXT/Markdown 后，浏览器完成文本向量化，seekdb 保存原文、向量和来源信息，并执行向量、全文或数据库内部混合检索。

## 技术路径

- React + TypeScript + Vite 页面；Transformers.js 4.3.2 Web Worker；ONNX Runtime Web。
- 固定公开模型 `Xenova/all-MiniLM-L6-v2`，Apache-2.0，revision `751bff37182d3f1213fa05d7196b954e230abad9`，384 维，mean pooling + L2 normalization。
- WebGPU FP16 优先；实际 adapter、加载和向量探测失败时回退 WASM INT8。性能页另可测 FP32/WASM。
- Node.js HTTP API 只校验、持久化和查询，不加载 embedding 模型。
- 官方 `seekdb` npm SDK `1.4.0`，外部向量配置 `embeddingFunction: null`；混合搜索走 `hybridSearch()` 与 seekdb 内部 RRF。

## 数据可信度

API 导入会校验 SHA-256、384 维、有限值、归一化和 model key；upsert 后调用 `refresh_index()`，再从真实 seekdb 回读向量并逐值比较。重复内容按知识库和 SHA-256 跳过。每个知识库有独立 collection。

## 已有证据

- 本地 seekdb Server 上 P0 外部向量读取、回读与 `DBMS_HYBRID_SEARCH.GET_SQL`：通过。
- 真实 API 集成覆盖增量搜索、重复导入、租户隔离与 Node API 重启持久化：通过。
- `npm run build`、4 个 unit tests、3 个 integration tests、npm audit：通过；实际日志与 timings 存于 `benchmark/results/`。

## 未验证项与风险

受 Windows 主机浏览器资源限制，浏览器模型加载、WebGPU/WASM、Chrome/Edge UI 上传与搜索均未完成实测；因此没有真实模型吞吐、压缩比或搜索端到端性能数据。所选模型偏英文，中文正式语料需重新评估召回。验收状态见 [VERIFICATION.md](VERIFICATION.md)。

## V2 优先事项

先在专用 Chrome/Edge 测试环境完成 T1–T4、T11–T12，再以正式中文语料比较英文模型与中文向量模型；确认质量后测量批量导入、热缓存与 WebGPU 推理的端到端瓶颈。
