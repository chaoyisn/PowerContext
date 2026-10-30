# 性能与检索质量基准

## V2.1 实测样本

固定模型本地文件：FP32 90,387,606、FP16 45,297,825、q8 22,972,370 字节；FP32/q8 约 3.94 倍。文件大小不代表 FP32 或 FP16 已完成推理。

单次 headless Chrome q8 实验页：Worker 初始化 1414.9 ms，三条串行推理 32.9 ms；Edge 同口径分别为 1334.2 ms、33.2 ms。Chrome 真实导入三条文档的单条向量化为 44.7、36.6、22.8 ms；写入 170.17、9.37、27.00 ms；索引刷新 527.36、805.56、603.42 ms。一次查询向量化 17.6 ms、seekdb 混合检索 27.99 ms、端到端 94.7 ms。原始样本在 `benchmark/results/v2/`，上述均非五次中位数。冷热缓存、FP32/FP16 对照、质量指标和批量比较尚未测量。

## 采集口径

浏览器通过 `performance.now()` 记录 Worker 与端到端阶段，通过 API 返回 `dbMs`、写入、索引刷新和可见性检查时间。下列事件写入浏览器 `localStorage` 的 `edgeseek.performance.v1`，上限 2000 条，可在性能页导出 JSON 或 CSV。

| 事件 | 含义 |
| --- | --- |
| `model.asset` | Transformers.js progress callback 提供的文件名、文件大小和资源获取耗时；无大小信息时不补估算值 |
| `model.load` | 页面总加载耗时、Worker 初始化耗时、模型精度/后端和资源大小报告状态 |
| `model.compression` | 同一固定 revision 实际加载 `model.onnx` 与 `model_int8.onnx` 后计算的 FP32/INT8 文件体积比；任一尺寸未实测时不生成该事件 |
| `embedding.batch` | 文档批次或查询 embedding 的数量、批大小、Worker 耗时、吞吐、维度、精度和后端 |
| `network.deduplicate` / `network.document-write` | 浏览器到本地 API 的去重与写入请求往返耗时 |
| `seekdb.write` | seekdb upsert 耗时 |
| `seekdb.index-refresh` | `refresh_index()` 和向量回读可见性耗时 |
| `query.embedding` | 单次查询向量化耗时 |
| `seekdb.search` | seekdb 内部查询耗时、API 网络往返扣除数据库时间后的估值、结果数 |
| `query.end-to-end` | 用户提交查询到结果更新后的页面动画帧耗时 |

资源获取耗时覆盖浏览器缓存读取或远端文件读取，不能单独等同于纯网络传输时长。文件大小来自实际模型加载回调。对跨源缓存命中，若运行时不提供文件大小，日志保留未测状态，不会写入估算压缩率。

模型可选 `auto`、FP32/WASM、INT8/WASM、FP16/WebGPU；文档批处理大小可选 1、4、8。FP32 和 INT8 的体积比只在同一浏览器实际取得两种权重尺寸后生成。

## 质量基准

`benchmark/corpus.json` 提供三篇小型英文技术文档，`benchmark/queries.json` 为每个查询标注相关文件。浏览器测试从真实 seekdb 搜索结果计算 Recall@1 与 MRR，覆盖混合、向量与全文模式。该语料只用于校验检索路径，不代表正式比赛语料的准确率。

完整 Browser E2E 成功后，会把原始结果写入 `benchmark/results/edge-actual.json` 与 `benchmark/results/chrome-actual.json`。目前只有真实 seekdb API/SDK 集成样本：`benchmark/results/seekdb-p0-actual.json` 和 `benchmark/results/seekdb-api-actual.json`。它们使用 API 集成测试的合成单位向量，明确不代表浏览器模型质量或性能。

## 结果解释

本轮没有可报告的浏览器冷启动/热启动、模型推理吞吐、模型压缩比或端到端搜索延迟。真实 seekdb 写入、刷新、回读与搜索耗时记录于集成 JSON；验收矩阵和浏览器资源限制见 [VERIFICATION.md](VERIFICATION.md)。
