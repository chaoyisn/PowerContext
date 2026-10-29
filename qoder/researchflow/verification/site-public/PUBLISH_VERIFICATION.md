# 站点公开发布验证记录

站点名称：ResearchFlow（比赛静态展示站）
真实 URL：<https://researchflow-5esfsogn38f.qoder.zone>
访问策略：**public**（`auth_integration_status=not_required`，无需登录即可访问）
发布时间：2026-10-29 10:44（本地，UTC+8）
验证时间：2026-10-29 10:46–10:47（本地，UTC+8）／02:47 UTC
客户端：Qoder CN Desktop 0.4.11（`productId=qoder-cn`、`region=cn`、`environment=prod`、`host.mode=desktop`）
站点标识：`site_id=01a18586-585e-79a0-9360-8857ac76263a`、`project_id=01a18586-585b-798b-83f6-59e45b2834f4`
发布动作：`actionId=b598cfeb-16d3-4968-8050-388b5ab3f173`、`publishOperationId=01a18589-6b9f-790c-aca6-bf7367d59e10`（`state=succeeded`、`committed=true`）

---

## 1. 发布流程的真实工具调用序列

| 步骤 | 调用 | 结果 |
| --- | --- | --- |
| 1 | `get_context` | `projectRoot=D:\OceanBase`、`sites=[]`、`filePreview=true`（服务已可达，不再是 `sites_unavailable`） |
| 2 | `list_sites(scope=owned)` | 正常返回，`total_size=0`（此前无站点，本次为新建） |
| 3 | `prepare_site` | `createNewSite=true`、`projectRoot=…\qoder\researchflow\site`、`webDirectory=public`、`spa=false`、`databaseAccess=none`、`displayName=ResearchFlow`、`slug=researchflow` → 返回 projectId / siteId |
| 4 | `get_publish_status` | `artifactReady=true`、`dependenciesReady=true`、`canPublish=true`、`blockers=[]`、`host=researchflow-5esfsogn38f.qoder.zone`、`access_mode=private` |
| 5 | `publish_site` | 返回 `publishOperationId=01a18589-…` |
| 6 | `get_publish_status` | `published=true`、`readiness=publication_completed`、`operation.state=succeeded`、`committed=true`、`site.url=https://researchflow-5esfsogn38f.qoder.zone` |
| 7 | `get_site_access` → `update_access_policy` | `mode=public`、`confirmPublic=true`（**公开切换已由本人明确授权**）→ 返回 `policy.mode=public` |
| 8 | `get_site_access` 复核 | `mode=public`、`rule_count=0`、`auth_integration_status=not_required` |

打包内容：`site/public/` 共 14 个文件、1.7 MB（`index.html`、`styles.css`、`app.js`、`data/evidence.json`、9 张真实运行截图 + 1 张基准 SVG）。上传前扫描无密钥、无完整 UID。

## 2. 匿名（未登录）访问验证

### 2.1 HTTP 直连（无 cookie、无凭据的 curl）

```
root               : 200  text/html; charset=utf-8  72818B
/styles.css        : 200
/app.js            : 200
/data/evidence.json: 200
/shots/s1-overview.png : 200
/#evidence（深链）  : 200
/no-such-page      : 404   ← 预期行为：站点为单页 + 锚点导航，spa=false，无客户端路由
```

### 2.2 无头浏览器全新上下文（等价无痕：无登录态、无 cookie）

命令：

```bash
NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" \
  node scripts/verify_site.cjs "https://researchflow-5esfsogn38f.qoder.zone/" \
  "qoder/researchflow/verification/site-public"
```

真实输出：

```
acc summary   : 9 / 9 PASS
pytest        : 149 passed
acceptance rows: 9
screenshots   : 9 broken: 0
seekdb fact   : 5.7.25-OceanBase seekdb-v1.4.0.0 @ 127.0.0.1:2881 · 分析器 ik · 集合 rf_chunks · 文档 3 / 页 7 / c
reload status : ok
mobile h-overflow px: 0
failed requests (>=400): 0
SITE VERIFY OK https://researchflow-5esfsogn38f.qoder.zone/
```

### 2.3 匿名验证清单核对

- [x] 未登录访客可打开真实 URL（curl 200 + 无头浏览器渲染成功）
- [x] 全部图片/CSS/JS/JSON 加载成功，Network 无 4xx/5xx（`failed requests (>=400): 0`；9 张截图 `broken: 0`）
- [x] 站内锚点跳转正常，整页 reload 不 404（`reload status: ok`）
- [x] 验收证据在页面上可见（T1–T9 表 9 行、`9 / 9 PASS`、`149 passed`）
- [x] seekdb / PowerContext 真实连接事实在页面上可见
- [x] 「在线版不连接数据库、不可交互」的体验边界说明可见
- [x] 1440px 与 390px 布局正常（移动端横向溢出 0px）
- [x] 无 console error / pageerror

## 3. 截图证据（本目录）

| 文件 | 内容 |
| --- | --- |
| `site-desktop.png` | 公开 URL 的 1440px 整页截图（无头浏览器全新上下文，未登录） |
| `site-mobile.png` | 公开 URL 的 390px 整页截图（同上） |

截图由 `scripts/verify_site.cjs` 在验证过程中直接产出，未经后期编辑。
`site/preview/site-desktop.png`、`site-mobile.png` 是发布前的**本地**预览截图，与本目录的**线上**截图分开保存，避免混淆证据来源。

## 4. 诚实声明

- 在线版是纯静态展示站：**不连接 seekdb、不连接 PowerContext、不提供任何模拟查询**。页面数据来自 `data/evidence.json`，由 `scripts/build_site_data.py` 从真实验收报告与真实 pytest 运行导出。
- 完整可交互系统需在本地按 `RUN.md` 启动（seekdb 2881 + PowerContext 17429 + FastAPI 8787）。
- 本次发布与公开切换均由用户在会话中明确授权后执行；发布前的 `sites_unavailable` 阻塞已在本轮解除，未使用任何伪造的发布状态。
