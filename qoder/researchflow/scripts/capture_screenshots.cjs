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
const PROJECT = 'demo-seekdb-hybrid';
const PDF_NAME = 'seekdb_hybrid_retrieval_notes.pdf';
const QUESTION = '根据文档，一条记录如果在两条腿里都排第一，RRF 融合分数是多少？';
const SEARCH_Q = '一条记录如果在两条腿里都排第一，RRF 融合分数是多少';

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

// 输入区的次要控件默认折叠，展开之后 #qa-project 才会出现在 DOM 里。
async function openComposerOptions(page) {
  const chip = page.locator('.composer-bar button[aria-expanded]');
  if ((await chip.getAttribute('aria-expanded')) !== 'true') await chip.click();
  await page.waitForSelector('#qa-project', { state: 'visible' });
}

(async () => {
  const executablePath = resolveExecutable();
  console.log('chromium executable:', executablePath || '(playwright default)');
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.setDefaultTimeout(60000);

  // 1 chat home
  await page.goto(BASE + '/', { waitUntil: 'networkidle' });
  await page.waitForSelector('text=每个回答');
  await shot(page, 's1-overview.png');

  // 2 cross-session resume brief (PowerContext)
  await page.goto(BASE + '/memory', { waitUntil: 'networkidle' });
  await selectOption(page, PROJECT);
  await page.waitForSelector('text=续研简报', { timeout: 120000 });
  await page.waitForSelector('.memory-brief');
  await page.locator('.memory-brief').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(500);
  await shot(page, 's2-resume-brief.png');

  // 3 page navigator with the blank page
  await page.goto(BASE + '/knowledge', { waitUntil: 'networkidle' });
  await page.click(`.doc-card:has-text("${PDF_NAME}") >> text=页导航`);
  await page.waitForSelector('text=空白页（保留页级身份）');
  await page.locator('text=共 5 个物理页').first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await shot(page, 's3-page-navigator.png');

  // 4 stored original page in the viewer
  await page.click('button:has-text("第 5 页")');
  await page.waitForSelector('text=页面原文');
  await page.waitForTimeout(500);
  await shot(page, 's4-page-viewer.png');
  await page.keyboard.press('Escape');

  // 5 gated retrieval result with the evidence panel
  await page.fill('#search-query', SEARCH_Q);
  await page.click('text=启用证据门控');
  await page.getByRole('button', { name: '检索', exact: true }).click();
  await page.waitForSelector('text=通过门控', { timeout: 120000 });
  await page.locator('.result-meta').scrollIntoViewIfNeeded();
  await page.waitForTimeout(400);
  await shot(page, 's5-retrieval.png');

  // 6 grounded QA with claims, citations and the memory channel
  // The hosted LLM intermittently holds a request open for minutes; resubmit once from a
  // clean page rather than aborting a run that already captured five scenes.
  let askErr;
  for (let attempt = 1; attempt <= 2; attempt++) {
    await page.goto(BASE + '/workbench', { waitUntil: 'networkidle' });
    await openComposerOptions(page);
    await page.fill('#qa-question', QUESTION);
    await selectOption(page, PROJECT);
    await page.click('button:has-text("提问")');
    try {
      await page.waitForSelector('.claims-section', { timeout: 300000 });
      askErr = null;
      break;
    } catch (err) {
      askErr = err;
      const shown = await page.locator('.error-state, .banner-red').allInnerTexts().catch(() => []);
      console.log(`  ! 第 ${attempt} 次提问没有返回论断区块`, shown.join(' / ').slice(0, 200));
      await page.waitForTimeout(2000);
    }
  }
  if (askErr) throw askErr;
  await page.waitForTimeout(1200);
  await shot(page, 's6-workbench.png', { fullPage: true });

  // 7 memory page: explicit save form, restore and history
  await page.goto(BASE + '/memory', { waitUntil: 'networkidle' });
  await selectOption(page, PROJECT);
  await page.waitForSelector('text=记忆条数', { timeout: 120000 });
  await page.waitForTimeout(800);
  await shot(page, 's7-memory.png', { fullPage: true });

  // 8 live backend health and counts
  await page.goto(BASE + '/verification', { waitUntil: 'networkidle' });
  await page.waitForSelector('text=后端健康状态');
  await page.waitForSelector('text=seekdb server_version');
  await page.waitForTimeout(600);
  await shot(page, 's10-verification.png', { fullPage: true });

  // 9 mobile layout
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(BASE + '/', { waitUntil: 'networkidle' });
  await mobile.waitForSelector('text=每个回答');
  await shot(mobile, 's8-mobile-overview.png');
  await mobile.goto(BASE + '/knowledge', { waitUntil: 'networkidle' });
  await mobile.waitForSelector('text=文档列表');
  await shot(mobile, 's9-mobile-knowledge.png');

  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  console.log('desktop viewport', overflow);
  if (overflow.scrollWidth > overflow.clientWidth + 1) {
    throw new Error('desktop layout overflows horizontally');
  }

  // 移动端每个路由都必须真正放得下：抽屉本身按设计在画布外，检查时排除。
  const mobileRoutes = ['/', '/knowledge', '/memory', '/workbench', '/verification', '/architecture'];
  for (const route of mobileRoutes) {
    await mobile.goto(BASE + route, { waitUntil: 'networkidle' });
    const check = await mobile.evaluate(() => {
      const w = document.documentElement.clientWidth;
      const out = [];
      const scrollers = [];
      if (document.documentElement.scrollWidth > w) {
        out.push({ node: 'html', scrollWidth: document.documentElement.scrollWidth });
      }
      // 宽表格在 .table-scroll 里横向滚动是设计：被滚动容器包住的元素不算溢出。
      const scrollsInside = (el) => {
        let node = el.parentElement;
        while (node) {
          const ox = getComputedStyle(node).overflowX;
          if (ox === 'auto' || ox === 'scroll') return true;
          node = node.parentElement;
        }
        return false;
      };
      document.querySelectorAll('.view, .view *').forEach((el) => {
        const cs = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.right > w + 1 && !scrollsInside(el)) {
          out.push({ node: el.tagName.toLowerCase() + '.' + String(el.className).trim().replace(/\s+/g, '.'), right: Math.round(r.right) });
        }
        if ((cs.overflowX === 'auto' || cs.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 1) {
          scrollers.push({ node: 'scroll:' + String(el.className).trim().replace(/\s+/g, '.'), scrollWidth: el.scrollWidth, clientWidth: el.clientWidth });
        }
      });
      // 中文可逐字断行：面板标题一旦被压成一列一个字，就是布局塌了。
      let names = 0;
      document.querySelectorAll('.panel-name').forEach((el) => {
        names += 1;
        const cs = getComputedStyle(el);
        const lh = parseFloat(cs.lineHeight);
        const line = Number.isFinite(lh) ? lh : parseFloat(cs.fontSize) * 1.5;
        const lines = el.getBoundingClientRect().height / line;
        if (lines > 1.6) {
          out.push({ node: 'panel-name:' + (el.textContent || '').trim().slice(0, 12), lines: Math.round(lines * 10) / 10 });
        }
      });
      return { bad: out, scrollers, names };
    });
    if (check.bad.length) {
      throw new Error(`mobile overflow on ${route}: ${JSON.stringify(check.bad.slice(0, 6))}`);
    }
    console.log(
      'mobile fits', route,
      '· panel 标题检查', check.names, '个',
      '· 容器内横向滚动', check.scrollers.length, '处',
      check.scrollers.length ? JSON.stringify(check.scrollers.slice(0, 3)) : ''
    );
  }

  await browser.close();
  console.log('SCREENSHOTS OK');
})().catch((err) => {
  console.error('SHOT FAILED:', err.message);
  process.exit(1);
});
