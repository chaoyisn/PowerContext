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
   - `shots/` 9 张**真实运行截图**（`scripts/capture_screenshots.cjs` 无头浏览器采集，可复现）；
   - `data/evidence.json` 由 `scripts/build_site_data.py` 从真实验收报告 + 真实 pytest 运行 + 实时
     `/api/health` 导出，**不含任何模拟数据**。
2. **本地验证通过**（`scripts/verify_site.cjs`，Playwright 无头）：
   - 证据数据渲染：`9 / 9 PASS`、`88 passed`、验收表 9 行；
   - 9 张截图全部加载成功（broken=0）；
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

**已正式发布，并已切换为公开访问。**

| 项目 | 值 |
| --- | --- |
| 真实 URL | <https://researchflow-5esfsogn38f.qoder.zone> |
| 站点标识 | `site_id=01a18586-585e-79a0-9360-8857ac76263a`、`project_id=01a18586-585b-798b-83f6-59e45b2834f4` |
| 发布动作 | `actionId=b598cfeb-16d3-4968-8050-388b5ab3f173`、`publishOperationId=01a18589-6b9f-790c-aca6-bf7367d59e10` |
| 发布状态 | `published=true`、`readiness=publication_completed`、`operation.state=succeeded`、`committed=true` |
| 访问策略 | `mode=public`、`rule_count=0`、`auth_integration_status=not_required`（无需登录） |
| 站点生命周期 | `lifecycle=active`、`governance_status=normal` |
| 客户端 | Qoder CN Desktop 0.4.11、`region=cn`、`environment=prod` |
| 发布/验证时间 | 2026-10-29 10:44 发布，10:46–10:47 验证（本地 UTC+8；02:47 UTC） |
| 打包内容 | `site/public/` 14 个文件、1.7 MB；上传前扫描无密钥、无完整 UID |

匿名验证结论（未登录、无 cookie）：根路径与全部静态资源 200；9 张真实截图 `broken=0`；
Network 无 ≥400 请求；锚点跳转与整页 reload 正常；验收表 9 行、`9 / 9 PASS`、`149 passed` 在页面可见；
390px 横向溢出 0px；无 console error / pageerror。线上整页截图：
`verification/site-public/site-desktop.png`、`verification/site-public/site-mobile.png`。

历史阻塞记录（保留作为过程证据）：V2 两轮共 3 次 `prepare_site` 返回 `sites_unavailable`、
`get_publish_status` 返回 `sites_action_unavailable`，本地遥测显示已进到云端准备阶段
（`is_new_site=true`、`creator_uid=01a175e3-…`、`trigger=agent`）；第二次自动重试被 Qoder
权限分类器拦截，要求人工核验账号权益。该阻塞在 V3 复核时已自行解除，未修改任何站点内容即发布成功。
