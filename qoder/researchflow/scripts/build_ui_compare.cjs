/**
 * Build a before/after contact sheet for a UI round.
 *
 * Left column = the saved "before" screenshots, right column = the current ones. Nothing is
 * drawn or composited by hand: the browser lays out two real PNG files and screenshots them.
 *
 *   NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" node scripts/build_ui_compare.cjs
 *
 * Defaults compare the committed pre-refactor shots against site/public/shots. A later round
 * overrides all four inputs, e.g. the simplification pass:
 *   RF_COMPARE_BEFORE=.../compare/ui-before-simplify RF_COMPARE_AFTER=.../browser-acceptance/responsive \
 *   RF_COMPARE_LABELS=home-1280-light.png,chat-1280-light.png RF_COMPARE_TITLE=... RF_COMPARE_NOTE=...
 */
const path = require('path');
const fs = require('fs');
const os = require('os');
const { chromium } = require('playwright-core');

const ROOT = path.join(__dirname, '..');
const dir = (...parts) => path.join(ROOT, 'verification', 'browser-acceptance', ...parts);
const BEFORE = process.env.RF_COMPARE_BEFORE
  ? path.resolve(process.env.RF_COMPARE_BEFORE)
  : dir('compare', 'ui-before-refactor');
const AFTER = process.env.RF_COMPARE_AFTER
  ? path.resolve(process.env.RF_COMPARE_AFTER)
  : path.join(ROOT, 'site', 'public', 'shots');
const OUT = process.env.RF_COMPARE_OUT ? path.resolve(process.env.RF_COMPARE_OUT) : dir('compare');
const BEFORE_CAPTION = process.env.RF_COMPARE_BEFORE_CAPTION || '重构前（已提交版本）';
const AFTER_CAPTION = process.env.RF_COMPARE_AFTER_CAPTION || '重构后（本轮真实运行）';

const DEFAULT_PAIRS = [
  { file: 's1-overview.png', label: '首页 / 对话入口', width: 1440 },
  { file: 's6-workbench.png', label: '证据问答：论断分级 + 可点引用', width: 1440 },
  { file: 's5-retrieval.png', label: '检索与证据面板', width: 1440 },
  { file: 's2-resume-brief.png', label: '跨会话续研简报', width: 1440 },
  { file: 's7-memory.png', label: '研究进度 / 记忆', width: 1440 },
  { file: 's10-verification.png', label: '验证页（本轮新增路由）', width: 1440 },
  { file: 's8-mobile-overview.png', label: '移动端 390px 首页', width: 390 },
  { file: 's9-mobile-knowledge.png', label: '移动端 390px 知识库', width: 390 },
];

const PAIRS = process.env.RF_COMPARE_LABELS
  ? process.env.RF_COMPARE_LABELS.split(',').map((file) => ({ file: file.trim(), label: file.trim(), width: 0 }))
  : DEFAULT_PAIRS;

function resolveExecutable() {
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
  found.sort((a, b) => Number(b.includes('headless')) - Number(a.includes('headless')));
  return found[0];
}

const cell = (dir, pair, prefix, missingLabel) => {
  const file = path.join(dir, pair.file);
  if (!fs.existsSync(file)) {
    return `<div class="cell empty">${missingLabel}</div>`;
  }
  return `<div class="cell"><img src="${encodeURIComponent(
    `${prefix}-${pair.file}`
  )}" alt="${pair.label}" /></div>`;
};

function sheet(pairs, title, note, beforeCaption, afterCaption) {
  const rows = pairs
    .map(
      (pair) => `<section class="row">
      <h2>${pair.label}<span class="dim"> · ${pair.file}</span></h2>
      <div class="cols">
        <figure>${cell(BEFORE, pair, 'before', '这一侧没有该截图')}<figcaption>${beforeCaption}</figcaption></figure>
        <figure>${cell(AFTER, pair, 'after', '缺少当前截图')}<figcaption>${afterCaption}</figcaption></figure>
      </div>
    </section>`
    )
    .join('\n');
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${title}</title>
<style>
  body{margin:0;padding:24px;background:#f4f5f7;font-family:"Segoe UI","Microsoft YaHei",sans-serif;color:#1c1f24}
  h1{font-size:22px;margin:0 0 6px}
  .note{font-size:13px;color:#5b6270;margin:0 0 22px}
  .row{margin-bottom:28px}
  h2{font-size:15px;margin:0 0 8px}
  .dim{color:#8b929e;font-weight:400;font-size:12px}
  .cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start}
  figure{margin:0;background:#fff;border:1px solid #dfe2e8;border-radius:10px;padding:8px}
  figcaption{font-size:12px;color:#5b6270;padding:6px 2px 0}
  img{display:block;width:100%;height:auto;border-radius:6px}
  .cell.empty{display:flex;align-items:center;justify-content:center;height:180px;color:#8b929e;font-size:13px;background:#fafbfc;border:1px dashed #dfe2e8;border-radius:6px}
</style></head><body>
<h1>${title}</h1><p class="note">${note}</p>${rows}</body></html>`;
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const executablePath = resolveExecutable();
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const generated = [];
  const groups = process.env.RF_COMPARE_LABELS
    ? [
        {
          name: process.env.RF_COMPARE_OUT_NAME || 'ui-compare.png',
          pairs: PAIRS,
          title: process.env.RF_COMPARE_TITLE || '界面截图前后对比',
        },
      ]
    : [
        {
          name: 'ui-refactor-compare-desktop.png',
          pairs: PAIRS.filter((p) => p.width === 1440),
          title: 'ResearchFlow 界面重构前后对比（桌面 1440px）',
        },
        {
          name: 'ui-refactor-compare-mobile.png',
          pairs: PAIRS.filter((p) => p.width === 390),
          title: 'ResearchFlow 界面重构前后对比（移动 390px）',
        },
      ];
  for (const group of groups) {
    const tmp = path.join(OUT, '_compare-tmp');
    fs.mkdirSync(tmp, { recursive: true });
    for (const pair of group.pairs) {
      for (const [base, prefix] of [[BEFORE, 'before'], [AFTER, 'after']]) {
        const src = path.join(base, pair.file);
        if (fs.existsSync(src)) fs.copyFileSync(src, path.join(tmp, `${prefix}-${pair.file}`));
      }
    }
    const html = path.join(tmp, 'sheet.html');
    fs.writeFileSync(
      html,
      sheet(
        group.pairs,
        group.title,
        process.env.RF_COMPARE_NOTE ||
          '两侧都是真实浏览器截图：左为重构前已提交版本，右为重构后当前运行；未做任何图像合成或修饰。',
        BEFORE_CAPTION,
        AFTER_CAPTION
      ),
      'utf8'
    );
    const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
    await page.goto('file:///' + html.replace(/\\/g, '/'), { waitUntil: 'networkidle' });
    await page.waitForFunction(() => [...document.images].every((i) => i.complete));
    await page.screenshot({ path: path.join(OUT, group.name), fullPage: true });
    await page.close();
    fs.rmSync(tmp, { recursive: true, force: true });
    generated.push(group.name);
    console.log('wrote', group.name, group.pairs.length, 'pairs');
  }
  await browser.close();
  console.log('COMPARE OK', generated.join(', '));
})().catch((err) => {
  console.error('COMPARE FAILED:', err.message);
  process.exit(1);
});
