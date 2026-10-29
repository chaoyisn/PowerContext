/**
 * Real-browser interaction acceptance for the ResearchFlow app (evidence class: automated).
 *
 * Every case performs the actual user gesture — click, keyboard type, Enter, Shift+Enter,
 * file selection, upload, save, reload — and then asserts on what the page really rendered,
 * cross-checked against the API response the browser itself received. A case that only
 * proves an element exists in the DOM is not accepted as evidence here.
 *
 *   NODE_PATH="$(npm root -g)/@playwright/cli/node_modules" node scripts/verify_interactions.cjs
 *
 * Requires the backend on 8787 with the seeded demo corpus plus a reachable LLM for the QA case.
 * Bounded side effects: one throwaway document (deleted again at the end) and one progress save
 * into a dedicated project named 浏览器交互验收 · 自动 — never into the demo project.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright-core');

const BASE = process.env.RF_APP_BASE || 'http://127.0.0.1:8787';
const OUT = path.join(__dirname, '..', 'verification', 'browser-acceptance');
const PROJECT_TITLE = '浏览器交互验收 · 自动';
const DEMO_PDF = path.join(__dirname, '..', 'demo', 'seekdb_hybrid_retrieval_notes.pdf');
const QUESTION = '根据文档，一条记录如果在两条腿里都排第一，RRF 融合分数是多少？';
const RETRIEVAL_Q = 'RRF 融合分数 排名';
// 固定文案：重复运行应当命中去重，而不是每次往 PowerContext 里堆新记忆。
const MEM_OBJECTIVE = '浏览器交互验收专用项目（automated），用于验证显式保存与跨会话恢复真实生效。';
const MEM_DECISION = 'D-ITX — 验收期间不修改证据门控阈值，保持 coverage 0.30 / semantic 0.62';
const MEM_NEXT = 'ITX-NEXT — 复核引用高亮与证据抽屉的开合状态';
const WIDTHS = [390, 768, 1280, 1920];
const ROUTES = ['/', '/workbench', '/knowledge', '/memory', '/verification', '/architecture'];
const LANDMARKS = {
  '/': '.composer',
  '/workbench': '.composer',
  '/knowledge': '#search-query',
  '/memory': '#memory-project',
  '/verification': 'text=后端健康状态',
  // SPA 里 /docs 归 FastAPI 的 Swagger，站内架构页是 /architecture。
  '/architecture': 'text=架构与接口',
};

/** The bundled playwright-core and the locally installed browsers may disagree on revision. */
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

const results = [];
async function testCase(name, fn) {
  const started = Date.now();
  try {
    await fn();
    results.push({ name, ok: true, ms: Date.now() - started });
    console.log(`PASS  ${name}  (${Date.now() - started}ms)`);
  } catch (err) {
    const full = String((err && err.stack) || (err && err.message) || err);
    const message = full.split('\n')[0].slice(0, 260);
    results.push({ name, ok: false, error: message, detail: full.slice(0, 1600), ms: Date.now() - started });
    console.log(`FAIL  ${name}  -> ${message}`);
    for (const line of full.split('\n').slice(1, 4)) {
      if (line.trim()) console.log(`        ${line.trim().slice(0, 200)}`);
    }
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function flat(text) {
  return String(text || '').replace(/\s+/g, ' ').trim();
}

/** React keeps the DOM value behind a native setter; use it for programmatic typing. */
async function typeInto(page, selector, value) {
  await page.evaluate(
    ({ selector, value }) => {
      const el = document.querySelector(selector);
      const proto =
        el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
      el.dispatchEvent(new Event('input', { bubbles: true }));
    },
    { selector, value }
  );
}

// 输入区的次要控件默认折叠，展开之后 #qa-project / .composer-switch 才会进入 DOM。
async function openComposerOptions(page) {
  const chip = page.locator('.composer-bar button[aria-expanded]');
  if ((await chip.getAttribute('aria-expanded')) !== 'true') await chip.click();
  await page.waitForSelector('#qa-project', { state: 'visible' });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const executablePath = resolveExecutable();
  console.log('chromium executable:', executablePath || '(playwright default)');
  console.log('target:', BASE);

  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);

  const reqCount = new Map();
  const lastJson = new Map();
  // 上游 LLM 抖动（第三方 5xx，后端已重试到上限才返回 503）不能把整条前端交互链判红：
  // 脚本如实记录并重发，同时把这些噪音从运行时健康断言里单独摘出来。
  const isTransientUpstream = (text) => /status of 50\d|bad gateway|service unavailable|gateway timeout/i.test(text);
  const consoleErrors = [];
  const pageErrors = [];
  const httpErrors = [];
  const qaResponses = [];
  const transientUpstream = [];
  // 受控失败用例期间产生的网络错误是脚本自己制造的，不能算进运行时健康检查。
  let injecting = false;

  page.on('request', (req) => {
    const url = new URL(req.url());
    if (url.pathname.startsWith('/api/')) {
      reqCount.set(url.pathname, (reqCount.get(url.pathname) || 0) + 1);
    }
  });
  page.on('response', async (res) => {
    const url = new URL(res.url());
    if (!url.pathname.startsWith('/api/')) return;
    const status = res.status();
    if (status >= 400) {
      const entry = { text: `${status} ${url.pathname}`, injected: injecting };
      httpErrors.push(entry);
      if (!injecting && url.pathname === '/api/qa/ask') transientUpstream.push(entry.text);
    }
    try {
      const body = await res.json();
      lastJson.set(url.pathname, body);
      if (url.pathname === '/api/qa/ask') qaResponses.push({ status, body });
    } catch {
      /* non-json api reply */
    }
  });
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const text = msg.text().slice(0, 200);
    consoleErrors.push({ text, injected: injecting, transient: isTransientUpstream(text) });
  });
  page.on('pageerror', (err) => pageErrors.push({ text: String(err.message).slice(0, 200), injected: injecting }));

  const count = (p) => reqCount.get(p) || 0;
  /** 记忆类接口路径里带 project_id，只能按模式找回最近一次响应。 */
  const findJson = (pattern) => {
    for (const [key, value] of [...lastJson.entries()].reverse()) {
      if (pattern.test(key)) return value;
    }
    return undefined;
  };
  const setViewport = async (width, height) => {
    await page.setViewportSize({ width, height });
    await page.waitForTimeout(220);
  };
  /** 落位标志等待：报错时必须能看出是哪个路由没渲染出来。 */
  const waitLandmark = async (route) => {
    try {
      await page.waitForSelector(LANDMARKS[route], { timeout: 30000 });
    } catch (err) {
      const snippet = flat(await page.$eval('body', (el) => el.innerText).catch(() => '')).slice(0, 120);
      throw new Error(
        `${route} 的落位标志「${LANDMARKS[route]}」没有出现（首屏文案「${snippet}」）：${String(err.message).split('\n')[0].slice(0, 120)}`
      );
    }
  };

  // ------------------------------------------------------------ 前置：健康检查

  const health = await page.request.get(`${BASE}/api/health`).then((r) => r.json());
  console.log(
    'backend:',
      health.status,
    '· seekdb',
      health.components.seekdb.available,
    '· powercontext',
      health.components.powercontext.available
  );

  // ------------------------------------------------------------ 外壳交互

  await testCase('侧边栏折叠后主区变宽、标题隐藏，再展开恢复', async () => {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    const columns = () =>
      page.$eval('.app-shell', (el) => getComputedStyle(el).gridTemplateColumns.split(' ')[0]);
    const mainWidth = () => page.$eval('.main-column', (el) => el.getBoundingClientRect().width);

    const wide = await columns();
    const mainBefore = await mainWidth();
    assert(parseFloat(wide) === 264, `默认侧栏宽度应为 264px，实测 ${wide}`);

    await page.click('[aria-label="收起侧边栏"]');
    await page.waitForTimeout(320);
    const collapsed = await columns();
    assert(parseFloat(collapsed) === 68, `折叠后侧栏宽度应为 68px，实测 ${collapsed}`);
    assert(!(await page.isVisible('.brand-name')), '折叠后品牌文字仍然可见');
    const mainAfter = await mainWidth();
    assert(mainAfter - mainBefore > 180, `折叠后主区应明显变宽：${mainBefore} -> ${mainAfter}`);

    await page.click('[aria-label="展开侧边栏"]');
    await page.waitForTimeout(320);
    assert(parseFloat(await columns()) === 264, '展开后侧栏宽度没有回到 264px');
    assert(await page.isVisible('.brand-name'), '展开后品牌文字没有恢复');
  });

  await testCase('证据面板可通过顶栏按钮开合，并改变网格列宽', async () => {
    const tracks = () =>
      page.$eval('.app-shell', (el) =>
        getComputedStyle(el)
          .gridTemplateColumns.split(' ')
          .map((v) => Math.round(parseFloat(v)))
      );
    const openTracks = await tracks();
    await page.click('[aria-label="收起证据面板"]');
    await page.waitForTimeout(320);
    const closedTracks = await tracks();
    // 收起后第三轨收缩为 0（列数仍是 3，宽度必须归零），主区应当吃掉这部分宽度。
    assert(
      closedTracks[2] === 0 && openTracks[2] > 200,
      `收起证据面板没有把第三列压到 0：${openTracks.join('/')} -> ${closedTracks.join('/')}`
    );
    assert(closedTracks[1] > openTracks[1], `证据面板收起后主区没有变宽：${openTracks[1]} -> ${closedTracks[1]}`);
    await page.click('[aria-label="展开证据面板"]');
    await page.waitForTimeout(320);
    const reopened = await tracks();
    assert(reopened[2] > 200, `证据面板没有重新展开：${reopened.join('/')}`);
    assert(await page.isVisible('.evidence'), '证据面板没有重新展开');
  });

  // ------------------------------------------------------------ 输入区交互

  await testCase('Shift+Enter 只换行、不发送；输入法组合态的 Enter 也不发送', async () => {
    await page.click('#qa-question');
    const before = count('/api/qa/ask');
    await page.keyboard.type('第一行');
    await page.keyboard.press('Shift+Enter');
    await page.keyboard.type('第二行');
    const value = await page.inputValue('#qa-question');
    assert(value.includes('\n'), `Shift+Enter 没有插入换行：${JSON.stringify(value)}`);
    assert(count('/api/qa/ask') === before, 'Shift+Enter 触发了一次真实提问');

    // isComposing 的 Enter 来自中文输入法确认候选词，不能当成发送。
    await page.evaluate(() => {
      const el = document.getElementById('qa-question');
      const ev = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
      Object.defineProperty(ev, 'isComposing', { value: true });
      el.dispatchEvent(ev);
    });
    await page.waitForTimeout(400);
    assert(count('/api/qa/ask') === before, '输入态 Enter 被当成了发送');
    await page.fill('#qa-question', '');
  });

  await testCase('输入框随内容长高，最高 240px 后内部滚动', async () => {
    await typeInto(page, '#qa-question', '一行短问题');
    await page.waitForTimeout(120);
    const short = await page.$eval('#qa-question', (el) => el.getBoundingClientRect().height);
    // 用显式换行撑高：纯空格长串会在一行内折行，未必超过 240px 上限。
    const long = Array.from({ length: 24 }, (_, i) => `第 ${i + 1} 行占位文本`).join('\n');
    await typeInto(page, '#qa-question', long);
    await page.waitForTimeout(200);
    const box = await page.$eval('#qa-question', (el) => ({
      height: el.getBoundingClientRect().height,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      maxHeight: getComputedStyle(el).maxHeight,
    }));
    assert(box.height > short + 60, `长文本没有让输入框长高：${short} -> ${JSON.stringify(box)}`);
    assert(box.height <= 241, `输入框超过了 240px 上限：${JSON.stringify(box)}`);
    assert(
      box.scrollHeight > box.clientHeight,
      `到顶后输入框没有内部滚动：${JSON.stringify(box)}`
    );
    await typeInto(page, '#qa-question', QUESTION);
    await page.waitForTimeout(160);
    const restored = await page.$eval('#qa-question', (el) => el.value);
    assert(restored === QUESTION, `输入框内容没有换回验收问题：${restored.slice(0, 40)}`);
  });

  // ------------------------------------------------------------ 完整聊天流程

  /** 后面引用/证据用例要用「这一轮真的渲染成功」的那份响应，不能拿被 5xx 污染的最近一次。 */
  let latestQaResponse = null;

  await testCase('Enter 发送真实问答：加载态 → 论断区块 → 引用 chip，文本与 API 返回一致', async () => {
    let asked = false;
    let response = null;
    const stalled = [];
    for (let attempt = 1; attempt <= 3 && !response; attempt++) {
      if (attempt > 1) {
        // 上一轮真实请求被上游 5xx 打断：按同一手势重新提问，而不是把失败传导给后面的用例。
        await setViewport(1440, 900);
        await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
        await page.click('#qa-question');
        await typeInto(page, '#qa-question', QUESTION);
        await page.waitForTimeout(160);
      }
      const before = count('/api/qa/ask');
      await page.focus('#qa-question');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(300);
      if (count('/api/qa/ask') === before) {
        await typeInto(page, '#qa-question', QUESTION);
        continue;
      }
      asked = true;
      const qaStart = qaResponses.length;
      assert(await page.isVisible('[role="status"]'), '提问后没有出现加载状态');
      const disabled = await page.$eval('.composer-send', (el) => el.disabled);
      assert(disabled, '生成期间发送按钮没有禁用');
      const label = flat(await page.$eval('.composer-send', (el) => el.textContent));
      assert(label.includes('生成中'), `发送按钮没有显示进行态文案：${label}`);
      try {
        await page.waitForSelector('.claims-section', { timeout: 300000 });
        // response 事件里的 json 是异步解析的，取这一轮真正对应的那条 200 响应。
        const ok = qaResponses.slice(qaStart).filter((r) => r.status === 200 && r.body && (r.body.claims || []).length);
        response = ok.length ? ok[ok.length - 1].body : lastJson.get('/api/qa/ask');
      } catch {
        const shown = flat((await page.locator('.error-state, .banner-red').allInnerTexts()).join(' / '));
        stalled.push(`第 ${attempt} 次：${shown.slice(0, 160) || '无论断区块且没有可见错误'}`);
        console.log(`  ! ${stalled[stalled.length - 1]}`);
        await page.waitForTimeout(1500);
      }
    }
    assert(asked, '三次都没有发出真实提问请求');
    assert(
      response,
      `上游问答接口连续失败（第三方 LLM 抖动，后端重试到上限后返回 5xx）：${stalled.join(' | ')}`
    );
    latestQaResponse = response;
    const userBubble = flat(await page.$eval('.msg-user .msg-bubble', (el) => el.textContent));
    assert(
      userBubble.includes(flat(QUESTION)),
      `用户气泡文本与输入不一致：${userBubble.slice(0, 80)}`
    );

    const claims = (response.claims || []).map((c) => flat(c.statement)).filter(Boolean);
    assert(claims.length > 0, '接口返回里没有论断，无法核对渲染一致性');
    const section = flat(await page.$eval('.claims-section', (el) => el.textContent));
    const matched = claims.filter((statement) => section.includes(statement));
    assert(matched.length > 0, `页面上找不到任何一条接口返回的论断：${claims[0].slice(0, 60)}`);

    const url = page.url();
    assert(/[?&]s=local-/.test(url), `回答完成后 URL 没有落到本机会话：${url}`);
    const chips = await page.locator('.cite-chip').count();
    assert(chips > 0, '有引用却没有可点击的引用 chip');
    // 后面的 citation 用例依赖本轮真的有引用；在这里如实失败，不要把问题传导下去。
    assert(
      (response.citations || []).length > 0,
      `接口没有返回任何通过门控的引用（回答前 120 字：${flat(response.answer || '').slice(0, 120)}）`
    );

    const turns = page.locator('.turn');
    const turnCount = await turns.count();
    if (turnCount >= 2) {
      const a = await turns.nth(turnCount - 2).evaluate((el) => el.getBoundingClientRect().bottom);
      const b = await turns.nth(turnCount - 1).evaluate((el) => el.getBoundingClientRect().top);
      assert(b - a >= 16, `两轮消息之间间距过小：${Math.round(b - a)}px`);
    }
    console.log(
      `      · 命中 ${matched.length}/${claims.length} 条论断一致；chip ${chips} 个；mode=${response.mode}；耗时 ${response.elapsed_ms}ms`
    );
  });

  await testCase('citation 点击：证据面板定位到高亮条目，并打开真实原文页', async () => {
    const response = latestQaResponse;
    assert(response && response.citations && response.citations.length > 0, '本轮回答没有任何引用可供点击');
    // 以接口返回的 citation_id 为准挑选 chip，避免点到一个页面上残留的旧轮 chip。
    const wanted = response.citations.map((c) => c.citation_id);
    const chips = await page.locator('.answer-paragraph .cite-chip, .claim-meta .cite-chip').all();
    let chip = null;
    let citationId = null;
    for (const candidate of chips) {
      const label = await candidate.getAttribute('aria-label');
      const id = ((label || '').match(/(?<![a-z])c\d{1,3}(?![0-9])/) || [])[0];
      if (id && wanted.includes(id) && (await candidate.isVisible())) {
        chip = candidate;
        citationId = id;
        break;
      }
    }
    assert(chip, `接口给出的引用 ${wanted.join(',')} 在页面上没有对应的可点击 chip`);
    const before = await chip.evaluate((el) => {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      const chain = [];
      let node = el;
      while (node && chain.length < 6) {
        const s = getComputedStyle(node);
        const b = node.getBoundingClientRect();
        chain.push(
          `${node.tagName.toLowerCase()}.${String(node.className).trim().split(/\s+/)[0]}=${s.display}/${s.visibility}/op${s.opacity}/w${Math.round(b.width)}h${Math.round(b.height)}`
        );
        node = node.parentElement;
      }
      return { rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) }, chain };
    });
    console.log(`      · 目标 chip [${citationId}] @${JSON.stringify(before.rect)} ${before.chain.join(' < ')}`);
    // 高亮是 2.4 秒的瞬时反馈，必须在窗口内断言，不能等固定时长后再看。
    // 注意：聊天区自己的引用 chip 与右侧面板的卡片会同时进入高亮态，这里要看的是面板里那一条。
    await chip.scrollIntoViewIfNeeded();
    await chip.click();
    let highlightedIds = [];
    try {
      await page
        .waitForFunction(
          (wanted) => [...document.querySelectorAll('.citation-highlight')].some((el) => el.id === wanted),
          `citation-${citationId}`,
          { timeout: 1500 }
        )
        .then(() => undefined);
      highlightedIds = await page.$$eval('.citation-highlight', (els) => els.map((el) => el.id || el.className));
    } catch {
      highlightedIds = await page.$$eval('.citation-highlight', (els) => els.map((el) => el.id || el.className));
    }
    const target = await page.evaluate(() => {
      const simplify = (text) => String(text || '').replace(/\s+/g, ' ').trim();
      const ids = [...document.querySelectorAll('[id^="citation-"]')].map((el) => el.id);
      const panel = document.querySelector('.evidence-body');
      return {
        ids: ids.slice(0, 6),
        panelChars: panel ? simplify(panel.innerText).length : -1,
        dataEvidenc: document.querySelector('.app-shell')?.getAttribute('data-evidence'),
      };
    });
    assert(
      target.ids.length > 0,
      `点击引用后右侧面板里没有任何 citation 条目（期望 #citation-${citationId}，面板 id=${JSON.stringify(target.ids)}）`
    );
    assert(
      highlightedIds.includes(`citation-${citationId}`),
      `点击 [${citationId}] 后面板条目没有进入高亮态；高亮元素 ${JSON.stringify(highlightedIds)}；` +
        `面板 id=${JSON.stringify(target.ids)}，面板可见字符 ${target.panelChars}，data-evidence=${target.dataEvidenc}`
    );

    const panelVisible = await page.isVisible('.evidence');
    assert(panelVisible, '高亮发生在证据面板收起的状态，说明面板没有联动打开');

    await page.locator('.citation-view').first().click();
    await page.waitForSelector('.page-viewer-dialog', { timeout: 30000 });
    try {
      // 正文是打开弹窗后才异步读取的：必须等事实区出现，不能假设同一帧就能读到。
      await page.waitForSelector('.page-viewer-facts', { timeout: 30000 });
      const factText = flat(await page.$eval('.page-viewer-facts', (el) => el.textContent));
      assert(/page_id/.test(factText), `原文页没有回显页级身份：${factText.slice(0, 80)}`);
      const stored = findJson(/\/pages\/\d+$/);
      assert(stored && stored.page_id, '没有捕获到页面原文接口响应');
      const bodyText = await page.$eval('.page-viewer-body', (el) => el.innerText).catch(() => '');
      if (stored.content && stored.content.trim()) {
        assert(
          flat(bodyText).includes(flat(stored.content).slice(0, 40)),
          '查看器渲染的正文与 seekdb 返回的原文不一致'
        );
      } else {
        assert(/空白页/.test(bodyText), '空白页没有如实标注页级身份');
      }
    } finally {
      // 无论断言结果如何都要关掉弹窗，否则遮罩会把后面的用例全部拖成超时。
      await page.keyboard.press('Escape');
      await page.waitForTimeout(320);
      if (await page.isVisible('.page-viewer-dialog')) {
        await page.click('.page-viewer-header [aria-label*="关闭"], .page-viewer-close').catch(() => {});
      }
    }
    assert(!(await page.isVisible('.page-viewer-dialog')), 'Esc 没有关闭原文页查看器');
    assert(await page.isVisible('.evidence'), '关闭查看器时把证据面板也一起关掉了');
  });

  await testCase('向上翻看历史时不再被强制拉回底部，「回到最新消息」可用', async () => {
    // 把视口压扁，保证聊天区真的可滚动；否则「滚到顶部」这个动作没有意义。
    await setViewport(1440, 560);
    const geometry = await page.$eval('.chat-scroll', (el) => ({
      scrollable: el.scrollHeight - el.clientHeight > 120,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }));
    assert(geometry.scrollable, `聊天区不可滚动，无法验证跟随逻辑：${JSON.stringify(geometry)}`);
    await page.$eval('.chat-scroll', (el) => {
      el.scrollTop = 0;
      el.dispatchEvent(new Event('scroll'));
    });
    await page.waitForTimeout(400);
    assert(await page.isVisible('.jump-latest'), '滚到顶部后没有出现回到最新消息的按钮');
    await page.click('.jump-latest');
    await page.waitForTimeout(700);
    const atBottom = await page.$eval('.chat-scroll', (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 80);
    assert(atBottom, '点击按钮后没有真正回到底部');
    assert(!(await page.isVisible('.jump-latest')), '回到底部后按钮仍然存在');
    await setViewport(1440, 900);
  });

  await testCase('仅检索模式：走 /api/retrieval/search，命中数与接口一致，不打 LLM', async () => {
    const beforeAsk = count('/api/qa/ask');
    const beforeSearch = count('/api/retrieval/search');
    await openComposerOptions(page);
    await page.click('.composer-switch >> text=仅检索');
    await typeInto(page, '#qa-question', RETRIEVAL_Q);
    await page.waitForTimeout(120);
    await page.focus('#qa-question');
    await page.keyboard.press('Enter');
    const turn = page.locator('.chat-inner .qa-footer-meta', { hasText: 'POST /api/retrieval/search' });
    await turn.first().waitFor({ state: 'visible', timeout: 60000 });
    assert(count('/api/retrieval/search') > beforeSearch, '仅检索没有发起真实检索请求');
    assert(count('/api/qa/ask') === beforeAsk, '仅检索模式仍然调用了问答接口');
    const json = lastJson.get('/api/retrieval/search');
    assert(json, '没有捕获到检索响应体');
    const rows = await page.locator('.chat-inner .hit-row').count();
    console.log(`      · 接口命中 ${json.hits.length} 条，门控通过 ${json.relevant_count} 条，渲染行 ${rows}`);
    assert(json.hits.length > 0 ? rows > 0 : rows === 0, '渲染的命中数量与接口结果不符');
    assert(/门控/.test(flat(await turn.first().innerText())) || /门控/.test(flat(await page.$eval('.chat-inner', (el) => el.textContent))), '检索结果没有说明证据门控状态');
  });

  await testCase('渐进披露：折叠选项后控件真的收起，但非默认设置仍写在按钮上', async () => {
    const chip = page.locator('.composer-bar button[aria-expanded]');
    await chip.click();
    await page.waitForTimeout(250);
    assert((await chip.getAttribute('aria-expanded')) === 'false', '再次点击「选项」没有收起');
    assert(!(await page.isVisible('#qa-project')), '折叠后 #qa-project 仍然可见');
    assert(!(await page.isVisible('.composer-switch')), '折叠后回答方式仍然可见');
    const collapsedLabel = flat(await chip.innerText());
    assert(/仅检索/.test(collapsedLabel), `折叠后看不出当前是仅检索模式：${collapsedLabel}`);
    // 重新展开必须回到同一份设置：折叠只是显示层，不吞掉用户选过的值。
    await chip.click();
    await page.waitForSelector('#qa-project', { state: 'visible' });
    assert(await page.isChecked('#qa-gate'), '重新展开后证据门控的勾选状态丢了');
    assert(
      (await page.$eval('.composer-switch .seg-item-active', (el) => el.textContent)).includes('仅检索'),
      '重新展开后回答方式回到了问答'
    );
    await page.click('.composer-switch >> text=问答');
    await page.waitForTimeout(200);
    assert(!/仅检索/.test(flat(await chip.innerText())), '切回问答后按钮上仍写着仅检索');
  });

  // ------------------------------------------------------------ 真实上传

  await testCase('PDF 上传：新文档入库、计数与接口一致、列表可见，随后清理', async () => {
    const stamp = `itx-browser-${Date.now()}`;
    const scratch = path.join(OUT, `${stamp}.md`);
    fs.writeFileSync(
      scratch,
      `# ${stamp}\n\n本文件由浏览器交互验收脚本创建，用于验证真实上传链路，验证结束后删除。\n`,
      'utf8'
    );
    await page.click('.composer-switch >> text=问答');
    const uploadResponse = page
      .waitForResponse((res) => /\/api\/documents\/upload$/.test(new URL(res.url()).pathname), { timeout: 60000 })
      .then((res) => res.json());
    await page.setInputFiles('#chat-upload-file', scratch);
    const json = await uploadResponse;
    assert(json && json.doc_id, `上传后没有拿到新文档的 doc_id：${JSON.stringify(json).slice(0, 160)}`);
    assert(!json.deduplicated, '新内容的文件被判定为去重命中，说明哈希链路有问题');
    const toastText = flat(await page.locator('.toast').first().innerText().catch(() => ''));
    assert(
      toastText.includes(String(json.page_count)) && toastText.includes(String(json.chunk_count)),
      `提示里的页数/chunk 与接口不一致：${toastText}`
    );
    await page.goto(`${BASE}/knowledge`, { waitUntil: 'networkidle' });
    assert(
      await page.locator(`.doc-card:has-text("${stamp}.md")`).count() > 0,
      '新上传的文档没有出现在知识库里'
    );
    const del = await page.request.delete(`${BASE}/api/documents/${json.doc_id}`);
    assert(del.status() === 200, `清理测试文档失败：HTTP ${del.status()}`);
    await page.goto(`${BASE}/knowledge`, { waitUntil: 'networkidle' });
    assert(
      await page.locator(`.doc-card:has-text("${stamp}.md")`).count() === 0,
      '删除后文档仍留在知识库里'
    );
    fs.rmSync(scratch, { force: true });
  });

  await testCase('重复上传同一 PDF：命中去重并直接复用库中版本', async () => {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    const dupResponse = page
      .waitForResponse((res) => /\/api\/documents\/upload$/.test(new URL(res.url()).pathname), { timeout: 60000 })
      .then((res) => res.json());
    await page.setInputFiles('#chat-upload-file', DEMO_PDF);
    await page.waitForFunction(() => !document.querySelector('.pending-file'), { timeout: 60000 });
    const json = await dupResponse;
    assert(json && json.deduplicated, '重复上传没有被识别为去重命中');
    const toastText = flat(await page.locator('.toast').first().innerText().catch(() => ''));
    assert(/去重/.test(toastText), `去重提示文案不对：${toastText}`);
    const hint = flat(await page.$eval('.composer-hint', (el) => el.textContent));
    assert(/已限定在单个文档/.test(hint), '去重后没有把提问限定到该文档');
  });

  // ------------------------------------------------------------ 记忆闭环

  await testCase('新建/选中验收项目后显式保存进度，写入结果与接口一致', async () => {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    const existing = page.locator('.side-row', { hasText: PROJECT_TITLE });
    if ((await existing.count()) === 0) {
      await page.click('.sidebar-section-head >> text=新建');
      await page.fill('#sidebar-project-title', PROJECT_TITLE);
      await page.click('button:has-text("创建并选中")');
      await page.waitForTimeout(1500);
    } else {
      await existing.first().click();
    }
    // 选中态是 React 状态驱动的：读取前等它落到 DOM 上，不要靠一次 $eval 抢跑。
    await page
      .waitForFunction(
        (title) =>
          [...document.querySelectorAll('.side-row-active')].some((el) =>
            String(el.textContent || '').replace(/\s+/g, ' ').includes(title)
          ),
        PROJECT_TITLE,
        { timeout: 15000 }
      )
      .catch(() => {});
    // flat() 只在 Node 侧存在，不能在 $eval 的浏览器回调里调用，否则永远读不到结果。
    const selected = flat(await page.$eval('.side-row-active', (el) => el.textContent).catch(() => ''));
    if (!selected.includes(PROJECT_TITLE)) {
      const state = await page.evaluate(() => {
        const simplify = (text) => String(text || '').replace(/\s+/g, ' ').trim().slice(0, 40);
        return {
          url: location.pathname + location.search,
          stored: localStorage.getItem('rf-project'),
          active: [...document.querySelectorAll('.side-row-active')].map((el) => simplify(el.textContent)),
          rows: [...document.querySelectorAll('.side-row')].slice(0, 6).map((el) => simplify(el.textContent)),
        };
      });
      assert(false, `项目没有被选中：${JSON.stringify(state)}`);
    }

    await page.goto(`${BASE}/memory`, { waitUntil: 'networkidle' });
    const projects = await page.request.get(`${BASE}/api/projects`).then((r) => r.json());
    const mine = projects.projects.find((p) => p.title === PROJECT_TITLE);
    assert(mine, '侧栏创建了项目但接口里查不到');
    await page.selectOption('#memory-project', mine.project_id);
    await page.waitForSelector('#save-objective', { timeout: 30000 });

    await page.fill('#save-objective', MEM_OBJECTIVE);
    await page.locator('fieldset').filter({ hasText: '已确认决策' }).locator('button:has-text("添加一行")').click();
    await page.fill('#save-decisions-0', MEM_DECISION);
    await page.locator('fieldset').filter({ hasText: '下一步' }).locator('button:has-text("添加一行")').click();
    await page.fill('#save-next-0', MEM_NEXT);
    await page.click('button:has-text("显式保存研究进度")');
    await page.waitForSelector('.save-result', { timeout: 120000 });

    const json = findJson(/\/memory\/save$/);
    const title = flat(await page.$eval('.save-result-title', (el) => el.textContent));
    assert(json, '没有捕获到保存响应');
    const unchanged = json.written === 0 && json.snapshot_unchanged;
    const showsUnchanged = (await page.locator('.save-result-unchanged').count()) > 0;
    assert(
      unchanged === showsUnchanged,
      `去重状态与界面不一致：written=${json.written} unchanged=${json.snapshot_unchanged} 文案=${title}`
    );
    console.log(`      · 写入 ${json.written} 条，去重跳过 ${json.skipped_duplicates} 条，界面文案「${title}」`);
  });

  await testCase('跨会话恢复：重新进入页面后凭 project_id 取回同一条记忆', async () => {
    await page.goto(`${BASE}/memory`, { waitUntil: 'networkidle' });
    const projects = await page.request.get(`${BASE}/api/projects`).then((r) => r.json());
    const mine = projects.projects.find((p) => p.title === PROJECT_TITLE);
    await page.selectOption('#memory-project', mine.project_id);
    await page.waitForSelector('.restore-view', { timeout: 120000 });
    await page.click('button:has-text("重新恢复")');
    await page.waitForTimeout(1500);

    const json = findJson(/\/memory\/restore/);
    assert(json && json.memory_available, `恢复失败：${json && json.error}`);
    const view = flat(await page.$eval('.restore-view', (el) => el.textContent));
    assert(view.includes(MEM_DECISION.replace(/\s+/g, ' ')), '恢复出来的简报里没有刚保存的决策');
    assert(view.includes(MEM_NEXT.replace(/\s+/g, ' ')), '恢复出来的简报里没有刚保存的下一步');
    const entryCount = await page.$eval('.restore-view .mem-fact strong', (el) => Number(el.textContent));
    assert(entryCount === json.entry_count, `界面记忆条数 ${entryCount} 与接口 ${json.entry_count} 不一致`);
    assert(/package_version/.test(view), '简报没有标注记忆后端版本');
    console.log(`      · 记忆条数 ${entryCount}，scope ${json.scope_id}`);
  });

  await testCase('相同内容重复保存：命中 snapshot_unchanged，不产生重复记忆', async () => {
    await page.fill('#save-objective', MEM_OBJECTIVE);
    await page.locator('fieldset').filter({ hasText: '已确认决策' }).locator('button:has-text("添加一行")').click();
    await page.fill('#save-decisions-0', MEM_DECISION);
    await page.locator('fieldset').filter({ hasText: '下一步' }).locator('button:has-text("添加一行")').click();
    await page.fill('#save-next-0', MEM_NEXT);
    await page.click('button:has-text("显式保存研究进度")');
    await page.waitForSelector('.save-result', { timeout: 120000 });
    const json = findJson(/\/memory\/save$/);
    assert(json.written === 0, `重复保存仍然写入了 ${json.written} 条`);
    assert(await page.locator('.save-result-unchanged').count() > 0, '界面没有呈现「内容未变化」');
  });

  // ------------------------------------------------------------ 错误与状态

  await testCase('请求失败时给出可读错误反馈（拦截 /api/qa/ask）', async () => {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    injecting = true;
    await page.route('**/api/qa/ask', (route) => route.abort('failed'));
    await page.click('#qa-question');
    // 用真实可答的问题：这样「重试」之后应当真的产出论断区块，而不是又一次门控拒绝。
    await typeInto(page, '#qa-question', QUESTION);
    await page.focus('#qa-question');
    await page.keyboard.press('Enter');
    await page.waitForSelector('.error-state', { timeout: 30000 });
    const text = flat(await page.$eval('.error-state', (el) => el.textContent));
    assert(text.length > 8, `错误块内容为空：${text}`);
    const retry = await page.locator('.error-state button').count();
    assert(retry > 0, '错误反馈里没有提供重试入口');
    // 重试入口必须真的能用：解除拦截后点一次，应当发出第二次真实请求。
    await page.unroute('**/api/qa/ask');
    const beforeRetry = count('/api/qa/ask');
    await page.click('.error-state button');
    await page.waitForSelector('.claims-section, .thinking', { timeout: 30000 });
    assert(count('/api/qa/ask') > beforeRetry, '点了重试却没有重新发起请求');
    await page.waitForSelector('.claims-section', { timeout: 300000 });
    assert(!(await page.isVisible('.error-state')), '重试成功后错误块仍然挂着');
    await page.waitForTimeout(1200);
    injecting = false;
    await page.fill('#qa-question', '');
  });

  await testCase('深色主题：切换生效、刷新后保持、正文对比度达 WCAG AA', async () => {
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await page.click('[aria-label*="深色主题"]');
    await page.waitForTimeout(260);
    assert((await page.getAttribute('html', 'data-theme')) === 'dark', 'html[data-theme] 没有切到 dark');
    const darkBg = await page.$eval('.main-column', (el) => getComputedStyle(el).backgroundColor);
    const channels = (darkBg.match(/\d+/g) || []).slice(0, 3).map(Number);
    assert(channels.length === 3 && Math.max(...channels) < 60, `深色下主区背景没有变暗：${darkBg}`);
    await page.reload({ waitUntil: 'networkidle' });
    assert((await page.getAttribute('html', 'data-theme')) === 'dark', '刷新后主题没有保持');

    const ratio = await page.evaluate(() => {
      const parse = (s) => s.match(/\d+/g).slice(0, 3).map(Number);
      const lum = ([r, g, b]) => {
        const f = (c) => {
          const v = c / 255;
          return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
        };
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
      };
      const el = document.querySelector('.msg-assistant .answer-paragraph') || document.querySelector('.composer-hint');
      const color = parse(getComputedStyle(el).color);
      let node = el;
      let bg = parse(getComputedStyle(node).backgroundColor);
      while (node && /rgba\(0, 0, 0, 0\)|transparent/.test(getComputedStyle(node).backgroundColor)) {
        node = node.parentElement;
        if (!node) break;
        bg = parse(getComputedStyle(node).backgroundColor);
      }
      const l1 = lum(color);
      const l2 = lum(bg);
      return { ratio: (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05), color, bg };
    });
    assert(ratio.ratio >= 4.5, `深色正文对比度不足：${ratio.ratio.toFixed(2)} ${JSON.stringify(ratio)}`);

    await page.click('[aria-label*="浅色主题"]');
    await page.waitForTimeout(200);
    assert((await page.getAttribute('html', 'data-theme')) === 'light', '切回浅色失败');
    console.log(`      · 深色对比度 ${ratio.ratio.toFixed(2)}:1`);
  });

  // ------------------------------------------------------------ 移动端

  await testCase('390px：侧栏与证据面板为抽屉，遮罩与 Esc 都能关闭', async () => {
    await setViewport(390, 844);
    await page.goto(`${BASE}/workbench`, { waitUntil: 'networkidle' });
    const hidden = await page.$eval('.sidebar', (el) => el.getBoundingClientRect().right <= 1);
    assert(hidden, '移动端侧栏默认应该是收起的抽屉');
    await page.click('[aria-label="打开侧边栏"]');
    await page.waitForTimeout(320);
    assert(await page.isVisible('.overlay-sidebar'), '侧栏抽屉打开后没有遮罩');
    const opened = await page.$eval('.sidebar', (el) => el.getBoundingClientRect().left >= 0);
    assert(opened, '侧栏抽屉没有滑入');
    // 遮罩的中心点正被抽屉本身盖住（侧栏宽 min(300px,88vw)），点击必须落在露出来的那一侧。
    await page.click('.overlay-sidebar', { position: { x: 380, y: 400 } });
    await page.waitForTimeout(320);
    assert(await page.$eval('.sidebar', (el) => el.getBoundingClientRect().right <= 1), '点遮罩没有关闭侧栏');

    await page.click('[aria-label="展开证据面板"]');
    await page.waitForTimeout(320);
    assert(await page.$eval('.evidence', (el) => el.getBoundingClientRect().left < 390), '证据抽屉没有滑入');
    await page.click('.overlay-evidence', { position: { x: 8, y: 400 } });
    await page.waitForTimeout(320);
    assert(
      await page.$eval('.evidence', (el) => el.getBoundingClientRect().left >= 390),
      '点遮罩没有关闭证据抽屉'
    );

    await page.click('[aria-label="展开证据面板"]');
    await page.waitForTimeout(320);
    assert(await page.$eval('.evidence', (el) => el.getBoundingClientRect().left < 390), '证据抽屉第二次没有滑入');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(320);
    assert(await page.$eval('.evidence', (el) => el.getBoundingClientRect().left >= 390), 'Esc 没有关闭证据抽屉');
    assert(!(await page.isVisible('.overlay-evidence')), 'Esc 后遮罩仍在');
  });

  await testCase('移动端键盘弹起（视口收缩）时输入框仍完整可见', async () => {
    await setViewport(390, 844);
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    await page.focus('#qa-question');
    // 模拟软键盘占用约一半高度：interactive-widget=resizes-content 之下布局视口同步收缩。
    await setViewport(390, 480);
    await page.waitForTimeout(300);
    const box = await page.$eval('#qa-question', (el) => {
      const r = el.getBoundingClientRect();
      return { top: r.top, bottom: r.bottom, height: r.height };
    });
    const vh = await page.evaluate(() => window.innerHeight);
    assert(box.bottom <= vh + 1, `输入框底部被键盘遮住：bottom=${Math.round(box.bottom)} viewport=${vh}`);
    assert(box.top >= 0, `输入框顶部跑出视口：top=${Math.round(box.top)} viewport=${vh}`);
    const docScroll = await page.evaluate(
      () => document.documentElement.scrollHeight - window.innerHeight
    );
    assert(docScroll <= 1, `移动端出现了整页滚动（${docScroll}px），输入框会被顶出首屏`);
    await setViewport(390, 844);
  });

  await testCase('390px 输入 16px 字号，避免 iOS 聚焦缩放', async () => {
    await setViewport(390, 844);
    const size = await page.$eval('#qa-question', (el) => getComputedStyle(el).fontSize);
    assert(size === '16px', `移动端输入框字号为 ${size}，iOS 聚焦时会自动放大页面`);
  });

  // ------------------------------------------------------------ 宽度矩阵

  for (const width of WIDTHS) {
    await testCase(`${width}px：六个路由均无横向溢出`, async () => {
      const height = width <= 500 ? 844 : width <= 900 ? 1024 : 900;
      await setViewport(width, height);
      for (const route of ROUTES) {
        await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' });
        await waitLandmark(route);
        const bad = await page.evaluate((w) => {
          const out = [];
          if (document.documentElement.scrollWidth > w) out.push('html');
          // 允许「容器内横向滚动」：表格之类的内容比容器宽不算页面溢出，只要滚动容器自己放得下。
          const scrollsInside = (el) => {
            let node = el.parentElement;
            while (node && node !== document.body) {
              const ox = getComputedStyle(node).overflowX;
              if (ox === 'auto' || ox === 'scroll') return node.getBoundingClientRect().right <= w + 1;
              node = node.parentElement;
            }
            return false;
          };
          document.querySelectorAll('.view, .view *').forEach((el) => {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.right > w + 1 && !scrollsInside(el)) {
              out.push(`${el.tagName.toLowerCase()}.${String(el.className).trim().split(/\s+/)[0]}@${Math.round(r.right)}`);
            }
          });
          document.querySelectorAll('.panel-name').forEach((el) => {
            const cs = getComputedStyle(el);
            const lh = parseFloat(cs.lineHeight);
            const line = Number.isFinite(lh) ? lh : parseFloat(cs.fontSize) * 1.5;
            if (el.getBoundingClientRect().height / line > 1.6) {
              out.push(`panel-name:${(el.textContent || '').trim().slice(0, 10)}`);
            }
          });
          return out.slice(0, 5);
        }, width);
        assert(bad.length === 0, `${route} 存在溢出：${bad.join(', ')}`);
      }
    });
  }

  await testCase('1920px：消息列与输入框同宽并水平居中', async () => {
    await setViewport(1920, 1080);
    await page.goto(`${BASE}/workbench`, { waitUntil: 'networkidle' });
    const boxes = await page.evaluate(() => {
      const grab = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return { width: Math.round(r.width), left: Math.round(r.left) };
      };
      return { inner: grab('.chat-inner'), composer: grab('.composer-wrap') };
    });
    assert(boxes.inner && boxes.composer, '找不到消息列或输入框容器');
    assert(
      Math.abs(boxes.inner.width - boxes.composer.width) <= 2,
      `消息列 ${boxes.inner.width}px 与输入框 ${boxes.composer.width}px 不对齐`
    );
    assert(Math.abs(boxes.inner.left - boxes.composer.left) <= 2, '消息列与输入框没有同一水平起点');
  });

  await testCase('每个路由深链直达与刷新都落在同一页', async () => {
    await setViewport(1280, 900);
    for (const route of ROUTES) {
      await page.goto(`${BASE}${route}`, { waitUntil: 'networkidle' });
      await page.waitForSelector(LANDMARKS[route], { timeout: 30000 });
      const before = page.url();
      await page.reload({ waitUntil: 'networkidle' });
      await page.waitForSelector(LANDMARKS[route], { timeout: 30000 });
      assert(page.url() === before, `${route} 刷新后 URL 变了：${page.url()}`);
    }
  });

  await testCase('顶栏导航可在 6 个页面之间来回切换且不残留抽屉', async () => {
    await setViewport(390, 844);
    await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
    for (const label of ['Knowledge 文献', 'Memory 研究进度', 'Verification 验证', 'Docs 架构与接口', 'Chat 对话']) {
      await page.click('[aria-label="打开侧边栏"]');
      await page.waitForTimeout(260);
      await page.click(`.nav-item:has-text("${label}")`);
      await page.waitForTimeout(420);
      const drawerOpen = await page.$eval('.sidebar', (el) => el.getBoundingClientRect().right > 1);
      assert(!drawerOpen, `切到「${label}」后侧栏抽屉仍开着`);
    }
  });

  // ------------------------------------------------------------ 运行时健康

  await testCase('整个过程没有未捕获的 JS 错误', async () => {
    const real = pageErrors.filter((e) => !e.injected);
    assert(real.length === 0, `页面抛错 ${real.length} 次：${real.slice(0, 3).map((e) => e.text).join(' | ')}`);
    const injected = pageErrors.length - real.length;
    if (injected) console.log(`      · 已排除 ${injected} 条受控失败注入期间的页面抛错`);
  });

  await testCase('控制台没有新增 error（资源缺失/接口异常）', async () => {
    const noise = consoleErrors.filter((e) => !e.injected && /favicon/i.test(e.text));
    const flaky = consoleErrors.filter((e) => !e.injected && !/favicon/i.test(e.text) && e.transient);
    const real = consoleErrors.filter((e) => !e.injected && !/favicon/i.test(e.text) && !e.transient);
    assert(real.length === 0, `控制台 error ${real.length} 条：${real.slice(0, 3).map((e) => e.text).join(' | ')}`);
    if (noise.length) console.log(`      · 忽略 ${noise.length} 条 favicon 噪音`);
    if (flaky.length) {
      console.log(
        `      · 另计 ${flaky.length} 条上游 5xx 资源报错（第三方 LLM 抖动，脚本已重发并由错误/重试用例单独断言）：` +
          flaky.map((e) => e.text).join(' | ')
      );
    }
  });

  await testCase('接口调用没有 4xx/5xx（受控失败与上游 LLM 抖动除外）', async () => {
    const flaky = httpErrors.filter((e) => !e.injected && /^5\d\d \/api\/qa\/ask/.test(e.text));
    const unexpected = httpErrors.filter((e) => !e.injected && !/^5\d\d \/api\/qa\/ask/.test(e.text));
    assert(unexpected.length === 0, `出现非预期错误响应：${unexpected.slice(0, 4).map((e) => e.text).join(' | ')}`);
    if (flaky.length) {
      console.log(`      · 另计 ${flaky.length} 条 /api/qa/ask 上游 5xx：${flaky.map((e) => e.text).join(' | ')}`);
    }
  });

  await testCase('localStorage 会话回放：刷新后同一段对话仍在，且标注为本机数据', async () => {
    await setViewport(1440, 900);
    const url = await page.evaluate(() => {
      const raw = JSON.parse(localStorage.getItem('rf-sessions') || '[]');
      return raw.length ? `/workbench?s=${encodeURIComponent(raw[0].id)}` : null;
    });
    assert(url, '本机没有留下任何会话记录，无法验证跨会话回放');
    await page.goto(BASE + url, { waitUntil: 'networkidle' });
    await page.waitForSelector('.turn', { timeout: 30000 });
    const turns = await page.locator('.turn').count();
    assert(turns > 0, '回放后消息流是空的');
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('rf-sessions') || '[]'));
    const firstQuestion = flat(stored[0].exchanges[0].question);
    const rendered = flat(await page.$eval('.msg-user .msg-bubble', (el) => el.textContent));
    assert(rendered.includes(firstQuestion), '回放出来的问题和存的不一致');
    const sessionLabel = flat(await page.$eval('.sidebar', (el) => el.textContent));
    assert(/最近会话 · 本机/.test(sessionLabel), '侧栏没有把会话标注为本机数据');
  });

  // ------------------------------------------------------------ 收尾

  const passed = results.filter((r) => r.ok).length;
  const failed = results.length - passed;
  const summary = {
    checked_at: new Date().toISOString(),
    target: BASE,
    viewport_matrix: WIDTHS,
    routes: ROUTES,
    passed,
    failed,
    cases: results,
    console_errors: consoleErrors.filter((e) => !e.injected),
    page_errors: pageErrors.filter((e) => !e.injected),
    http_errors: httpErrors.filter((e) => !e.injected),
    upstream_5xx_on_qa_ask: transientUpstream,
    errors_during_controlled_failure: {
      console: consoleErrors.filter((e) => e.injected).length,
      page: pageErrors.filter((e) => e.injected).length,
      http: httpErrors.filter((e) => e.injected).length,
    },
  };
  fs.writeFileSync(path.join(OUT, 'interactions.json'), JSON.stringify(summary, null, 2), 'utf8');
  await browser.close();

  console.log('');
  console.log(`交互验收：${passed} 通过 / ${failed} 失败（共 ${results.length} 组）`);
  console.log(`明细：${path.join(OUT, 'interactions.json')}`);
  process.exit(failed === 0 ? 0 : 1);
})().catch(async (err) => {
  console.error('脚本异常终止：', err);
  process.exit(2);
});
