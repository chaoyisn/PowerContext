# EdgeSeek 架构

## 数据路径

1. React 页面读取 TXT/Markdown，在浏览器中计算 SHA-256 并按 850 字符、120 字符重叠切块。
2. 页面将文本交给 Web Worker。Worker 使用 Transformers.js 加载固定 revision 的 ONNX 模型，优先试 WebGPU FP16；adapter、模型载入或推理校验失败后，在 WASM 上用 INT8 重新初始化并验证。Pooling、归一化和向量校验都在 Worker 中完成。
3. Node API 接收浏览器传来的文本、SHA-256、分块和归一化向量。后端没有 Transformers.js 依赖，不计算或补造 embedding。
4. API 使用 `seekdb` npm 包（seekdb-js）连接本机 seekdb Server。每个知识库拥有一张元数据记录和一个独立 collection。collection 的 `embeddingFunction` 显式设为 `null`，禁用 SDK 默认模型。
5. 导入时 API 逐份 upsert 文档、向量与元数据，批次完成后调用一次 `refresh_index()`，再读回所有 ID 和完整向量逐值校验。只有校验成功才把 SQL 文档状态改成 `imported`；中途失败保留 `processing` 以便重试。
6. 查询向量由同一浏览器 Worker 生成。混合模式调用 `collection.hybridSearch()` 并将 RRF 配置传给 seekdb；JavaScript 不拼接或融合独立的全文与向量列表。

## 数据模型

- `edgeseek_kbs`：知识库 ID、名称、固定 `modelKey`、向量维度。
- `edgeseek_documents`：原文、SHA-256、分块数、处理状态和创建时间。
- `edgeseek_kb_<32位ID>`：seekdb collection，保存 chunk ID、chunk 文本、浏览器生成的 embedding 与元数据。
- metadata 包含文档 ID、文件名、SHA-256、chunk 序号、模型 key 和精度。

同一索引只接受与创建时记录的模型、revision、tokenizer/Transformers 版本、精度和后端一致的 384 维向量；不匹配返回 HTTP 409，非法向量返回 422。后端分别隔离是保守措施，并不宣称不同后端的输出必然不兼容。旧版缺失精度身份的知识库保留原文，但需要新建知识库并重新向量化后才能查询或导入。Worker 运行中途回退时会丢弃先前 GPU 批次并以 q8 重算整批，API 与前端均阻止其进入不匹配的索引。活动知识库和主题偏好保存在浏览器 `localStorage`，原文与向量保存在 seekdb，API 重启不会清除它们。

## 检索模式

- **向量**：`collection.query()`，由 seekdb 向量索引排序。
- **全文**：`collection.hybridSearch()` 仅提供全文条件，由 seekdb 全文索引检索。
- **混合**：`collection.hybridSearch()` 同时提供全文条件和外部 `queryEmbeddings`，并配置 seekdb 内部 RRF。SDK 通过 `DBMS_HYBRID_SEARCH.GET_SQL` 请求数据库生成执行 SQL。

三个模式的结果都来自当前知识库的真实 collection。界面不保存演示结果；数据库不可用时会显示错误状态。

## 组件边界

- `frontend/`：React、交互、Worker 客户端、耗时采集和导出。
- `server/`：最小 Node HTTP API 与 seekdb-js 数据访问。
- `scripts/`：本地 seekdb、开发服务、生产服务与 P0 SDK 验证。
- `tests/`：Node 单元测试、真实数据库/API 集成测试、Playwright 浏览器 E2E。
- `benchmark/`：标注语料、质量函数与实际运行记录。

## 已知限制

模型针对英文语义，中文赛题语料的质量尚未实测。当前认证配置针对单机开发，不包含多用户鉴权。WebGPU/FP16 的真实设备兼容性和浏览器运行已列为验收项，但本机资源不足时不能据此宣称通过。
