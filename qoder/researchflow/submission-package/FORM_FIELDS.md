# FORM_FIELDS · 报名平台可直接复制的填写内容

按官方通用提交要求（A 作品信息 / B 访问与代码 / C 运行与验证 / D Qoder 开发证明 /
E 演示视频与使用效果）组织。每条都是**可直接粘贴**的成品文本，内容全部来自本仓库
已有的真实产物；不同平台的字段名可能不完全一致，按语义取用即可。

> 粘贴前的两条硬规则：
> 1. **不要**在任何平台字段里写完整 Qoder UID、API key、数据库口令或本机用户目录路径；
>    UID 只填在报名平台要求它的那一个字段（见 `MANUAL_ONLY.md` §2）。
> 2. 凡涉及「使用效果」的字段，只用下面的文本，不要改成「提效 X 倍」——
>    W1/W2 是**脚本代理测量**，不是真人实测（口径见 `09-usage-impact-sources.md`）。

---

## A · 作品信息

### A1 作品名称

```
ResearchFlow —— 基于 seekdb 与 PowerContext 的科研知识与任务连续性助手
```

### A2 一句话简介（≤ 60 字）

```
带证据的科研知识库 + 长期任务记忆：每条结论可点开 seekdb 里的原文页，换个会话也能从 PowerContext 恢复研究进度。
```

### A3 作品简介（正文字数不限版）

```
ResearchFlow 解决两个具体问题：AI 给的结论能不能回查原文，以及换一个会话以后研究进度还在不在。

它把两件事做成两条可以独立断开的存储通道：seekdb 负责文献证据（PDF 按物理页入库，
内容寻址主键 doc_id = SHA-256(文件字节)，ik 全文索引 + 384 维 HNSW 余弦向量，
vector / fulltext / hybrid(RRF) 三模可同屏对比），PowerContext 负责任务记忆
（一个项目 = 一个 Scope，写入显式、幂等键绑定、重复内容自动跳过）。

每条论断都标注「资料直接支持 / 模型推断 / 尚无证据」，并且 citation 由服务端逐条回查
seekdb 校验：不在检索结果里的引用、页码不存在的引用会被剔除并上报 invalid_citations，
失去引用的结论自动降级为「模型推断」。语料里没有答案时走 no_evidence，不产生任何引用。

技术栈：FastAPI + React 18 / Vite / TypeScript 前端，seekdb v1.4.0.0（Docker，
127.0.0.1:2881），PowerContext 1.4.1（127.0.0.1:17429），LLM 走可配置的 deepseek-chat；
未配置密钥时问答进入明确标注的「仅检索模式」，不会把检索摘要冒充模型回答。

没有任何 mock 层或预置答案：断掉 seekdb 或 PowerContext，接口返回真实错误而不是漂亮的
空结果——这一点本身就是端到端验收用例 T7 / T8。
```

### A4 核心亮点（要点式，4～6 条）

```
1. 证据可回查：每条引用都能点开该物理页在 seekdb 中的原文，页码用 PDF 物理页号，空白页也保留页级身份。
2. 引用是服务端校验的，不是提示词承诺的：无效 citation 被剔除并上报，无证据时不编造页码。
3. 三模检索并排可视：vector / fulltext / hybrid(RRF, k=60) 同屏，附按 chunk_id 的重叠分析。
4. 任务连续性：仅凭 project_id 从 PowerContext 恢复已确认决策与 next_steps，生成确定性续研简报。
5. 两条通道可独立断开并被验收：T7 断 PowerContext、T8 断 seekdb，验证「断了会怎样」。
6. 全链路可复现：149 项 pytest + T1–T9 端到端验收 150 项校验 + 30 组真实浏览器交互验收
   + 一次全新 venv/容器/数据目录的 23/23 步评审旅程，全部打真实依赖。
```

### A5 技术栈 / 依赖

```
后端：Python 3.12 + FastAPI，pyseekdb（连接 seekdb v1.4.0.0，MySQL 协议 127.0.0.1:2881）
检索：ik 全文分析器 + all-MiniLM-L6-v2 ONNX 384 维向量 + RRF 混合排序
记忆：PowerContext 1.4.1（本地 HTTP 服务 127.0.0.1:17429，Scope 隔离 + 幂等写入）
前端：React 18.3 + Vite 5 + TypeScript 5.6，react-router 6，自研 token 主题（浅/深色）
测试：pytest（149 项）、自研端到端验收运行器、Playwright 驱动真实 Chromium
部署：Qoder Sites 纯静态展示站（本地完整版需按 RUN.md 启动三个进程）
```

---

## B · 访问与代码

### B1 在线作品地址

```
https://researchflow-5esfsogn38f.qoder.zone
```

紧跟着这一句，**不要省略**（避免评委把它当成在线可交互产品）：

```
该站点是 Qoder Sites 托管的纯静态展示版：不连接 seekdb、不连接 PowerContext、不提供任何
模拟查询或在线问答；完整可交互系统需按仓库内 RUN.md 在本地启动。
访问策略为 public（未登录可访问）。已用无 Cookie 的 HTTP 抓取逐文件核验：线上 15/15 文件
与本地最终构建逐字节一致（HTML 需先剥离平台自动注入的水印脚本），无头浏览器全新上下文
渲染 0 个失败请求、390px 移动端 0 横向溢出。核验明细在 verification/site-public/。
```

### B2 Git 仓库地址 / 分支 / 作品目录

```
仓库：https://github.com/chaoyisn/PowerContext.git
分支：2026-competition-ecosystem
作品目录：qoder/researchflow/
官方基线提交：d647275c308e09b7b623f322a26f5c4e85734fb0（本次全部改动均为其后代，
              且只落在 qoder/researchflow/** 之内，未触碰其他赛题目录或其他工作树）
推送方式：逐次 fast-forward 推送，未使用 --force，未改写已推送历史
```

### B3 提交 SHA（评委可直接核对）

平台若要求填写「最终提交 SHA」，**先执行下面两条命令取当前值再填**，不要抄本文：

```bash
cd <PowerContext 仓库>
git fetch origin
git rev-parse HEAD origin/2026-competition-ecosystem   # 两个 SHA 必须相同
```

本仓库所有文档都刻意**不写死 tip**（`AUDIT.md` §1 同此约定），以免文档与远端出现两个"真值"。
封版前最后一次已核对一致的远端 tip：`fe8c14c7a7621638622235bbbde0920c36fd529b`。

### B4 仓库可见性

若主办方要求公开仓库或添加协作者，需本人操作——本轮未改动仓库公开权限。
（详见 `MANUAL_ONLY.md` §3。）

---

## C · 运行与验证

### C1 最短运行路径（贴进"如何运行"字段）

与仓库根目录的 `RUN.md` 一致，下面只摘最短路径；两条前置是**必须**的：
Docker 里有正在运行的 seekdb 容器（`docker start contest-seekdb`，监听 `127.0.0.1:2881`），
以及两个项目自带 venv（`backend/.venv`、`services/.venv-powercontext`）。
**不要**用系统 Python 或 Anaconda base。

```bash
cd qoder/researchflow

# 1) PowerContext 记忆服务（:17429）
POWERCONTEXT_HOME="$PWD/services/powercontext-data" \
  services/.venv-powercontext/Scripts/powercontext.exe server run \
  --host 127.0.0.1 --port 17429 --no-env-file

# 2) 前端构建（产物 frontend/dist 由后端同源托管）
cd frontend && npm install && npm run build && cd ..

# 3) ResearchFlow 后端（:8787）；RF_LLM_API_KEY 可选，不配则问答进入「仅检索模式」
cd backend
RF_LLM_API_KEY="$DEEPSEEK_API_KEY" .venv/Scripts/python -m app.api.main

# 4) 另开一个终端，灌演示语料（3 份文档 / 7 物理页 / 13 chunk + 一条真实进度快照）
backend/.venv/Scripts/python scripts/seed_demo.py

# 5) 浏览器打开 http://127.0.0.1:8787
```

### C2 测试与验收命令 + 期望结果

```bash
cd qoder/researchflow/backend && .venv/Scripts/python -m pytest tests/ -q
# 期望：149 passed（直接打真实 seekdb 与真实 PowerContext，含 held-out 用例）

backend/.venv/Scripts/python scripts/run_acceptance.py
# 期望：T1–T9 = 9 PASS / 0 FAIL / 0 SKIP，共 150 项校验
# 该运行器自带独立 PowerContext(:17430) 与 API(:8788)，会真实重启与真实断连，不复用产品实例

backend/.venv/Scripts/python scripts/fresh_env_e2e.py
# 期望：23/23 步全 PASS（全新 venv + 全新 seekdb 容器与卷 + 全新 PowerContext 数据目录，
#       结束自动清理，不影响同机其他赛题）

NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" \
  node scripts/verify_interactions.cjs
# 期望：30/30 PASS（真实 Chromium 手势 + 渲染文本与接口 JSON 逐字比对，四档视口）
```

### C3 验证结果摘要（可直接粘贴的数字）

```
端到端验收 T1–T9：9 PASS / 0 FAIL / 0 SKIP，150 项校验（运行号 20261029-213920）
  T1 上传 PDF 全部物理页入库 · T2 明确问题返回真实页码 · T3 无答案问题不伪造 citation
  T4 新建项目并写入决策与 next_steps · T5 重建会话后恢复 · T9-LLM 真实证据问答+服务端校验
  T6 重启服务后数据与记忆可查 · T7 断开 PowerContext · T8 断开 seekdb 报真实错误
pytest：149 passed in 55.21s
真实浏览器交互验收：30/30 PASS（6 个路由 × 390/768/1280/1920 视口；48 张截图 0 溢出）
全新环境复现：23/23 步 PASS（68.4 s）
公开站点核验：15/15 文件与本地最终构建逐字节一致；未登录可访问；失败请求 0；移动端横向溢出 0
演示视频成片自检：25 项交付检查全 PASS（解码无错、音画差 0.028 s、28 条字幕覆盖 0.89、11 场景全有关键帧）
```

### C4 诚实披露（建议一并填入"局限性 / 说明"字段）

```
1. 在线站点是纯静态展示版，不提供真实在线数据库交互；静态输入框不伪装成可用的在线 AI 服务。
2. 工作流提效测量（W1/W2）是脚本代理测量，不是真实用户实测，未表述为「提效 X 倍」。
3. 已知未通过项保留未删：检索基准 B2 有 2 条「英文改写问中文原文」在默认阈值下被证据门控
   判为不可答（保守失败，不是错误答案）；W1 有 1 条排序不符预期（正确块排第 6，被 top_k=5 截断）。
4. 后端只监听 127.0.0.1:8787，不对公网暴露：PowerContext 侧没有多用户鉴权，直接开放会让
   匿名用户互相读取文档与记忆。因此本项目不提供公网可写的实例。
5. 材料中不含完整 Qoder UID、API key、数据库口令或个人主目录路径；原始 PDF 与数据库未上传站点。
```

---

## D · Qoder 开发证明

### D1 「使用 Qoder 做了什么」文本

```
本项目全程在 Qoder Desktop 中开发（Qoder CN Desktop 0.4.11，region=cn，environment=prod），
从依赖可行性实测、数据闭环、记忆闭环、产品前端到交付验收都由 Agent 在真实仓库内执行，
人负责授权与决策。开发过程逐轮记录在仓库内的 qoder/researchflow/QODER_LOG.md，
包含每轮的真实命令输出与失败记录（例如 prepare_site 三次返回 sites_unavailable 的失败、
一次因同机端口占用而失败的全新环境复现，均保留未美化）。

Qoder 的实际作用体现在三类可核验产物上：
· 代码与测试：backend/app 四个领域模块、149 项 pytest、端到端验收运行器、React 前端与展示站；
· 工具链：scripts/ 下的录屏/配音/字幕/成片校验、站点逐文件哈希核验、ZIP 打包自校验脚本；
· 平台闭环：通过 Qoder Sites 把展示站发布为公开可访问的静态站点，并保留发布链路的工具调用记录。
```

### D2 必须人工补的截图

**8 张 Qoder 对话截图**，逐张的搜索关键词、文件名与存放路径见
`../submission-package/07-qoder-dev-evidence.md` 的 Q1–Q8 表 + `MANUAL_ONLY.md` §1。
**禁止**用 `git log` 截图冒充对话记录，也**禁止**生成或伪造对话画面。

### D3 UID

```
完整 Qoder UID 只填报名平台的对应字段；仓库、站点、ZIP、聊天截图内一律只保留前缀 01a175e3-…
用于说明「已核对」。UID 由本人在 Qoder Desktop 账号页读取，并建议附账号页截图作为归属证明。
```

---

## E · 演示视频与使用效果

### E1 视频文件（上传用绝对路径）

```
D:\OceanBase\PowerContext-researchflow\qoder\researchflow\submission-package\demo\researchflow-demo.mp4
规格：1280×800 · H.264 High / yuv420p · 30 fps · 134.97 s（2 分 15 秒）· AAC 48 kHz 立体声 · 6 796 164 B
SHA-256：f0dfab386a67cd10699cd5aa6db5844a8b2e37fea69524e822cc41c499da2528
```

若平台对时长有「约 3 分钟」的硬性要求，用下面这段说明，不要改视频去凑时长：

```
成片 2 分 15 秒：11 个场景覆盖全部必答点（seekdb 真实入库、三模检索、Citation 原文页回查、
PowerContext 保存与跨会话恢复、断连降级、真实测试结果、线上站点画面）。
录屏按旁白时长等比重放，系数逐场景记录在 demo/video-manifest.json，未删除或跳剪任何真实步骤，
因此时长由真实操作决定而非剪出来的。需要更长版本可按 DEMO_SCRIPT.md §3 的旁白稿真人重录。
```

### E2 视频内容口径（如平台要求「说明视频真实性」）

```
8 个场景是真实浏览器录屏，其中展示站的两个场景（c2 / c10）直接录自线上公开地址
https://researchflow-5esfsogn38f.qoder.zone；3 个场景（c1 片头、c9 测试结果、c11 片尾）
是日志/文本卡，卡片页脚已注明，不冒充操作画面。旁白中的每个数字都从同一次运行的产物读回
（pytest 日志、验收报告 JSON、浏览器交互验收 JSON、全新环境复现 JSON），
逐场景采集方式、真实耗时与重放系数见 demo/video-manifest.json，
成片文件本身另经 25 项自动检查（demo/video-check.json，全 PASS）。
配音为 Windows 合成语音（Microsoft Huihui），非真人。
```

### E3 真实使用效果（如平台要求填写）

```
已有：自动化验收（T1–T9 150 项校验）、真实浏览器交互验收（30/30）、全新环境复现（23/23）、
检索与记忆基准（B1/B2/D），以及脚本代理的工作流对照测量（W1/W2）。
缺少：真实人工使用的耗时与纠错记录、真实用户反馈——本轮标记为「未收集」，
未由 Agent 代写，也未折算成任何提效结论。
分级口径见 submission-package/09-usage-impact-sources.md。
```
