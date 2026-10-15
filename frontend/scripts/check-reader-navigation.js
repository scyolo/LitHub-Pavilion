/** Run via playwright-cli run-code --filename. The current page sets the local base URL. */
async page => {
  const browser = page.context().browser(), base = new URL(page.url()).origin + '/';
  const report = { base, cases: [] };
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const ready = p => p.waitForFunction(() => document.querySelector('.explorer-results')?.getAttribute('aria-busy') === 'false' && document.querySelectorAll('.paper-card').length > 0, { timeout: 20000 });
  async function create() {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const p = await context.newPage();
    await p.addInitScript(() => {
      const Original = window.Worker; window.__readerEvents = []; window.__readerTerminated = 0;
      window.Worker = class extends Original {
        postMessage(data, ...args) { window.__readerEvents.push({ id: data.id, method: data.method, type: data.type }); return super.postMessage(data, ...args); }
        terminate() { window.__readerTerminated++; return super.terminate(); }
      };
    });
    await p.goto(base); await p.locator('.metric-value').first().waitFor();
    return { context, p };
  }
  // Cancelling a search must release real network work, not just its UI promise.
  {
    const { context, p } = await create();
    let release, blocked, first = true;
    const gate = new Promise(resolve => { release = resolve; });
    const started = new Promise(resolve => { blocked = resolve; });
    const failed = [];
    context.on('requestfailed', request => { if (request.url().includes('/search-')) failed.push(request.failure()?.errorText); });
    await context.route('**/search-*.json.gz', async route => {
      if (first) { first = false; blocked(); await gate; }
      await route.continue().catch(() => {});
    });
    try {
      await p.goto(base + '#/papers?q=learning'); await started;
      const oldId = await p.evaluate(() => window.__readerEvents.findLast(e => e.method === 'search').id);
      const start = Date.now();
      await p.getByRole('navigation', { name: '按研究方向浏览' }).getByRole('link', { name: '大语言模型', exact: true }).click();
      await ready(p);
      const stats = await p.evaluate(id => ({ cancelled: window.__readerEvents.some(e => e.type === 'cancel' && e.id === id), terminated: window.__readerTerminated, url: location.hash }), oldId);
      assert(stats.cancelled && stats.terminated === 0 && stats.url.includes('direction=llm'), 'Abandoned search poisoned the next sidebar page');
      report.cases.push({ name: 'cancel-blocked-search', next_page_ms: Date.now() - start, ...stats, failed_requests: failed });
      release();
      const startRapid = Date.now();
      for (const name of ['智能体', '机器学习', '投机解码', '计算机视觉']) {
        await p.getByRole('navigation', { name: '按研究方向浏览' }).getByRole('link', { name, exact: true }).click();
      }
      await ready(p);
      assert((await p.url()).includes('direction=cv'), 'Rapid navigation showed the wrong direction');
      assert(await p.getByRole('alert').count() === 0, 'Rapid navigation produced a loading failure');
      report.cases.push({ name: 'rapid-sidebar', ready_ms: Date.now() - startRapid, result: await p.locator('.results-toolbar strong').textContent() });
    } finally { release(); await context.close(); }
  }
  // Background manifest revalidation is not allowed to terminate the search worker.
  {
    const { context, p } = await create();
    let release, blocked;
    const gate = new Promise(resolve => { release = resolve; });
    const started = new Promise(resolve => { blocked = resolve; });
    await context.route('**/manifest.json', async route => { blocked(); await gate; await route.continue().catch(() => {}); });
    try {
      await p.getByRole('button', { name: '检查更新', exact: true }).click(); await started;
      const start = Date.now();
      await p.getByRole('navigation', { name: '按研究方向浏览' }).getByRole('link', { name: '智能体', exact: true }).click();
      await ready(p);
      await p.waitForTimeout(Math.max(0, 13000 - (Date.now() - start)));
      const stats = await p.evaluate(() => ({ terminated: window.__readerTerminated, busy: document.querySelector('.explorer-results')?.getAttribute('aria-busy'), cards: document.querySelectorAll('.paper-card').length }));
      assert(stats.terminated === 0 && stats.busy === 'false' && stats.cards === 20, 'A refresh timeout killed an unrelated page');
      report.cases.push({ name: 'refresh-timeout-isolation', ...stats });
    } finally { release(); await context.close(); }
  }
  // Actual dynamic import failures can behave differently from mocked Promises.
  {
    const { context, p } = await create(); let attempts = 0;
    await context.route('**/PaperList-*.js', async route => {
      attempts++; if (attempts === 1) await route.abort('failed'); else await route.continue();
    });
    try {
      await p.getByRole('link', { name: '论文探索', exact: true }).click();
      await ready(p);
      assert(attempts >= 2 && attempts <= 3, 'Route recovery retried indefinitely or never retried');
      report.cases.push({ name: 'transient-route-chunk', attempts, result: await p.locator('.results-toolbar strong').textContent() });
    } finally { await context.close(); }
  }
  report.passed = true;
  return report;
}
