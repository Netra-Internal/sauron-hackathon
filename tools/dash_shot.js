// Read-only check of the live /hack/ page: navigate, read state, screenshot. NO clicks (never touches PTZ controls).
// usage: PW=<path to playwright module> node tools/dash_shot.js <logged-in chromium profile dir (a copy)> <out.png>
const { chromium } = require(process.env.PW);
(async () => {
  const ctx = await chromium.launchPersistentContext(process.argv[2], { headless: true, viewport: { width: 1600, height: 900 } });
  const page = ctx.pages()[0] || await ctx.newPage();
  // read-only: navigate, read, screenshot. NO clicks (never touch PTZ controls).
  await page.goto('https://internal.netralabs.net/hack/');
  await page.waitForFunction(() => typeof S !== 'undefined' && S.st && S.st.state !== 'starting' && S.live, null, { timeout: 30000 });
  await page.waitForTimeout(3000);
  const r = await page.evaluate(() => ({ url: location.href, st: S.st.state + ' ' + (S.st.mode || S.st.why || ''), panel: !!document.querySelector('#panel'),
    stageW: document.querySelector('#stage').clientWidth, vidW: document.querySelector('#vid').clientWidth,
    open: [...S.inc.values()].filter(x => x.status !== 'closed').length, cards: document.querySelector('#droneout').innerText,
    lag: document.querySelector('#lag').innerText.replace(/\n/g, ' '), debug: !!document.querySelector('a[href="/hack/api/incidents"]') }));
  await page.screenshot({ path: process.argv[3] });
  console.log(JSON.stringify(r)); await ctx.close();
})().catch(e => { console.error(e.message); process.exit(1); });
