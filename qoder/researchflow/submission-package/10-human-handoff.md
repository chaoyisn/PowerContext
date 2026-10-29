# 10 · 人工交接（只剩 5 项，每项含步骤 / 存放位置 / 完成标准）

自动部分已完成：演示视频、站点发布与匿名验证、测试与验收证据、提交包文档、交付审计。
下面 5 项是 Agent 无法代做的。**第 2 / 3 / 4 项阻塞提交；第 1、5 项是可选加分项。**

---

## 1. 演示视频（可选覆盖，默认无需操作）

- **现状**：`submission-package/demo/researchflow-demo.mp4` 已存在（**2 分 15 秒 / 6.5 MB**，
  2026-10-29 22:21 定稿；真实产品录屏 + 中文合成语音 + 烧录字幕，展示站两个场景录自线上地址），
  25 项成片自动检查全 PASS，可直接提交。
- **只有在这两种情况下才需要人工**：① 想要真人配音；② 想要真人出镜口播。
- **步骤**：按 [`../DEMO_SCRIPT.md`](../DEMO_SCRIPT.md) §1 准备环境 → §2 分镜逐段录屏
  （1440×900、1080p/30fps、浅色主题、关通知）→ 照读 §3 旁白稿录音 → 拼接加字幕。
  **旁白稿里的数字与结论一个字都不要改。**
- **存放位置**：覆盖或并列放在 `submission-package/demo/`；原始片段放本机，不必入库。
- **完成标准**：成片能覆盖 §2 的 8 个必答点，且画面中的每个数字都能在
  `verification/acceptance-run/` 或 `logs/` 里找到同值原始输出。

## 2. Qoder 对话与开发过程截图（必须，8 张）

- **步骤**：在 Qoder Desktop 左侧/顶部打开会话历史，按
  [`07-qoder-dev-evidence.md`](07-qoder-dev-evidence.md) 的 Q1–Q8 表逐条搜索关键词
  （关键词已核对确实存在于本次开发会话记录中），截取**含用户消息 + Agent 回复 + 时间信息**的窗口。
  截图前确认画面里**没有**完整 UID、API key、内部数据。
- **存放位置**：`submission-package/qoder-evidence/`（目录当前不存在，截图时新建即可），
  文件名按表中的建议名：`qoder-01-requirements.png`、`qoder-02-architecture.png`、
  `qoder-03-seekdb-integration.png`、`qoder-04-powercontext-memory.png`、
  `qoder-05-bugfix-debug.png`、`qoder-06-testing-acceptance.png`、
  `qoder-07-sites-publish.png`、`qoder-08-honesty-rules.png`。
- **完成标准**：8 个文件都在，每张能看出是 Qoder 对话界面（非终端、非 Git 提交列表）；
  **禁止**用 `git log` 截图冒充对话记录（仓库里已有真实提交时间线，两者应互证而非互替）。

## 3. 完整 Qoder UID（必须，但只填在报名平台）

- **步骤**：Qoder Desktop → 账号/设置页查看本人 UID → **只填进比赛报名平台的报名表**。
- **存放位置**：报名平台字段。**不要**写入仓库、站点、日志、提交包、ZIP 或聊天截图。
  仓库与站点里只保留 UID 前缀（`01a175e3-…`）用于说明「已核对」这一事实。
- **完成标准**：报名表内 UID 与账号页一致；`git log -p`、`submission-package/**`、
  站点页面上都搜不到完整 UID（提交包已按 `PUSH_PRECHECK.md` §2 的扫描口径复核）。

## 4. 比赛平台最终提交（必须）

- **步骤**：
  0. **先确认评审能否访问仓库**：`origin` 是 `chaoyisn/PowerContext`（开发日志记为私有仓库）。
     若主办方要求公开或加协作者，按平台要求授权（本 Agent 不代为改动仓库可见性）。
  1. 仓库地址 `https://github.com/chaoyisn/PowerContext.git`，分支 `2026-competition-ecosystem`，
     作品目录 `qoder/researchflow/`；提交前执行
     `git fetch origin && git rev-parse HEAD origin/2026-competition-ecosystem`
     确认两个 SHA 相同（本文不写死 tip）。
  2. 在线站点填 <https://researchflow-5esfsogn38f.qoder.zone>（先无痕窗口打开一次确认可访问）。
  3. 演示视频上传 `submission-package/demo/researchflow-demo.mp4`（1280×800 / 2:15 / 6.5 MB，
     2026-10-29 22:21 定稿，展示站场景录自线上地址）。
  4. 文字说明可直接粘贴 `submission-package/01-overview-and-highlights.md` 的 §1–§2
     与 `05-acceptance-index.md` 的结果表。
  5. 若平台要求单文件附件：用 `FINAL_SUBMISSION.md` + `submission-package/` 打包 ZIP
     （打包命令见 `../AUDIT.md` §附，已排除 venv / 数据库 / 日志敏感字段 / 临时文件）。
- **完成标准**：平台侧显示提交成功，且**评审只凭仓库 + 站点 + 视频就能复现**每个数字。

## 5. 真实用户反馈（可选，不阻塞验收）

- **步骤**：邀请 1–2 位同学/同事，给 `RUN.md` 链接和 `demo/` 语料，让其用 10 分钟完成
  「上传 → 检索 → 点开引用页 → 保存进度 → 新会话恢复」这条路径；
  **原样保留**其反馈文本与时间戳（聊天截图/邮件原文），并记录其是否成功复现。
- **存放位置**：`submission-package/qoder-evidence/feedback-<姓名缩写>-<YYYYMMDD>.txt`（或 png）。
- **完成标准**：有原始文本 + 时间 + 反馈人可辨认（可用化名，但需注明「化名」）。
  **不得由 Agent 代写、不得事后补记为「实测」**；没有这项也不影响其他验收结论，
  材料里对应位置保持「缺：真实人工使用记录」（见 `09-usage-impact-sources.md` §3）。

---

## 附：这些人工项与自动项的关系

| 提交要求 | 自动已完成 | 人工待补 |
| --- | --- | --- |
| 项目介绍 / 架构 / 运行说明 | ✅ `01` `02` `11` | — |
| seekdb / PowerContext 真实证据 | ✅ `03` `04` | — |
| 测试与验收报告 | ✅ `05` | — |
| 公开站点与匿名验证 | ✅ `06` | — |
| Qoder 开发证据索引 | ✅ `07`（索引与定位关键词） | 8 张截图（本文件 §2） |
| 演示视频 | ✅ `08`（成片已生成） | 可选真人配音（§1） |
| 真实使用效果材料 | ✅ 自动化 + 脚本代理（分级标注） | 可选真人反馈（§5） |
| 报名与 UID | — | §3、§4 |
