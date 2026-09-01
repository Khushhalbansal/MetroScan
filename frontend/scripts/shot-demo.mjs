// Demo-review capture: Overview / Repository / an open scan at 1280 + 1920, mobile at
// 390, plus two short videos (the scan-reveal sequence and the Dashboard draw-in).
//
//   node scripts/shot-demo.mjs <outdir>
//
// Needs both dev servers up and the demo seed loaded (backend/scripts/seed_demo.py).

import { chromium } from "playwright";
import { mkdirSync, renameSync, readdirSync } from "node:fs";

const OUT = process.argv[2] ?? "demo-shots";
const BASE = "http://localhost:5173";
const EMAIL = "demo@metrology.gov.in";
const PASSWORD = process.env.METROSCAN_PASSWORD ?? "vernier-brass-plumb-2026";
mkdirSync(OUT, { recursive: true });
mkdirSync(`${OUT}/video`, { recursive: true });

const browser = await chromium.launch();
const problems = [];

async function signedInPage(ctx) {
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && problems.push(`console: ${m.text()}`));
  await page.goto(BASE, { waitUntil: "networkidle" });
  if (page.url().includes("/sign-in") || (await page.$("#email"))) {
    await page.fill("#email", EMAIL);
    await page.fill("#password", PASSWORD);
    await page.click('button[type="submit"]');
  }
  await page.waitForURL("**/dashboard", { timeout: 20000 });
  return page;
}

async function scanIdFor(page, nameFragment) {
  await page.goto(`${BASE}/scans`, { waitUntil: "networkidle" });
  await page.waitForSelector(".repo__link");
  const href = await page
    .locator(".repo__link", { hasText: nameFragment })
    .first()
    .getAttribute("href");
  return href.split("/").pop();
}

// ---- stills --------------------------------------------------------------------
{
  const ctx = await browser.newContext({ deviceScaleFactor: 2 });
  const page = await signedInPage(ctx);

  const scanId = await scanIdFor(page, "Nutri Millet Puffs");

  for (const [w, h, tag] of [
    [1280, 1000, "1280"],
    [1920, 1200, "1920"],
  ]) {
    await page.setViewportSize({ width: w, height: h });

    await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1400);
    await page.screenshot({ path: `${OUT}/overview-${tag}.png`, fullPage: true });

    await page.goto(`${BASE}/scans`, { waitUntil: "networkidle" });
    await page.waitForTimeout(900);
    await page.screenshot({ path: `${OUT}/repository-${tag}.png`, fullPage: true });

    await page.goto(`${BASE}/scans/${scanId}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(3000); // let the reveal settle
    await page.screenshot({ path: `${OUT}/examination-${tag}.png`, fullPage: true });
  }

  // mobile
  await page.setViewportSize({ width: 390, height: 850 });
  await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1400);
  await page.screenshot({ path: `${OUT}/overview-390.png`, fullPage: true });
  await page.goto(`${BASE}/scans/${scanId}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: `${OUT}/examination-390.png`, fullPage: true });

  // reduced motion — content must all be present, no staging
  await ctx.close();
  const rmCtx = await browser.newContext({ deviceScaleFactor: 2, reducedMotion: "reduce" });
  const rm = await signedInPage(rmCtx);
  await rm.setViewportSize({ width: 1280, height: 1000 });
  await rm.goto(`${BASE}/scans/${scanId}`, { waitUntil: "networkidle" });
  await rm.waitForTimeout(800);
  await rm.screenshot({ path: `${OUT}/examination-reduced-motion.png`, fullPage: true });
  await rmCtx.close();
}

// ---- videos -----------------------------------------------------------------
async function clip(name, steps) {
  const ctx = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    recordVideo: { dir: `${OUT}/video`, size: { width: 1280, height: 900 } },
  });
  const page = await signedInPage(ctx);
  await steps(page);
  await ctx.close();
  const vids = readdirSync(`${OUT}/video`).filter((f) => f.endsWith(".webm") && !f.startsWith("clip-"));
  if (vids.length) renameSync(`${OUT}/video/${vids[0]}`, `${OUT}/video/clip-${name}.webm`);
}

await clip("scan-reveal", async (page) => {
  const id = await scanIdFor(page, "Nutri Millet Puffs");
  await page.goto(`${BASE}/scans`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  await page.click(`.repo__link[href$="${id}"]`);
  await page.waitForTimeout(3200); // whole reveal
});

await clip("dashboard-draw-in", async (page) => {
  await page.goto(`${BASE}/scans`, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);
  await page.click('a[href="/dashboard"]');
  await page.waitForTimeout(2600);
});

await browser.close();
console.log(problems.length ? `PROBLEMS:\n${problems.join("\n")}` : "clean — no console/page errors");
