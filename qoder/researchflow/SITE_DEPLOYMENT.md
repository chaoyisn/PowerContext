# SITE_DEPLOYMENT.md — Qoder Sites 发布状态与方案

更新时间：2026-10-29（V3 最终交付轮）
状态：**已正式发布并公开访问。** 真实 URL：<https://researchflow-5esfsogn38f.qoder.zone>（`access_mode=public`）。
V2 期间的 `sites_unavailable` 平台阻塞已解除；发布、公开切换与匿名验证的完整证据见
`verification/site-public/PUBLISH_VERIFICATION.md`。下文 §1 保留阻塞期的实测记录作为过程证据。

---

## 1. 本轮对 Sites 实际能力的复核（不凭旧文档）

用当前 Qoder CN Desktop 环境的真实工具调用复核，而非仅读文档：

| 调用 | 结果 |
| --- | --- |
| `get_context` | `projectRoot=D:\OceanBase`，`sites=[]`，`productId=qoder-cn`，`region=cn`，`environment=prod`，`host.mode=desktop`，`filePreview=true` |
| `list_sites(scope=owned)` | 正常返回，`total_size=0`（账号已认证、服务可达） |
| `prepare_site`（完整参数） | **`sites_unavailable`** |
| `prepare_site`（同一 actionId 重试） | **`sites_unavailable`** |
| `prepare_site`（最小参数 + 新 actionId） | **`sites_unavailable`** |
| `get_publish_status(actionId)` | `sites_action_unavailable`（该 action 未在服务端建立） |

本地痕迹：`~/.qoder-cn/sites/state/telemetry-v1/` 中记录了准备动作已启动
（`is_new_site=true`、`creator_uid=01a175e3-…`、`trigger=agent`），说明失败发生在云端准备阶段，
而非本地打包阶段。`sites_unavailable` 不在 skill 文档的错误码清单中
（文档仅有 `artifact_size_exceeded` / `sites_quota_exceeded` / `sites_rate_limited` /
`sites_storage_file_too_large` 等），因此判定为**平台侧可用性/权益问题**，需人工在 Qoder Desktop 内确认。

能力边界结论（与 V1 文档核对一致，仍成立）：
- 可托管：静态站点（Vite/纯静态产物）、单个 Deno/TS Edge Function、托管 PostgreSQL、对象存储、Secrets。
- 不可托管：Python/FastAPI、持久进程、seekdb、PowerContext；托管 PostgreSQL 无向量/全文检索。
- 新站点默认 private；公开需额外授权 + `confirmPublic=true`；平台子域名寻址。

---

## 2. 已完成的发布准备（可随时重试）

1. **比赛网站已构建**：`site/public/`（纯静态，无构建步骤）
   - `index.html` 单页 + 锚点导航 → **不存在路由刷新 404**；
   - `styles.css` 中文科研 SaaS 风格，960px / 640px 两档响应式；
   - `app.js` 渲染 `data/evidence.json`；
   - `shots/` 10 张**真实运行截图**（`scripts/capture_screenshots.cjs` 无头浏览器采集，可复现；
     2026-10-29 前端 UI 重构后新增 `s10-verification.png`，`s1`/`s2`/`s8` 改指向新 IA 的对话首页与 `/memory`）；
   - `data/evidence.json` 由 `scripts/build_site_data.py` 从真实验收报告 + 真实 pytest 运行 + 实时
     `/api/health` 导出，**不含任何模拟数据**。
2. **本地验证通过**（`scripts/verify_site.cjs`，Playwright 无头；V2 首轮记录）：
   - 证据数据渲染：`9 / 9 PASS`、`88 passed`、验收表 9 行
     （V2 收尾后站点数据已重建为 `149 passed`，线上现状见 §5 与
     `verification/site-public/PUBLISH_VERIFICATION.md`）；
   - 9 张截图全部加载成功（broken=0）；
     （2026-10-29 UI 重构 + 简化后本地重跑：`screenshots: 10 broken: 0`、`mobile h-overflow px: 0`、
     `failed requests (>=400): 0`；该版本已于 21:46 更新发布，线上与本地现已逐字节一致，见 §5 / §6。）
   - 锚点跳转与整页 reload 正常；
   - 390px 移动端横向溢出 0px；
   - 无 console / pageerror。
   预览截图：`site/preview/site-desktop.png`、`site/preview/site-mobile.png`。
3. **prepare 参数（V3 实际使用，与发布成功一一对应）**：
   ```json
   {
     "actionId": "b598cfeb-16d3-4968-8050-388b5ab3f173",
     "createNewSite": true,
     "projectRoot": "D:\\OceanBase\\PowerContext-researchflow\\qoder\\researchflow\\site",
     "webDirectory": "public",
     "displayName": "ResearchFlow",
     "slug": "researchflow",
     "spa": false,
     "databaseAccess": "none"
   }
   ```
   无 Function、无数据库、无 Secrets → 不触发 backend 权益分支。
   `projectRoot` 指向 `site/`（而非会话根 `D:\OceanBase`），使平台生成的
   `.站点名称.qoder.site` 描述符落在 `qoder/researchflow/**` 范围内，符合赛题的改动范围约束。

---

## 3. 体验方案结论

**采用方案一：Qoder Sites 公共展示站 + 本地完整项目复现。**

方案二（Sites 前端 + 独立公网 HTTPS 后端）本轮**不具备条件**，原因：
- 本机无公网 HTTPS 后端宿主与凭据（任务纪律：碰到外部服务器凭据说明操作并继续）；
- 赛题明确禁止把本地私有服务直接暴露公网；
- Function 出站是否允许调用自托管后端在官方文档中**未承诺**，未实测前不能作为方案依据。

方案二的安全评估（若后续获得公网后端）见 `SECURITY.md` §4：固定 HTTPS 目的地、Secret 存放密钥、
上传/频率/用量限制、演示数据与个人资料隔离、匿名只读、记忆按项目隔离。

展示版与完整版边界在网站「体验说明」一节中明确标注：在线版不连接任何数据库，不提供模拟查询。

---

## 4. 发布步骤（V3 已按此执行完毕）

1. 在 Qoder Desktop 中确认账号的 Sites 权益/服务状态 —— V3 复核时 `get_context` 与
   `list_sites` 均正常返回（不再是 `sites_action_unavailable`），无需额外开通动作。
2. `prepare_site`（§2.3 参数，新 actionId）→ `get_publish_status` 读
   `artifactReady` / `dependenciesReady` / `blockers` → `publish_site(actionId)` → 复查至 `published=true`。✅
3. Desktop 宿主调用 `show_publish_confirmation(actionId)` 查看冻结预览（不发布）。✅
4. **切换为公开访问前已取得用户明确确认**（2026-10-29 会话内授权「发布并切换公开访问」），
   随后 `update_access_policy(mode=public, confirmPublic=true)`。✅
5. 匿名验证清单：全部通过，逐项结果与原始输出见
   `verification/site-public/PUBLISH_VERIFICATION.md` §2.3。✅
6. 真实 URL、发布时间、访问策略与验证结果已回填本文 §5。✅

---

## 5. 发布结果

**已正式发布两次，同一个 project / site / 域名，访问策略全程 `public`。**

| 项目 | 首次发布 10:44 | 更新发布 21:46（当前线上版本） |
| --- | --- | --- |
| 真实 URL | <https://researchflow-5esfsogn38f.qoder.zone> | 同上（域名未变） |
| 站点标识 | `site_id=01a18586-585e-79a0-9360-8857ac76263a`<br>`project_id=01a18586-585b-798b-83f6-59e45b2834f4` | 同上（同一 project / site） |
| 发布动作 | `actionId=b598cfeb-16d3-4968-8050-388b5ab3f173`<br>`publishOperationId=01a18589-6b9f-790c-aca6-bf7367d59e10` | `actionId=7aad1843-5316-4a49-b465-2de01f0e6356`<br>`publishOperationId=01a187e8-18d8-7566-a38e-8f7a829a775e` |
| prepare 参数 | `createNewSite=true`、`webDirectory=public`、`spa=false`、`databaseAccess=none` | 传 `projectId` 走更新路径，**不传** `createNewSite`（禁止新建替代站点） |
| 发布状态 | `published=true`、`readiness=publication_completed`、`operation.state=succeeded`、`committed=true` | 同上，`lifecycle=active`、`governance_status=normal` |
| 访问策略 | 发布后由 `update_access_policy(mode=public, confirmPublic=true)` 切公开（本人授权） | 发布前 `get_site_access` 已是 `public`，本轮**未改策略**，发布后复核仍为 `public` |
| 打包内容 | 14 个文件、1.7 MB（9 张截图） | **15 个文件、1.4 MB**（10 张截图 + 1 张基准 SVG） |
| 构件指纹 | — | `artifactSha256=6743cfb9…`、`indexSha256=efb56204…`（与本地 `site/public/index.html` 相同） |

客户端：Qoder CN Desktop 0.4.11、`region=cn`、`environment=prod`。

匿名验证结论（未登录、无 cookie）：根路径与全部静态资源 200，**15/15 文件与本地最终构建
逐字节一致**（`scripts/verify_published_site.py`，明细 `verification/site-public/published-site-check.json`）；
10 张真实截图 `broken=0`；Network 无 ≥400 请求；锚点跳转与整页 reload 正常；
验收表 9 行、`9 / 9 PASS`、`149 passed`、`browser itx 30 / 30` 在页面可见；
390px 横向溢出 0px；无 console error / pageerror。
线上整页截图：`verification/site-public/published-browser/site-desktop.png`、`site-mobile.png`
（旧版对照仍保留在 `verification/site-public/site-*.png`）。

一点必须如实说明的差异：Qoder Sites 会在服务端返回的每个 HTML 文档里注入自身的水印脚本
`<script data-qoder-watermark="v1">`。抓取到的 `index.html` 是 73 239 字节，去掉这一个注入块后
是 16 197 字节，与本地文件逐字节相等。注入块由平台添加、不来自 `site/public`。

历史阻塞记录（保留作为过程证据）：V2 两轮共 3 次 `prepare_site` 返回 `sites_unavailable`、
`get_publish_status` 返回 `sites_action_unavailable`，本地遥测显示已进到云端准备阶段
（`is_new_site=true`、`creator_uid=01a175e3-…`、`trigger=agent`）；第二次自动重试被 Qoder
权限分类器拦截，要求人工核验账号权益。该阻塞在 V3 复核时已自行解除，未修改任何站点内容即发布成功。

---

## 6. UI 重构 + 简化轮：线上现状核对与更新发布

前端经历「GPT 风格重构」和「整体简化」两步。为避免把"本地已改"当成"线上已更新"，
先记录重构完成时线上的真实内容，再记录更新发布之后的结果。

### 6.1 更新发布之前线上是什么（抓取核对，非推断）

无痕抓取 `https://researchflow-5esfsogn38f.qoder.zone/` 的响应体已存档：
`verification/browser-acceptance/compare/online-live-site/live-index.html`（72 818 字节）
与整页截图 `live-desktop.png` / `live-mobile.png`。核对结论：

- 当时线上是**前端重构与简化之前**那份自包含静态展示页，页面里 **0 个 `<button>` / 0 个 `<input>` / 0 个 `<form>`**，
  全部是文本、图片与锚点链接。因此不存在"看着能点、点了没反应"的死控件——它本来就不承诺任何操作。
- 它**不包含**新版界面的任何截图，也没有「浏览器交互验收」证据卡。
- 抓取当时的匿名验证记录：`acc 9/9 PASS`、`pytest 149 passed`、`reload ok`、
  `mobile h-overflow 0px`、`failed requests (>=400): 0`（见同目录 `fetch.log`）。

### 6.2 已发布的新版资源

`site/public/` 由最终构建产物重新生成，先本地验证再发布：

| 资源 | 状态 |
| --- | --- |
| `index.html` / `app.js` / `styles.css` | 「浏览器交互验收（真实 Chromium）」证据卡；验证区三卡自适应排布 |
| `shots/*.png`（10 张） | 由 `scripts/capture_screenshots.cjs` 对简化后的界面重采，含移动端逐路由溢出断言（21:41–21:42） |
| `data/evidence.json` | 由 `scripts/build_site_data.py` 重新生成：acceptance 9/9（150 项校验）、pytest 149 passed、浏览器交互 30/30、`/api/health` 实时快照 |
| 发布前本地静态验证 | `node scripts/verify_site.cjs http://127.0.0.1:4181/ site/preview-local` → 截图 10 张 broken 0、锚点与整页刷新正常、390px 溢出 0px、失败请求 0，`browser itx: 30 / 30 PASS` |
| 发布后线上验证 | §5 的 15/15 逐字节一致 + 同一脚本对公开 URL 再跑一遍，结论相同 |

展示版与完整版的边界仍写在网站「体验说明」一节：在线版不运行 Python、不连接 seekdb / PowerContext、
不提供任何模拟查询；上传、问答、保存记忆在在线版标注为**不可用（无后端）**，只有本地完整运行可用。

### 6.3 本轮结果

1. 已对同一 project 重新 `prepare_site` → `publish_site`，发布后重跑匿名线上验证并覆盖
   `verification/site-public/` 证据（§5）。
2. 演示视频随后重录，c2 / c10 两个展示站场景改为**直接录自公开 URL**，旁白统一为「已正式发布」
   （见 `submission-package/08-demo-video.md`）。
3. 已知需要留意的偏差：`site/.ResearchFlow.qoder.site` 描述符里的 `workspaceRoot` 记录为
   `D:/Qcode/Qoder CN/PowerContext-researchflow`，与本机实际路径 `D:/OceanBase/PowerContext-researchflow`
   不一致（历史环境留下的字段）。发布时以 `prepare_site` 显式传入的 `projectRoot`/`webDirectory` 为准，
   本轮实测由此得到正确的构件冻结（`indexSha256` 与本地文件一致可证）。

