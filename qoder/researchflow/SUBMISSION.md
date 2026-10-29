# SUBMISSION.md — 比赛最终提交材料清单

提交对象：OceanBase × Qoder 2026 数据库比赛 · Qoder 赛道 · ResearchFlow
分支：`2026-competition-ecosystem`（基线 `d647275c308e09b7b623f322a26f5c4e85734fb0`）
远端已推送并核对一致：全部提交均为 fast-forward 推送（未使用 `--force`），
最近一次核对时本地 HEAD 与 `origin/2026-competition-ecosystem` 完全一致。
推送过程的逐次记录见 `PUSH_PRECHECK.md` §3 与 `QODER_LOG.md` V3 日志；
当前远端 tip 请随时以 `git rev-parse origin/2026-competition-ecosystem` 为准。
代码与材料位置：`qoder/researchflow/`
**在线展示站（已正式发布、公开访问）**：<https://researchflow-5esfsogn38f.qoder.zone>

---

## 1. 仓库内材料（评审可直接核对）

| 材料 | 路径 | 内容 |
| --- | --- | --- |
| 项目介绍与卖点 | `README.md` | 定位、功能、架构一图流、快速开始、诚实声明、线上站点入口 |
| 部署与演示 | `RUN.md` | Windows 与 Linux/WSL 启动命令、演示流程、验证命令、基准与站点预览、故障表 |
| 验证证据 | `VERIFICATION.md` | seekdb / PowerContext 真实使用证据、T1–T9、限制清单、Sites 可行性 |
| 验收原始记录 | `verification/acceptance-run/` | 报告 md/json + 9 个用例日志 + 服务日志（随仓库提交） |
| 站点发布记录 | `verification/site-public/` | 发布验证记录 + 未登录状态采集的线上整页截图（桌面/移动） |
| 架构 | `ARCHITECTURE.md` | 基线审计、数据模型、门控标定、运行期实测补充、Sites 边界 |
| 基准 | `BENCHMARK.md` | B1 中文记忆 / B2 中英检索 / D 工作流提效，含方法与原始数据位置 |
| 安全 | `SECURITY.md` | 15 项审计结论、SDK 层过滤绕过缺陷的实测与修复、公网前置条件 |
| 站点部署 | `SITE_DEPLOYMENT.md` | Sites 能力复核、真实发布结果（URL/访问策略/操作 ID）、匿名验证清单 |
| 演示视频脚本 | `DEMO_SCRIPT.md` | 2–3 分钟分镜、逐句旁白稿、录制步骤、关键帧清单、人工移交项 |
| 推送前检查 | `PUSH_PRECHECK.md` | 远端分叉核对、敏感内容扫描结论与处理方案 |
| 开发日志 | `QODER_LOG.md` | P0–P4、V2、V3 全过程、踩坑与修复、人工截图取证清单 |
| 计划 | `PLAN.md` | 分阶段计划与验收映射 |
| 配置 | `.env.example` | 全部配置项与安全占位值，含多语 embedding 与阈值标定说明 |
| 比赛网站 | `site/public/` | 静态展示站源文件：真实截图、真实验证数据、基准图表、体验边界说明 |
| 演示语料 | `demo/` | 可复现样例：多页 PDF（第 4 页刻意留空）、Markdown 研究计划、结构化实验记录、手工进度笔记 |
| 测试 | `backend/tests/` | 149 个测试：单元 / seekdb 集成 / PowerContext 集成 / 安全 / 保留集 / 中文记忆 |
| 脚本 | `scripts/` | 能力探针、冒烟、种子、截图、站点数据、站点验证、三项基准、全新环境复现、验收运行器 |

## 2. 关键可复现命令

```bash
# 注意：一律使用项目 venv，不要用系统 / Anaconda base 的 python（base 会 ModuleNotFoundError）
cd backend && .venv/Scripts/python -m pytest tests/ -q   # 149 passed
cd ..
backend/.venv/Scripts/python scripts/run_acceptance.py    # T1-T9，150 项校验
backend/.venv/Scripts/python scripts/fresh_env_e2e.py     # 全新环境 23/23 步
backend/.venv/Scripts/python scripts/bench_memory_zh.py   # B1 中文记忆召回
backend/.venv/Scripts/python scripts/bench_retrieval.py   # B2 中英混合检索
backend/.venv/Scripts/python scripts/bench_workflow.py    # D 工作流（脚本代理）
NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" \
  node scripts/capture_screenshots.cjs                    # 网站真实截图
backend/.venv/Scripts/python scripts/build_site_data.py   # 站点数据（由真实产物导出）
NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" \
  node scripts/verify_site.cjs https://researchflow-5esfsogn38f.qoder.zone/ <outDir>   # 线上站点验证
NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" \
  node scripts/make_demo_video.cjs                        # 重新生成演示视频
```

## 3. 核心主张与对应证据

| 主张 | 证据 | 来源类型 |
| --- | --- | --- |
| seekdb 真实写入与混合检索 | T1/T2 日志；`probe_seekdb_capability.py`；RRF `0.0328` 与文档手写值一致 | 自动化 |
| 页级证据可回查、不伪造页码 | T1 空白页身份行；T2 引用逐条回查；不存在页 404 | 自动化 |
| 无答案不伪造 citation | T3；`test_security.py` 注入用例；门控标定数据 | 自动化 |
| PowerContext 真实写入与跨会话恢复 | T4/T5；全新环境复现第 8–9 步（独立进程恢复） | 自动化 |
| 两后端职责分离、可独立断开 | T7/T8 日志（断连后各自行为） | 自动化 |
| 中文记忆检索增强有效 | B1：PowerContext 原生 6/10（负例误报 1/1）→ 本地 CJK 召回 hit@3 10/10（负例误报 0/1） | 自动化 |
| 跨语言检索能力有实测边界 | B2 两轮阈值表 + 相似度实测（多语 0.79–0.81 vs 默认 0.17–0.44） | 自动化 |
| 站点已真实发布并公开访问 | `SITE_DEPLOYMENT.md` §5 + `verification/site-public/PUBLISH_VERIFICATION.md`（`published=true`、`access_mode=public`、未登录 curl 200、无头浏览器 0 个 ≥400 请求） | 自动化 + 人工授权 |
| 发布过程不伪造 | V2 期间 `sites_unavailable` 三次实测与权限分类器拦截记录同样保留在 `SITE_DEPLOYMENT.md` §1/§5 | 自动化 |
| 工作流提效 | D：W1/W2 对照实验（见 §5 与 `BENCHMARK.md` §3） | **脚本代理** |

## 4. 数据来源与标注口径

每一项测试/测量数据都归入下列三类之一，**不得混用**：

| 标注 | 含义 | 本项目对应内容 |
| --- | --- | --- |
| **自动化** | 由 pytest / 验收运行器 / 基准脚本对**真实** seekdb 与**真实** PowerContext 执行并断言，输出可复现 | 149 个测试；T1–T9 共 150 项校验；全新环境 23/23；B1、B2 基准；站点渲染与资源加载验证 |
| **脚本代理** | 用脚本模拟人工判读（关键词扫描、邮件式扫描）得到的对照数据，**不是真实用户实测** | D 工作流基准 W1/W2 的「基线」与「ResearchFlow」两侧耗时与正确率 |
| **人工** | 需要真人操作或真人判断，Agent 不代做、不代写 | Qoder 对话与开发过程截图、账号 UID 核验、真实用户反馈、公开访问授权；（可选）真人配音覆盖自动成片 |

关于 D 工作流基准的强制口径：**脚本代理结果不得表述为真实用户提效结论。**
可表述为「在与人工无关的脚本代理对照中，ResearchFlow 侧的引用完整性与恢复精确度更高」，
并同时给出 caveat（`BENCHMARK.md` §3 与网站基准区块均已标注）。原始数字：

- W1（问答取证，6 题）：基线正确 6/6 但引用对象 0 条；ResearchFlow top1 5/6、top5 5/6、带引用 5/6、总耗时 909.1ms。
- W2（进度恢复，7 项）：基线恢复 5/7、需 2 次人工纠正、结构不完整；ResearchFlow 7/7 精确、0 次纠正、总耗时 2586.8ms（独立进程恢复）。
- 已知失败项如实保留：W1 有 1 条排序不符预期；B2 有 2 条「英文改写问中文原文」在默认阈值下被门控拦下。

## 5. 提交包完整性清单（逐项）

| # | 提交要求 | 状态 | 位置 / 说明 |
| --- | --- | --- | --- |
| 1 | Git 仓库与提交 SHA | ✅ 已完成 | 分支 `2026-competition-ecosystem` 已推送基线之后的全部交付提交（逐次 fast-forward，无 force）；每次推送后核对本地 HEAD 与远端 tip 一致；历史中的运行期凭据与完整 UID 已按授权方案清除，核对与推送记录见 `PUSH_PRECHECK.md` |
| 2 | Sites 站点 URL | ✅ 已完成 | <https://researchflow-5esfsogn38f.qoder.zone>，`published=true`、`access_mode=public`、`lifecycle=active`；21:46 已按简化后的最终构建**更新发布到同一 project / 同一域名**（未新建替代站点、未改访问权限） |
| 3 | README / RUN / VERIFICATION | ✅ 已完成 | 三份文档齐备并互链；README 顶部给出线上入口 |
| 4 | seekdb 与 PowerContext 真实使用证据 | ✅ 已完成 | `VERIFICATION.md`、`verification/acceptance-run/`（含 9 个用例日志与服务日志）、`ARCHITECTURE.md` 运行期实测补充 |
| 5 | Qoder 对话截图与 UID | ❌ 缺（人工） | 需本人补：Qoder 对话窗口截图；完整 UID 属个人信息不入库，以账号页截图作为归属证明 |
| 6 | 演示视频 | ✅ 已生成（自动） | `submission-package/demo/researchflow-demo.mp4`（1280×800、**135.0 s / 6.5 MB**，2026-10-29 22:21 定稿：界面简化 + 站点重新发布之后重录，展示站两个场景直接录自线上地址）：Playwright 无头浏览器录制的真实产品流程 + 真实日志卡 + 中文配音 + 烧录字幕；`video-manifest.json` 记录每个场景的采集方式、真实耗时与重放系数，`video-check.json` 是对**成片文件**执行的 25 项自动检查（全 PASS），`demo/keyframes/` 是逐场景自动抽取的 11 张关键帧。分镜与旁白稿仍在 `DEMO_SCRIPT.md`（如需真人配音可覆盖重录） |
| 7 | 测试报告 | ✅ 已完成 | 149 pytest（自动化）、T1–T9 150 项校验（自动化）、全新环境 23/23（自动化）、B1/B2/D 基准（D 为脚本代理） |
| 8 | 可复现样例 | ✅ 已完成 | `demo/` 四份语料 + `scripts/seed_demo.py` + `scripts/fresh_env_e2e.py`（全新 venv/容器/数据目录，23/23，结束自动清理） |
| 9 | 真实使用效果 | ⚠️ 部分 | 已有：自动化验收与脚本代理对照（口径见 §4）。缺：真实人工使用的耗时/纠错记录 |
| 10 | 用户反馈 | ❌ 缺（人工） | 不得由 Agent 代写；如邀请试用，请保留原始反馈文本与时间 |
| 11 | 公开访问证明 | ✅ 已完成 | `verification/site-public/site-desktop.png`、`site-mobile.png`（未登录、无 cookie 的无头浏览器采集）+ `PUBLISH_VERIFICATION.md` 逐项清单 + `published-site-check.json`（15/15 文件与本地最终构建一致） |
| 12 | 安全说明 | ✅ 已完成 | `SECURITY.md`：15 项审计、SDK 层过滤绕过缺陷的实测与修复、公网部署前置条件与残余风险 |

### 5.1 封版终审新增的交付物（不属于官方 12 项，为「能直接报名 + 能复核」而做）

| 产物 | 位置 | 实测 |
| --- | --- | --- |
| 报名表可直接复制文本 | `submission-package/FORM_FIELDS.md` | A 作品信息 / B 访问与代码 / C 运行与验证 / D Qoder 证明 / E 视频与使用效果，每条都是成品段落，含「必须一并粘贴的展示模式声明」与「不要填的东西」 |
| 上传清单 | `submission-package/FILES_TO_UPLOAD.md` | 视频与 ZIP 的绝对路径 / 字节 / SHA-256、ZIP 逐目录文件数、**逐条排除理由**、隐私终检三条命令 |
| 六阶段终审 | `submission-package/FINAL_AUDIT.md` | 阶段一～六逐条结论 + 真实命令输出 + 五方同步矩阵 + 保留的未通过项与失败记录 |
| 只剩人工的 6 项 | `submission-package/MANUAL_ONLY.md` | 按「是否阻塞报名」排序，每项含在哪做 / 做什么 / 完成标准 |
| 最终上传 ZIP | `D:\OceanBase\deliverables\researchflow-final\`（Git 之外） | 303 成员 ≈32.75 MB；凭据与本机路径扫描 0 命中；解压回临时目录逐字节核对 `missing/differing/unexpected = 0/0/0`；`.sha256` 与 `final-zip-manifest.json` 写在 ZIP **外部**（压缩包不含自身校验和） |

## 6. 需要人工补充的材料（Agent 无法代为完成）

逐条含「在哪做 / 做什么 / 完成标准」的版本见 `submission-package/MANUAL_ONLY.md`；
下面只列要点。

1. **演示视频（可选覆盖）**：成片已由 `scripts/make_demo_video.cjs` 自动生成（真实浏览器录屏 +
   Windows 中文语音配音 + 烧录字幕）。若希望改为**真人配音**，按 `DEMO_SCRIPT.md` §1–§3 录制，
   旁白中的数字与结论不得改动；否则本项无需人工操作。
2. **Qoder 对话与开发过程截图**：`QODER_LOG.md` 末尾 15 项清单 + `DEMO_SCRIPT.md` §4 的 8 项关键帧。
3. **Qoder UID / 账号信息**：本地遥测中可见 `creator_uid`（前缀 `01a175e3-…`）；完整 UID 属个人信息，
   **不写入公开仓库**，请在 Qoder Desktop 账号页确认后填入报名表，并以截图作为归属证明。
4. **真实用户反馈与人工使用效果**：如邀请同学/同事试用，保留原始反馈文本、时间与操作记录。
5. ~~**仓库推送**~~ ✅ 已完成：已获授权按 `PUSH_PRECHECK.md` §2 方案 A 执行
   （改写 13 个未推送提交后正常 fast-forward 推送，无 force），每次推送后远端 tip
   与本地 HEAD 核对一致；后续回填提交同样为 fast-forward。

## 7. 提交前自检

- [x] 分支与基线正确，改动仅限 `qoder/researchflow/**`（其他赛题目录与 worktree 零改动）
- [x] HEAD 树无密钥/凭据/个人 UID；`.gitignore` 已补齐运行期产物与站点描述符规则
- [x] 历史中的运行期凭据与完整 UID 已按授权方案清除（`filter-branch --index-filter`，
      逐提交扫描零命中；最终内容与清除前逐字节一致；核对与推送记录见 `PUSH_PRECHECK.md`）
- [x] 无 Mock 冒充真实能力（所有数字来自真实运行产物；脚本代理数据单独标注）
- [x] 测试与验收全部真实执行，失败项如实记录（B2 的 2 条未覆盖正例、W1 的 1 条排序失败）
- [x] Sites 已正式发布并公开访问，发布与验证证据随仓库提交，未伪造任何发布状态
- [x] 在线展示站不含任何模拟查询，体验边界在页面与文档中明确标注
- [x] 仓库推送：基线之后的交付提交全部 fast-forward 推送，远端 tip 与本地一致，`master` 未被触碰
- [x] 演示视频：已由真实运行的产品录屏自动生成（`submission-package/demo/`，含逐场景事实清单）
- [ ] 开发过程截图、UID、真实用户反馈（人工项，见 §6）
