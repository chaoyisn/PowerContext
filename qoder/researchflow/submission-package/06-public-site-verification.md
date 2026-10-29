# 06 · 公开 Qoder Sites 站点与匿名访问验证

真实 URL：<https://researchflow-5esfsogn38f.qoder.zone>
访问策略：**public**（`auth_integration_status=not_required`，未登录即可访问）
形态：**纯静态展示站**，不连接 seekdb、不连接 PowerContext、不提供任何模拟查询。
当前线上版本：GPT 风格前端重构 + 简化之后的**冻结构建**（2026-10-29 21:46 更新发布）。

原始记录：`../verification/site-public/PUBLISH_VERIFICATION.md`（含逐步工具调用序列与哈希明细）
逐文件比对：`../verification/site-public/published-site-check.json`
线上截图：`../verification/site-public/published-browser/site-desktop.png`（1440px 全新上下文）、
`site-mobile.png`（390px）；`../verification/site-public/site-*.png` 为首次发布时的旧版对照。

---

## 1. 发布链路（真实工具调用，非口头声明）

站点发布过两次，**同一个 project、同一个 site、同一个域名**，未新建替代站点。

### 1.1 首次发布 2026-10-29 10:44

| 步骤 | 调用 | 可核验结果 |
| --- | --- | --- |
| 1 | `get_context` | 服务可达、`filePreview=true` |
| 2 | `list_sites(scope=owned)` | `total_size=0`（本次为新建站点） |
| 3 | `prepare_site` | `createNewSite=true`、`webDirectory=public`、`spa=false`、`databaseAccess=none` |
| 4 | `get_publish_status` | `artifactReady=true`、`canPublish=true`、`blockers=[]` |
| 5 | `publish_site` | `publishOperationId=01a18589-6b9f-790c-aca6-bf7367d59e10` |
| 6 | `get_publish_status` | `published=true`、`operation.state=succeeded`、`committed=true` |
| 7 | `update_access_policy(mode=public, confirmPublic=true)` | 公开切换由本人在会话中明确授权后执行 |
| 8 | `get_site_access` | `mode=public`、`rule_count=0`、`auth_integration_status=not_required` |

### 1.2 更新发布 2026-10-29 21:46（当前线上版本）

| 步骤 | 调用 | 可核验结果 |
| --- | --- | --- |
| 1 | `get_context` | `local.sites` 命中既有描述符 → `projectId=01a18586-585b…`、`siteId=01a18586-585e…` |
| 2 | `get_site_access`（发布前） | `policy.mode=public` → 已是公开，本轮**不需要也不再触发**公开切换 |
| 3 | `prepare_site` | 传 `projectId`、**不传** `createNewSite` → 返回**同一个** projectId / siteId；`actionId=7aad1843-5316-4a49-b465-2de01f0e6356` |
| 4 | `get_publish_status` | `artifactReady=true`、`preparation.state=ready`、`canPublish=true`、`blockers=[]`、`site.access_mode=public`、host 未变 |
| 5 | `prepare_site`（同 action 同参数重试） | `descriptorStatus=written`、`descriptorPath=…\site\.ResearchFlow.qoder.site`（平台生成，未手工编辑） |
| 6 | `publish_site` | `publishOperationId=01a187e8-18d8-7566-a38e-8f7a829a775e` |
| 7 | `get_publish_status` | `published=true`、`readiness=publication_completed`、`operation.state=succeeded`、**`committed=true`**、`lifecycle=active`、`access_mode=public` |
| 8 | `scripts/verify_published_site.py` | 15/15 文件与本地最终构建逐字节一致（见 §2.1） |

站点标识：`site_id=01a18586-585e-79a0-9360-8857ac76263a`、
`project_id=01a18586-585b-798b-83f6-59e45b2834f4`
本次构件：`releaseId=01a187e8-18d8-751c-a4bc-4050bd3f157a`、
`artifactSha256=6743cfb97fe6281acc989f3ec258ede4e9ea47752250135d5acb5f1c8bf2a617`、
`indexSha256=efb562040880b423a65bebe52dcbc6dd0d30cfc720a79fe414b1c4425fad00f8`
（`indexSha256` 与本地 `site/public/index.html` 的 SHA-256 相同 → 冻结构件确实是本地最终构建）
客户端：Qoder CN Desktop 0.4.11（`region=cn`、`environment=prod`）
打包内容：`site/public/` 共 **15 个文件、1.4 MB**（`index.html`、`styles.css`、`app.js`、
`data/evidence.json`、10 张真实运行截图 + 1 张基准 SVG）；上传前扫描无密钥、无完整 UID、
无个人主目录路径。

## 2. 匿名（未登录）可达性

### 2.1 逐文件无凭据抓取 + SHA-256 比对（更新发布后）

```bash
backend/.venv/Scripts/python scripts/verify_published_site.py https://researchflow-5esfsogn38f.qoder.zone
```

`urllib` 不建 cookie 罐、带 `Cache-Control: no-cache`，把 `site/public` 下每一个文件拉下来
与本地逐字节比对。真实输出（完整明细见 `published-site-check.json`）：

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

需要如实说明的一处差异：**Qoder Sites 会在服务端返回的每个 HTML 文档中注入自身的水印脚本**
`<script data-qoder-watermark="v1">`。原始抓取到的 `index.html` 为 73239 B，去掉这一个注入块后
为 16197 B，与本地文件逐字节相等。注入块不来自 `site/public`，因此比对只对它归一化，
其余文件一律原样比对。

发布前后对照（证明线上确实换了内容，不是缓存）：

| | 更新发布前 | 更新发布后 |
| --- | --- | --- |
| `index.html` 原始字节 | 72818 B（`ea9068b1a777…`） | 73239 B（`2a83c2ad093b…`；去水印后 `efb562040880…` = 本地） |
| `data/evidence.json` | `generated_at 2026-10-29T10:08:59`，无 `interactions` 字段，9 张截图 | `generated_at 2026-10-29T21:44`，`interactions 30/30`，10 张截图 |

### 2.2 无头浏览器全新上下文（等价无痕）

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

## 3. 发布验收清单（本轮 8 项逐条核对）

- [x] 未登录访客可打开真实 URL（无凭据抓取 200 + 全新无头浏览器渲染成功）
- [x] 首页显示**新版**：`index.html` 去水印后与本地冻结构建逐字节一致
- [x] JS / CSS / 图片 / JSON 全部可加载：15/15 哈希一致；浏览器侧 `screenshots: 10 broken: 0`、`failed requests (>=400): 0`
- [x] 移动端无横向溢出：`mobile h-overflow px: 0`（390px 整页截图已存档）
- [x] 按钮 / 导航 / 内部链接正常：8 个锚点都有对应 `id`（死链 0），整页 reload 正常（`reload status: ok`）
- [x] 仓库与运行说明链接正确：页面唯一外链 `https://github.com/chaoyisn/PowerContext` → 200；正文标明分支 `2026-competition-ecosystem` 与目录 `qoder/researchflow/`
- [x] 公开版本与本地最终构建一致：§2.1 的 15/15 + 描述符 `indexSha256` 交叉验证
- [x] 不存在新旧版本缓存混用：`evidence.json` 时间戳与字节数均已更新，curl 与浏览器得到同一份新内容
- [x] 页面仍明确标注在线版是**展示模式**：不连数据库、不可交互、输入框不伪装成可用的在线 AI 服务

## 4. 边界（必须在材料里如实说明）

1. 在线站点**只用于展示**：不能上传、不能提问、不能查询记忆。完整可交互系统需按
   `RUN.md` 在本地启动（seekdb :2881 + PowerContext :17429 + FastAPI :8787）。
2. 页面数据来自 `site/public/data/evidence.json`，由 `scripts/build_site_data.py`
   从真实验收报告（`logs/acceptance-20261029-213920`）、真实 pytest 运行与真实浏览器交互
   验收导出；没有任何手工填写或预置假数据。
3. 站点为 `access_mode=public`，任何人都能读；因此内容中**不含**完整 Qoder UID、
   API key、内部数据。原始 PDF 与数据库未上传到站点。
4. 本地后端同样**不对公网暴露**：只监听 `127.0.0.1:8787`，且不承载任何真实用户凭据；
   PowerContext 无多用户鉴权，把后端直接开放会造成跨用户读取记忆/文档的风险。
5. 站点的 `access_mode` 全程为 `public`：本轮只做内容替换，未新建站点、未改域名、
   未把公开改为私有。发布前用 `get_site_access` 读回、发布后用 `get_publish_status` 复核。
