// As William: /hack/ -> "Calibrate / site setup" -> the Axis is listed under "Add a camera" -> add it -> its
// calibration opens -> back to Site setup -> "Remove camera" + inline "Yes, remove" on the Axis record just added.
// Camera 1 (camera-1-5621) is never touched. Screenshots plans/calib-addcam-*.png. Auth only to internal.netralabs.net.
const { chromium } = require("playwright-core");
const fs = require("fs"), os = require("os"), path = require("path");
const ENV = Object.fromEntries(fs.readFileSync(path.join(os.homedir(), ".config/netra/hack-launch.env"), "utf8").split(/\s+/).filter(l => l.includes("=")).map(l => l.split(/=(.*)/s).slice(0, 2)));
const AUTH = "Basic " + Buffer.from(`${ENV.HACK_LAUNCH_USER}:${ENV.HACK_LAUNCH_PASSWORD}`).toString("base64");
const OUT = path.join(__dirname, "..", "plans"), FEED = process.argv[2] || "axis-q6215";
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1680, height: 960 }, colorScheme: "dark" });
  await ctx.route(u => u.hostname === "internal.netralabs.net", r => r.continue({ headers: { ...r.request().headers(), authorization: AUTH } }));
  const page = await ctx.newPage();
  page.on("pageerror", e => console.log("PAGE ERROR", e.message));
  page.on("dialog", d => { console.log("dialog:", d.message()); d.dismiss(); });
  await page.goto("https://internal.netralabs.net/hack/");
  await page.getByRole("button", { name: "Calibrate / site setup" }).click();
  await page.waitForSelector("#calib:not(.hidden) .addcam, #calib:not(.hidden) #cpane .card", { timeout: 30000 });
  await page.waitForTimeout(3500);
  console.log("site tab:", (await page.locator("#cpane").innerText()).replace(/\n+/g, " | "));
  await page.screenshot({ path: `${OUT}/calib-addcam-1-site.png` });
  const add = page.locator("#cpane .addcam", { hasText: FEED });
  console.log("Add button for", FEED, "visible:", await add.isVisible());
  await add.click();
  await page.waitForFunction(f => window.Calib.state.tab === "camera" && window.Calib.state.site.cameras.some(c => c.source?.camera_id === f && c.id === window.Calib.state.cid), FEED, { timeout: 20000 });
  await page.waitForTimeout(2500);
  const cid = await page.evaluate(() => window.Calib.state.cid);
  console.log("added + calibration opened:", cid, "|", (await page.locator("#cpane").innerText()).slice(0, 300).replace(/\n+/g, " | "));
  await page.screenshot({ path: `${OUT}/calib-addcam-2-opened.png` });
  await page.locator(".ctabs button[data-tab=site]").click();
  await page.waitForTimeout(800);
  const card = page.locator("#cpane .card", { hasText: cid });
  await card.getByRole("button", { name: "Remove camera" }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT}/calib-addcam-3-remove-confirm.png` });
  console.log("confirm shown:", (await card.innerText()).replace(/\n+/g, " | "));
  await card.getByRole("button", { name: "Yes, remove" }).click();
  await page.waitForFunction(id => !window.Calib.state.site.cameras.some(c => c.id === id), cid, { timeout: 20000 });
  await page.waitForTimeout(800);
  console.log("removed:", cid, "| cameras now:", await page.evaluate(() => window.Calib.state.site.cameras.map(c => `${c.id}(${c.source?.camera_id})`).join(", ")));
  console.log("Axis back in Add list:", await page.locator("#cpane .addcam", { hasText: FEED }).isVisible());
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
