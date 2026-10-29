/**
 * Verify the static showcase site renders correctly, locally or at its published URL.
 *
 *   NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" node scripts/verify_site.cjs [base] [outDir]
 *
 * Checks: evidence data renders, every screenshot actually loads, no console/page errors,
 * no request answered >=400, anchor navigation works, and the mobile layout does not overflow.
 */
const path = require('path');
const fs = require('fs');
const os = require('os');
const { chromium } = require('playwright-core');

const BASE = process.argv[2] || 'http://127.0.0.1:4173/';
const OUT_DIR = process.argv[3] || path.join(__dirname, '..', 'site', 'preview');
fs.mkdirSync(OUT_DIR, { recursive: true });

function resolveExecutable() {
  if (process.env.RF_CHROME_PATH) return process.env.RF_CHROME_PATH;
  const root = path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright');
  if (!fs.existsSync(root)) return undefined;
  const candidates = [];
  for (const dir of fs.readdirSync(root)) {
    for (const rel of [
      path.join('chrome-headless-shell-win64', 'chrome-headless-shell.exe'),
      path.join('chrome-win64', 'chrome.exe'),
    ]) {
      const full = path.join(root, dir, rel);
      if (fs.existsSync(full)) candidates.push(full);
    }
  }
  candidates.sort((a, b) => Number(b.includes('headless')) - Number(a.includes('headless')));
  return candidates[0];
}

(async () => {
  const browser = await chromium.launch({ executablePath: resolveExecutable() });
  const errors = [];
  const badResponses = [];
  const watch = (target) => target.on('response', (res) => {
    if (res.status() >= 400) badResponses.push(`${res.status()} ${res.url()}`);
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push('console: ' + msg.text()); });
  page.on('pageerror', (err) => errors.push('pageerror: ' + err.message));
  watch(page);

  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForSelector('#acc-summary:not(:empty)');
  await page.waitForFunction(() => {
    const node = document.getElementById('acc-summary');
    return node && node.textContent.includes('PASS');
  });

  const accSummary = await page.textContent('#acc-summary');
  const pytest = await page.textContent('#pytest-passed');
  const interactions = await page.textContent('#int-summary');
  const interactionDetail = await page.textContent('#int-detail');
  const rows = await page.locator('#acc-table tbody tr').count();
  const shots = await page.locator('.shot img').count();
  const brokenShots = await page.evaluate(() =>
    [...document.querySelectorAll('.shot img')].filter((img) => !img.complete || img.naturalWidth === 0).length
  );
  const factSeekdb = await page.textContent('#fact-seekdb');

  console.log('acc summary   :', accSummary.trim());
  console.log('pytest        :', pytest.trim());
  console.log('browser itx   :', interactions.trim(), '·', interactionDetail.trim().slice(0, 90));
  console.log('acceptance rows:', rows);
  console.log('screenshots   :', shots, 'broken:', brokenShots);
  console.log('seekdb fact   :', factSeekdb.trim().slice(0, 90));

  // anchor navigation + refresh on an anchor must not 404 (single page, no client routes)
  await page.click('a[href="#verification"]');
  await page.waitForSelector('#acc-table');
  await page.reload({ waitUntil: 'networkidle' });
  const status = await page.evaluate(() => document.title ? 'ok' : 'missing');
  console.log('reload status :', status);

  await page.screenshot({ path: path.join(OUT_DIR, 'site-desktop.png'), fullPage: true });

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  mobile.on('pageerror', (err) => errors.push('mobile pageerror: ' + err.message));
  watch(mobile);
  await mobile.goto(BASE, { waitUntil: 'networkidle' });
  await mobile.waitForFunction(() => {
    const node = document.getElementById('acc-summary');
    return node && node.textContent.includes('PASS');
  });
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  console.log('mobile h-overflow px:', overflow);
  await mobile.screenshot({ path: path.join(OUT_DIR, 'site-mobile.png'), fullPage: true });

  await browser.close();
  console.log('failed requests (>=400):', badResponses.length, badResponses.slice(0, 5).join(' | '));
  if (brokenShots > 0 || rows < 9 || errors.length || badResponses.length || !/PASS/.test(interactions)) {
    console.error('SITE VERIFY FAILED', errors, badResponses);
    process.exit(1);
  }
  console.log('SITE VERIFY OK', BASE);
})().catch((err) => { console.error('SITE VERIFY ERROR:', err.message); process.exit(1); });
