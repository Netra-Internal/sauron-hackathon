// Move camera screen on the deployed /hack/, real Axis: in-browser latency (kept-alive https) + screenshot plans/ptz-live.png.
//   NODE_PATH=<dir with playwright-core> node tools/ptz_shots.js
// Credentials (~/.config/netra/hack-launch.env) are added only to requests for $HACK_BASE (https://<internal host>).
// Moves the camera only by a 0.6 s nudge right and the same back left at speed 0.15.
if (process.env.PTZ_TEST_WILLIAM_ASKED !== "1") {     // HARD RULE (William, Oct 24): this MOVES the camera
  console.error("ptz_shots.js nudges the Axis. Never run it unless William asked directly (PTZ_TEST_WILLIAM_ASKED=1)."); process.exit(1);
}
const { chromium } = require("playwright-core");
const fs = require("fs"), os = require("os"), path = require("path");
const ENV = Object.fromEntries(fs.readFileSync(path.join(os.homedir(), ".config/netra/hack-launch.env"), "utf8").split(/\s+/).filter(l => l.includes("=")).map(l => l.split(/=(.*)/s).slice(0, 2)));
const AUTH = "Basic " + Buffer.from(`${ENV.HACK_LAUNCH_USER}:${ENV.HACK_LAUNCH_PASSWORD}`).toString("base64");
const BASE = process.env.HACK_BASE || (() => { throw new Error("set HACK_BASE=https://<internal host>"); })();
const CAM = process.argv[2] || "axis-q6215";
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, colorScheme: "dark" });
  await ctx.route(u => u.hostname === new URL(BASE).hostname, r => r.continue({ headers: { ...r.request().headers(), authorization: AUTH } }));
  const page = await ctx.newPage();
  page.on("pageerror", e => console.log("PAGE ERROR", e.message));
  await page.goto(`${BASE}/hack/`);
  await page.waitForTimeout(3000);
  const top = await page.locator("#topbar").innerText();
  console.log("topbar:", top.replace(/\n/g, " | "));
  await page.getByRole("button", { name: `Move ${CAM}` }).click();
  await page.waitForFunction(() => document.querySelector("#p-img")?.naturalWidth > 0, null, { timeout: 20000 });
  await page.waitForTimeout(2500);
  const lat = await page.evaluate(async cam => {
    const out = [];
    for (let i = 0; i < 15; i++) { const t0 = performance.now(); await fetch(`/hack/api/ptz/${cam}/state`); out.push(performance.now() - t0); }
    return out.sort((a, b) => a - b);
  }, CAM);
  console.log("in-browser GET /state x15 ms: median", lat[7].toFixed(0), "min", lat[0].toFixed(0), "max", lat[14].toFixed(0));
  const pose = () => page.evaluate(async cam => { const r = await fetch(`/hack/api/ptz/${cam}/state`); const t = await r.text(); try { const s = JSON.parse(t); return [s.pan, s.tilt, s.zoom]; } catch { return `HTTP ${r.status}: ${t.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").slice(0, 160)}`; } }, CAM);
  const p0 = await pose();
  await page.locator("#p-img").hover();
  await page.keyboard.down("ArrowRight"); await page.waitForTimeout(600); await page.keyboard.up("ArrowRight");
  await page.waitForTimeout(1200);
  const p1 = await pose();
  const r1 = await page.locator("#p-lat").innerText();
  await page.keyboard.down("ArrowLeft"); await page.waitForTimeout(600); await page.keyboard.up("ArrowLeft");
  await page.waitForTimeout(1500);
  const p2 = await pose();
  console.log("nudge right:", p0, "->", p1, "| back left ->", p2);
  console.log("UI latency readout:", r1, "|", await page.locator("#p-lat").innerText());
  console.log("side panel:", (await page.locator("#p-side").innerText()).replace(/\n+/g, " | "));
  console.log("calib chip:", await page.locator("#p-calib").innerText());
  await page.screenshot({ path: path.join(__dirname, "..", "plans", "ptz-live.png") });
  await browser.close();
})();
