# 08 · 演示视频（最终成片）与素材清单

**当前成片为 2026-10-29 22:21 定稿的版本**：11 个场景在同一次真实运行里采集，
展示站场景（c2 / c10）**直接录自已发布的线上地址**，旁白口径统一为「已正式发布」。
历史版本：13:33 那版（界面重构前）仍在 HEAD `fe8c14c7` 里可取回
（`git show HEAD:qoder/researchflow/submission-package/demo/researchflow-demo.mp4`）；
20:36 的中间版只存在于本地工作树，已被本次覆盖，未单独提交。

| 项 | 值 |
| --- | --- |
| 成片 | `submission-package/demo/researchflow-demo.mp4` |
| 大小 | **6 796 164 B（6.5 MB）** |
| 时长 | **134.97 s（2 分 15 秒）**，4 046 帧 |
| 规格 | 1280×800、H.264 High / yuv420p、30 fps、AAC 48 kHz 立体声 |
| 字幕 | 烧录进画面 + 独立轨道 `researchflow-demo.vtt`（28 条，与旁白逐句一致） |
| 溯源 | `video-manifest.json`：逐场景采集方式、真实耗时、重放系数与全部读回数字 |
| 自动检查 | `video-check.json`：**25 项全 PASS**（解码无错、音画差 0.028 s、字幕覆盖 0.89、11 场景、11 关键帧、线上可达且与本地构建一致） |
| 关键帧 | `demo/keyframes/01-c1-intro.png … 11-c11-outro.png`（从成片逐场景中点抽帧，路径写进 manifest） |
| 生成 | `node scripts/make_demo_video.cjs --force-record`（全量重录）；本次定稿用 `--no-pytest` 复用 22:01 的真实 pytest 输出与 22:03 的录屏 |

**采集方式（manifest `captureMethod` 原文口径）**
- 浏览器场景（c3–c8）：Playwright 无头浏览器录屏，驱动真实运行的前端 + FastAPI + seekdb + PowerContext
  （本地地址 `http://127.0.0.1:8787`）。
- 展示站场景（c2 / c10）：**录自公开 URL `https://researchflow-5esfsogn38f.qoder.zone`**，
  即评审实际打开的那个站点。该站点 21:46 已按简化后的最终构建更新发布，
  与本地 `site/public` 逐文件哈希一致（`verification/site-public/published-site-check.json`，15/15）。
  这条来源写进了 `sources.showcaseScenesRecordedFrom` 与 `sources.publishedSiteNote`。
- 文本卡场景（c1 / c9 / c11）：由当次真实命令输出原样渲染（**日志回放，非屏幕录制**，卡片页脚已注明）。
- 旁白：Windows `System.Speech` 中文语音（Microsoft Huihui）合成；
  **旁白里的数字是本次录制从页面读回的真实值**，不是预先写死的稿子。
- 重放：录屏按旁白时长用 `setpts` 等比重放（短片段放慢、长片段适度加速，
  系数 0.858–2.5 逐场景记录在 `speedFactor`），**未删除或跳剪任何真实步骤**。

---

## 1. 八个必答覆盖点 → 场景映射

| 要求 | 场景 | 画面中真实出现的证据（本次运行读回） |
| --- | --- | --- |
| 1 项目介绍与真实科研痛点 | c1-intro（卡）+ 旁白 | 定位与两个痛点（能否回查原文 / 换会话进度还在不在） |
| 2 上传 PDF 经 seekdb 真正入库 | c3-upload | 健康条 `5.7.25-OceanBase seekdb-v1.4.0.0`、`ik`、`文档 3 · 页 7 · chunks 13`、去重提示 |
| 3 向量 / 全文 / RRF 混合检索 | c4-retrieval | 三模切换、`score 0.4407 余弦相似度`、`score 0.0328 RRF 融合分`、三列并排 + 按 chunk_id 的重叠分析 |
| 4 通过 citation 查看 PDF 真实来源页 | c5-pages + c6-workbench | 第 4 页 `page_id …:p0004 char_count 0` 空白页身份；第 5 页 `…:p0005 char_count 847` 原文；引用编号点开同一页 |
| 5 PowerContext 保存决策与进度 | c7-memory | 本次同一条计划命中幂等：`written=0`、`skipped_duplicates=2`，再次保存提示「内容未变化，未产生重复记忆」 |
| 6 新建会话恢复决策与 next_steps | c8-restore（**全新浏览器上下文**） | 续研简报含上一轮保存的那条 next_step；恢复 18 条记忆；标注来源为历史记忆而非文献证据 |
| 7 技术架构与真实测试结果 | c9-tests（卡：`149 passed in 55.21s` 原样回放 + 浏览器交互验收 `30/30` + 全新环境复现 `23/23 步`）+ c10-arch | 站点架构区块与验证区块（`149 passed`、`9 / 9 PASS`） |
| 8 展示站与已发布站点 | c2-site + c10-arch + c11-outro | 画面即线上地址上当前的简化后构建；片尾卡写明站点 host 与「已正式发布」 |

界面简化本身在 c6 有一段口播与画面：提问框默认只有**上传 / 检索方式 / 选项**三个控件，
`project_id`、`top_k`、门控等收进「选项」，非默认值直接写在按钮上（画面里是折叠态的干净输入条）。

## 2. 逐场景时长与真实操作耗时

| 场景 | 类型 | 成片 | 真实操作耗时 | 重放系数 |
| --- | --- | --- | --- | --- |
| c1-intro | 卡 | 8.50s | — | — |
| c2-site | 浏览器（线上） | 11.40s | 3.74s | 2.5 |
| c3-upload | 浏览器 | 13.87s | 4.79s | 2.5 |
| c4-retrieval | 浏览器 | 13.88s | 8.95s | 1.528 |
| c5-pages | 浏览器 | 12.30s | 8.77s | 1.405 |
| c6-workbench | 浏览器 | 17.73s | 19.36s | 0.858 |
| c7-memory | 浏览器 | 14.21s | 8.14s | 1.751 |
| c8-restore | 全新上下文 | 15.31s | 6.44s | 1.832 |
| c9-tests | 卡 | 13.17s | — | — |
| c10-arch | 浏览器（线上） | 9.27s | 6.44s | 1.446 |
| c11-outro | 卡 | 5.27s | — | — |

## 3. 画面里可读回的真实数字（manifest `facts`）

| 数字 | 值 | 来源 |
| --- | --- | --- |
| 后端测试 | `149 passed in 55.21s` | `logs/pytest-20261029T140102.log`（本次运行实跑，项目 venv + 真实 seekdb + 真实 PowerContext） |
| 端到端验收 | T1–T9 全 PASS，150 项校验 | `verification/acceptance-run/`（运行号 20261029-213920） |
| 浏览器交互验收 | `30/30` | 展示站 `data/evidence.json`，`generated_at 2026-10-29T21:42:26+08:00` |
| 全新环境复现 | `23/23 步`（旅程本体 21 步 + 端口检查 + 清理），68.4 s | `logs/fresh-env-20261029-222030.json`（22:20 实跑：全新 venv + 全新 seekdb 容器 + 全新 PowerContext 数据目录，跑完自动清理） |
| 语料规模 | 文档 3 · 物理页 7 · chunk 13 · 项目 6 | `/api/health` 与知识库页 |
| 向量命中分 | `score 0.4407 余弦相似度` | c4 检索结果卡片 |
| 混合命中分 | `score 0.0328 RRF 融合分` | c4 检索结果卡片（与文档手写 RRF 值一致） |
| 论断标注 | `资料直接支持：3 模型推断：0 尚无证据：0` | c6 正常问答 |
| 无证据分支 | `资料直接支持：0 模型推断：0 尚无证据：1`，引用列表为空 | c6 第三段 |
| 幂等 | `written=0`、`skipped_duplicates=2`、「内容未变化，未产生重复记忆」 | c7 |
| 恢复 | 18 条记忆，简报含上一轮 next_step | c8 |

## 4. 重新生成 / 覆盖

```bash
# 前置：seekdb :2881 + PowerContext :17429 + 后端 :8787 已启动，已跑过 scripts/seed_demo.py。
#       c2 / c10 现在录自线上地址，无需本地起 :4181 静态站。
NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" node scripts/make_demo_video.cjs
#   --no-pytest      复用 logs/ 里最近一次真实 pytest 输出（不重跑约 55 s 测试）
#   --force-record   忽略缓存录屏，全部重录
# 中间件在 build/video/（已 gitignore）：逐场景 webm / wav / ass / facts.json
# 环境变量：RF_APP_BASE、RF_SITE_URL（线上地址，同时是 c2/c10 的录屏来源）、
#           RF_SITE_LOCAL（临时改成本地地址可录本地构建）、RF_CHROME_PATH
# 收尾自动执行 scripts/check_demo_video.cjs，任一检查不过则整个构建以非零码失败
```

**缓存语义（重要）**：不加 `--force-record` 时，已存在的 `<scene>.webm` 会被直接复用，
其 `realWallSeconds` 取自 `facts.json` 里当初实测的 `wallSeconds`，**不是** webm 容器时长
（容器比交互本身长，用它会把真实耗时写虚高）。因此局部重录单个场景后，其余场景的
耗时数字仍然可信；但若旁白文案改了而画面没重录，成片会出现「新字幕配旧画面」，
所以**凡是改动了浏览器场景文案的正式重录一律加 `--force-record`**。
本次定稿只改了 c9（文本卡）的文案与数字，卡片画面本身由脚本按同一份 facts 重绘，
因此复用录屏不会造成音画错位。

**数字取自报告，不写死**：c9 卡片与旁白里的全新环境复现步数现在由脚本读
`logs/fresh-env-*.json` 最新一份的 `passed/total` 生成。此前它被硬编码为 `20/20`，
与 09:44 实跑报告的 `22/22` 不符——修正口径后重跑了一次全新环境旅程：
22:12 那次因本机另一进程恰好占用了 8790 端口而失败（报告
`logs/fresh-env-20261029-221217.json` 如实保留），于是给 `fresh_env_e2e.py` 加了
端口占用前置检查与「健康响应必须含 `components`」的就绪判据，并把三个端口改成
可用 `RF_FRESH_*` 覆盖；22:20 换到空闲端口重跑得 **23/23**（新增的一步就是端口检查）。
成片用的就是这个 23/23。任一场景的真实值与本文不一致时，
**以重新运行的结果为准**，并同步修正本文与 `BENCHMARK.md`。

## 5. 可选的真人覆盖（非必需）

若希望把配音换成真人，或加入真人口播：按 [`../DEMO_SCRIPT.md`](../DEMO_SCRIPT.md) §1–§3 录制，
§3 旁白稿可直接照读（**其中的数字与结论不得改动**）。自动成片已满足「有演示视频」这一项，
因此这是可选项，不阻塞提交。

## 6. 视频未覆盖、仍需人工截图的素材

对照 `DEMO_SCRIPT.md` §4 列出的 8 项待补关键帧：

| §4 项 | 本次录屏是否覆盖 | 说明 |
| --- | --- | --- |
| 1 三模并排 + 重叠分析 | ✅ | c4 → `keyframes/04-c4-retrieval.png` |
| 2 RRF `0.0328` 特写 | ✅ | c4（结果卡片 `score 0.0328 RRF 融合分`） |
| 3 「尚无证据」且引用为空 | ✅ | c6 第三段（`资料直接支持：0 模型推断：0 尚无证据：1`） |
| 4 幂等与「内容未变化」两次保存 | ✅ | c7（本次画面为 `written=0 / skipped_duplicates=2` 分支） |
| 5 无痕窗口只凭 project_id 恢复 | ⚠️ 部分 | c8 用的是**全新浏览器上下文**（无 cookie、无登录态），实质等价，但画面里没有可见的无痕地址栏；若评审要求「肉眼可见无痕模式」需人工补一张 |
| 6 终端 `149 passed` | ❌ | c9 是**日志回放的文本卡**，不是终端屏幕录制；需要终端截图时人工补拍 |
| 7 Qoder 对话窗口 | ❌ | 无法由产品录屏替代，见 `07-qoder-dev-evidence.md` Q1–Q8 |
| 8 `ARCHITECTURE.md` 一图流 | ⚠️ 部分 | c10 展示的是**线上展示站** architecture 区块，不是仓库内 `ARCHITECTURE.md` 原文 |

11 张逐场景关键帧已随成片一起生成在 `demo/keyframes/`（脚本自动从成片中点抽帧，
路径记录在 `video-manifest.json` 的 `keyframes`），上表的 ✅ 项可直接取用，无需再手工截屏。
