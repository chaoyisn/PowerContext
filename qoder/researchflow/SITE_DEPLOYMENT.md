# SITE_DEPLOYMENT.md — Qoder Sites 发布状态与方案

更新时间：2026-10-29（V2 第一轮）
状态：**网站已构建并本地验证通过；云端 prepare 被平台拒绝（`sites_unavailable`），发布阻塞，未发布、未伪造任何发布记录。**

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
3. **prepare 参数已确定**（重试时直接使用）：
   ```json
   {
     "projectRoot": "D:\\OceanBase",
     "webDirectory": "qoder/researchflow/site/public",
     "displayName": "ResearchFlow",
     "slug": "researchflow",
     "spa": false,
     "databaseAccess": "none"
   }
   ```
   无 Function、无数据库、无 Secrets → 不触发 backend 权益分支。

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

## 4. 阻塞解除后的发布步骤（人工 + Agent）

1. 在 Qoder Desktop 中确认账号的 Sites 权益/服务状态（设置或官网权益页）；若提示升级或开通，按提示操作。
2. 服务恢复后重跑：`prepare_site`（§2.3 参数，**新 actionId**）→ `get_publish_status` 读
   `artifactReady` / `dependenciesReady` / `blockers` → `publish_site(actionId)` → 轮询至 `published=true`。
3. Desktop 宿主调用 `show_publish_confirmation(actionId)` 查看冻结预览（不发布）。
4. **切换为公开访问前必须取得用户明确确认**，然后 `update_access_policy(..., confirmPublic=true)`。
5. 匿名验证清单（发布后执行并记录到本文件）：
   - 未登录访客可打开真实 URL；
   - 全部图片/CSS/JS 加载成功（Network 无 4xx/5xx）；
   - 站内锚点与整页刷新不 404；
   - 仓库链接、运行说明、验证证据在页面上可找到；
   - 「在线不可交互」的说明可见；
   - 390px 与 1440px 布局正常。
6. 将真实 URL、发布时间、访问策略与上述验证结果回填本文件第 5 节。

---

## 5. 发布结果

**尚未发布。** 无 URL。原因：`prepare_site` 在当前环境返回 `sites_unavailable`（三次，含最小参数），
属平台侧阻塞；本地站点与全部证据已就绪并通过验证，服务恢复后可按 §4 直接发布。
