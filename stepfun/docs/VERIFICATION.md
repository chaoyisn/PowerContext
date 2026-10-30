# 验证记录

## V3（2026-10-30）

- 实际浏览器向量查询的 seekdb-js 执行边界追踪：`GET_SQL` 返回语句与后续执行语句 SHA-256 均为 `528ee53fea21627bcfdb3964f981a15c52c52d981480e4859ef229f5e4a40c87`；数据库返回 3 行，ID、原文、得分和排序与 API 响应一致。SQL 中的全文、向量和 RRF 均在数据库执行。证据是 SDK 执行边界，而非数据库审计日志：`benchmark/results/v3/trace-verification.json`、`api-sql-trace.log`。
- 有窗口 Edge 156.0.4314.50 使用 Intel Gen12LP 非回退适配器，支持 shader-f16，WebGPU FP16 加载本地权重并完成真实 384 维推理。重复输入 L2 差异 0.0041175；不能假定与 q8 空间可混用。`edge-gpu.json`、`edge-gpu.png`。
- 模拟 adapter 不可用与初始化失败均回退 WASM q8 并完成两段真实推理：`fallback.json`。另在有窗口 Edge 成功加载 GPU 模型后注入错误，清理并回退 q8 推理通过：`gpu-disposal.json`。模拟仅注入测试 Worker 响应，不修改全局浏览器设置；GPU 推理中途故障与实际设备丢失未实测。
- `space-probe.json` 使用真实 FP32/q8 输出验证双向错配被前端拦截，数据库 API 另有 409 测试；刷新恢复、API 重启查询、知识库隔离和连续导入/重复导入用真实向量验证（`restart-probe.json`、`chrome-workflow.json`）。数据库断连恢复和真实向量失败批次恢复尚未验证。
- `batch-ui.json` 用四份真实浏览器 q8 向量验证单请求批量导入、去重和检索可见；`batch-integration.log` 使用合成 fixture 验证批次中途失败保留 processing、随后重试成功。Chrome/Edge 的 headless E2E 和有窗口 Edge 工作流均通过，创建知识库后选回旧 ID 的缺陷已修复。
- T1–T9：PASS；T10：BLOCKED（断连恢复未测）；T11：PASS（Chrome 完整 UI 为 headless，Edge 完整 UI 为有窗口）；T12：BLOCKED（缺冷/热完整基准、应用端同口径优化前后样本及峰值内存）。V1/V2 记录保留在下方。

## V2.1（2026-10-30）

- 独立 Playwright Chrome 156.0.8078.73 与 Edge 156.0.4314.50，均为 headless、单页、单 Worker 串行执行：静态页面 L0、实验页 L1、普通 Worker L2、真实 WASM 模型初始化与推理 L3 均 PASS。截图、网络、控制台、向量摘要见 `benchmark/results/v2/{chrome,msedge}-probe.json` 和对应截图。
- 两条固定文本及重复输入得到 384 个有限值；范数范围 0.9999996845–1.0000001586，不同输入 L2 距离 1.30189424，重复输入距离 0。q8 实际请求本机 `model_quantized.onnx`（22,972,370 字节），本地 ONNX Runtime WASM 与模块均加载成功，最终网络记录无外部 HTTPS 请求。
- Chrome 实际 UI 导入三份文档，Worker 生成向量并经 API 写入 seekdb，导入完成前回读校验；重复导入被跳过。自然语言查询得到三条数据库混合检索结果，`privacy.md` 排名第一。见 `chrome-workflow.json` 和 `chrome-workflow.png`。该记录不包含其他知识库列表内容。
- seekdb 1.4.0 SDK 的 `hybridSearch()` 源码先执行 `GET_SQL`，再校验并执行返回的 `querySql`，结果直接来自数据库；当前样本没有捕获该次生成 SQL 的数据库执行跟踪，不能将该证据缺口称为已闭合。
- Vite 的依赖预构建会触发页面刷新，实验服务器禁用热更新以避免初始化被中断。首次运行曾从 CDN 获取 WASM；现显式使用安装包中的本地 WASM 和模块，重新运行后无外部请求。上轮桌面浏览器控制失败的根因仍未确认。
- T1、T2、T3、T5 本轮 PASS；T4 BLOCKED（GPU/回退未测）；T6 BLOCKED（缺本次生成 SQL 执行跟踪）；T7 部分通过（增量、去重，其他状态待复验）；T8、T9 本轮真实向量待复验；T10 部分；T11 BLOCKED（仅 headless Chrome 完整 UI 和 headless Edge 实验页）；T12 部分。下方 V1 PASS 是合成向量的历史结果。
- `npm run build`、unit 4/4、串行 integration 3/3 通过；数据库 integration 仍使用合成向量，结果单独写入 V2 目录。向量空间目前没有按精度强制隔离，切换精度或 GPU 回退后不得将向量混入同一知识库；这项修复及验证仍待完成。

## 环境与 SDK

- 官方基线：`upstream/2026-competition-ecosystem`，基线 commit `d647275c308e09b7b623f322a26f5c4e85734fb0`。
- 项目分支：`competition/stepfun-edgeseek`，基于上述基线的隔离 worktree。
- Node.js `24.14.0`、npm `11.3.0`、seekdb-js npm 包 `seekdb@1.4.0`。
- 本机 `oceanbase/seekdb:latest` Server，项目专用 `127.0.0.1:2882` 与持久化 volume。
- 官方 npm registry 安全审计：0 vulnerabilities；通过 `adm-zip@0.6.1` override 修复 seekdb native binding 的传递依赖告警。
- 已核验模型仓库与 Apache-2.0 许可、revision 和 ONNX 文件。该项不等于浏览器已成功运行模型。

## 已执行检查

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| TypeScript 与 Vite production build | PASS | `npm run build` 成功；输出 Worker、ONNX Runtime Web WASM、React bundle |
| Unit | PASS，4/4 | chunk、SHA-256、Recall@K/MRR 与压缩比缺失值处理 |
| Integration | PASS，3/3 | API 错误校验、seekdb-js 真实向量回读与混合检索、真实 API 导入/重启流程 |
| P0 数据库 | PASS | `benchmark/results/seekdb-p0-actual.json` 含 SDK 版本、回读向量、结果和 `GET_SQL` 语句 |
| 官方 npm audit | PASS | 0 vulnerabilities |
| Playwright 发现测试 | PASS | `npm run test:e2e -- --list` 发现 Edge、Chrome 两个项目 |
| Playwright 浏览器运行 | BLOCKED | 首次 Edge page target crash；Chrome worker 退出码 `3221226505`。资源释放后 Edge 在 Playwright page fixture setup 等待 180 秒后超时。浏览器桥尝试打开第二个 Edge tab 时返回 `net::ERR_INSUFFICIENT_RESOURCES` |

一次真实 API 集成样本（384 维单位 fixture vector，不是浏览器模型输出）：upsert `6.77 ms`、索引刷新 `608.54 ms`、回读可见性 `4.72 ms`、全文搜索 `10.20 ms`；API 重启后混合搜索 `6.15 ms`。单次测试测量会受系统负载与 seekdb 状态影响，不作为稳定基准。最新原始值在 `benchmark/results/seekdb-api-actual.json`。

seekdb 混合检索测试通过 SDK `hybridSearch()`，拦截到数据库 SQL：`SELECT DBMS_HYBRID_SEARCH.GET_SQL(..., @search_parm) ...`。`embeddingFunction: null` 下的外部向量真实写入并回读一致。4 维 P0 fixture 用于验证 SDK/数据库接口；384 维 API 流程由工作流集成测试覆盖。

## T1–T12 验收矩阵

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| T1 文档向量在浏览器运行且没有云端推理 | **BLOCKED** | Worker 链路已实现，E2E 未到达页面测试体，尚无真实浏览器推理或网络请求记录 |
| T2 查询向量维度及数值合法 | **BLOCKED** | Worker 和 API 均有归一化/维度校验；查询 Worker 实测未完成 |
| T3 INT8 或 FP16 权重实际加载 | **BLOCKED** | Hugging Face 模型 revision 与权重文件已核验；浏览器未成功下载并运行权重 |
| T4 WebGPU 实际运行或自动 WASM 回退 | **BLOCKED** | WebGPU adapter、推理验证及 WASM 兜底代码已实现；没有真实 GPU/浏览器执行证据 |
| T5 浏览器向量写入 seekdb 并精确回读 | **BLOCKED** | API 集成用 384 维 fixture vector 通过精确回读校验；浏览器生成向量未进入真实 DB 流程 |
| T6 混合检索由 seekdb 内部执行 | **PASS** | `seekdb-js@1.4.0` `hybridSearch()` 成功，真实 DB 生成 `DBMS_HYBRID_SEARCH.GET_SQL` SQL |
| T7 连续/重复/增量导入及索引刷新 | **PASS** | 真实 API/seekdb 集成验证重复跳过、新文档刷新/回读可见并可全文检索 |
| T8 多知识库隔离 | **PASS** | 真实 API/seekdb 集成验证两个独立 collection 不返回对方文档 |
| T9 后端重启后文档与向量仍在 | **PASS** | 真实 Node API 子进程停止、重启后原文可读，混合搜索仍返回已保存文档 |
| T10 模型错误、维度、网络和数据库断连错误处理 | **BLOCKED** | 模型 key `409`、错误维度 `422` 已测；网络中断与数据库断连尚未执行 |
| T11 Chrome/Edge 上传、搜索和结果 UI | **BLOCKED** | Playwright 测试已配置并发现两项目，但浏览器 page fixture 无法启动/取得资源，未执行交互流程 |
| T12 冷/热启动与实际性能 | **BLOCKED** | 计时和 JSON/CSV 导出实现；仅取得 API/DB 集成耗时，浏览器模型和端到端数据尚无实测 |

本轮未把 fixture vector、模型文件仓库信息、代码分支或页面渲染当成浏览器模型实测证据。必须在资源充足的 Chrome/Edge 环境中重跑 `npm run test:e2e`，并在实际 WebGPU 设备上单独完成 T4 GPU 路径验证。
