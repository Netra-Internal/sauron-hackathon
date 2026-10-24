// Screenshots of the Calibrate screen on the deployed /hack/ (real frames, real map), plans/calib-*.png.
//   node tools/calib_shots.js            (needs playwright-core: NODE_PATH=<dir with playwright-core>)
// A: production site + camera-1-5621, READ ONLY (no Save pressed). B: a THROWAWAY site + still-only camera made through
// the UI: freeze a real jetson-c920 frame, click 7 frame/map pairs (the production pairs' pixels/points, re-clicked),
// see the draft fit, Save, check netra-ask holds it, then delete camera + site.
// Credentials (~/.config/netra/hack-launch.env) are added only to requests for internal.netralabs.net.
const { chromium } = require("playwright-core");
const fs = require("fs"), os = require("os"), path = require("path");
const ENV = Object.fromEntries(fs.readFileSync(path.join(os.homedir(), ".config/netra/hack-launch.env"), "utf8").split(/\s+/).filter(l => l.includes("=")).map(l => l.split(/=(.*)/s).slice(0, 2)));
const AUTH = "Basic " + Buffer.from(`${ENV.HACK_LAUNCH_USER}:${ENV.HACK_LAUNCH_PASSWORD}`).toString("base64");
const BASE = "https://internal.netralabs.net";
const OUT = path.join(__dirname, "..", "plans");
const PROD_SITE = "ucsd-design-innovation-building-c1dd";
const log = (...a) => console.log(...a);

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
  const ctx = await browser.newContext({ viewport: { width: 1680, height: 960 }, colorScheme: "dark" });
  await ctx.route(u => u.hostname === "internal.netralabs.net", r => r.continue({ headers: { ...r.request().headers(), authorization: AUTH } }));
  const page = await ctx.newPage();
  page.on("dialog", d => { log("dialog:", d.message().slice(0, 120)); d.accept(d.type() === "prompt" ? "calib screenshot test (delete me)" : undefined); });
  page.on("pageerror", e => log("PAGE ERROR", e.message));
  const api = async (method, p, body) => page.evaluate(async ([m, p, b]) => {
    const r = await fetch("/hack/api" + p, { method: m, headers: b ? { "Content-Type": "application/json" } : {}, body: b ? JSON.stringify(b) : undefined });
    return { status: r.status, body: r.status === 204 ? null : await r.json() };
  }, [method, p, body]);
  const settle = (ms = 2500) => page.waitForTimeout(ms);

  await page.goto(`${BASE}/hack/`);
  await settle(3000);
  // ---- A: production, read only
  await page.getByRole("button", { name: "Site setup" }).click();
  await page.waitForSelector("#calib:not(.hidden) #cpane h2", { timeout: 30000 });
  await settle(4000);
  await page.screenshot({ path: `${OUT}/calib-site.png` });
  log("A1 site tab:", await page.locator("#cpane").innerText().then(t => t.slice(0, 300).replace(/\n/g, " | ")));
  await page.locator("#cpane .card").first().click();
  await page.waitForFunction(() => document.querySelector("#cf-img")?.naturalWidth > 0, null, { timeout: 30000 });
  await settle(4000);
  const box = await page.locator("#cf-img").boundingBox();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.8);   // hover: where that pixel lands on the map
  await settle(800);
  await page.screenshot({ path: `${OUT}/calib-camera.png` });
  log("A2 camera tab:", await page.locator("#cpane").innerText().then(t => t.slice(0, 900).replace(/\n/g, " | ")));
  const prod = (await api("GET", `/calib/sites/${PROD_SITE}`)).body.cameras.find(c => c.id === "camera-1-5621");

  // ---- B: throwaway, through the UI
  const prodSite = (await api("GET", `/calib/sites/${PROD_SITE}`)).body;
  await page.selectOption("#cb-site", "+new");                 // prompt -> "calib screenshot test (delete me)"
  await page.waitForFunction(() => window.Calib.state.site?.name?.startsWith("calib screenshot test"), null, { timeout: 20000 });
  const sid = await page.evaluate(() => window.Calib.state.site.id);
  log("B throwaway site", sid);
  try {
    await page.locator(".ctabs button[data-tab=camera]").click();
    await page.getByRole("button", { name: "Add a still-only camera" }).click();
    const m = await page.evaluate(([lon, lat]) => { const p = window.Calib.map().project([lon, lat]); const r = document.querySelector("#cmap").getBoundingClientRect(); return [r.left + p.x, r.top + p.y]; }, [prod.lon, prod.lat]);
    await page.mouse.click(m[0], m[1]);
    await page.waitForFunction(() => window.Calib.state.d, null, { timeout: 20000 });
    await settle(1500);
    await page.selectOption("#cpane select.full", "jetson-c920");
    await page.getByRole("button", { name: /Freeze the live frame/ }).click();
    await page.waitForFunction(() => document.querySelector("#cf-img")?.naturalWidth > 0 && window.Calib.state.d?.frame?.kind === "frozen", null, { timeout: 30000 });
    await settle(1000);
    const fr = await page.evaluate(() => window.Calib.state.d.frame);
    log("B frozen", fr.width, fr.height, fr.from, fr.source, fr.age_s, "s old");
    await page.getByRole("button", { name: "Add point pairs" }).click();
    const sx = fr.width / prod.frame.width, sy = fr.height / prod.frame.height;
    const use = prod.points.slice(0, 7);
    for (const p of use) {
      const ib = await page.locator("#cf-img").boundingBox();
      await page.mouse.click(ib.x + p.u * sx * ib.width / fr.width, ib.y + p.v * sy * ib.height / fr.height);
      await page.evaluate(([lon, lat]) => window.Calib.map().jumpTo({ center: [lon, lat] }), [p.lon, p.lat]);
      await settle(300);
      const q = await page.evaluate(([lon, lat]) => { const x = window.Calib.map().project([lon, lat]); const r = document.querySelector("#cmap").getBoundingClientRect(); return [r.left + x.x, r.top + x.y]; }, [p.lon, p.lat]);
      await page.mouse.click(q[0], q[1]);
      await page.waitForFunction(n => window.Calib.state.d.points.length === n, use.indexOf(p) + 1);
    }
    await page.getByRole("button", { name: "Done adding" }).click();
    await page.waitForFunction(() => window.Calib.state.d.fit && !window.Calib.state.d.fitting, null, { timeout: 30000 });
    await page.evaluate(([lon, lat]) => window.Calib.map().jumpTo({ center: [lon, lat], zoom: 18 }), [prod.lon, prod.lat]);
    await settle(3000);
    await page.screenshot({ path: `${OUT}/calib-draft.png` });
    const draft = await page.evaluate(() => window.Calib.state.d.fit);
    log("B draft fit", draft.n, "pairs", draft.rms_px.toFixed(1), "px, LOO", JSON.stringify(draft.loo), "at_limit", draft.at_limit);
    log("B pane:", await page.locator("#cpane").innerText().then(t => t.slice(0, 700).replace(/\n/g, " | ")));
    await page.getByRole("button", { name: "Save calibration" }).click();
    await page.waitForFunction(() => !window.Calib.state.saving && !window.Calib.state.d.dirty, null, { timeout: 30000 });
    await settle(2500);
    await page.screenshot({ path: `${OUT}/calib-saved.png` });
    const cid = await page.evaluate(() => window.Calib.state.cid);
    const saved = (await api("GET", `/calib/sites/${sid}`)).body.cameras.find(c => c.id === cid);
    log("B saved in netra-ask:", cid, "calibrated", saved.calibrated, "n", saved.fit?.n, "LOO", JSON.stringify(saved.fit?.loo), "== draft:", JSON.stringify(saved.fit?.loo) === JSON.stringify(draft.loo));
    log("B toast/pane:", await page.locator("#toasts").innerText().then(t => t.replace(/\n/g, " | ")));
    const ppl = await page.locator("#cpeople").innerText();
    log("B people:", ppl);
  } finally {
    const s = (await api("GET", `/calib/sites/${sid}`)).body;
    for (const c of s?.cameras || []) log("delete camera", c.id, (await api("DELETE", `/calib/sites/${sid}/cameras/${c.id}`)).status);
    log("delete site", sid, (await api("DELETE", `/calib/sites/${sid}`)).status, "-> now", (await api("GET", `/calib/sites/${sid}`)).status);
    const p2 = (await api("GET", `/calib/sites/${PROD_SITE}`)).body.cameras.find(c => c.id === "camera-1-5621");
    log("production camera-1-5621 untouched:", p2.updated_at === prod.updated_at && JSON.stringify(p2.points) === JSON.stringify(prod.points), p2.updated_at);
    log("production boundary untouched:", JSON.stringify((await api("GET", `/calib/sites/${PROD_SITE}`)).body.boundary) === JSON.stringify(prodSite.boundary));
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
