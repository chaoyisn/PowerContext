# FINAL_SUBMISSION.md — ResearchFlow 参赛封版入口

OceanBase × Qoder 2026 数据库比赛 · Qoder 赛道
作品目录：`qoder/researchflow/` ｜ 在线展示站：<https://researchflow-5esfsogn38f.qoder.zone>

> 本文件是提交包的**唯一入口**。其余文档按编号阅读；`AUDIT.md` 是封版审计结论。
> 所有数字都来自真实运行产物，可按 `../RUN.md` 复现；三类证据（自动化 / 脚本代理 / 人工）
> 在所有文档中强制分级，未通过项如实保留。

---

## 1. 30 秒定位

ResearchFlow = **带证据的科研知识库（seekdb）** + **长期任务记忆（PowerContext）**。
它回答两个问题：**AI 给的结论能不能回查原文**，以及**换一个会话以后研究进度还在不在**。
两者被做成两个可独立断开的存储通道，并且「断了会怎样」本身是验收用例（T7 / T8）。

## 2. 提交包索引

| 文件 | 内容 |
| --- | --- |
| `FINAL_SUBMISSION.md` | 本入口 |
| `01-overview-and-highlights.md` | 项目介绍、真实痛点、亮点、规模、边界 |
| `02-run-and-reproduce.md` | 最短运行路径、复现命令、必须避开的坑 |
| `03-evidence-seekdb.md` | seekdb 真实读写与检索证据（版本、索引、页级身份、RRF） |
| `04-evidence-powercontext.md` | PowerContext 真实记忆写入与跨会话恢复证据 |
| `05-acceptance-index.md` | T1–T9 结果、150 项校验、逐用例日志索引 |
| `06-public-site-verification.md` | 发布链路、匿名可达性、线上资源与数据核验 |
| `07-qoder-dev-evidence.md` | Qoder 开发证据索引（7 个领域 + 8 张人工截图定位） |
| `08-demo-video.md` | 演示视频规格、8 个必答点映射、逐场景时长与溯源 |
| `09-usage-impact-sources.md` | 真实使用效果材料与来源（三类证据分级） |
| `10-human-handoff.md` | 只剩 5 项的人工交接（步骤 / 存放位置 / 完成标准） |
| `11-v3-requirement-matrix.md` | 本轮 V3 简报逐条要求 → 交付物对照 |
| `AUDIT.md` | 封版交付审计 10 项检查的真实输出 |
| `demo/researchflow-demo.mp4` | 演示视频成片（1280×800、2:05、6.2 MB） |
| `demo/researchflow-demo.vtt` | 字幕轨（24 条，与旁白逐句一致） |
| `demo/video-manifest.json` | 逐场景采集方式、真实耗时、重放系数与读回数字 |

## 3. 六项交付状态

| # | 项 | 状态 |
| --- | --- | --- |
| 1 | Git | 分支 `2026-competition-ecosystem`；本地 HEAD 与 `origin` 一致；全部 fast-forward 推送，无 force。当前 tip 以 `git rev-parse origin/2026-competition-ecosystem` 为准（本文不写死） |
| 2 | 站点 | 已正式发布且 `mode=public`；封版复核：curl 全 200（首页 72818B 与发布当时逐字节一致）、无头浏览器 `failed requests (>=400): 0` |
| 3 | 视频 | **已自动生成**（真实产品录屏 + 中文合成配音 + 烧录字幕），2:05；真人配音为可选覆盖 |
| 4 | 提交包 | `qoder/researchflow/submission-package/`（14 个文件 + `demo/` 3 个产物） |
| 5 | 比赛要求 | 通用 12 项：11 项完成、1 项（真实使用效果）为「部分」且缺口已标注；本轮逐条见 `11-v3-requirement-matrix.md` |
| 6 | 待人工 | 8 张 Qoder 对话截图、报名平台完整 UID、平台最终提交、（可选）真人配音与真实用户反馈 —— 全在 `10-human-handoff.md` |

## 4. 一键复现（评审路径）

```bash
# 启动三进程 + 灌演示数据：见 02-run-and-reproduce.md §2
cd backend && .venv/Scripts/python -m pytest tests/ -q      # 期望 149 passed
cd .. && backend/.venv/Scripts/python scripts/run_acceptance.py   # 期望 T1–T9 全 PASS
backend/.venv/Scripts/python scripts/fresh_env_e2e.py       # 期望 20/20
```

## 5. 诚实声明

1. 在线站点是**纯静态展示版**：不连 seekdb、不连 PowerContext、不提供任何模拟查询；
   完整体验需在本地按 `RUN.md` 启动。
2. 工作流提效数字（W1 / W2）是**脚本代理测量**，不是真实用户实测，**不得**表述为「提效 X 倍」。
3. 未配置 LLM key 时问答进入明确标注的「仅检索模式」，不会把检索摘要冒充模型回答。
4. 已知未通过项保留：B2 有 2 条「英文改写问中文原文」在默认阈值下被门控拦下；
   W1 有 1 条排序不符预期（正确块排第 6，被 `top_k=5` 截断）。
5. 演示视频中的两张文本卡是**日志回放**（卡片上已注明），其余场景是真实运行的浏览器录屏；
   录屏按旁白时长等比重放，系数逐场景记录在 `demo/video-manifest.json`，未删除或跳剪任何真实步骤。
6. 不含完整 Qoder UID、API key 或内部数据；后端不对公网暴露（PowerContext 无多用户鉴权）。
7. V2 期间 `prepare_site` 三次返回 `sites_unavailable` 的**失败记录同样保留**在
   `SITE_DEPLOYMENT.md`，未伪造任何发布状态。
