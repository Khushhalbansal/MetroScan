/*
  Drive the real app in a real browser and capture each screen.

  Used for the design self-critique — a picture catches what a passing test never
  will — and as the end-to-end smoke check that the client and the API actually talk
  to each other.
*/
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const OUT = process.argv[2] ?? "./shots";
const BASE = "http://localhost:5173";
const EMAIL = "controller@metrology.gov.in";
const PASSWORD = process.env.METROSCAN_PASSWORD ?? "";

mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 960 },
  deviceScaleFactor: 2,
});
const page = await context.newPage();

const problems = [];
page.on("console", (m) => {
  if (m.type() === "error") problems.push(`console: ${m.text()}`);
});
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

async function shot(name, opts = {}) {
  await page.waitForTimeout(900); // let the reveal settle before capturing
  await page.screenshot({ path: `${OUT}/${name}.png`, ...opts });
  console.log("shot", name);
}

// --- sign in -----------------------------------------------------------------
await page.goto(BASE, { waitUntil: "networkidle" });
await shot("01-signin");

await page.fill("#email", EMAIL);
await page.fill("#password", PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL("**/dashboard", { timeout: 20000 });
await page.waitForLoadState("networkidle");
await shot("02-repository");

// --- new check ---------------------------------------------------------------
await page.goto(`${BASE}/scans/new`, { waitUntil: "networkidle" });
await shot("03-new-check");

// --- examination --------------------------------------------------------------
await page.goto(`${BASE}/scans`, { waitUntil: "networkidle" });
const firstRow = page.locator(".repo__link").first();
await firstRow.click();
await page.waitForSelector(".ledger__row", { timeout: 20000 });
await page.waitForLoadState("networkidle");
await shot("04-examination");
await shot("04-examination-full", { fullPage: true });

// hover a ledger row to prove the bidirectional link
const geometryRow = page.locator('[data-rule="FONT_HEIGHT_NET_QUANTITY"]');
if (await geometryRow.count()) {
  await geometryRow.scrollIntoViewIfNeeded();
  await geometryRow.hover();
  await shot("05-measure-hover");
}

// --- override dialog ----------------------------------------------------------
const overrule = page.locator(".ledger__overrule").first();
if (await overrule.count()) {
  await overrule.click();
  await page.waitForSelector(".dialog", { timeout: 5000 });
  await shot("06-override");
  await page.keyboard.press("Escape");
}

// --- narrow viewport ----------------------------------------------------------
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(`${BASE}/scans`, { waitUntil: "networkidle" });
await shot("07-repository-mobile", { fullPage: true });

await browser.close();

if (problems.length) {
  console.error("PAGE PROBLEMS:");
  for (const p of problems) console.error("  " + p);
  process.exit(1);
}
console.log("no console errors");
