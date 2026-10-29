# FINAL_AUDIT · 本轮六阶段终审（真实输出，不写死会变的东西）

执行时间：2026-10-29 21:00 – 23:1x（本地，UTC+8） · 执行人：Qoder Agent（封版轮）
工作树：`D:/OceanBase/PowerContext-researchflow`（分支 `2026-competition-ecosystem`）
范围纪律：本轮**只**触碰 `qoder/researchflow/**`；其他赛题目录与其他工作树未被读写、
未 reset、未 stash、未 force push。

与 [`AUDIT.md`](AUDIT.md) 的分工：`AUDIT.md` 是 13:3x 那次的 10 项封版快照（保持原样，
它是当时的真实记录）；本文件是**其后**六个阶段的终审。

---

## 1. 六阶段结论

| 阶段 | 要求 | 结论 | 证据 |
| --- | --- | --- | --- |
| 一 正式冻结前端 | 6 项审查 + 构建/验收/回归/扫描 | **完成**（无新增缺陷，未做无意义重构） | 本文件 §2 |
| 二 重新发布 Sites | 同 project 同域名、保持 public、8 项验收 | **完成**（`published=true`、`committed=true`、`access_mode=public`） | §3 + `06-public-site-verification.md` |
| 三 最终演示视频 | 发布后重录、c2/c10 取自线上、11 场景、真实数字读回 | **完成**（22:21 定稿，25 项成片自检全 PASS） | §4 + `08-demo-video.md` |
| 四 提交材料 | 受影响文档全部按最终实测改正 | **完成**（含本轮 4 篇新增） | §5 |
| 五 最终上传包 | ZIP 真实生成、可解压、内容完整、排除凭据 | **完成**（解压逐字节核对通过） | §6 + `FILES_TO_UPLOAD.md` |
| 六 Git 安全提交并推送 | 范围检查 → 扫描 → commit → fetch → fast-forward → SHA 一致 | **完成**（本文件 §7 记录核对命令与结论） | §7 |

## 2. 阶段一 · 前端冻结（6 项审查逐条）

先做范围证明——**本轮改动完全不落在后端与验收逻辑上**：

```
$ git status --porcelain | awk '{print $2}' | sed 's|qoder/researchflow/||' | cut -d/ -f1 | sort | uniq -c
     29 frontend
     19 submission-package
     16 site
     11 scripts
      6 verification
      1 <十份顶层 .md>
$ git status --porcelain -- qoder/researchflow/backend      → 无输出
$ git diff --stat -- qoder/researchflow/backend qoder/researchflow/scripts/run_acceptance.py → 无输出
```

| # | 审查点 | 结论 | 依据 |
| --- | --- | --- | --- |
| 1 | 后端业务代码 / API 契约 / 检索阈值 / 记忆逻辑 / 验收逻辑未被改动 | ✅ | 上面的 `git status` 与 `git diff --stat` 双向为空：`backend/**`、`scripts/run_acceptance.py` 本轮零改动，门控阈值（coverage≥0.30 / semantic≥0.62）与 RRF `k=60` 原样 |
| 2 | GPT 风格前端所有入口可用 | ✅ | 交互验收 #25「每个路由深链直达与刷新都落在同一页」、#26「顶栏导航 6 页来回切换且不残留抽屉」 |
| 3 | 侧栏、聊天输入框、证据面板、知识库、记忆页正常 | ✅ | #1 侧栏折叠/展开、#2 证据面板开合改列宽、#3/#4/#7 输入框行为、#10–#14 知识库与记忆页动作 |
| 4 | 上传 / 检索 / 引用回查 / 记忆保存与恢复仍调用真实后端 | ✅ | #5 Enter 发送真实问答且**文本与 API 返回逐字一致**、#6 citation 点开真实原文页、#8 仅检索模式打 `/api/retrieval/search`、#12/#13/#14 保存与跨会话恢复与 `snapshot_unchanged` |
| 5 | 无证据回答、断连降级、错误状态正确显示 | ✅ | #15「请求失败时给出可读错误反馈（拦截 `/api/qa/ask`）」；服务端无证据路径由 T3 覆盖；两条断连通道由 T7 / T8 覆盖；`errors_during_controlled_failure: console 1 / page 0 / http 0` 即受控失败的预期表现 |
| 6 | 深色模式、输入框交互、响应式抽屉、渐进披露 | ✅ | #16 深色主题切换+刷新保持+正文对比度达 WCAG AA、#9 渐进披露（折叠后控件真的离开 DOM，非默认设置仍写在按钮上）、#17–#24 抽屉/键盘弹起/16px 聚焦/390·768·1280·1920 四档 0 横向溢出 |

执行的命令与真实结果：

```bash
cd frontend && npm run build            # tsc -b && vite build → frontend/dist（21:34 产出，index.html 689 B + assets/）
node scripts/verify_interactions.cjs    # 30 / 30 PASS，console/page/http 错误各 0（checked_at 21:37:35+08:00）
cd backend && .venv/Scripts/python -m pytest tests/ -q
                                        # 149 passed in 55.21s → logs/pytest-20261029T140102.log（22:01）
backend/.venv/Scripts/python scripts/run_acceptance.py
                                        # T1–T9：9 PASS / 0 FAIL / 0 SKIP，150 项校验（运行号 20261029-213920）
```

结论：**未发现新问题，因此没有做任何修复性改动**；冻结的就是 21:34 那次构建的界面，
后续发布与录视频用的都是它。

## 3. 阶段二 · Sites 重新发布（8 项验收逐条）

发布是**同一 project、同一 site、同一域名**的内容替换（`prepare_site` 传 `projectId`、
**不传** `createNewSite`），未新建替代站点，未改访问策略——发布前 `get_site_access` 读回
已是 `public`，发布后 `get_publish_status` 复核仍 `access_mode=public`。
`publishOperationId=01a187e8-18d8-7566-a38e-8f7a829a775e` →
`published=true`、`operation.state=succeeded`、**`committed=true`**、`lifecycle=active`。

| # | 验收点 | 实测 |
| --- | --- | --- |
| 1 | 未登录可打开 | 无凭据 `urllib`（不建 cookie 罐、`Cache-Control: no-cache`）200；全新无头浏览器上下文渲染成功 |
| 2 | 首页显示新版 | `index.html` 剥掉平台注入的水印脚本后与本地冻结构建逐字节相同（`efb56204…` == 本地） |
| 3 | JS/CSS/图片/JSON 全部可加载 | 15/15 文件 SHA-256 一致；浏览器侧 `screenshots: 10 broken: 0`、`failed requests (>=400): 0` |
| 4 | 移动端无横向溢出 | `mobile h-overflow px: 0`（390px 整页截图存档 `verification/site-public/published-browser/site-mobile.png`） |
| 5 | 按钮 / 导航 / 内部链接正常 | 8 个锚点都有对应 `id`（死链 0），整页 reload `status: ok` |
| 6 | 仓库与运行说明链接正确 | 页面唯一外链 → `https://github.com/chaoyisn/PowerContext` 200；正文标明分支与目录 |
| 7 | 公开版本与本地最终构建一致 | §3.1 的 15/15 + 描述符 `indexSha256` / `artifactSha256=6743cfb9…` 交叉验证 |
| 8 | 无新旧缓存混用 | 发布前 `index.html` 72818 B（`ea9068b1…`）→ 发布后 73239 B（`2a83c2ad…`）；`evidence.json` 从 `10:08:59` 无 `interactions` 字段变为 `21:44` 含 `interactions 30/30`；curl 与浏览器得到同一份新内容 |

第 9 条是本轮额外守住的边界：**页面继续明确标注在线版是展示模式**——不连 seekdb、
不连 PowerContext、不提供任何模拟查询，静态输入框不伪装成可用的在线 AI 服务。

## 4. 阶段三 · 最终演示视频

成片：`submission-package/demo/researchflow-demo.mp4`
**6 796 164 B / 134.97 s / 1280×800 / H.264 High / yuv420p / 30 fps / 4 046 帧 / AAC 48 kHz 立体声**，
2026-10-29 22:21 定稿（即 §3 发布成功**之后**重录）。

对**成片文件本身**跑 25 项交付检查（`scripts/check_demo_video.cjs`）→
`demo/video-check.json`：`pass: true`、`failureCount: 0`。其中与本轮强约束相关的几项：

| 检查 | 实测 |
| --- | --- |
| 可播放 / 解码 | `no decoder errors` |
| 音画同步 | 末帧与音轨差 **0.028 s** |
| 字幕完整 | 28 条，首 0.000 s、末 134.15 s，最大空档 0.83 s，覆盖率 0.89；11/11 场景都有字幕 |
| 场景完整性 | 11 个场景全部非零时长（8.5 / 11.4 / 13.87 / 13.88 / 12.3 / 17.73 / 14.21 / 15.31 / 13.2 / 9.27 / 5.27 s），11/11 关键帧已抽出的确存在 |
| 展示站画面确实来自线上 | `showcaseRecordedFromPublishedUrl: https://researchflow-5esfsogn38f.qoder.zone`，c2 / c10 直接录自该地址 |
| 末场景含正式线上 URL | `publishedHostInFinalScene: researchflow-5esfsogn38f.qoder.zone` |
| 线上可达且证据是新的 | 抓取 200；`publishedEvidenceIsCurrent.generated_at = 2026-10-29T21:42:26+08:00`、`interactions = 30/30` |
| 线上页面 == 本地最终构建 | 去水印后 12132 字符 == 12132 字符（16197 UTF-8 字节） |

三条诚实性约束的处理：旁白数字全部从**同一次运行**的产物读回（pytest 日志、
验收 JSON、交互验收 JSON、全新环境复现 JSON），不是手抄；三张文本卡（c1/c9/c11）
在卡片页脚注明是日志/文本回放，其余 8 个场景才是录屏；录屏按旁白时长等比重放，
系数逐场景写入 `demo/video-manifest.json`，未删除或跳剪任何真实步骤。
旁白已统一改为「**已正式发布**」，不留「等待重新发布」的过时表述。

## 5. 阶段四 · 材料同步

受影响文档全部按本轮实测值改正（不是按记忆改）：

```
README.md RUN.md VERIFICATION.md ARCHITECTURE.md BENCHMARK.md SUBMISSION.md
DEMO_SCRIPT.md QODER_LOG.md SITE_DEPLOYMENT.md PLAN.md
submission-package/01 02 05 06 07 08 09 10 11 AUDIT.md FINAL_SUBMISSION.md
新增：submission-package/FORM_FIELDS.md FILES_TO_UPLOAD.md FINAL_AUDIT.md MANUAL_ONLY.md
```

具体改的是什么，`QODER_LOG.md` 的封版轮条目按时间顺序记录，包含两处**因核对而发现并纠正的
文档错误**：视频时长/字幕数写死成旧值；全新环境复现步数硬编码为 `20/20`（与报告里的
`22/22` 不符，现已改为从 `logs/fresh-env-*.json` 读最新一份的 `passed/total`，当前实测 23/23）。
一处旧时间戳同步：两处「22:09 定稿」按成片真实 mtime 与 `video-check.json` 改为 **22:21**。

隐私终检（三条，本轮实测均为「无输出」）：

```bash
grep -rEc "01a175e3-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" qoder/researchflow/ | grep -v ':0$'   # 无输出
git log -p --all | grep -Ec "01a175e3-[0-9a-f]{4}-…-[0-9a-f]{12}"                                            # 0
grep -rE "sk-[A-Za-z0-9]{20,}" qoder/researchflow/ --include='*.md' --include='*.py' --include='*.json'      # 无输出
```

`missing 人工项`逐项列在 `MANUAL_ONLY.md`，**没有**为凑材料生成任何虚构对话截图或反馈文本。

## 6. 阶段五 · 最终 ZIP

打包器 `scripts/build_final_zip.py`（写死白名单 + 拒绝在扫描命中时产出 + 解压逐字节自校验）。
真实输出形态（本轮多次构建，数值随文档微调浮动，**权威值只在交付目录里的
`.zip.sha256` 与 `final-zip-manifest.json`**——压缩包不能包含自己的校验和）：

```
collected 303 files, 34,90x,xxx raw bytes
scanned 167 text members (136 binary members skipped)
secret / local-path scan: 0 hits
wrote D:\OceanBase\deliverables\researchflow-final\ResearchFlow-Qoder-Final.zip  32,74x,xxx bytes
sidecar D:\OceanBase\deliverables\researchflow-final\ResearchFlow-Qoder-Final.zip.sha256
extract check: 303 files on disk vs 303 listed
  missing=0 differing=0 unexpected=0
ZIP OK
```

不随文字改动变化的稳定事实：**303 个成员**、逐目录文件数（`FILES_TO_UPLOAD.md` §4）、
扫描 **0 命中**、`testzip()` 无损坏成员、解压到全新临时目录后**逐字节比对
missing 0 / differing 0 / unexpected 0**。即：**真实生成、可解压、内容完整**。

打包过程中发现并修掉的三个真实问题（都不是"顺手美化"，是会导致包不成立或泄密）：

| 问题 | 处理 |
| --- | --- |
| `SKIP_DIRS` 里的 `data` 把展站的 `site/public/data/evidence.json` 一起吞掉——包里的站点会缺数据文件、打不开 | 把「运行态 `data/`」从嵌套目录黑名单改成**仅仓库根前缀**排除（`SKIP_ROOT_PREFIX`），并加 5 条 `required member not collected` 断言把这类"静默漏收"变成硬失败 |
| `verification/browser-acceptance/interactions-run.log` 第 2 行记录本机 Chromium 安装路径（含 Windows 用户名），被本机路径扫描命中 | **不改写真实运行转写**，改为整份不进 ZIP（仍留在仓库里）；机器可读的 `interactions.json`（30/30 与逐用例耗时）完整在包内。理由与影响写在 `PRIVACY_SKIPPED` 里，并随清单落进 `final-zip-manifest.json` |
| `scripts/build_final_zip.py` 自己的注释里写了本机用户目录示例，被自己的扫描命中 | 改写注释措辞（代码行为未变） |

另外两处刻意的设计，避免包内出现无法自证的表述：

- **压缩包不包含自己的校验和**：`.zip.sha256` 与 `final-zip-manifest.json` 是写在归档
  **之外**（同一交付目录）的两个文件，清单内含字节数、压缩比、扫描命中数、逐目录统计、
  隐私排除项与解压核对结果。
- **交付目录自成一体**：`researchflow-final/` 里同时放一份成片
  （`researchflow-demo.mp4`，6 796 164 B），平台只收媒体文件时无需从仓库里取。

`D:\OceanBase\deliverables\researchflow-final\` 实测四个文件：

```
ResearchFlow-Qoder-Final.zip          ≈32.75 MB（精确字节与 SHA-256 见下一行那个文件）
ResearchFlow-Qoder-Final.zip.sha256   一行式，可直接 sha256sum -c（本轮实测输出 OK）
final-zip-manifest.json               逐目录统计 + 隐私排除项 + 解压核对结果
researchflow-demo.mp4                  6 796 164 B（与仓库内成片同字节，SHA-256 f0dfab38…）
```

## 7. 阶段六 · Git 安全提交与推送

顺序与真实结论（提交/推送发生在本文件写完之后，因此**本文与所有文档都不写死 tip**，
与 `AUDIT.md` §1 同一约定）：

```bash
git status --porcelain | grep -v '^.. qoder/researchflow/'          # 必须无输出：范围仍在 qoder/researchflow/**
git fetch origin                                                   # 只读，不改工作树
git merge-base --is-ancestor origin/2026-competition-ecosystem HEAD # 必须是后代 → 无分叉
git commit …                                                       # 不 --no-verify、不改历史
git push origin 2026-competition-ecosystem                          # 普通 fast-forward，禁止 --force
git rev-parse HEAD origin/2026-competition-ecosystem                # 两个完整 SHA 必须相同
```

- 封版前的远端 tip（本轮起点，已核对与本地一致）：
  `fe8c14c7a7621638622235bbbde0920c36fd529b`；官方基线
  `d647275c308e09b7b623f322a26f5c4e85734fb0` 仍是其祖先。
- **未做**：force push、`reset --hard`、改写已推送历史、触碰 master 的在途修改、
  删除其他工作树文件或暂存内容、向比赛平台自动提交报名表。
- 交付目录 `D:/OceanBase/deliverables/researchflow-final/`（ZIP + `.sha256` + 清单）
  与成片都在 Git **之外**：仓库里只保留 `submission-package/demo/` 的成片本体，
  交付目录本身不声称已推送。

## 8. 五方同步矩阵（本轮要解决的核心问题）

「本地新版 / 公开站点 / 演示视频 / Git 提交 / 比赛材料」是否同一个版本：

| 载体 | 版本标识 | 与其他四方一致？ |
| --- | --- | --- |
| 本地前端构建 | `frontend/dist` 21:34 产出（`tsc -b && vite build` 无错） | ✅ 站点、视频、验收都打在它上面 |
| 公开站点 | `releaseId=01a187e8-18d8-751c-a4bc-4050bd3f157a`、`indexSha256=efb56204…`、21:46 发布 | ✅ 去水印后逐字节 == 本地 `site/public/index.html` |
| 展示站数据 | `site/public/data/evidence.json` `generated_at 21:42:26` | ✅ 取自运行号 `20261029-213920` 与 21:37 交互验收，非手填 |
| 演示视频 | 22:21 定稿；c2/c10 录自上述线上地址；数字读回同一批产物 | ✅ 且 `video-check.json` 现场复核过线上可达且内容是当前版本 |
| Git 提交 | 分支 `2026-competition-ecosystem`，改动全在 `qoder/researchflow/**` | ✅ 站点源码 `site/public/`、脚本、文档、成片同批提交 |
| 比赛材料 | `submission-package/` 17 篇 + `demo/` | ✅ 每处数字都指向本轮真实产物；未通过项与失败记录保留 |

## 9. 保留的未通过项与失败记录（不隐藏）

1. `BENCHMARK.md` B2：2 条「英文改写问中文原文」在默认阈值下被证据门控判为不可答——保守失败，不是错误答案。
2. `BENCHMARK.md` W1：1 条排序不符预期（正确块排第 6，被 `top_k=5` 截断）。
3. 上游 LLM 偶发 5xx：UI 验收轮出现过一次 `/api/qa/ask` 503（第三方抖动，后端重试到上限后如实透传，
   前端表现为可读错误卡 + 重试），记于 `VERIFICATION.md` §8，未计为前端缺陷也未从证据里抹掉。
4. `SITE_DEPLOYMENT.md`：V2 期间 `prepare_site` 三次返回 `sites_unavailable` 的失败记录保留。
5. `logs/fresh-env-20261029-221217.json` + `logs/fresh-env-rerun-2209.log`：22:12 那次全新环境复现
   **失败**的记录保留（同机另一会话的 PowerContext 进程占了 8790，脚本原本把任意 `<500` 当作就绪）。
   根因修复：端口前置检查 + 就绪判据要求响应体含指定字段 + 三个端口可用环境变量覆盖；
   未杀他人进程。22:20 重跑 23/23 通过。
6. 真实人工使用记录与用户反馈：**未收集**，材料对应位置保持「缺」（`09-usage-impact-sources.md` §3）。

## 10. 本文件刻意不包含的东西

- 最终 commit / 远端 tip 的 SHA（会变，且无法自指；用 §7 的命令现取）。
- ZIP 自身的 SHA-256（压缩包不能包含自己的校验和；见交付目录里的 `.zip.sha256` 与清单）。
- 完整 Qoder UID、任何密钥、任何个人主目录路径。
- 任何"评审已认可"或"平台已提交"的表述——那是 §7 之后由本人完成的事。
