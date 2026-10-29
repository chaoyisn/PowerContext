# SUBMISSION.md — 比赛最终提交材料清单

提交对象：OceanBase × Qoder 2026 数据库比赛 · Qoder 赛道 · ResearchFlow
分支：`2026-competition-ecosystem`（基线 `d647275c308e09b7b623f322a26f5c4e85734fb0`）
代码与材料位置：`qoder/researchflow/`

---

## 1. 仓库内材料（已提交，评审可直接核对）

| 材料 | 路径 | 内容 |
| --- | --- | --- |
| 项目介绍与卖点 | `README.md` | 定位、功能、架构一图流、快速开始、诚实声明 |
| 部署与演示 | `RUN.md` | Windows 与 Linux/WSL 启动命令、演示流程、验证命令、故障表 |
| 验证证据 | `VERIFICATION.md` | seekdb / PowerContext 真实使用证据、T1–T9、限制清单、Sites 可行性 |
| 验收原始记录 | `verification/acceptance-run/` | 报告 md/json + 9 个用例日志 + 服务日志（随仓库提交） |
| 架构 | `ARCHITECTURE.md` | 基线审计、数据模型、门控标定、运行期实测补充、Sites 边界 |
| 基准 | `BENCHMARK.md` | B1 中文记忆 / B2 中英检索 / D 工作流提效，含方法与原始数据位置 |
| 安全 | `SECURITY.md` | 15 项审计结论、SDK 层过滤绕过缺陷的实测与修复、公网前置条件 |
| 站点部署 | `SITE_DEPLOYMENT.md` | Sites 能力复核、阻塞证据、重试参数、发布步骤、匿名验证清单 |
| 开发日志 | `QODER_LOG.md` | P0–P4 与 V2 全过程、踩坑与修复、人工截图取证清单 |
| 计划 | `PLAN.md` | 分阶段计划与验收映射（已全部勾选完成） |
| 配置 | `.env.example` | 全部配置项与安全占位值，含多语 embedding 与阈值标定说明 |
| 比赛网站 | `site/public/` | 静态展示站：真实截图、真实验证数据、基准图表、体验边界说明 |
| 演示语料 | `demo/` | 多页 PDF（含空白页）、Markdown 研究计划、结构化实验记录、手工进度笔记 |
| 测试 | `backend/tests/` | 149 个测试：单元 / seekdb 集成 / PowerContext 集成 / 安全 / 保留集 / 中文记忆 |
| 脚本 | `scripts/` | 能力探针、冒烟、种子、截图、站点数据、三项基准、全新环境复现、验收运行器 |

## 2. 关键可复现命令

```bash
cd backend && python -m pytest tests/ -q          # 149 passed
python scripts/run_acceptance.py                  # T1-T9，150 项校验
python scripts/fresh_env_e2e.py                   # 全新环境 20/20 步
python scripts/bench_memory_zh.py                 # B1
python scripts/bench_retrieval.py                 # B2
python scripts/bench_workflow.py                  # D
python scripts/capture_screenshots.cjs            # 网站真实截图
python scripts/build_site_data.py && python scripts/verify_site.cjs   # 站点数据与渲染验证
```

## 3. 核心主张与对应证据

| 主张 | 证据 |
| --- | --- |
| seekdb 真实写入与混合检索 | T1/T2 日志；`probe_seekdb_capability.py`；RRF 0.0328 与文档手写值一致 |
| 页级证据可回查、不伪造页码 | T1 空白页身份行；T2 引用逐条回查；不存在页 404 |
| 无答案不伪造 citation | T3；安全测试注入用例；门控标定数据 |
| PowerContext 真实写入与跨会话恢复 | T4/T5；全新环境复现第 8–9 步（独立进程恢复） |
| 两后端职责分离、可独立断开 | T7/T8 日志（断连后各自行为） |
| 中文记忆检索增强有效 | B1 前后对比（6/10 → 10/10，负例 1 → 0） |
| 跨语言检索能力有实测边界 | B2 两轮阈值表 + 相似度实测 |
| 公开部署不伪造 | SITE_DEPLOYMENT.md：`sites_unavailable` 三次实测 + 权限分类器拦截记录 |

## 4. 需要人工补充的材料（Agent 无法代为完成）

1. **Qoder UID / 账号信息**：用于报名表与作品归属（当前仅知 creator_uid
   `<REDACTED-QODER-UID>`，来自本地遥测，需以账号页为准）。
2. **Sites 权益核验与发布**：在 Qoder Desktop 中确认账号的 Sites 服务状态；恢复后按
   `SITE_DEPLOYMENT.md` §4 执行 prepare → publish；**切换公开访问前需本人确认**。
3. **仓库推送**：`git push origin 2026-competition-ecosystem`（当前 6 个新提交仅在本地；
   推送属共享状态变更，需本人执行或明确授权）。
4. **演示视频**：建议录制 3–5 分钟，覆盖「上传 → 检索 → 页级引用 → 保存进度 → 新会话恢复」；
   分镜可直接用 `QODER_LOG.md` 末尾的 15 项截图清单。
5. **开发过程截图**：Qoder 对话窗口、测试运行终端、浏览器四页面（清单同上）。
6. **公开访问证明**：发布后截图匿名浏览器打开真实 URL 的画面。
7. **真实用户反馈**：如邀请同学/同事试用，请保留原始反馈文本与时间；**不得由 Agent 代写**。

## 5. 提交前自检（Agent 已完成部分）

- [x] 分支与基线正确，改动仅限 `qoder/researchflow/**`
- [x] 无密钥/凭据进入仓库（每次提交前扫描）
- [x] 无 Mock 冒充真实能力（所有数字来自运行产物）
- [x] 测试与验收全部真实执行，失败项如实记录（B2 的 2 条未覆盖正例、W1 的 1 条排序失败）
- [x] 其他赛题目录与 worktree 零改动（`git status` 逐 worktree 核对）
- [ ] Sites 公开发布（阻塞中，见 SITE_DEPLOYMENT.md）
- [ ] 仓库推送（待授权）
