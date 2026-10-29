# 09 · 真实使用效果材料与来源（三类证据强制分级）

**口径（不可混用）**

| 级别 | 含义 | 允许的说法 |
| --- | --- | --- |
| `automated` | 脚本直接打真实组件、断言真实返回值 | 「自动化测试通过 / 实测指标为 X」 |
| `script-proxy` | 用脚本模拟人工判读（关键词扫描、正则扫描）得到的对照 | 「脚本代理测量，**非真实用户实测**」 |
| `human` | 真人操作或真人判断 | 目前**仅有开发者自用**，无外部用户实测 |

原始数据全部可复跑，脚本与 JSON 路径见每节；环境：Windows 11 / Python 3.11.7 /
seekdb v1.4.0.0（Docker，127.0.0.1:2881）/ PowerContext 1.4.1（127.0.0.1:17429）/
DeepSeek `deepseek-chat`。测量日期 2026-10-29。

---

## 1. `automated` — 系统能力与正确性（可当作事实陈述）

| 项 | 结果 | 来源 |
| --- | --- | --- |
| 后端测试 | **149 passed**（88 基础 + 21 中文记忆 + 25 安全 + 15 保留集） | `cd backend && .venv/Scripts/python -m pytest tests/ -q` |
| 端到端验收 | T1–T9 **9 PASS / 0 FAIL / 0 SKIP**，共 **150 项**逐条校验 | `verification/acceptance-run/`（`05-acceptance-index.md`） |
| 全新环境复现 | 评审旅程 **20/20** 通过（新 venv + 新 seekdb 容器 2890 + 新 PowerContext 17431，跑完自动清理） | `scripts/fresh_env_e2e.py` |
| 检索质量 B2 | 3 provider × 3 mode：R@1/R@3/R@5/MRR 全表；默认阈值 0.62 下**负例误报 0/2** | `scripts/bench_retrieval.py` → `logs/bench-retrieval-*.json`、`BENCHMARK.md` §2 |
| 中文记忆召回 B1 | 修复前 6/10（含 1 次负例误报）→ 修复后 **hit@3 10/10、hit@1 8/10、负例误报 0** | `scripts/bench_memory_zh.py` → `logs/bench-memory-zh-20261029-090133.json`、`BENCHMARK.md` §1 |
| 混合检索正确性 | 演示问题 RRF 融合分 **0.0328** = 文档中手写的 `1/61+1/61` | T2 日志 + 站点截图 `s5-retrieval.png` |
| 无证据不编造 | 语料外问题 → `answerable=false`、`claims=[no_evidence]`、`citations` 为空 | T3 日志 + 视频 c6 场景 |

## 2. `script-proxy` — 工作流对照（必须带限定语）

脚本：`scripts/bench_workflow.py`；原始结果：`logs/bench-workflow-20261029-095416.json`；
图表：`site/public/shots/bench-workflow.svg`；结论表：`BENCHMARK.md` §3。

**W1 上传多文档 → 定位技术问题 → 给出引用页（6 问）**

| 指标 | 基线（Ctrl-F 关键词扫描代理） | ResearchFlow（hybrid + 门控） |
| --- | --- | --- |
| 总耗时 | 0.0 ms（仅机器扫描，**不含人工阅读与核对**） | 909 ms（含 embedding、ANN、FTS、门控、引用组装） |
| 定位正确 top1 / top5 | 6/6 / 6/6 | 5/6 / 5/6 |
| 需人工修正 | 0 | 1（`w1-hnsw` 正确块排第 6，被 `top_k=5` 截断） |
| 产出可点引用 / 页级证据对象 | **0** | 5/6 |

**W2 记录进度 → 结束会话 → 恢复决策与 next_steps**

| 指标 | 基线（正则扫描手工笔记） | ResearchFlow（PowerContext 保存 + 跨进程恢复） |
| --- | --- | --- |
| 耗时 | 0.3 ms（正则扫描代理） | 保存 599 ms + 恢复 1988 ms = **2587 ms** |
| 字段恢复 | 5/7（笔记 fixture 故意漏记 D4、N3） | **7/7 逐字段精确相等** |
| 需人工修正 | 2 | 0 |
| 结构化 / 来源指针 / 跨会话恢复 | 否 / 否 / 否 | 是 / 是（doc_id+page_no+chunk_id） / 是（独立进程实测） |

**必须同时说明的三点**
1. 基线侧的「0 ms / 0.3 ms」是**下界代理**：真实人工要打开 PDF、逐页翻找、肉眼核对页码，
   该成本无法在本机自动测量，因此**没有虚构**。
2. 因此**不得**把这两组数字表述为「提效 X 倍」「节省 X 小时」。
   可主张的是：在同等可核对性上，代理基线**给不出任何页级证据对象**（0/6），
   而 ResearchFlow 给出 5/6 且逐条可点开回查。
3. W1 的 1 条失败与 B2 的 2 条「英文改写问中文原文」被默认阈值拦下，
   都是**如实保留的未通过项**，不是全部通过。

## 3. `human` — 目前有什么、缺什么

已有（可主张）：
- 开发者本人以真实语料自用：`demo/` 三份材料来自本项目研究过程中真实整理的
  seekdb 混合检索笔记（含手写期望值 `1/61+1/61=0.0328`，用于自校验页级引用是否对得上）。
  这是**开发者自用**，不是外部用户反馈。

缺失（不得声称）：
- **没有**外部真实用户试用记录、**没有**人工实测的耗时对照、**没有**用户满意度数据。
- 若要补齐，最低成本方案（见 `10-human-handoff.md` 第 5 项）：邀请 1–2 位同学/同事按
  `RUN.md` 用 10 分钟，保留**原始反馈文本 + 时间戳 + 操作录屏或截图**；
  不得由 Agent 代写、不得事后补记为「实测」。

## 4. 材料来源清单（评审可自行核对）

| 材料 | 位置 |
| --- | --- |
| 验收报告与逐用例日志 | `verification/acceptance-run/acceptance-report.md` / `.json` / `logs/` |
| 基准原始 JSON | `logs/bench-*.json`（仓库内保留最近一次；复跑即生成新的） |
| 真实运行截图（9 张） | `site/public/shots/`，由 `scripts/capture_screenshots.cjs` 无头浏览器采集 |
| 公开站点匿名验证 | `verification/site-public/PUBLISH_VERIFICATION.md` + `06-public-site-verification.md` |
| 演示视频与逐场景事实 | `submission-package/demo/`（`video-manifest.json` 记录采集方式与重放系数） |
| 开发过程记录 | `QODER_LOG.md` + `07-qoder-dev-evidence.md` |
