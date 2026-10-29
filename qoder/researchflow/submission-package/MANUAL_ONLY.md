# MANUAL_ONLY · 只剩本人能做的操作（逐项：在哪做 / 做什么 / 完成标准）

本轮自动部分已全部完成（前端冻结、站点重发布、演示视频重录、文档同步、ZIP 打包与自校验、
Git 提交推送）。下面 6 项是 Agent **无法也不应代为完成**的。
§1 / §2 / §4 **阻塞正式报名**；§3 视主办方要求；§5 / §6 是可选项。

> 红线复述（任何一项都不得为了「材料看起来更全」而绕过）：
> 不伪造 Qoder 对话截图；不代写用户反馈；不把脚本代理数据写成真人提效；
> 不把完整 UID / 密钥 / 内部数据写进仓库、站点或 ZIP；不擅自改动仓库公开权限。

---

## 1. Qoder 对话与开发过程截图（8 张 · 阻塞）

- **在哪做**：Qoder Desktop → 会话历史（左侧/顶部），按关键词搜索本次开发会话。
- **做什么**：按 [`07-qoder-dev-evidence.md`](07-qoder-dev-evidence.md) 的 Q1–Q8 表逐条截取
  **同时包含「用户消息 + Agent 回复 + 时间信息」**的窗口。8 个主题分别是：
  需求与边界、架构决策、seekdb 接入实测、PowerContext 记忆接入、缺陷定位与修复、
  测试与验收、Sites 发布链路、诚实性规则。表中给出的关键词均已核对确实存在于本轮会话记录中。
- **截图前自检**：画面里没有完整 UID、没有 API key、没有 `.env` 内容、没有个人主目录路径。
- **存放位置**：`submission-package/qoder-evidence/`（目录当前不存在，截图时新建即可）。
  文件名固定为
  `qoder-01-requirements.png`、`qoder-02-architecture.png`、`qoder-03-seekdb-integration.png`、
  `qoder-04-powercontext-memory.png`、`qoder-05-bugfix-debug.png`、`qoder-06-testing-acceptance.png`、
  `qoder-07-sites-publish.png`、`qoder-08-honesty-rules.png`。
- **完成标准**：8 个文件都在，每张一眼可辨是 Qoder 对话界面（不是终端、不是 Git 提交列表）。
  **禁止**用 `git log` 截图冒充对话记录——仓库里已有真实提交时间线，两者应互证而非互替。
- **注意**：截图落盘后如果希望一并进 ZIP，需重新执行
  `backend/.venv/Scripts/python scripts/build_final_zip.py`（该目录当前不存在于归档中，
  见 `FILES_TO_UPLOAD.md` §4 的排除说明）。

## 2. 完整 Qoder UID（阻塞）

- **在哪做**：Qoder Desktop → 账号 / 设置页读取本人 UID。
- **做什么**：**只填进比赛报名平台的 UID 字段**。建议同时截一张账号页画面作为归属证明。
- **禁止**：写入仓库、站点页面、日志、`submission-package/**`、ZIP 或聊天截图。
  仓库与站点里只保留前缀 `01a175e3-…`，用于说明「已核对」这一事实。
- **完成标准**：报名表内的 UID 与账号页一致；同时在仓库根执行下面两条，
  **第一条必须输出 `0`、第二条必须无输出**（本轮封版实测：`0` 与无输出）——

  ```bash
  git log -p --all | grep -Ec "01a175e3-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
  grep -rEc "01a175e3-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" qoder/researchflow/ | grep -v ':0$'
  ```

## 3. 仓库可见性 / 评审可访问性（视主办方要求）

- **现状**：`origin` 为 `https://github.com/chaoyisn/PowerContext.git`（开发日志记为私有仓库）。
  本轮**未**改动仓库公开权限，也未添加协作者。
- **若主办方要求公开或加协作者**：由本人在 GitHub 侧操作，并按平台要求授权。
  Agent 不代为改动可见性——这属于对外可见状态的变更，且影响该仓库内其他赛题的可见性。
- **完成标准**：用一个未登录浏览器（或无痕窗口）能打开
  `https://github.com/chaoyisn/PowerContext/tree/2026-competition-ecosystem/qoder/researchflow`；
  或已在报名表里写明评审访问方式（例如邀请协作者的账号 / 提供的镜像）。

## 4. 比赛平台最终提交（阻塞）

- **在哪做**：比赛报名平台。**Agent 不代为提交。**
- **做什么**（内容全部可直接从 [`FORM_FIELDS.md`](FORM_FIELDS.md) 复制）：
  1. A 作品信息 → `FORM_FIELDS.md` §A；
  2. B 访问与代码 → §B。**填 SHA 前先跑**
     `git fetch origin && git rev-parse HEAD origin/2026-competition-ecosystem`，
     两个 SHA 相同才继续；本文与所有文档都不写死 tip。
  3. C 运行与验证 → §C。先用无痕窗口打开一次站点确认可访问。
  4. D Qoder 开发证明 → §D + 上面 §1 的 8 张截图。
  5. E 视频与使用效果 → §E + 上传
     `submission-package/demo/researchflow-demo.mp4`（或其所在交付目录的副本）。
  6. 若平台要求单文件附件：用
     `D:\OceanBase\deliverables\researchflow-final\ResearchFlow-Qoder-Final.zip`
     （校验与成员清单见 `FILES_TO_UPLOAD.md` §3）。
- **完成标准**：平台侧显示提交成功；且**评审只凭仓库 + 站点 + 视频**就能复现每一个数字
  （复现命令在 `RUN.md` 与 `02-run-and-reproduce.md`）。

## 5. 真人配音 / 真人出镜（可选）

- **现状**：成片已自动生成并可直接提交（真实浏览器录屏 + Windows 合成中文语音 + 烧录字幕，
  25 项成片自动检查全 PASS）。
- **只有两种情况需要人工**：① 想要真人配音；② 想要真人出镜口播。
- **步骤**：按 [`../DEMO_SCRIPT.md`](../DEMO_SCRIPT.md) §1 准备环境 → §2 逐段录屏
  （1440×900、1080p/30fps、浅色主题、关通知）→ 照读 §3 旁白稿录音 → 拼接加字幕。
  **旁白稿里的数字与结论一个字都不要改。**
- **完成标准**：新成片覆盖 `08-demo-video.md` §2 的 8 个必答点，画面中每个数字都能在
  `verification/acceptance-run/` 或 `logs/` 里找到同值原始输出；旧成片与生成记录保留。

## 6. 真实用户反馈（可选，不阻塞）

- **现状**：材料里对应位置是「**未收集**」，没有编造任何反馈或真人提效数字。
- **步骤**：邀请 1–2 位同学/同事，给 `RUN.md` 链接和 `demo/` 语料，让其用约 10 分钟走完
  「上传 → 检索 → 点开引用页 → 保存进度 → 新会话恢复」；
  **原样保留**其反馈文本与时间戳（聊天截图 / 邮件原文），并记录是否成功复现。
- **存放位置**：`submission-package/qoder-evidence/feedback-<姓名缩写>-<YYYYMMDD>.txt`（或 png）。
- **完成标准**：有原始文本 + 时间 + 反馈人可辨认（可用化名，但需注明「化名」）。
  没有这项不影响其他验收结论。

---

## 附：状态一览

| # | 项 | 阻塞报名 | 当前状态 |
| --- | --- | --- | --- |
| 1 | 8 张 Qoder 对话截图 | 是 | 待人工（自动侧已给出定位关键词与文件名） |
| 2 | 完整 Qoder UID | 是 | 待人工（只进报名表） |
| 3 | 仓库可见性 | 视要求 | 未改动（私有），需本人按平台要求授权 |
| 4 | 平台最终提交 | 是 | 待人工（表单文本已备好） |
| 5 | 真人配音 / 出镜 | 否 | 可选；成片已可直接提交 |
| 6 | 真实用户反馈 | 否 | 未收集，材料中如实标注 |
