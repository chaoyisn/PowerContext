# EdgeSeek 运行说明

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
