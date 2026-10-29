/**
 * Capture the real running app at 390 / 768 / 1280 / 1920 px and write a machine-readable
 * manifest next to the images. Nothing is composited: every file is a screenshot of a page
 * the browser actually rendered against the live backend.
 *
 *   NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" node scripts/capture_responsive_matrix.cjs
 */
const path = require('path');
const fs = require('fs');
const os = require('os');
const { chromium } = require('playwright-core');

const BASE = process.env.RF_SHOT_BASE || 'http://127.0.0.1:8787';
const OUT = path.join(__dirname, '..', 'verification', 'browser-acceptance', 'responsive');
const QUESTION = '根据文档，一条记录如果在两条腿里都排第一，RRF 融合分数是多少？';
const ROUTES = [
  { route: '/', slug: 'home', landmark: 'text=每个回答' },
  { route: '/workbench', slug: 'chat', landmark: '.chat-scroll' },
  { route: '/knowledge', slug: 'knowledge', landmark: 'text=文档列表' },
  { route: '/memory', slug: 'memory', landmark: 'text=研究进度' },
  { route: '/verification', slug: 'verification', landmark: 'text=后端健康状态' },
  { route: '/architecture', slug: 'architecture', landmark: 'text=架构与接口' },
];
const WIDTHS = [
  { width: 390, height: 844 },
  { width: 768, height: 1024 },
  { width: 1280, height: 800 },
  { width: 1920, height: 1080 },
];

function resolveExecutable() {
  if (process.env.RF_CHROME_PATH) return process.env.RF_CHROME_PATH;
  const root = path.join(os.homedir(), 'AppData', 'Local', 'ms-playwright');
  if (!fs.existsSync(root)) return undefined;
  const found = [];
  for (const dir of fs.readdirSync(root)) {
    for (const rel of [
      path.join('chrome-headless-shell-win64', 'chrome-headless-shell.exe'),
      path.join('chrome-win64', 'chrome.exe'),
      path.join('chrome-win', 'chrome.exe'),
    ]) {
      const full = path.join(root, dir, rel);
      if (fs.existsSync(full)) found.push(full);
    }
  }
  found.sort((a, b) => Number(b.includes('headless')) - Number(a.includes('headless')));
  return found[0];
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const executablePath = resolveExecutable();
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);

  // 一次真实问答，之后所有宽度都回放同一段对话：截图里的内容是接口真返回的。
  await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
  await page.click('#qa-question');
  await page.keyboard.type(QUESTION);
  await page.keyboard.press('Enter');
  await page.waitForSelector('.claims-section', { timeout: 300000 });
  const sessionUrl = new URL(page.url()).pathname + new URL(page.url()).search;
  const answerChars = await page.$eval('.claims-section', (el) => el.innerText.replace(/\s+/g, ' ').length);
  console.log(`真实问答已落位：${sessionUrl} · 论断区块 ${answerChars} 字`);

  const manifest = { captured_at: new Date().toISOString(), target: BASE, session: sessionUrl, shots: [] };
  for (const { width, height } of WIDTHS) {
    await page.setViewportSize({ width, height });
    await page.waitForTimeout(260);
    for (const theme of ['light', 'dark']) {
      await page.evaluate((mode) => localStorage.setItem('rf-theme', mode), theme);
      for (const { route, slug, landmark } of ROUTES) {
        const target = route === '/workbench' ? sessionUrl : route;
        await page.goto(BASE + target, { waitUntil: 'networkidle' });
        try {
          await page.waitForSelector(landmark, { timeout: 30000 });
        } catch {
          console.log(`  ! ${width}px ${route} 落位标志未出现`);
        }
        await page.waitForTimeout(320);
        const name = `${slug}-${width}-${theme}.png`;
        await page.screenshot({ path: path.join(OUT, name), fullPage: false });
        const geometry = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
        }));
        const overflow = geometry.scrollWidth - geometry.clientWidth;
        manifest.shots.push({ file: name, width, theme, route, ...geometry, overflow_px: overflow });
        if (overflow > 1) console.log(`  ! 横向溢出 ${overflow}px：${width}px ${route} ${theme}`);
      }
    }
  }
  await page.evaluate(() => localStorage.removeItem('rf-theme'));
  fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2), 'utf8');
  const bad = manifest.shots.filter((s) => s.overflow_px > 1);
  console.log(`截图 ${manifest.shots.length} 张 · 溢出 ${bad.length} 张 · 输出 ${OUT}`);
  await browser.close();
  if (bad.length) process.exit(1);
})().catch((err) => {
  console.error('RESPONSIVE CAPTURE FAILED:', err.message);
  process.exit(1);
});
