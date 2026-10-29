# 08 · 演示视频（已生成）与素材清单

| 项 | 值 |
| --- | --- |
| 成片 | `submission-package/demo/researchflow-demo.mp4` |
| 时长 | **124.8 s（2 分 05 秒）** |
| 规格 | 1280×800、H.264 + AAC 48 kHz 立体声、30 fps、6.2 MB |
| 字幕 | 烧录进画面 + 独立轨道 `researchflow-demo.vtt`（24 条，与旁白逐句一致） |
| 溯源 | `video-manifest.json`：逐场景采集方式、真实耗时、重放系数与全部读回数字 |
| 生成 | `node scripts/make_demo_video.cjs`（约 6 分钟，需三个进程已启动并 seed） |

**采集方式（manifest 原文）**
- 浏览器场景：Playwright 无头浏览器录屏，驱动真实运行的前端 + FastAPI + seekdb + PowerContext。
- 文本卡场景：由当次真实命令输出原样渲染（日志回放，**非屏幕录制**，卡片上已注明）。
- 旁白：Windows `System.Speech` 中文语音（Microsoft Huihui）合成；
  **旁白里的数字是本次录制从页面读回的真实值**，不是预先写死的稿子。
- 重放：录屏按旁白时长用 `setpts` 等比重放（短片段放慢、长片段适度加速，
  系数 0.75–2.5 逐场景记录在 `speedFactor`），**未删除或跳剪任何真实步骤**。

---

## 1. 八个必答覆盖点 → 场景映射

| 要求 | 场景 | 画面中真实出现的证据 |
| --- | --- | --- |
| 1 项目介绍与真实科研痛点 | c1-intro（卡）+ 旁白 | 定位与两个痛点（能否回查原文 / 换会话进度还在不在） |
| 2 上传 PDF 经 seekdb 真正入库 | c3-upload | 健康条 `5.7.25-OceanBase seekdb-v1.4.0.0`、`ik`、`文档 3 · 页 7 · chunks 13 · 项目 5`、去重提示 |
| 3 向量 / 全文 / RRF 混合检索 | c4-retrieval | 三模切换、`score 0.0328 RRF 融合分`、三列并排 + 重叠分析（按 chunk_id） |
| 4 通过 citation 查看 PDF 真实来源页 | c5-pages + c6-workbench | 第 4 页 `page_id …:p0004 char_count 0` 空白页身份；第 5 页 `…:p0005 char_count 847` 原文；引用编号点开同一页 |
| 5 PowerContext 保存决策与进度 | c7-memory | `written=1`、`seq` 递增到 2、再次保存「内容未变化，未产生重复记忆」 |
| 6 新建会话恢复决策与 next_steps | c8-restore（**全新浏览器上下文**） | 续研简报含刚保存的那条 next_step；恢复 18 条记忆；标注来源为历史记忆而非文献证据 |
| 7 技术架构与真实测试结果 | c9-tests（卡：`149 passed in 48.86s` 原样回放）+ c10-arch | 站点架构区块与验证区块（`149 passed`、`9 / 9 PASS`） |
| 8 已发布 Qoder Sites 公共网站 | c2-site + c10-arch | 直接录屏公开 URL 的真实渲染 |

## 2. 逐场景时长

| 场景 | 类型 | 成片 | 真实操作耗时 | 重放系数 |
| --- | --- | --- | --- | --- |
| c1-intro | 卡 | 8.50s | — | — |
| c2-site | 浏览器 | 9.60s | 2.76s | 2.5 |
| c3-upload | 浏览器 | 13.87s | 4.60s | 2.5 |
| c4-retrieval | 浏览器 | 13.88s | 7.80s | 1.779 |
| c5-pages | 浏览器 | 12.30s | 7.84s | 1.57 |
| c6-workbench | 浏览器 | 14.80s | 19.68s | 0.752 |
| c7-memory | 浏览器 | 12.14s | 8.60s | 1.411 |
| c8-restore | 全新上下文 | 15.31s | 8.28s | 1.849 |
| c9-tests | 卡 | 9.63s | — | — |
| c10-arch | 浏览器 | 9.51s | 6.64s | 1.432 |
| c11-outro | 卡 | 5.27s | — | — |

## 3. 重新生成 / 覆盖

```bash
# 前置：seekdb :2881 + PowerContext :17429 + 后端 :8787 已启动，且已跑过 scripts/seed_demo.py
NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" node scripts/make_demo_video.cjs
#   --no-pytest      复用缓存的真实 pytest 输出（不重跑 49s 测试）
#   --force-record   忽略缓存录屏，全部重录
# 中间件在 build/video/（已 gitignore）：逐场景 webm / wav / ass / facts.json
```

任一场景的真实值与本文不一致时，**以重新运行的结果为准**，并同步修正本文与 `BENCHMARK.md`。

## 4. 可选的真人覆盖（非必需）

若希望把配音换成真人，或加入真人口播：按 [`../DEMO_SCRIPT.md`](../DEMO_SCRIPT.md) §1–§3 录制，
§3 旁白稿可直接照读（**其中的数字与结论不得改动**）。自动成片已满足「有演示视频」这一项，
因此这是可选项，不阻塞提交。

## 5. 视频未覆盖、仍需人工截图的素材

对照 `DEMO_SCRIPT.md` §4 列出的 8 项待补关键帧：

| §4 项 | 本次录屏是否覆盖 | 说明 |
| --- | --- | --- |
| 1 三模并排 + 重叠分析 | ✅ | c4 |
| 2 RRF `0.0328` 特写 | ✅ | c4（结果卡片 `score 0.0328 RRF 融合分`） |
| 3 「尚无证据」且引用为空 | ✅ | c6 第三段 |
| 4 `written=1` 与「内容未变化」两次保存 | ✅ | c7 |
| 5 无痕窗口只凭 project_id 恢复 | ⚠️ 部分 | c8 用的是**全新浏览器上下文**（无 cookie、无登录态），实质等价，但画面里没有可见的无痕地址栏；若评审要求「肉眼可见无痕模式」需人工补一张 |
| 6 终端 `149 passed` | ❌ | c9 是**日志回放的文本卡**，不是终端屏幕录制；需要终端截图时按 §2 的 `identify` 之外的方式人工补拍 |
| 7 Qoder 对话窗口 | ❌ | 无法由产品录屏替代，见 `07-qoder-dev-evidence.md` Q1–Q8 |
| 8 `ARCHITECTURE.md` 一图流 | ⚠️ 部分 | c10 展示的是**站点** architecture 区块，不是仓库内 `ARCHITECTURE.md` 原文 |

抽帧可从成片截取（中间件目录 `build/video/check/` 不入库，重跑脚本即可再生成）。
