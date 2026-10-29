# FILES_TO_UPLOAD · 上传什么、放哪里、怎么核对

三个层次，不要混用：

| 层次 | 是什么 | 用在哪 |
| --- | --- | --- |
| ① Git 仓库 | `qoder/researchflow/**` 的全部源码、文档与验证产物（分支 `2026-competition-ecosystem`） | 报名表里的仓库地址；评审的主入口 |
| ② 公开站点 | <https://researchflow-5esfsogn38f.qoder.zone>（纯静态展示版） | 报名表里的作品在线地址 |
| ③ 交付目录 / ZIP | 仓库**之外**的本地产物：成片、字幕、关键帧、最终提交包 ZIP 与校验文件 | 平台要求上传视频或单文件附件时使用 |

③ 刻意放在仓库外：`D:\OceanBase\deliverables\researchflow-final\`。
**没有任何一个 ZIP 或大体积视频被提交进 Git**，因此也不存在「误把包 push 上去」的可能。

---

## 1. 演示视频（平台一般要求单独上传）

```
D:\OceanBase\PowerContext-researchflow\qoder\researchflow\submission-package\demo\researchflow-demo.mp4
```

| 项 | 实测值 |
| --- | --- |
| 字节 | 6 796 164 B（6.48 MiB） |
| SHA-256 | `f0dfab386a67cd10699cd5aa6db5844a8b2e37fea69524e822cc41c499da2528` |
| 规格 | 1280×800 · H.264 High / yuv420p · 30 fps · 4 046 帧 · 134.97 s（2 分 15 秒）· AAC 48 kHz 立体声 |
| 音画同步差 | 0.028 s |
| 定稿时间 | 2026-10-29 22:21（本地，UTC+8） |
| 自检 | 25 项交付检查全 PASS → `demo/video-check.json`（`failureCount: 0`） |

同目录并列的三个文件（若平台允许附带，建议一起交）：

```
researchflow-demo.vtt    4 217 B  字幕轨（28 条，与旁白逐句一致；SHA-256 310bdd3e…）
video-manifest.json     12 702 B  逐场景采集方式 / 真实耗时 / 重放系数 / 读回数字（b9add171…）
video-check.json         1 246 B  对成片文件本身执行的 25 项自动检查（c8b143d9…）
keyframes/01…11.png                从成片逐场景中点自动抽帧的 11 张关键帧
```

## 2. 提交包（仓库内，评审按链接浏览即可）

```
qoder/researchflow/submission-package/
├── FINAL_SUBMISSION.md            唯一入口
├── 01…11-*.md                     11 篇分主题文档
├── AUDIT.md                       封版交付审计（自动检查真实输出）
├── FORM_FIELDS.md                 报名表可直接复制文本
├── FILES_TO_UPLOAD.md             本文件
├── FINAL_AUDIT.md                 本轮六阶段终审
├── MANUAL_ONLY.md                 只剩本人能做的 6 项
└── demo/                          成片 + 字幕 + 清单 + 自检 + 关键帧
```

## 3. 最终 ZIP（平台要求「单个附件」时用）

```
包：D:\OceanBase\deliverables\researchflow-final\ResearchFlow-Qoder-Final.zip
校验：D:\OceanBase\deliverables\researchflow-final\ResearchFlow-Qoder-Final.zip.sha256
清单：D:\OceanBase\deliverables\researchflow-final\final-zip-manifest.json
```

**为什么 ZIP 里不写自己的 SHA-256**：压缩包无法包含自身的校验和。校验和与成员清单
是打包脚本在归档**写完之后**生成的两个外部文件（`.zip.sha256` 一行式，可直接用于
`sha256sum -c`；`final-zip-manifest.json` 记录字节数、压缩比、扫描命中数、逐目录统计与
解压逐字节核对结果）。若某平台只允许一个附件，上传 ZIP 并把 SHA-256 填在文字字段里。

打包与自校验命令（在项目 venv 内执行，会**拒绝**在扫描命中时写出文件）：

```bash
cd qoder/researchflow
backend/.venv/Scripts/python scripts/build_final_zip.py
```

脚本每次都做四件事：收集显式白名单 → 对全部文本成员跑 7 条凭据/隐私正则 →
写归档 → **解压到全新临时目录并逐字节比对每个成员**（缺失 / 差异 / 多余三项必须全为 0）。

## 4. ZIP 内容（实测清单）

本轮构建：**303 个成员**；扫描 **0 命中**；解压到全新临时目录后逐字节比对
**missing 0 / differing 0 / unexpected 0**；`testzip()` 无损坏成员。
字节数与归档大小会随文档改动浮动几 KB（上一次实测 34 902 037 B 原始 →
32 746 684 B，压缩比 0.9382，大头是 PNG 与 MP4 本就压不动），因此**权威值以
`.zip.sha256` 与 `final-zip-manifest.json` 为准**，下表只列不随内容改动变化的文件数。

| 包内目录 | 文件数 | 内容 |
| --- | --- | --- |
| `ResearchFlow/`（顶层） | 13 | README / RUN / VERIFICATION / ARCHITECTURE / SECURITY / BENCHMARK / SUBMISSION / DEMO_SCRIPT / QODER_LOG / PLAN / SITE_DEPLOYMENT / PUSH_PRECHECK / `.env.example` |
| `ResearchFlow/backend/` | 45 | `app/` 四个领域模块 + `tests/` 全部 149 项（含 `tests/data/` 两份基准问句集）+ `pyproject.toml` |
| `ResearchFlow/frontend/` | 32 | `src/` 全部源码与样式 + 5 份工程配置 + `index.html` + `package.json` |
| `ResearchFlow/scripts/` | 22 | 验收、基准、站点核验、录屏/配音/成片检查、打包等全部可复现脚本 |
| `ResearchFlow/demo/` | 5 | 四份演示语料 + 生成脚本（可 `seed_demo.py` 重放） |
| `ResearchFlow/site/public/` | 15 | 公开展站源码——与线上 15/15 逐字节一致的那一份（线上 HTML 多出的部分是平台注入的水印脚本，不来自本地文件） |
| `ResearchFlow/verification/` | 138 | T1–T9 逐用例日志与报告、真实浏览器交互验收 JSON + 48 张四宽度截图 + 新旧对比、线上站点核验 JSON 与截图 |
| `ResearchFlow/submission-package/` | 32 | 17 篇文档 + 成片 + 字幕 + 清单 + 自检 + 11 张关键帧 |
| `ResearchFlow/evidence-logs/` | 1 | `pytest-20261029T140102.log`（`149 passed in 55.21s`，即视频 c9 卡片逐字回放的原文） |

排除项（**逐条是有意为之，不是遗漏**）：

| 排除 | 原因 |
| --- | --- |
| `backend/.venv`、`services/.venv-powercontext`、`frontend/node_modules`、`frontend/dist` | 依赖与构建产物，按 `RUN.md` 重建；入库会造成版本漂移 |
| `*.db` / `*.db-wal` / `*.db-shm` / `*.sqlite3` / `data/` / `services/powercontext-data/` | 本地数据库与服务运行态数据 |
| `.env`（只保留 `.env.example`） | 真实密钥；`.env` 也在 `.gitignore` 内 |
| `logs/`（只把被引用的那份 pytest 输出改名放进 `evidence-logs/`） | 其余运行日志含本机绝对路径 |
| `verification/browser-acceptance/interactions-run.log` | 真实运行转写，但其第 2 行记录了本机 Chromium 安装路径（含 Windows 用户名）。**不改写证据**，因此整份排除；机器可读的 `interactions.json`（30/30 与逐用例耗时）完整在包里，仓库里也有原文件 |
| `build/`（录屏 webm、配音 wav、ASS 等中间件） | 可由 `scripts/make_demo_video.cjs` 重新生成，非提交材料 |
| `site/preview/`、`site/preview-local/` | 本地预览截图；线上核验证据在 `verification/site-public/` |
| `*cursor-key*`、任何 `sk-…` 形态串 | 运行凭据 |
| 完整 Qoder UID | 个人信息，只进报名表（`MANUAL_ONLY.md` §2） |
| `submission-package/qoder-evidence/` | 该目录尚不存在（8 张对话截图待人工，见 `MANUAL_ONLY.md` §1）；截图补齐后重跑打包命令即可一并纳入 |
| 原始未公开的个人科研资料 | 演示语料只用 `demo/` 下四份可公开样本 |

## 5. 核对命令（评审侧）

```bash
# 校验包完整性
cd "D:/OceanBase/deliverables/researchflow-final"
sha256sum -c ResearchFlow-Qoder-Final.zip.sha256

# 解压后逐目录看规模
python -c "import zipfile;zipfile.ZipFile('ResearchFlow-Qoder-Final.zip').testzip() or print('no corrupt member')"

# 仓库侧：确认远端与本地一致（所有文档都不写死 tip）
git fetch origin && git rev-parse HEAD origin/2026-competition-ecosystem
```

## 6. 隐私与凭据终检（提交前在仓库根跑）

```bash
grep -rEc "01a175e3-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}" qoder/researchflow/ | grep -v ':0$'   # 无输出
grep -rE "sk-[A-Za-z0-9]{20,}" qoder/researchflow/ --include='*.md' --include='*.py' --include='*.json'      # 无输出
git status --porcelain | grep -v '^.. qoder/researchflow/'                                                   # 无输出
```

本轮实测：三条均无输出（详见 `FINAL_AUDIT.md` §4）。
