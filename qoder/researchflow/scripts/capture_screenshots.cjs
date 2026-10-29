/**
 * Capture real runtime screenshots of the ResearchFlow app for the competition site.
 *
 * Requires the backend (8787) with seeded demo data. Uses the Chromium that ships with the
 * globally installed Playwright CLI; NODE_PATH must include its node_modules, e.g.
 *
 *   NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" node scripts/capture_screenshots.cjs
 *
 * Every shot is a real page of the running product - nothing is mocked or composited.
 */
const path = require('path');
const fs = require('fs');
const os = require('os');
const { chromium } = require('playwright-core');

const BASE = process.env.RF_SHOT_BASE || 'http://127.0.0.1:8787';
const OUT = path.join(__dirname, '..', 'site', 'public', 'shots');
const PROJECT_TITLE = 'seekdb 混合检索在科研知识库中的效果验证';
const QUESTION = '根据文档，一条记录如果在两条腿里都排第一，RRF 融合分数是多少？';

/** The bundled playwright-core and the locally installed browsers may disagree on the
 *  revision number; prefer an explicit path, then any installed chromium build. */
function resolveExecutable() {
  if (process.env.RF_CHROME_PATH) return process.env.RF_CHROME_PATH;
  const root = path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright');
  if (!fs.existsSync(root)) return undefined;
  const candidates = [];
  for (const dir of fs.readdirSync(root)) {
    for (const rel of [
      path.join('chrome-headless-shell-win64', 'chrome-headless-shell.exe'),
      path.join('chrome-win64', 'chrome.exe'),
      path.join('chrome-win', 'chrome.exe'),
    ]) {
      const full = path.join(root, dir, rel);
      if (fs.existsSync(full)) candidates.push(full);
    }
  }
  candidates.sort((a, b) => Number(b.includes('headless')) - Number(a.includes('headless')));
  return candidates[0];
}

async function shot(page, name, options = {}) {
  const file = path.join(OUT, name);
  await page.screenshot({ path: file, ...options });
  console.log('shot', name);
}

async function selectOption(page, value) {
  await page.evaluate((v) => {
    const sel = [...document.querySelectorAll('select')].find((s) =>
      [...s.options].some((o) => o.value === v)
    );
    if (!sel) throw new Error('select not found for ' + v);
    const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
    setter.call(sel, v);
    sel.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
}

(async () => {
  const executablePath = resolveExecutable();
  console.log('chromium executable:', executablePath || '(playwright default)');
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(60000);

  // 1 overview
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.waitForSelector('text=后端健康状态');
  await shot(page, 's1-overview.png');

  // 2 project resume brief
  await page.click(`text=${PROJECT_TITLE}`);
  await page.waitForSelector('text=记忆条数');
  await page.locator('text=续研简报 resume_brief').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await shot(page, 's2-resume-brief.png');

  // 3 page navigator with the blank page
  await page.goto(BASE + '/knowledge', { waitUntil: 'networkidle' });
  await page.click(`tr:has-text("seekdb_hybrid_retrieval_notes.pdf") >> text=页导航`);
  await page.waitForSelector('text=空白页（保留页级身份）');
  await page.locator('text=共 5 个物理页').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await shot(page, 's3-page-navigator.png');

  // 4 stored original page in the viewer
  await page.click('button:has-text("第 5 页")');
  await page.waitForSelector('text=页面原文');
  await page.waitForTimeout(400);
  await shot(page, 's4-page-viewer.png');
  await page.keyboard.press('Escape');

  // 5 gated retrieval result
  await page.fill('textarea', QUESTION.replace('是多少', '是多少'));
  await page.locator('textarea').first().fill('一条记录如果在两条腿里都排第一，RRF 融合分数是多少');
  await page.click('text=启用证据门控');
  await page.click('button:has-text("检 索"), button:has-text("检索")');
  await page.waitForSelector('text=通过门控');
  await page.locator('text=命中').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await shot(page, 's5-retrieval.png');

  // 6 grounded QA with claims and the memory channel
  await page.goto(BASE + '/workbench', { waitUntil: 'networkidle' });
  await page.locator('textarea').first().fill(QUESTION);
  await selectOption(page, 'demo-seekdb-hybrid');
  await page.click('button:has-text("提 问"), button:has-text("提问")');
  await page.waitForSelector('text=论断核验');
  await page.waitForTimeout(800);
  await shot(page, 's6-workbench.png', { fullPage: true });

  // 7 memory page restore
  await page.goto(BASE + '/memory', { waitUntil: 'networkidle' });
  await selectOption(page, 'demo-seekdb-hybrid');
  await page.waitForSelector('text=记忆条数');
  await page.waitForTimeout(500);
  await shot(page, 's7-memory.png', { fullPage: true });

  // 8 mobile layout
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(BASE + '/', { waitUntil: 'networkidle' });
  await mobile.waitForSelector('text=后端健康状态');
  await shot(mobile, 's8-mobile-overview.png');
  await mobile.goto(BASE + '/knowledge', { waitUntil: 'networkidle' });
  await mobile.waitForSelector('text=文档列表');
  await shot(mobile, 's9-mobile-knowledge.png');

  await browser.close();
  console.log('SCREENSHOTS OK');
})().catch((err) => {
  console.error('SHOT FAILED:', err.message);
  process.exit(1);
});
