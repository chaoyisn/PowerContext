# 验证记录

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
