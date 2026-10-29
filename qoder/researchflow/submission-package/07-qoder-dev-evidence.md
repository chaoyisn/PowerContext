# 07 · Qoder 开发证据索引

本文件把 ResearchFlow 的开发过程映射到**已存在的真实记录**：Qoder 会话、Git 提交、日志与验收产物。
它不新增叙述，只做索引；每一条都能点开核对。

- 会话载体：Qoder Desktop 会话「开发科研任务连续性助手」（sessionId 前缀 `dc847bc1-…`，工作目录 `D:\OceanBase`）。
  三轮迭代（V1 实现 / V2 交付强化 / V3 封版）都在同一会话内连续进行。
- 逐时点开发日志：[`../QODER_LOG.md`](../QODER_LOG.md)（P0→P4 + V2 + V3，共 504 行，含每次失败与定位过程）。
- 提交序列：`git log --reverse d647275c..HEAD`（15 个提交，全部位于 `qoder/researchflow/`）。

---

## 1. 七类开发证据的落点

| # | 要求覆盖的主题 | 真实记录位置 | 可核对的产物 |
| --- | --- | --- | --- |
| 1 | 需求分析与任务拆解 | `QODER_LOG.md` §P0 仓库审计（01:05 基线确认 / 01:15 环境审计）；[`../PLAN.md`](../PLAN.md) P0–P4 阶段表 | 提交 `7b666fb1`（P0 audit） |
| 2 | 技术架构设计 | [`../ARCHITECTURE.md`](../ARCHITECTURE.md) §2 依赖可行性实测、§3 系统架构（ASCII 一图流）、§4 数据模型、§5 模块划分 | 提交 `7b666fb1`、`3682702b` |
| 3 | seekdb 集成开发 | `QODER_LOG.md` §P1（01:45 建表与集合 → 02:30 测试套件）；实测脚本 `scripts/probe_seekdb_capability.py` | 提交 `3682702b`；`logs/acceptance-20261029-100634/T2.log` |
| 4 | PowerContext 记忆开发 | `QODER_LOG.md` §P2（02:40 契约实测 → 03:05 跨会话恢复）；§V2 09:10 中文召回诊断 | 提交 `3682702b`、`eec43693`；`T5/T6/T7.log` |
| 5 | Bug 修复与调试 | `QODER_LOG.md` 01:35 控制台中文乱码、02:20 两个真实 bug、02:50 闭包变量 bug、03:15 启动期缺陷、04:00 性能问题；V2 09:30 SDK 层过滤绕过 | 对应修复提交与回归测试（`backend/tests/test_seekdb_integration.py`、`test_security.py`） |
| 6 | 自动化测试与验收 | [`../VERIFICATION.md`](../VERIFICATION.md)（T1–T9 逐条输入/期望/实际）；`verification/acceptance-run/`；`logs/pytest-*.log` | 9 用例 / 150 项校验全 PASS；`149 passed` |
| 7 | Qoder Sites 发布过程 | [`../SITE_DEPLOYMENT.md`](../SITE_DEPLOYMENT.md) §2.3 实际参数、§5 真实结果；`QODER_LOG.md` V2 09:00（阻塞如实记录）与 V3 10:40（解除并发布） | 提交 `a1a84e8e`、`ff67da60`；[`../verification/site-public/PUBLISH_VERIFICATION.md`](../verification/site-public/PUBLISH_VERIFICATION.md) |

> 补充：安全审计（`../SECURITY.md` 9 个领域）、性能与提效基准（`../BENCHMARK.md` + `logs/bench-*.json`）、
> 全新环境复现（`logs/fresh-env-20261029-222030.json`，23/23；同日 09:44 那次为 22/22）。

---

## 2. 需要人工截取的 Qoder 对话（精确定位）

以下 8 张图**只能由本人在 Qoder Desktop 界面截取**：Agent 无法截图自己的对话窗口，
也**不得**用 Git 提交记录或本文档冒充对话截图。定位方式：打开上述会话，
在会话内搜索「定位关键词」，滚动到首次命中的消息。

| 编号 | 主题 | 会话内定位关键词（原文片段） | 截图目标（画面必须包含） | 建议文件名 |
| --- | --- | --- | --- | --- |
| Q1 | 需求分析与拆解 | `科研知识与任务连续性助手` | 首轮提问全文 + Agent 给出的 P0–P4 阶段计划 | `qoder-01-requirements.png` |
| Q2 | 架构设计 | `系统架构` 或 `数据模型` | Agent 输出架构图/数据模型的消息气泡 | `qoder-02-architecture.png` |
| Q3 | seekdb 集成 | `rf_chunks` 或 `建表与集合` | 真实建集合、写入与检索的工具调用与返回 | `qoder-03-seekdb.png` |
| Q4 | PowerContext 记忆 | `idempotency_key` | 契约实测的工具输出（幂等/非幂等差异） | `qoder-04-powercontext.png` |
| Q5 | Bug 定位与修复 | `两个真实 bug` 或 `闭包变量` | 失败测试输出 + 修复后的通过输出（同屏最佳） | `qoder-05-bugfix.png` |
| Q6 | 自动化测试与验收 | `run_acceptance` 或 `150` | 终端里 `149 passed` 与 `T1–T9 9/9 PASS` 的真实输出 | `qoder-06-tests.png` |
| Q7 | Sites 发布 | `sites_unavailable` 与 `confirmPublic` | 阻塞时的错误码消息 + 发布成功后返回的 URL | `qoder-07-sites-blocked.png` / `qoder-07-sites-published.png` |
| Q8 | 交付纪律（禁止伪造） | `不得伪造` | 用户提出的诚实约束原文（证明证据口径由人设定） | `qoder-08-honesty-rules.png` |

**完成判断标准**：每张截图能看到 Qoder Desktop 的界面外壳（会话标题栏或输入框），
且画面内包含上表「截图目标」列的文字；文件名与上表一致，放入
`submission-package/qoder-evidence/`（需先创建该目录）。

**截图前必须检查**：画面中不得出现完整 Qoder UID、API Key、`.env` 内容或他人会话内容。
若工具输出里带了密钥字段，用画板遮盖后再保存。

---

## 3. 时间线（真实提交时刻）

| 时刻 | 提交 | 内容 |
| --- | --- | --- |
| 01:37 | `7b666fb1` | P0 基线审计（含不可改动资产红线） |
| 02:41 | `3682702b` | seekdb 证据库 + PowerContext 任务记忆 |
| 03:31 | `f2bf83ba` | 证据问答、HTTP API、四页工作台 |
| 03:45 | `e1e79cea` | P4 交付：验收证据、运行手册、Sites 可行性 |
| 08:54 | `a1a84e8e` | 比赛展示站（真实截图与真实验证数据） |
| 09:26 | `eec43693` | 中文记忆召回、跨语言 embedding、安全加固 |
| 10:01 | `3ffda476` | B/C/D：中文召回、跨语言基准、安全与工作流测量 |
| 10:12 | `ad91dd1e` | V2 交付文档与证据刷新 |
| 10:32 | `63cea54c` | 清理运行期凭据与个人信息 |
| 10:35 | `3d615a08` | 推送前检查结论与待授权方案 |
| 10:54 | `ff67da60` | 展示站正式发布并公开访问 |
| 11:09 | `d2b53ce9` | V3 交付材料（演示脚本、提交清单） |
| 11:20 | `2e0e61cc` | 历史清理执行记录与最终质检 |
| 11:32 | `4221081a` | 回填推送结果 |
| 11:42 | `2fce2615` | 推送结论改为不随回填过期的口径 |

> 本轮（V3 封版）新增的提交以 `git log --oneline d647275c..HEAD` 为准；
> 上表只列到封版前最后一次已推送提交，避免写死会随回填变化的 tip。
