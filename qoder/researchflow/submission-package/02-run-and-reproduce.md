# 02 · 完整运行说明与复现路径

权威文档是仓库内的 [`../RUN.md`](../RUN.md)（含 Windows / Linux-WSL、配置表、基准脚本、排障）。
本文只给出评审最短路径，并标注**必须避开的坑**。所有路径相对仓库根
`https://github.com/chaoyisn/PowerContext.git` 的 `qoder/researchflow/` 目录。

| 项 | 值 |
| --- | --- |
| 仓库 | `https://github.com/chaoyisn/PowerContext.git` |
| 分支 | `2026-competition-ecosystem` |
| 作品目录 | `qoder/researchflow/`（仅此目录属于本作品） |
| 当前 tip | 以 `git rev-parse origin/2026-competition-ecosystem` 为准（本文不写死 SHA） |
| 公开站点 | <https://researchflow-5esfsogn38f.qoder.zone> |

---

## 1. 前置条件

| 依赖 | 要求 | 检查命令 |
| --- | --- | --- |
| seekdb | 运行中的容器，监听 `127.0.0.1:2881` | `docker start contest-seekdb`（机器重启后） |
| seekdb 版本 | `5.7.25-OceanBase seekdb-v1.4.0.0` | 见下方 `docker exec … SELECT VERSION();` |
| 后端 venv | `backend/.venv`（Python 3.11） | 重建见 `RUN.md` §1 |
| PowerContext venv | `services/.venv-powercontext`（1.4.1） | 同上 |
| 前端产物 | `frontend/dist`（存在则被后端同源挂载） | `cd frontend && npm run build` |
| LLM key | **可选**；不配置则问答进入「仅检索模式」 | `RF_LLM_API_KEY` |

```bash
docker exec contest-seekdb mysql --no-defaults --protocol=TCP -h 127.0.0.1 -P 2881 \
  -u root --batch -e "SELECT VERSION();"
```

## 2. 启动三个进程

```bash
# 1) PowerContext 记忆服务 :17429
POWERCONTEXT_HOME="$PWD/services/powercontext-data" \
  services/.venv-powercontext/Scripts/powercontext.exe server run \
  --host 127.0.0.1 --port 17429 --no-env-file

# 2) ResearchFlow 后端 :8787（同源提供前端；LLM 可选）
cd backend && RF_LLM_API_KEY="$DEEPSEEK_API_KEY" .venv/Scripts/python -m app.api.main

# 3) 演示数据：3 文档 / 7 物理页 / 13 chunk + 项目 + 快照 + 一次真实问答
cd .. && backend/.venv/Scripts/python scripts/seed_demo.py
```

打开 <http://127.0.0.1:8787/>（对话首页，可直接提问）。健康状态与真实计数在 <http://127.0.0.1:8787/verification>，
应显示 `5.7.25-OceanBase seekdb-v1.4.0.0`、`PowerContext 1.4.1`、分析器 `ik`、集合 `rf_chunks`
与真实计数；若显示降级状态，先按 `RUN.md` §9 排障。
PowerContext 就绪判断：`curl http://127.0.0.1:17429/health/ready` → `{"status":"ready",…}`。

体验路径：`/knowledge`（上传 · 三模检索 · 页导航）→ `/workbench`（带引用问答 · 无证据不编造）
→ `/memory`（显式保存 · 换会话按 project_id 恢复）。详细逐屏动作见 `RUN.md` §3 与 [`../DEMO_SCRIPT.md`](../DEMO_SCRIPT.md)。

## 3. 复现测试与验收

```bash
# 自动化测试：149 个，直接打真实 seekdb 与真实 PowerContext
cd backend && .venv/Scripts/python -m pytest tests/ -q
# 期望尾部输出：149 passed

# T1–T9 端到端验收（自带独立 PowerContext:17430 与 API:8788，真实重启与断连）
cd .. && backend/.venv/Scripts/python scripts/run_acceptance.py
# 报告：logs/acceptance-<时间戳>/acceptance-report.md + .json + 每用例 .log

# 全新环境评审旅程（新建 venv / 新 seekdb 容器 / 新 PowerContext 数据目录，跑完自动清理）
backend/.venv/Scripts/python scripts/fresh_env_e2e.py
# 期望：报告 JSON 里 passed == total（封版当晚一跑为 23/23，68.4 s）
# 端口被本机其他进程占用时会**在第 2 步就明确失败**，可改用
#   RF_FRESH_SEEKDB_PORT / RF_FRESH_PC_PORT / RF_FRESH_API_PORT / RF_FRESH_CONTAINER
# 指定空闲端口与容器名后重跑

# 只清理本项目对象（rf_ 前缀），不碰同机其他赛题
backend/.venv/Scripts/python scripts/reset_store.py --yes
```

## 4. 必须避开的坑（实测踩过）

1. **不要用系统 / Anaconda base 的 python 跑测试。**
   `python -m pytest tests/ -q` 在 base 环境下得到
   `17 failed, 54 passed, 78 errors` + `ModuleNotFoundError: No module named 'pyseekdb'`，
   并且后端进入降级健康状态。正确命令是
   `cd backend && .venv/Scripts/python -m pytest tests/ -q` → `149 passed`。
   测试目录在 `backend/tests`，从项目根直接 `pytest tests/` 会报找不到。
2. **Windows 必须用远程模式。** `RF_SEEKDB_MODE=server`；嵌入式模式在 Windows 不可用。
3. **seekdb upsert 后需要 `refresh_index()`** 才能立刻被检索到，本项目已在写入路径处理。
4. **同机共享 seekdb 容器**：本项目全部对象带 `rf_` / `rfacc_` 前缀隔离；
   `run_acceptance.py --restart-seekdb` 会影响同机其他赛题，除非必要不要加。
   封版本机就出现过另一个会话的进程占用 8790，导致全新环境复现误判就绪——
   现在脚本会先检查三个端口是否空闲，因此这类冲突在第 2 步就报出来，
   而不是拖到后面变成一句看不懂的 `KeyError`。
5. **不配置 `RF_LLM_API_KEY` 不影响验收主链路**：问答会明确标注「仅检索模式」，
   不会把检索摘要冒充模型回答。

## 5. 复现演示视频（Task A 产物）

```bash
# 前置：三个进程已启动并已 seed_demo.py（见 §2）；展示站两个场景直接录公开线上地址
NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" \
  node scripts/make_demo_video.cjs
# 产物：submission-package/demo/researchflow-demo.mp4 + .vtt + video-manifest.json
#       + video-check.json（对成片执行的 25 项交付自动检查）+ keyframes/（11 张逐场景抽帧）
# 中间件（录屏 / 配音 / ASS）：build/video/（已 gitignore，不进提交包）
```

`--no-pytest` 复用缓存的真实 pytest 输出；`--force-record` 忽略缓存录屏全部重录；
`RF_SITE_URL` 改线上地址（默认即已发布站点），`RF_SITE_LOCAL` 可临时改回本地构建。
收尾会自动跑 `scripts/check_demo_video.cjs`，任一检查不过则整个出片流程非零退出。

## 5.1 复现最终上传包（ZIP）

```bash
backend/.venv/Scripts/python scripts/build_final_zip.py     # 可选参数：自定义输出 zip 路径
# 产物（默认写到仓库之外的交付目录，避免大体积媒体被误提交）：
#   D:\OceanBase\deliverables\researchflow-final\
#     ResearchFlow-Qoder-Final.zip        303 个成员
#     ResearchFlow-Qoder-Final.zip.sha256 一行式，可 sha256sum -c
#     final-zip-manifest.json             字节数 / 压缩比 / 逐目录统计 / 隐私排除项 / 解压核对结果
#     researchflow-demo.mp4               成片副本（与仓库内同字节）
```

四条内建纪律，改脚本时不要绕过：**白名单外一律不收**（`INCLUDE_DIRS` / `INCLUDE_FILES` /
`INCLUDE_LOGS`）；**5 个关键成员缺失即失败**（`required member not collected`，防止嵌套同名目录
被 `SKIP_DIRS` 静默吞掉，例如展站的 `site/public/data/evidence.json`）；
**7 条凭据与本机路径正则命中即拒绝写出**；**写完必须解压回全新临时目录逐字节比对**，
`missing / differing / unexpected` 任一非 0 则非零退出。
`PRIVACY_SKIPPED` 里那份 `interactions-run.log` 是"真实转写含本机路径"的例子——
不改写证据、不放进包、理由随清单落盘。

## 6. 本地边界

- 后端只监听 `127.0.0.1:8787`，**不对公网暴露**：PowerContext 侧没有多用户鉴权，
  直接开放会让匿名用户互相读取文档与记忆。
- 公开站点是纯静态展示版，与本地后端不是同一套运行体（见 `06-public-site-verification.md`）。
