# EdgeSeek 运行说明

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
