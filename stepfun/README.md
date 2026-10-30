# EdgeSeek

EdgeSeek 是一个浏览器端知识库：TXT/Markdown 文档在 Web Worker 中计算向量，Node API 将原文、向量和元数据写入本机 seekdb，并由 seekdb 执行全文、向量或内部 RRF 混合检索。项目不提供 LLM 聊天，也没有云端推理 API。

## 当前状态

- 浏览器 Worker 的 WASM q8 与有窗口 Edge 的物理 GPU WebGPU FP16 均已真实推理；模拟 GPU 不可用和初始化失败后，WASM q8 真实推理通过。
- 浏览器真实向量已写入 seekdb。SDK 执行边界追踪核对了 `GET_SQL` 返回语句与后续执行的语句及数据库结果，详见 [VERIFICATION.md](docs/VERIFICATION.md)。
- 知识库绑定精度与后端；旧版未记录精度的知识库必须重新创建并导入。精度质量对照为小样本，批量刷新优化、完整桌面 UI 及断连恢复仍待验收。

## 启动

Windows PowerShell：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\scripts\install.ps1
npm run fetch:model
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
