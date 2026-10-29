# AUDIT.md · 封版交付审计（10 项自动检查）

执行时间：2026-10-29 13:3x（本地，UTC+8） · 执行人：Qoder Agent（本轮封版）
所有输出均为当次真实命令结果；未通过或有保留的项已如实标注，未做任何美化。

---

## 1. Git 分支 / HEAD / 远端一致 ✅

```
$ git rev-parse --abbrev-ref HEAD        → 2026-competition-ecosystem
$ git rev-parse HEAD                     → 2fce2615377fedf5bd769a499c1e1a3899dfdb21
$ git rev-parse origin/2026-competition-ecosystem
                                         → 2fce2615377fedf5bd769a499c1e1a3899dfdb21   （与本地一致）
$ git status -sb                         → ## 2026-competition-ecosystem...origin/2026-competition-ecosystem
```

- 基线 `d647275c308e09b7b623f322a26f5c4e85734fb0` 之后全部为 fast-forward 推送，**未使用 `--force`**。
- 本文与所有文档**刻意不写死最终 tip**；封版提交后的核对命令：
  `git fetch origin && git rev-parse HEAD origin/2026-competition-ecosystem`（两个 SHA 必须相同）。

## 2. 改动范围仍在 `qoder/researchflow/**` ✅

```
$ git diff --name-only d647275c...HEAD | grep -v '^qoder/researchflow/'
（无输出）
```

本轮（封版）工作区改动清单：

```
 M qoder/researchflow/DEMO_SCRIPT.md      （§5 移交清单：录屏/配音已自动化）
 M qoder/researchflow/SUBMISSION.md       （§2 命令改用项目 venv；§4/§5/§6/§7 视频状态回填）
 M qoder/researchflow/.gitignore          （新增 build/ 中间产物忽略规则）
?? qoder/researchflow/submission-package/ （提交包 12 份文档 + demo 成片）
?? qoder/researchflow/scripts/make_demo_video.cjs / tts_line.ps1 （视频生成工具）
```

其他赛题目录与 worktree（`PowerContext/`、`PowerContext-integrated/`、`PowerContext-pdf/`、
`PowerContext-embedding/`、`powercontext-pdf-retrieval/`、`pytest-http-rerank-*` 等）
本轮**零写入**；`master` 的在途改动未被触碰。

## 3. 用项目 venv 运行测试 ✅（并记录误用陷阱）

```
$ cd backend && .venv/Scripts/python -m pytest tests/ -q
149 passed in 51.55s
```

**陷阱（本轮再次确认为文档缺陷来源）**：系统 / Anaconda base 的 `python -m pytest tests/ -q`
会得到 `17 failed, 54 passed, 78 errors` + `ModuleNotFoundError: No module named 'pyseekdb'`。
`SUBMISSION.md` §2 原有 8 条命令写成了裸 `python …`，本轮已统一改为
`backend/.venv/Scripts/python …`（`.cjs` 脚本改为 `node …` + `NODE_PATH`）。

## 4. 公开站点仍可匿名访问 ✅

无 cookie、无凭据的 curl（2026-10-29 13:3x）：

```
/                          200 text/html; charset=utf-8 72818B
/styles.css                200 text/css; charset=utf-8    8126B
/app.js                    200 application/javascript     6879B
/data/evidence.json        200 application/json           8175B
/shots/s1-overview.png     200 image/png                 91049B
/no-such-page              404                              0B
```

首页字节数（72818B）与发布当时记录**逐字节一致** → 线上内容未变，**本轮无需重新发布**。

## 5. 站点链接 / 图片 / 真实验证数据可用 ✅

```
$ NODE_PATH=… node scripts/verify_site.cjs https://researchflow-5esfsogn38f.qoder.zone/ build/site-recheck
acc summary   : 9 / 9 PASS
pytest        : 149 passed
acceptance rows: 9
screenshots   : 9 broken: 0
seekdb fact   : 5.7.25-OceanBase seekdb-v1.4.0.0 @ 127.0.0.1:2881 · 分析器 ik · 集合 rf_chunks · 文档 3 / 页 7 / c
reload status : ok
mobile h-overflow px: 0
failed requests (>=400): 0
SITE VERIFY OK
```

复核输出写到 `build/site-recheck/`（已 gitignore），**没有覆盖**仓库内已提交的
`verification/site-public/site-desktop.png` / `site-mobile.png` 原始证据。

## 6. 仓库 URL 与运行说明一致 ✅

`git remote -v` → `origin https://github.com/chaoyisn/PowerContext.git`、
`upstream https://github.com/oceanbase/powercontext.git`。
文档引用点：`ARCHITECTURE.md` §仓库、`QODER_LOG.md` §环境、
`submission-package/02-run-and-reproduce.md`、`10-human-handoff.md` §4 —— 四处与 remote 完全一致
（上游/私有 fork 的角色没有混写）。

## 7. 凭据与完整 UID 扫描 ✅（含保留项说明）

扫描范围：当前 tracked 文件 + 本轮待提交的新文件（本轮唯一待推提交即本目录内容）。

| 模式 | 结果 |
| --- | --- |
| `sk-[A-Za-z0-9]{16,}` / `api_key=…` / `password=…` / `Bearer …` | tracked 文件**零命中**；命中项全部位于 `backend/.venv/`、`services/.venv-powercontext/` 第三方库源码，二者已在 `.gitignore` 中 |
| 完整 UID `01a175e3-…` | **零命中**；仓库内只出现截断形式 `creator_uid=01a175e3-…`（`QODER_LOG.md`、`SITE_DEPLOYMENT.md`、`SUBMISSION.md` §6） |
| `.env` / key 文件 | 未跟踪（`.gitignore` 覆盖 `.env`、`.env.local`） |

**保留项（有意保留，非疏漏）**：`site_id` / `project_id` / `actionId` / `publishOperationId`
四个 UUID 出现在 `SITE_DEPLOYMENT.md` 与 `PUBLISH_VERIFICATION.md` 中。它们是**站点资源标识**，
随公开站点本身可推得，不承载账号凭据，也不等于账号 UID；保留是为了让发布记录可被独立核对。
若主办方要求完全去除，可单独一次提交删除并按需重新发布站点（本轮不做该可选优化）。

## 8. 站点为纯展示、未谎称在线交互 ✅

- `site/public/app.js` 中唯一的网络调用是 `fetch('data/evidence.json')`（同源静态文件），
  无 `<form>`、无 XHR、无任何后端地址。
- `index.html` 明确写出：
  「在线版不连接任何数据库」（§验收）、对比表里
  「上传文档 / 检索 / 问答 → 不可用（无后端）」「任务记忆保存 / 跨会话恢复 → 不可用（无后端）」
  「seekdb / PowerContext 实时状态 → 不连接」，以及
  「本网站是**静态展示版**：不运行 Python、不连接 seekdb 或 PowerContext，也不提供任何模拟的『在线查询』」。
- 后端只监听 `127.0.0.1:8787`，未做任何公网暴露（PowerContext 无多用户鉴权，开放会造成
  跨用户读取；见 `SECURITY.md` 与 `06-public-site-verification.md` §4）。

## 9. 比赛要求覆盖 ✅（缺口如实）

- 通用 12 项材料清单：`SUBMISSION.md` §5（本轮把第 6 项「演示视频」从 ❌ 缺（人工）改为 ✅ 已生成）。
- 本轮 V3 简报逐条（任务 A–E、视频 8 个必答点、提交包 12 项内容）：
  [`11-v3-requirement-matrix.md`](11-v3-requirement-matrix.md)。
- **仍缺（不得由 Agent 代做）**：8 张 Qoder 对话截图、报名平台 UID、平台最终提交、
  外部真实用户反馈；视频时长 2:05 偏短。逐项见 `10-human-handoff.md`。

## 10. 代码冻结、无无关优化 ✅

- 本轮**零产品代码改动**：`backend/app/**`、`frontend/src/**`、`site/public/**`、
  `tests/**` 全部未修改（见 §2 的改动清单）。
- 新增的两个脚本只服务于交付（视频生成），不改变任何运行期行为；站点未重新构建、未重新发布。
- 明确放弃的可选优化：不重构前端、不补多用户鉴权、不把后端上线、不改门控阈值、
  不追 3:00 时长、不生成 ZIP 二进制（命令已给出，见下）。

---

## 附 · 需要单文件附件时的打包命令（本轮未执行）

```bash
cd qoder/researchflow
zip -r ../ResearchFlow-submission.zip submission-package README.md RUN.md VERIFICATION.md \
    ARCHITECTURE.md SECURITY.md BENCHMARK.md SUBMISSION.md DEMO_SCRIPT.md QODER_LOG.md \
    PLAN.md SITE_DEPLOYMENT.md PUSH_PRECHECK.md .env.example \
    backend/app backend/tests frontend/src scripts demo site/public verification \
    -x "*/__pycache__/*" -x "*.pyc" -x "*/node_modules/*" -x "*/.venv*/*" \
    -x "*/logs/*" -x "*/build/*" -x "*.db*" -x "*.qoder.site" -x "*.env"
```

排除项：venv、数据库文件、`logs/`（含运行期字段）、`build/` 中间产物、`.env`、站点描述符。
打包前请再跑一次 §7 的扫描命令确认零命中。
