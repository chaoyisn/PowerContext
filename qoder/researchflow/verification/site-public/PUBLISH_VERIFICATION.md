# 站点公开发布验证记录

站点名称：ResearchFlow（比赛静态展示站）
真实 URL：<https://researchflow-5esfsogn38f.qoder.zone>（两次发布同一个域名，未新建站点）
访问策略：**public**（`auth_integration_status=not_required`，无需登录即可访问）
站点标识：`site_id=01a18586-585e-79a0-9360-8857ac76263a`、`project_id=01a18586-585b-798b-83f6-59e45b2834f4`
客户端：Qoder CN Desktop 0.4.11（`productId=qoder-cn`、`region=cn`、`environment=prod`、`host.mode=desktop`）

| 发布 | 时间（本地 UTC+8） | actionId | publishOperationId | 内容版本 |
| --- | --- | --- | --- | --- |
| 首次发布 | 2026-10-29 10:44 | `b598cfeb-16d3-4968-8050-388b5ab3f173` | `01a18589-6b9f-790c-aca6-bf7367d59e10` | 前端重构与简化**之前**的展示页 |
| 更新发布 | 2026-10-29 21:46–21:47 | `7aad1843-5316-4a49-b465-2de01f0e6356` | `01a187e8-18d8-7566-a38e-8f7a829a775e` | GPT 风格重构 + 简化后的冻结构建（**当前线上版本**） |

---

## 1. 本轮（更新发布）的真实工具调用序列

| 步骤 | 调用 | 结果 |
| --- | --- | --- |
| 1 | `get_context` | 服务可达；`local.sites` 命中既有描述符，`projectId=01a18586-585b…`、`siteId=01a18586-585e…` |
| 2 | `get_site_access`（发布前） | `policy.mode=public`、`rule_count=0` → 确认站点当前已是公开访问，无需再次切换 |
| 3 | `prepare_site` | **更新路径**：传入 `projectId=01a18586-585b-798b-83f6-59e45b2834f4`，**不传** `createNewSite`（按要求禁止新建替代站点）；`projectRoot=…\qoder\researchflow\site`、`webDirectory=public`、`spa=false`、`databaseAccess=none`、`displayName=ResearchFlow`、`slug=researchflow`、新 `actionId=7aad1843-5316-4a49-b465-2de01f0e6356` → 返回**同一个** projectId / siteId，`verificationOperationId=01a187e7-8a45-724a-894d-b2523f3af7c1`、`descriptorStatus=pending` |
| 4 | `get_publish_status` | `artifactReady=true`、`dependenciesReady=true`、`preparation.state=ready`、`canPublish=true`、`blockers=[]`、`site.access_mode=public`、`site.host` 未变 |
| 5 | `prepare_site`（同一 action、同一参数重试） | `descriptorStatus=written`、`descriptorPath=…\site\.ResearchFlow.qoder.site`（描述符由平台生成，未手工编辑） |
| 6 | `publish_site` | 返回 `publishOperationId=01a187e8-18d8-7566-a38e-8f7a829a775e` |
| 7 | `get_publish_status` | `published=true`、`readiness=publication_completed`、`operation.state=succeeded`、**`committed=true`**、`site.url=https://researchflow-5esfsogn38f.qoder.zone`、`site.lifecycle=active`、`site.access_mode=public` |
| 8 | 匿名逐文件复核 | 见 §2.1，15/15 与本地构建逐字节一致 |

**没有执行 `update_access_policy`**：站点在发布前已是 `public`，本轮只替换内容，访问策略保持原样，
`get_publish_status` 返回的 `site.access_mode` 仍为 `public`。

打包内容：`site/public/` 共 **15 个文件、1.4 MB**（`index.html`、`styles.css`、`app.js`、
`data/evidence.json`、10 张真实运行截图 + 1 张基准 SVG）。上传前扫描：无密钥、无完整 UID、
无个人主目录路径（扫描方式见 `FINAL_AUDIT.md`）。

描述符回读的关键字段（由 `prepare_site` 写入，可用作交叉验证）：

```
indexSha256    efb562040880b423a65bebe52dcbc6dd0d30cfc720a79fe414b1c4425fad00f8
artifactSha256 6743cfb97fe6281acc989f3ec258ede4e9ea47752250135d5acb5f1c8bf2a617
releaseId      01a187e8-18d8-751c-a4bc-4050bd3f157a
deploymentId   01a187e7-8779-7cd1-b0a2-36188f60be0e
```

其中 `indexSha256` 与本地 `site/public/index.html` 的 SHA-256 完全相同
（`efb562040880b423…`），证明冻结的构件就是本地最终构建。

## 2. 匿名（未登录）访问验证

### 2.1 逐文件无凭据抓取 + 哈希比对

命令：

```bash
backend/.venv/Scripts/python scripts/verify_published_site.py https://researchflow-5esfsogn38f.qoder.zone
```

脚本用 `urllib`（**不建 cookie jar**、无凭据、带 `Cache-Control: no-cache`）拉取
`site/public` 下的每一个文件，逐字节 SHA-256 与本地构建比对。
真实结果（完整明细写入 `published-site-check.json`）：

```
PASS  app.js                           200 local=    7469B live=    7469B sha=30f220eeee35
PASS  data/evidence.json               200 local=    8784B live=    8784B sha=21eb05406764
PASS  index.html                       200 local=   16197B live=   16197B sha=efb562040880
PASS  shots/bench-workflow.svg         200 local=    1485B live=    1485B sha=e9382aa033d5
PASS  shots/s1-overview.png            200 local=   97502B live=   97502B sha=745fefcd84dc
PASS  shots/s10-verification.png       200 local=  123159B live=  123159B sha=2c4b828ed14b
PASS  shots/s2-resume-brief.png        200 local=  161222B live=  161222B sha=0ab9924dd9bb
PASS  shots/s3-page-navigator.png      200 local=  135325B live=  135325B sha=7e3326be1d5b
PASS  shots/s4-page-viewer.png         200 local=  154588B live=  154588B sha=117dc90ff83f
PASS  shots/s5-retrieval.png           200 local=  161116B live=  161116B sha=8d131a32b036
PASS  shots/s6-workbench.png           200 local=  180038B live=  180038B sha=3667daeba1ba
PASS  shots/s7-memory.png              200 local=  181309B live=  181309B sha=733c29c68a62
PASS  shots/s8-mobile-overview.png     200 local=   51186B live=   51186B sha=a2cb2e000772
PASS  shots/s9-mobile-knowledge.png    200 local=   60567B live=   60567B sha=7bbcb3cb9b88
PASS  styles.css                       200 local=    8155B live=    8155B sha=84829c498ccf

15/15 files byte-identical to the local build
```

一点必须如实说明的差别：Qoder Sites 会在**服务端返回的每个 HTML 文档里注入自己的水印脚本**
`<script data-qoder-watermark="v1">`。原始抓取到的 `index.html` 是 73239 B，去掉这一个脚本块后
是 16197 B，与本地 `site/public/index.html` 逐字节相等（SHA-256 相同）。
注入块由平台添加、不来自 `site/public`，因此比对只针对它做归一化，其余文件一律原样比对。

发布前后对照（证明线上内容确实换了，而不是缓存）：

| | 发布前 | 发布后 |
| --- | --- | --- |
| `index.html` 原始字节 | 72818 B（`ea9068b1a777…`） | 73239 B（`2a83c2ad093b…`；去水印后 `efb562040880…` = 本地） |
| `data/evidence.json` | `generated_at 2026-10-29T10:08:59`，无 `interactions` 字段 | `generated_at 2026-10-29T21:44`，含 `interactions: 30/30`、10 张截图 |

### 2.2 无头浏览器全新上下文（等价无痕：无登录态、无 cookie）

```bash
NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" \
  node scripts/verify_site.cjs "https://researchflow-5esfsogn38f.qoder.zone/" \
  "qoder/researchflow/verification/site-public/published-browser"
```

真实输出：

```
acc summary   : 9 / 9 PASS
pytest        : 149 passed
browser itx   : 30 / 30 PASS · 记录于 2026-10-29 21:37:35+08:00 的 Chromium 真实运行；覆盖 6 个页面、390 / 768 / 1280 / 1920 px 视口；0 项失败
acceptance rows: 9
screenshots   : 10 broken: 0
seekdb fact   : 5.7.25-OceanBase seekdb-v1.4.0.0 @ 127.0.0.1:2881 · 分析器 ik · 集合 rf_chunks · 文档 3 / 页 7 / c
reload status : ok
mobile h-overflow px: 0
failed requests (>=400): 0
SITE VERIFY OK https://researchflow-5esfsogn38f.qoder.zone/
```

### 2.3 发布验收清单逐条核对

- [x] 未登录访客可打开真实 URL（无凭据 curl 200 + 全新无头浏览器渲染成功）
- [x] 首页显示**新版**：`index.html` 去水印后与本地冻结构建逐字节一致（`efb562040880…`）
- [x] JS / CSS / 图片 / JSON 全部可加载：15/15 文件 200 且哈希一致；浏览器侧 `screenshots: 10 broken: 0`、`failed requests (>=400): 0`
- [x] 移动端无横向溢出：`mobile h-overflow px: 0`（390px 视口整页截图见 `published-browser/site-mobile.png`）
- [x] 按钮 / 导航 / 内部链接正常：8 个锚点全部有对应 `id`（死链 0），整页 reload 正常（`reload status: ok`）
- [x] 仓库与运行说明链接正确：页面唯一外链 `https://github.com/chaoyisn/PowerContext` 返回 200；正文标明分支 `2026-competition-ecosystem` 与目录 `qoder/researchflow/`
- [x] 公开版本与本地最终构建一致：见 §2.1 的 15/15 与描述符 `indexSha256`
- [x] 不存在新旧版本缓存混用：抓取带 `no-cache`，且 `evidence.json` 从 10:08 变为 21:44、`index.html` 哈希变化，浏览器与 curl 得到同一份新内容
- [x] 页面仍明确写着在线版是**展示模式**：不连 seekdb、不连 PowerContext、不提供模拟查询；输入框不会伪装成可用的在线 AI 服务

## 3. 截图证据（本目录）

| 文件 | 内容 |
| --- | --- |
| `published-browser/site-desktop.png` | 更新发布后公开 URL 的 1440px 整页截图（全新无头浏览器上下文，未登录） |
| `published-browser/site-mobile.png` | 更新发布后公开 URL 的 390px 整页截图（同上） |
| `site-desktop.png`、`site-mobile.png` | 10:46 **首次**发布时的线上截图，保留作历史对照（旧版界面） |
| `published-site-check.json` | §2.1 的逐文件哈希明细（含原始字节数与归一化后的哈希） |

截图由 `scripts/verify_site.cjs` 在验证过程中直接产出，未经后期编辑。
`site/preview-local/` 下的同名文件是发布前的**本地**预览截图，与本目录的**线上**截图分开保存，
避免混淆证据来源。

## 4. 诚实声明

- 在线版是纯静态展示站：**不连接 seekdb、不连接 PowerContext、不提供任何模拟查询**。
  页面数据来自 `data/evidence.json`，由 `scripts/build_site_data.py` 从真实验收报告
  （`logs/acceptance-20261029-213920`）、真实 pytest 运行与真实浏览器交互验收导出。
- 完整可交互系统需在本地按 `RUN.md` 启动（seekdb 2881 + PowerContext 17429 + FastAPI 8787）。
- 两次发布与首次的公开切换均由用户在会话中明确授权后执行；本轮更新发布沿用原域名、
  原 project、原 public 策略，未新建替代站点，未使用任何伪造的发布状态。
