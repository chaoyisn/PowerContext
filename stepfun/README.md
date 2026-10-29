# EdgeSeek

EdgeSeek 是一个浏览器端知识库：TXT/Markdown 文档在 Web Worker 中计算向量，Node API 将原文、向量和元数据写入本机 seekdb，并由 seekdb 执行全文、向量或内部 RRF 混合检索。项目不提供 LLM 聊天，也没有云端推理 API。

## 当前状态

- P1 数据与 API 路径已在真实 seekdb Server 上验证，包含向量回读、增量导入、去重、索引刷新、知识库隔离和 API 重启持久化。
- seekdb-js `1.4.0` 的 `hybridSearch()` 已验证调用数据库 `DBMS_HYBRID_SEARCH.GET_SQL` 路径。
- 浏览器 Worker、WebGPU 优先与 WASM 降级逻辑已实现。受本机浏览器资源限制，端侧模型推理、Chrome/Edge E2E 和实际性能采样尚未完成；详见 [VERIFICATION.md](docs/VERIFICATION.md)。

## 启动

Windows PowerShell：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\scripts\install.ps1
.\scripts\start.ps1
```

开发 UI：<http://127.0.0.1:5174/>。Node API：<http://127.0.0.1:4174/>。启动脚本会启动项目专用 seekdb 容器，监听 `127.0.0.1:2882`，使用持久化 Docker volume `edgeseek-seekdb-data`。

详细依赖、Linux 启动方式、生产构建和测试说明见 [RUN.md](docs/RUN.md)。

## 设计与验证

- [架构](docs/ARCHITECTURE.md)
- [验证记录与 T1–T12 矩阵](docs/VERIFICATION.md)
- [性能与质量基准](docs/BENCHMARK.md)
- [技术单页](docs/TECHNICAL_ONE_PAGE.md)

模型固定为 Apache-2.0 的 `Xenova/all-MiniLM-L6-v2`，revision `751bff37182d3f1213fa05d7196b954e230abad9`，384 维。它面向英文语义；正式中文语料的召回质量应另行评估。
