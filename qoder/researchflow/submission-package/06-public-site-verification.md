# 06 · 公开 Qoder Sites 站点与匿名访问验证

真实 URL：<https://researchflow-5esfsogn38f.qoder.zone>
访问策略：**public**（`auth_integration_status=not_required`，未登录即可访问）
形态：**纯静态展示站**，不连接 seekdb、不连接 PowerContext、不提供任何模拟查询。

原始记录：`verification/site-public/PUBLISH_VERIFICATION.md`（含逐步工具调用序列）
线上截图：`verification/site-public/site-desktop.png`（1440px 全新上下文）、`site-mobile.png`（390px）

---

## 1. 发布链路（真实工具调用，非口头声明）

| 步骤 | 调用 | 可核验结果 |
| --- | --- | --- |
| 1 | `get_context` | `projectRoot`、`sites=[]`、`filePreview=true` |
| 2 | `list_sites(scope=owned)` | `total_size=0`（本次为新建站点） |
| 3 | `prepare_site` | `createNewSite=true`、`webDirectory=public`、`spa=false`、`databaseAccess=none` |
| 4 | `get_publish_status` | `artifactReady=true`、`canPublish=true`、`blockers=[]` |
| 5 | `publish_site` | 返回发布 Operation |
| 6 | `get_publish_status` | `published=true`、`readiness=publication_completed`、`operation.state=succeeded`、`committed=true` |
| 7 | `update_access_policy(mode=public, confirmPublic=true)` | 公开切换由本人在会话中明确授权后执行 |
| 8 | `get_site_access` | `mode=public`、`rule_count=0`、`auth_integration_status=not_required` |

站点标识：`site_id=01a18586-585e-79a0-9360-8857ac76263a`、
`project_id=01a18586-585b-798b-83f6-59e45b2834f4`、
`actionId=b598cfeb-16d3-4968-8050-388b5ab3f173`、
`publishOperationId=01a18589-6b9f-790c-aca6-bf7367d59e10`
客户端：Qoder CN Desktop 0.4.11（`region=cn`、`environment=prod`）
打包内容：`site/public/` 共 14 个文件、1.7 MB（`index.html`、`styles.css`、`app.js`、
`data/evidence.json`、9 张真实运行截图 + 1 张基准 SVG）；上传前扫描无密钥、无完整 UID。

## 2. 匿名（未登录）可达性

### 2.1 发布当时的 curl 记录

```
root                  : 200  text/html; charset=utf-8  72818B
/styles.css           : 200
/app.js               : 200
/data/evidence.json   : 200
/shots/s1-overview.png: 200
/#evidence（深链）     : 200
/no-such-page         : 404   ← 预期：单页 + 锚点导航，spa=false，无客户端路由
```

### 2.2 封版复核（2026-10-29 13:3x 本地，无 cookie、无凭据）

```
/                          200 text/html; charset=utf-8 72818B
/styles.css                200 text/css; charset=utf-8    8126B
/app.js                    200 application/javascript     6879B
/data/evidence.json        200 application/json           8175B
/shots/s1-overview.png     200 image/png                 91049B
/no-such-page              404                              0B
```

首页字节数与发布当时完全一致（72818B），说明线上仍是同一份已验证内容，封版期间未发生
未复核的改动。**站点内容未变更，因此本轮不需要重新发布。**

### 2.3 无头浏览器全新上下文（等价无痕）

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

## 3. 核对清单

- [x] 未登录访客可打开真实 URL（curl 200 + 无头浏览器渲染成功）
- [x] 全部图片 / CSS / JS / JSON 加载成功，Network 无 4xx/5xx（`failed requests (>=400): 0`，9 张截图 `broken: 0`）
- [x] 站内锚点跳转正常，整页 reload 不 404（`reload status: ok`）
- [x] 验收证据在页面上可见（T1–T9 表 9 行、`9 / 9 PASS`、`149 passed`）
- [x] seekdb / PowerContext 真实连接事实在页面上可见
- [x] 「在线版不连接数据库、不可交互」的体验边界说明可见
- [x] 1440px 与 390px 布局正常（移动端横向溢出 0px）
- [x] 无 console error / pageerror

## 4. 边界（必须在材料里如实说明）

1. 在线站点**只用于展示**：不能上传、不能提问、不能查询记忆。完整可交互系统需按
   `RUN.md` 在本地启动（seekdb :2881 + PowerContext :17429 + FastAPI :8787）。
2. 页面数据来自 `site/public/data/evidence.json`，由 `scripts/build_site_data.py`
   从真实验收报告与真实 pytest 输出导出；没有任何手工填写或预置假数据。
3. 站点为 `access_mode=public`，任何人都能读；因此内容中**不含**完整 Qoder UID、
   API key、内部数据。原始 PDF 与数据库未上传到站点。
4. 本地后端同样**不对公网暴露**：只监听 `127.0.0.1:8787`，且不承载任何真实用户凭据；
   PowerContext 无多用户鉴权，把后端直接开放会造成跨用户读取记忆/文档的风险。
