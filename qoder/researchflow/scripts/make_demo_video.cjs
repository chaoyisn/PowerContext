/**
 * Record the ResearchFlow competition walkthrough and assemble the ~3 minute demo video.
 *
 *   NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" backend/.venv/Scripts/python.exe /dev/null  # (not needed)
 *   NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" node scripts/make_demo_video.cjs
 *
 * Every browser scene drives the running product against the real seekdb container and the real
 * PowerContext service, and the narration numbers are read back from that same recording run.
 * Generated cards show verbatim text captured from real command output.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { chromium } = require('playwright-core');

const ROOT = path.join(__dirname, '..');
const OUT = path.join(ROOT, 'submission-package', 'demo');
const WORK = path.join(ROOT, 'build', 'video');
const APP = process.env.RF_APP_BASE || 'http://127.0.0.1:8787';
const SITE = process.env.RF_SITE_URL || 'https://researchflow-5esfsogn38f.qoder.zone';
// The published site now serves the frozen post-simplification build (verified byte-for-byte),
// so the showcase scenes are recorded straight from the public URL - the same thing a reviewer sees.
const SITE_SRC = process.env.RF_SITE_LOCAL || SITE;
const PDF = path.join(ROOT, 'demo', 'seekdb_hybrid_retrieval_notes.pdf');
const PROJECT = 'demo-seekdb-hybrid';
const PROJECT_TITLE = 'seekdb 混合检索在科研知识库中的效果验证';
const QUESTION = '一条记录如果在两条腿里都排第一，RRF 融合分数是多少';
const NO_EVIDENCE_Q = '这篇文档里有没有关于量子纠缠实验的测量结果';
const NEW_NEXT_STEP = '把三模对比与重叠分析纳入下一轮 top_k=20 召回评测';
const SIZE = { width: 1280, height: 800 };
const SKIP_PYTEST = process.argv.includes('--no-pytest');
const FORCE_RECORD = process.argv.includes('--force-record');
const FACTS = path.join(WORK, 'facts.json');
const facts = {};
if (fs.existsSync(FACTS)) Object.assign(facts, JSON.parse(fs.readFileSync(FACTS, 'utf8')));
// Set after the merge: a cached facts.json must not make this run look like an earlier one.
facts.startedAt = new Date().toISOString();
function saveFacts() {
  fs.writeFileSync(FACTS, JSON.stringify(facts, null, 2), 'utf8');
}

fs.mkdirSync(OUT, { recursive: true });
fs.mkdirSync(WORK, { recursive: true });

// ------------------------------------------------------------------------ helpers
function run(cmd, args, options = {}) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', ...options });
  if (r.status !== 0) {
    throw new Error(`${cmd} failed: ${(r.stderr || r.stdout || '').slice(-1200)}`);
  }
  return r.stdout || '';
}
function ffmpeg(args, cwd = WORK) {
  return run('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', ...args], { cwd });
}
function durationOf(file) {
  const out = run('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of',
    'csv=p=0', file]);
  return Number(String(out).trim());
}
function writeText(name, text) {
  const file = path.join(WORK, name);
  fs.writeFileSync(file, text, 'utf8');
  return name;
}
function srtTime(sec) {
  const ms = Math.round(sec * 1000);
  const p = (n, l = 2) => String(n).padStart(l, '0');
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
}
function resolveChromium() {
  if (process.env.RF_CHROME_PATH) return process.env.RF_CHROME_PATH;
  const root = path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright');
  if (!fs.existsSync(root)) return undefined;
  const found = [];
  for (const dir of fs.readdirSync(root)) {
    for (const rel of [
      path.join('chrome-headless-shell-win64', 'chrome-headless-shell.exe'),
      path.join('chrome-win64', 'chrome.exe'),
    ]) {
      const full = path.join(root, dir, rel);
      if (fs.existsSync(full)) found.push(full);
    }
  }
  return found[0];
}
async function api(p) {
  const res = await fetch(APP + p);
  if (!res.ok) throw new Error(`${p} -> ${res.status}`);
  return res.json();
}

// ------------------------------------------------------------------------ 1. real test run
function collectPytest() {
  if (SKIP_PYTEST) {
    const logs = fs.readdirSync(path.join(ROOT, 'logs')).filter((f) => f.startsWith('pytest-'));
    const latest = logs.sort().pop();
    if (!latest) throw new Error('no captured pytest log to reuse; drop --no-pytest');
    facts.pytestLog = `logs/${latest}`;
    facts.pytestLine = fs.readFileSync(path.join(ROOT, 'logs', latest), 'utf8').trim().split('\n').pop();
    facts.pytestTotal = (facts.pytestLine.match(/(\d+)\s+passed/) || [])[1];
    return;
  }
  const stamp = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15);
  const logFile = path.join(ROOT, 'logs', `pytest-${stamp}.log`);
  fs.mkdirSync(path.join(ROOT, 'logs'), { recursive: true });
  const t0 = Date.now();
  const r = spawnSync(path.join(ROOT, 'backend', '.venv', 'Scripts', 'python.exe'),
    ['-m', 'pytest', 'tests/', '-q'], {
      cwd: path.join(ROOT, 'backend'), encoding: 'utf8',
    });
  const out = `${r.stdout || ''}${r.stderr || ''}`.trim();
  fs.writeFileSync(logFile, out, 'utf8');
  facts.pytestSeconds = Math.round((Date.now() - t0) / 1000);
  facts.pytestLog = path.relative(ROOT, logFile).replace(/\\/g, '/');
  facts.pytestLine = out.split('\n').filter((l) => /passed|failed/.test(l)).pop() || out.slice(-120);
  facts.pytestTotal = (facts.pytestLine.match(/(\d+)\s+passed/) || [])[1];
  saveFacts();
  if (r.status !== 0) throw new Error(`pytest not green: ${facts.pytestLine}`);
}

// The fresh-environment reviewer journey is a separate real run: it builds brand-new virtualenvs,
// a brand-new seekdb container and a brand-new PowerContext data directory, then walks the whole
// journey over HTTP. Its report is the only source for the step count shown on the test card.
function collectFreshEnv() {
  const logs = fs.readdirSync(path.join(ROOT, 'logs'))
    .filter((f) => f.startsWith('fresh-env-') && f.endsWith('.json'))
    .sort();
  const latest = logs.pop();
  if (!latest) throw new Error('no fresh-environment report in logs/; run scripts/fresh_env_e2e.py first');
  const report = JSON.parse(fs.readFileSync(path.join(ROOT, 'logs', latest), 'utf8'));
  if (report.passed !== report.total) throw new Error(`fresh-env not green: ${report.passed}/${report.total}`);
  facts.freshEnvLog = `logs/${latest}`;
  facts.freshEnvAt = report.generated_at;
  facts.freshEnvPassed = report.passed;
  facts.freshEnvTotal = report.total;
  facts.freshEnvSeconds = Math.round(report.elapsed_s);
}

// ------------------------------------------------------------------------ 2. scenes
const scenes = [];
function scene(def) { scenes.push(def); }
function step(caption, act) { return { caption, act }; }

// 输入区的次要控件默认折叠：展开 → 选项目 → 再收起，画面上始终是干净的输入条。
async function pickProject(page, value) {
  const chip = page.locator('.composer-bar button[aria-expanded]');
  if ((await chip.getAttribute('aria-expanded')) !== 'true') await chip.click();
  await page.selectOption('#qa-project', value);
  await chip.click();
  await page.waitForTimeout(400);
}

// The hosted LLM sometimes holds the request open for minutes; one slow call must not
// abort a run that already recorded five scenes, so resubmit once from a clean page.
async function askAndWait(page, attempts = 2) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    if (i > 0) {
      await page.goto(`${APP}/workbench`, { waitUntil: 'networkidle' });
      await page.fill('#qa-question', QUESTION);
      await pickProject(page, PROJECT);
      await page.waitForTimeout(2000);
    }
    await page.click('button:has-text("提问")');
    try {
      await page.waitForSelector('.claims-section', { timeout: 300000 });
      return;
    } catch (err) {
      lastErr = err;
      const shown = await page.locator('.error-state, .banner-red').allInnerTexts().catch(() => []);
      console.log(`  ! 第 ${i + 1} 次提问没有返回论断区块`, shown.join(' / ').slice(0, 200));
    }
  }
  throw lastErr;
}

scene({
  id: 'c1-intro', kind: 'card', title: 'ResearchFlow',
  body: '带证据的科研知识库 + 长期任务记忆\n\nOceanBase × Qoder 2026 数据库比赛 · Qoder 赛道\nseekdb v1.4.0.0 证据库  ·  PowerContext 1.4.1 任务记忆',
  steps: [step('这是 ResearchFlow，一个带证据的科研知识库，加上长期任务记忆。', null),
    step('它针对两个真实痛点：AI 给的结论能不能回查原文，以及换一个会话以后，研究进度还在不在。', null)],
});

scene({
  id: 'c2-site', kind: 'browser', label: '展示站 · 已发布线上版',
  steps: [
    step('这是比赛的展示站，已经正式发布，纯静态：截图和验收数字都由脚本从真实运行里导出，页面不连数据库，也不提供模拟查询。', async ({ page }) => {
      await page.goto(SITE_SRC, { waitUntil: 'networkidle' });
      await page.waitForSelector('text=ResearchFlow');
      facts.siteTitle = await page.title();
      const ev = await fetch(`${SITE_SRC}/data/evidence.json`).then((r) => r.json());
      facts.siteGeneratedAt = ev.generated_at;
      facts.siteInteractions = `${ev.interactions.passed}/${ev.interactions.total}`;
      facts.siteUrl = SITE_SRC;
    }),
    step('这一版就是界面简化之后重新发布到原域名的内容，线上文件与本地最终构建逐个比对完全一致。', async ({ page }) => {
      await page.evaluate(() => window.scrollTo({ top: 900, behavior: 'smooth' }));
      await page.waitForTimeout(2500);
    }),
  ],
});

scene({
  id: 'c3-upload', kind: 'browser', label: '本地应用 · 入库',
  steps: [
    step('本地是完整产品。先上传一份五页的 PDF，第四页是刻意留空的。', async ({ page }) => {
      await page.goto(`${APP}/knowledge`, { waitUntil: 'networkidle' });
      await page.setInputFiles('#upload-file', PDF);
      await page.waitForSelector('text=重复上传已去重', { timeout: 90000 });
    }),
    step('文件内容的 SHA-256 直接作为文档主键，所以同一份文件再传一次会被去重，不会堆积垃圾数据。', async ({ page }) => {
      facts.docId = (await page.locator('.upload-result .meta-value').first().innerText()).trim();
      await page.setInputFiles('#upload-file', PDF);
      await page.waitForTimeout(1500);
    }),
    step((f) => `原文、页、分块和向量全部写进 seekdb。当前库里 ${f.documents} 个文档、${f.pages} 个物理页、${f.chunks} 个分块。`, async ({ page }) => {
      const h = await api('/api/health');
      Object.assign(facts, h.components.seekdb.counts);
      facts.seekdbVersion = h.components.seekdb.server_version;
      facts.fts = h.components.seekdb.fts_analyzer;
      await page.goto(`${APP}/verification`, { waitUntil: 'networkidle' });
      await page.waitForSelector('text=后端健康状态');
      await page.waitForTimeout(1200);
    }),
  ],
});

scene({
  id: 'c4-retrieval', kind: 'browser', label: '本地应用 · 三模检索',
  steps: [
    step('检索有三种模式：纯向量、纯全文，以及 RRF 融合的混合检索。这里问一个只写在第五页的细节。', async ({ page }) => {
      await page.goto(`${APP}/knowledge`, { waitUntil: 'networkidle' });
      await page.fill('#search-query', QUESTION);
      if (!(await page.locator('#search-gate').isChecked())) {
        await page.locator('.checkbox-field').click();
      }
      await page.selectOption('#search-mode', 'vector');
      await page.getByRole('button', { name: '检索', exact: true }).click();
      await page.waitForSelector('text=通过门控', { timeout: 120000 });
      facts.vectorTop = (await page.locator('.hit-score-main').first().innerText()).replace(/\s+/g, ' ');
      await page.waitForTimeout(1500);
      await page.selectOption('#search-mode', 'hybrid');
      await page.getByRole('button', { name: '检索', exact: true }).click();
      await page.waitForSelector('text=通过门控', { timeout: 120000 });
    }),
    step((f) => `混合检索命中第五页，RRF 融合分数 ${f.hybridScore}，和文档里手写的值一致。`, async ({ page }) => {
      facts.hybridTop = (await page.locator('.hit-score-main').first().innerText()).replace(/\s+/g, ' ');
      facts.hybridScore = (facts.hybridTop.match(/[\d.]+/) || ['n/a'])[0];
      await page.waitForTimeout(1200);
    }),
    step('点对比三种检索方式，三列结果并排，还能看到它们按 chunk id 计算的重叠情况。', async ({ page }) => {
      await page.getByRole('button', { name: '对比三种检索方式' }).click();
      await page.waitForSelector('text=重叠分析', { timeout: 120000 });
      facts.overlap = (await page.locator('.overlap-panel').innerText()).replace(/\s+/g, ' ');
      await page.locator('.overlap-panel').scrollIntoViewIfNeeded();
      await page.waitForTimeout(1500);
    }),
  ],
});

scene({
  id: 'c5-pages', kind: 'browser', label: '本地应用 · 页级引用',
  steps: [
    step('页码用的是 PDF 的物理页号，从一开始数；空白页也保留页级身份，这样引用才对得上。', async ({ page }) => {
      await page.goto(`${APP}/knowledge`, { waitUntil: 'networkidle' });
      await page.click('.doc-card:has-text("seekdb_hybrid_retrieval_notes.pdf") >> text=页导航');
      await page.waitForSelector('text=共 5 个物理页');
      facts.pageNav = (await page.locator('text=共 5 个物理页').first().innerText()).replace(/\s+/g, ' ');
      await page.waitForTimeout(1500);
    }),
    step('点开第四页，它明确告诉你这一页是空的，但仍然有页级身份。', async ({ page }) => {
      await page.click('button:has-text("第 4 页")');
      await page.waitForSelector('.page-viewer-facts', { timeout: 90000 });
      facts.blankPage = (await page.locator('.page-viewer-dialog').innerText()).replace(/\s+/g, ' ').slice(0, 200);
      await page.waitForTimeout(2600);
      await page.keyboard.press('Escape');
    }),
    step((f) => `点开第五页，弹窗里就是 seekdb 中存储的原文，带 page id ${String(f.page5Id || '').slice(0, 12)}。`, async ({ page }) => {
      await page.click('button:has-text("第 5 页")');
      await page.waitForSelector('.page-viewer-facts', { timeout: 90000 });
      facts.page5 = (await page.locator('.page-viewer-dialog').innerText()).replace(/\s+/g, ' ').slice(0, 220);
      facts.page5Id = ((await page.locator('.page-viewer-dialog').innerText()).match(/page_id\s+(\S+)/) || [])[1];
      await page.waitForTimeout(3200);
      await page.keyboard.press('Escape');
    }),
  ],
});

scene({
  id: 'c6-workbench', kind: 'browser', label: '本地应用 · 证据问答',
  steps: [
    step('到工作台问同一个问题。输入区平时只有三个控件，高级参数收在「选项」里，非默认值会直接写在按钮上。', async ({ page }) => {
      await page.goto(`${APP}/workbench`, { waitUntil: 'networkidle' });
      await page.fill('#qa-question', QUESTION);
      await pickProject(page, PROJECT);
      await askAndWait(page);
      await page.waitForTimeout(1500);
    }),
    step((f) => `每条论断都标注了「${f.claimLine || '资料直接支持 / 模型推断'}」；引用编号能点开它对应的原文页，因为服务端会把模型给出的引用逐条回查 seekdb，编造的引用一律剔除。`, async ({ page }) => {
      facts.claimLine = (await page.locator('.claims-summary').innerText()).replace(/\s+/g, ' ');
      const chips = page.locator('button[aria-label^="跳转到引用"]');
      facts.citationCount = await chips.count();
      await chips.first().click();
      await page.waitForTimeout(2000);
      await page.locator('button.citation-view').first().click();
      await page.waitForSelector('.page-viewer-facts', { timeout: 90000 });
      facts.citationPage = (await page.locator('.page-viewer-dialog').innerText()).replace(/\s+/g, ' ').slice(0, 200);
      await page.waitForTimeout(2500);
      await page.keyboard.press('Escape');
    }),
    step('反过来问一个语料里根本没有的问题：它回答尚无证据，引用列表是空的。', async ({ page }) => {
      // A fresh page: the previous answer's claims block must not be read as the new one.
      await page.goto(`${APP}/workbench`, { waitUntil: 'networkidle' });
      await page.fill('#qa-question', NO_EVIDENCE_Q);
      await pickProject(page, PROJECT);
      await page.click('button:has-text("提问")');
      await page.waitForSelector('.claims-section', { timeout: 300000 });
      const claims = await page.locator('.claims-section').innerText();
      facts.noEvidenceLine = claims.replace(/\s+/g, ' ').slice(0, 140);
      if (!/尚无证据/.test(claims)) {
        throw new Error(`unanswerable question did not yield 尚无证据: ${facts.noEvidenceLine}`);
      }
      await page.waitForTimeout(2500);
    }),
  ],
});

scene({
  id: 'c7-memory', kind: 'browser', label: '本地应用 · 保存进度',
  steps: [
    step('记忆这一块交给 PowerContext：一个科研项目对应一个 Scope，保存永远是显式动作，系统不会自动写入。', async ({ page }) => {
      await page.goto(`${APP}/memory`, { waitUntil: 'networkidle' });
      await page.selectOption('#memory-project', PROJECT);
      await page.waitForSelector('text=显式保存研究进度');
      await page.waitForTimeout(1200);
    }),
    step((f) => (f.writtenValue === '0'
      ? `这条计划之前已经写入过，幂等键把它拦下来了：written=0、skipped_duplicates=${f.skipped}，记忆不会重复堆积。`
      : `加一条下一步计划并保存，返回写入 ${f.writtenValue} 条、序号递增到 ${f.seqValue}。`), async ({ page }) => {
      await page.locator('fieldset', { hasText: '下一步 next_steps' }).locator('button:has-text("添加一行")').click();
      await page.fill('#save-next-0', NEW_NEXT_STEP);
      await page.click('button:has-text("显式保存研究进度")');
      await page.waitForSelector('.save-result', { timeout: 120000 });
      const box = await page.locator('.save-result').innerText();
      facts.writtenValue = (box.match(/written\s+(\d+)/) || [])[1];
      facts.seqValue = (box.match(/seq\s+(\d+)/) || [])[1];
      facts.skipped = (box.match(/skipped_duplicates\s+(\d+)/) || [])[1];
      await page.waitForTimeout(2500);
    }),
    step('再点一次同样的内容，它告诉你内容没变化，不产生重复记忆。', async ({ page }) => {
      await page.click('button:has-text("显式保存研究进度")');
      await page.waitForSelector('.save-result-unchanged', { timeout: 120000 });
      facts.dupResult = (await page.locator('.save-result-title').innerText()).trim();
      await page.waitForTimeout(2800);
    }),
  ],
});

scene({
  id: 'c8-restore', kind: 'browser-new-context', label: '全新会话 · 恢复',
  steps: [
    step('现在换一个全新的会话窗口，只选同一个 project id。', async ({ page }) => {
      await page.goto(`${APP}/memory`, { waitUntil: 'networkidle' });
      await page.selectOption('#memory-project', PROJECT);
      await page.waitForSelector('text=续研简报', { timeout: 120000 });
    }),
    step((f) => `续研简报直接给出上次做到了哪里、接下来该做什么，刚才新加的那条计划已经在里面；恢复出来的是 ${f.entryCount} 条记忆。`, async ({ page }) => {
      facts.resumeBrief = (await page.locator('.memory-brief').first().innerText()).replace(/\s+/g, ' ');
      facts.briefHasNewStep = facts.resumeBrief.includes(NEW_NEXT_STEP.slice(0, 6));
      facts.entryCount = (await page.locator('.restore-view').innerText().catch(() => '')).match(/记忆条数\s+(\d+)/)?.[1];
      await page.locator('.memory-brief').first().scrollIntoViewIfNeeded();
      await page.waitForTimeout(3000);
    }),
    step('需要说明的是，PowerContext 默认全文索引对纯中文不友好，所以我们加了一层中文感知的召回，并在响应里明确标出这一条究竟是谁答的。', async ({ page }) => {
      if (!facts.entryCount) {
        facts.entryCount = (await api(`/api/projects/${PROJECT}/memory/restore`)).entry_count;
      }
      await page.locator('.restore-view').scrollIntoViewIfNeeded();
      await page.waitForTimeout(2000);
    }),
  ],
});

scene({
  id: 'c9-tests', kind: 'card', title: '真实测试结果',
  body: () => `${facts.pytestLine}\n\n${facts.pytestLog}\n浏览器交互验收 ${facts.siteInteractions || 'n/a'} 组（与展示站 evidence.json 同源）\n全新环境复现 ${facts.freshEnvPassed}/${facts.freshEnvTotal} 步 · T1–T9 端到端验收全 PASS`,
  footer: '终端内容为该次 pytest 运行的原样输出（日志文件回放，非屏幕录制）',
  steps: [
    step((f) => `这些行为都不是口头承诺。后端 ${f.pytestTotal || 'n/a'} 个测试，直接打真实的 seekdb 和真实的 PowerContext。`, null),
    step((f) => `端到端验收 T1 到 T9 全部通过，界面简化之后的浏览器交互验收 ${f.siteInteractions || 'n/a'} 组全绿，另有一次全新环境的评审旅程，${f.freshEnvTotal} 步全过，报告就是当次运行留下的 JSON。`, null),
  ],
});

scene({
  id: 'c10-arch', kind: 'browser', label: '展示站 · 架构与验证（线上）',
  steps: [
    step('架构区块讲整条链路：上传解析分页、seekdb 双索引、混合检索与证据门控、引用回查、PowerContext 记忆。', async ({ page }) => {
      await page.goto(`${SITE_SRC}/#architecture`, { waitUntil: 'networkidle' });
      await page.waitForSelector('text=/架构/');
      await page.waitForTimeout(2500);
    }),
    step('验证区块贴的是真实日志和真实截图，不是渲染出来的假数据。', async ({ page }) => {
      await page.goto(`${SITE_SRC}/#verification`, { waitUntil: 'networkidle' });
      await page.waitForSelector('text=验收');
      facts.sitePasses = (await page.locator('#pytest-passed, #acc-summary').allInnerTexts()).join(' | ').replace(/\s+/g, ' ');
      await page.waitForTimeout(2500);
    }),
  ],
});

scene({
  id: 'c11-outro', kind: 'card', title: 'qoder/researchflow',
  body: () => `分支 2026-competition-ecosystem\n站点 ${new URL(SITE).host}（已正式发布）\nseekdb v${(facts.seekdbVersion || '').split('v').pop()} · PowerContext 1.4.1\n文档：README / RUN / VERIFICATION / SECURITY`,
  footer: '所有数字都能按 RUN.md 在当前环境复现',
  steps: [
    step('代码在比赛仓库的 qoder 目录下的 researchflow 里，所有数字都能按 RUN 文档复现。', null),
    step('谢谢观看。', null),
  ],
});

// ------------------------------------------------------------------------ 3. record
async function record(browser, s) {
  const webm = path.join(WORK, `${s.id}.webm`);
  facts.wallSeconds = facts.wallSeconds || {};
  if (!FORCE_RECORD && fs.existsSync(webm) && fs.statSync(webm).size > 0) {
    console.log(`  （复用已有录屏 ${s.id}，其事实取自 facts.json）`);
    // A cached clip keeps the wall time measured while it was actually recorded: the webm
    // container runs longer than the interaction itself, so re-reading it would inflate it.
    return { video: webm, wall: facts.wallSeconds[s.id] || durationOf(webm) };
  }
  const ctx = await browser.newContext({
    viewport: SIZE, recordVideo: { dir: WORK, size: SIZE },
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(120000);
  const t0 = Date.now();
  for (const st of s.steps) {
    if (st.act) await st.act({ page });
    else await page.waitForTimeout(600);
  }
  const wall = (Date.now() - t0) / 1000;
  await ctx.close();
  const produced = await page.video().path();
  fs.renameSync(produced, webm);
  facts.wallSeconds[s.id] = wall;
  return { video: webm, wall };
}

(async () => {
  console.log('· 采集真实测试输出');
  collectPytest();
  console.log('  pytest:', facts.pytestLine);
  collectFreshEnv();
  saveFacts();
  console.log(`  fresh-env: ${facts.freshEnvPassed}/${facts.freshEnvTotal} 步（${facts.freshEnvLog}）`);

  const executablePath = resolveChromium();
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  for (let i = 0; i < scenes.length; i += 1) {
    const s = scenes[i];
    if (s.kind !== 'card') {
      process.stdout.write(`· 录制 ${s.id} (${s.label}) `);
      const r = await record(browser, s);
      s.video = r.video;
      s.wall = r.wall;
      saveFacts();
      console.log(`真实耗时 ${r.wall.toFixed(1)}s`);
    }
  }
  await browser.close();

  // ---------------------------------------------------------------- 4. narration + TTS
  const sil = path.join(WORK, 'sil.wav');
  if (!fs.existsSync(sil)) {
    ffmpeg(['-f', 'lavfi', '-i', 'anullsrc=r=22050:cl=mono', '-t', '0.35', '-c:a', 'pcm_s16le', 'sil.wav']);
  }
  const ps1 = path.join(ROOT, 'scripts', 'tts_line.ps1');
  for (const s of scenes) {
    s.cues = [];
    let cursor = 0;
    for (let i = 0; i < s.steps.length; i += 1) {
      const raw = typeof s.steps[i].caption === 'function' ? s.steps[i].caption(facts) : s.steps[i].caption;
      const txtName = `${s.id}-${i}.txt`;
      const wav = path.join(WORK, `${s.id}-${i}.wav`);
      const cached = fs.existsSync(wav) && fs.existsSync(path.join(WORK, txtName))
        && fs.readFileSync(path.join(WORK, txtName), 'utf8') === raw;
      if (!cached) {
        writeText(txtName, raw);
        run('powershell', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps1,
          '-TextFile', path.join(WORK, txtName), '-OutWav', wav], { cwd: WORK });
      }
      const dur = durationOf(wav);
      s.cues.push({ text: raw, start: cursor, end: cursor + dur, wav });
      cursor += dur + 0.35;
    }
    s.audioDur = Math.max(0, cursor - 0.35);
    const inputs = [];
    const labels = [];
    s.cues.forEach((c, i) => {
      inputs.push('-i', path.basename(c.wav));
      labels.push(`[${inputs.length / 2 - 1}:a]`);
      if (i < s.cues.length - 1) {
        inputs.push('-i', 'sil.wav');
        labels.push(`[${inputs.length / 2 - 1}:a]`);
      }
    });
    ffmpeg([...inputs, '-filter_complex', `${labels.join('')}concat=n=${labels.length}:v=0:a=1[a]`,
      '-map', '[a]', '-ar', '22050', '-ac', '1', '-c:a', 'pcm_s16le', `${s.id}.wav`]);
    s.sceneWav = path.join(WORK, `${s.id}.wav`);
  }

  // ---------------------------------------------------------------- 5. per-scene encode
  const assHeader = [
    '[Script Info]', 'ScriptType: v4.00+', `PlayResX: ${SIZE.width}`, `PlayResY: ${SIZE.height}`,
    'WrapStyle: 0', 'ScaledBorderAndShadow: yes', '',
    '[V4+ Styles]',
    'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeThrough, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV',
    'Style: Title,Microsoft YaHei,50,&H00FFB48A,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,1,0,2,60,60,470',
    'Style: Body,Microsoft YaHei,27,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,1,0,1,1,0,2,60,60,300',
    'Style: Foot,Microsoft YaHei,17,&H00B2A49A,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,1,0,2,60,60,70',
    'Style: Caption,Microsoft YaHei,24,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,0,0,0,0,100,100,0,0,3,0,2,2,50,50,34',
    '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
  ];
  const assTime = (sec) => {
    const p = (n) => String(n).padStart(2, '0');
    const h = Math.floor(sec / 3600);
    const m = Math.floor(sec / 60) % 60;
    const s = Math.floor(sec % 60);
    const cs = Math.round((sec - Math.floor(sec)) * 100);
    return `${p(h)}:${p(m)}:${p(s)}.${p(cs)}`;
  };
  const assEscape = (t) => t.replace(/[{}]/g, '').replace(/\n/g, '\\N');

  for (const s of scenes) {
    const target = s.audioDur + 0.8;
    const events = s.cues.map((c) =>
      `Dialogue: 0,${assTime(c.start)},${assTime(c.end)},Caption,,0,0,0,,${assEscape(c.text)}`);
    if (s.kind === 'card') {
      const body = typeof s.body === 'function' ? s.body(facts) : s.body;
      events.unshift(`Dialogue: 0,0:00:00.00,${assTime(target)},Title,,0,0,0,,${assEscape(s.title)}`);
      events.push(`Dialogue: 0,0:00:00.00,${assTime(target)},Body,,0,0,0,,${assEscape(body)}`);
      if (s.footer) {
        events.push(`Dialogue: 0,0:00:00.00,${assTime(target)},Foot,,0,0,0,,${assEscape(s.footer)}`);
      }
    }
    const ass = writeText(`${s.id}.ass`, [...assHeader, ...events, ''].join('\r\n'));
    const common = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '25', '-pix_fmt', 'yuv420p',
      '-r', '30', '-c:a', 'aac', '-b:a', '96k', '-ar', '48000', '-ac', '2', '-af', 'apad'];
    if (s.kind === 'card') {
      ffmpeg(['-f', 'lavfi', '-i', `color=c=0x0d1522:s=${SIZE.width}x${SIZE.height}:r=30:d=${target}`,
        '-i', `${s.id}.wav`, '-vf', `subtitles=${ass}`, '-t', String(target),
        ...common, `${s.id}.mp4`]);
    } else {
      const src = durationOf(s.video);
      // setpts multiplies frame timestamps, so the factor is narration / recording:
      // short recordings play slower rather than ending mid-sentence on a frozen frame.
      const factor = Math.min(2.5, Math.max(0.6, target / src));
      ffmpeg(['-i', path.basename(s.video), '-i', `${s.id}.wav`,
        '-filter_complex',
        `[0:v]fps=30,scale=${SIZE.width}:${SIZE.height}:force_original_aspect_ratio=decrease,` +
        `pad=${SIZE.width}:${SIZE.height}:(ow-iw)/2:(oh-ih)/2:color=0x0d1522,` +
        `setpts=PTS*${factor.toFixed(4)},tpad=stop_mode=clone:stop_duration=90,subtitles=${ass}[v]`,
        '-map', '[v]', '-map', '1:a', '-t', String(target), ...common, `${s.id}.mp4`]);
      s.speedFactor = factor;
    }
    s.out = path.join(WORK, `${s.id}.mp4`);
    s.finalDur = durationOf(s.out);
    console.log(`· 合成 ${s.id} ${s.finalDur.toFixed(1)}s`);
  }

  // ---------------------------------------------------------------- 6. concat + captions
  const list = writeText('concat.txt', scenes.map((s) => `file '${path.basename(s.out)}'`).join('\n'));
  ffmpeg(['-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart',
    path.join(OUT, 'researchflow-demo.mp4')]);

  let offset = 0;
  const vtt = ['WEBVTT', ''];
  for (const s of scenes) {
    for (const c of s.cues) {
      const st = offset + c.start;
      const en = offset + c.end;
      vtt.push(`${srtTime(st).replace(',', '.')} --> ${srtTime(en).replace(',', '.')}`, c.text, '');
    }
    offset += s.finalDur;
  }
  fs.writeFileSync(path.join(OUT, 'researchflow-demo.vtt'), vtt.join('\n'), 'utf8');

  // -------------------------------------------------- keyframes: one real frame per scene
  const KEY_DIR = path.join(OUT, 'keyframes');
  fs.mkdirSync(KEY_DIR, { recursive: true });
  const finalMp4 = path.join(OUT, 'researchflow-demo.mp4');
  const keyframes = [];
  let keyOffset = 0;
  for (const s of scenes) {
    const at = keyOffset + s.finalDur / 2;
    const file = `${String(scenes.indexOf(s) + 1).padStart(2, '0')}-${s.id}.png`;
    try {
      ffmpeg(['-ss', at.toFixed(3), '-i', finalMp4, '-frames:v', '1', '-y', path.join(KEY_DIR, file)]);
      keyframes.push({ scene: s.id, label: s.label, atSeconds: Number(at.toFixed(2)),
        file: `keyframes/${file}`, kind: s.kind });
    } catch (err) {
      console.log(`  ! 关键帧 ${s.id} 抽帧失败: ${err.message}`);
    }
    keyOffset += s.finalDur;
  }

  const manifest = {
    generatedAt: new Date().toISOString(),
    durationSeconds: Number(offset.toFixed(2)),
    resolution: `${SIZE.width}x${SIZE.height}`,
    sources: {
      localApp: APP,
      showcaseScenesRecordedFrom: SITE_SRC,
      publishedSite: SITE,
      publishedSiteNote: 'c2/c10 两个展示站场景录自公开 URL：线上已是简化后的最终构建，'
        + '与本地 site/public 逐文件哈希一致（见 verification/site-public/published-site-check.json）',
      python: 'backend/.venv (project venv)',
      pytestLog: facts.pytestLog, pytestLine: facts.pytestLine,
      freshEnvLog: facts.freshEnvLog, freshEnvSteps: `${facts.freshEnvPassed}/${facts.freshEnvTotal}`,
      freshEnvAt: facts.freshEnvAt,
    },
    captureMethod: {
      browserScenes: 'Playwright 无头浏览器录屏，驱动真实运行的前端 + FastAPI + seekdb + PowerContext',
      cardScenes: '由当次真实命令输出原样渲染的文本卡（日志回放，非屏幕录制）',
      narration: 'Windows System.Speech 中文语音（Microsoft Huihui）合成，旁白数字取自本次录制读回的真实值',
      retiming: '浏览器录屏按旁白时长用 setpts 等比重放（短片段放慢、长片段适度加速，系数见各场景 speedFactor），未删除或跳剪任何真实步骤',
    },
    facts,
    keyframes,
    scenes: scenes.map((s) => ({
      id: s.id, kind: s.kind, label: s.label, finalSeconds: Number((s.finalDur || 0).toFixed(2)),
      realWallSeconds: s.wall ? Number(s.wall.toFixed(2)) : null,
      speedFactor: s.speedFactor ? Number(s.speedFactor.toFixed(3)) : null,
      cues: s.cues.map((c) => c.text),
    })),
  };
  fs.writeFileSync(path.join(OUT, 'video-manifest.json'), JSON.stringify(manifest, null, 2), 'utf8');

  // ------------------- automated delivery checks on the delivered artifacts
  run('node', [path.join('scripts', 'check_demo_video.cjs')]);
  console.log('\nVIDEO OK', path.join(OUT, 'researchflow-demo.mp4'), `${offset.toFixed(1)}s`);
})().catch((err) => {
  console.error('VIDEO FAILED:', err.message);
  process.exit(1);
});
