# EdgeSeek 运行说明

## V4 操作与恢复

Windows 11 先启动 Docker Desktop，在 `stepfun` 目录执行 `npm ci --legacy-peer-deps`、`npm run fetch:model`，再执行 `./scripts/start.ps1`；打开 `http://127.0.0.1:5174/`。已有模型会先做完整性校验；缺失模型会从固定 revision 获取，下载完成后浏览器从本机读取。Linux 使用 `./scripts/install.sh` 和 `./scripts/start.sh`。

选择自动模式时优先 WebGPU FP16，失败回退 WASM q8。不同精度/后端使用不同知识库；回退后不兼容的查询会被阻止，需切换匹配知识库或重新导入。旧版缺少精度身份的知识库需要新建并重新向量化。模型缺失或连接异常会显示错误，不生成假向量。

数据库连接出错会返回 503，失效单连接被丢弃；只读操作最多重试一次，写入不自动重放。批次可能部分写入，尚未确认的文档保持 `processing`，恢复后重新导入即可按稳定 ID 重试。SDK 的单连接查询由最多 16 项的队列保护，等待超过 30 秒返回繁忙错误，单条数据库操作超时 10 秒；大批量请求并非跨文档事务。

复现实验时数据库中的知识库 ID 每次不同。为保留原始记录，在 PowerShell 设置 `$env:EDGESEEK_QUALITY_DIR='benchmark/results/v4/reproduction/small'`、`$env:EDGESEEK_V4_OUTPUT_DIR='benchmark/results/v4/reproduction/runs'` 和 `$env:EDGESEEK_PERF_SUFFIX='-instrumented'`。先启动应用，依次运行 `node scripts/quality-probe.mjs int8`、`fp32`、`fp16` 重建小语料配置；`v4-query-perf.mjs`、`v4-gpu-stability.mjs` 和断连脚本将读取小语料目录的新 ID。每次运行断连脚本可用不同的 `$env:EDGESEEK_RESULT_NAME` 区分输出。运行断连脚本前停止本次启动的 API/Vite，由 `v4-disconnect-probe.mjs` 自行启动隔离代理与测试服务器。运行 V4 的 100 文档评测使用 `node scripts/v4-quality.mjs int8`（或 `fp32`、`fp16`）；评测标注仅由脚本计算指标，不进入产品请求。

## V3 验收与旧知识库

进入 `stepfun` 后，先确保 Docker 中专用 seekdb 服务运行，执行 `npm run fetch:model` 校验固定模型，再运行 `npm run dev`；访问 `http://127.0.0.1:5174/`。创建知识库时先加载所选推理配置；切换精度或实际后端后需使用匹配的知识库。旧版没有记录精度的知识库需新建并重新导入，原数据不会自动迁移。

诊断时可在隔离测试数据下设置 `EDGESEEK_TRACE_SQL=1` 启动 API，输出 SDK 执行边界的 SQL 跟踪；日志可能包含测试查询和文档，不要在真实私有数据上开启。V3 原始记录及脚本见 `benchmark/results/v3/` 与 `scripts/*probe.mjs`。

## V2.1 本地模型与实验页

安装依赖后执行 `npm run fetch:model`，脚本从固定 revision 获取并校验模型，权重保存在被 Git 忽略的 `frontend/public/models/`。运行 `npm run dev:lab`，访问 `http://127.0.0.1:5174/embedding-lab.html`，选择 q8 / INT8 后点击加载；完成后可下载 JSON。实验页使用本地 ONNX Runtime 文件，缺失模型时会报告错误。`node scripts/browser-probe.mjs chrome` 或 `msedge` 可运行独立浏览器的分层检查。完整应用还需启动专用 seekdb 和 `npm run dev:server`。

## 依赖

- Node.js 20 或更新版本；已验证 Node.js 24.14.0、npm 11.3.0。
- Docker Desktop（Windows 11）或 Docker Engine（Linux）。
- seekdb Server 镜像 `oceanbase/seekdb:latest`。
- Edge 或 Chrome 稳定版用于浏览器运行；WebGPU 还要求浏览器、驱动和设备提供可用 adapter。

## Windows 11

在 PowerShell 中进入 `stepfun/`：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
.\scripts\install.ps1
.\scripts\start.ps1
```

`.env` 可配置 API 端口与 seekdb 连接信息。默认端口分别为 UI `5174`、API `4174`、seekdb `2882`。密码留空仅适用于本机新建的开发容器；不要在 `.env` 中填入并提交真实凭据。

`start.ps1` 会调用 `start-seekdb.ps1`，然后启动 API 与 Vite。seekdb 使用名为 `edgeseek-seekdb-data` 的持久化 volume。项目容器和数据卷与仓库中的其他比赛项目隔离。

## Linux

```bash
[ -f .env ] || cp .env.example .env
chmod +x scripts/*.sh
./scripts/install.sh
./scripts/start.sh
```

如果 `docker run` 需要额外权限，请使用当前账户可访问的 Docker socket；脚本不会清理或重置现有容器和 volume。

## 生产构建

```bash
npm run build
npm start
```

构建产物位于 `frontend/dist/`，API 与静态页面由 `http://127.0.0.1:4174/` 提供。`npm start` 不启动数据库容器，须先运行独立的 seekdb Server。

## 检查与测试

```bash
npm run p0:database
npm run test:unit
npm run test:integration
npm run test:e2e
```

集成测试连接 `127.0.0.1:2882` 的真实 seekdb，并创建带时间戳的测试知识库和集合。浏览器 E2E 会访问固定端口 `5174`/`4174`，并下载公开模型权重。若浏览器或机器资源不足，E2E 结果必须标记为未验证；当前环境记录见 [VERIFICATION.md](VERIFICATION.md)。
